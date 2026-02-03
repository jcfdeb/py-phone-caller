import logging
from datetime import UTC, datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from py_phone_caller_utils.config import settings
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    AddressBook,
)

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)


def _parse_iso_utc(ts: str) -> Optional[datetime]:
    """
    Parses an ISO 8601 formatted UTC timestamp string.

    This function processes an ISO 8601 UTC timestamp string and attempts to
    convert it into a timezone-aware datetime object. If the input string is
    empty, invalid, or can't be processed, the function will return None.
    Handles "Z" suffix as a shorthand for "+00:00" UTC offset.

    :param ts: str
        The input ISO 8601 UTC timestamp string.
    :return: Optional[datetime]
        A timezone-aware datetime object representing the input timestamp,
        or None if parsing fails.
    """

    try:
        ts = (ts or "").strip()
        if not ts:
            return None
        # Support Zulu suffix
        if ts.endswith("Z"):
            ts = f"{ts[:-1]}+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            # Assume UTC if naive
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


async def add_contact(payload: Dict[str, Any]) -> str:
    """
    Adds a contact to the address book by creating a new record with the details
    provided and saving it to the database. The function requires certain fields
    to be present in the payload, validates them, and constructs the corresponding
    record.

    :param payload: A dictionary containing the contact details for the new record.
                    The following fields are required:
                    - name
                    - phone_number
                    - on_call_availability
                    - enabled
    :return: The unique identifier of the created contact entry as a string.
    :raises ValueError: If any of the required fields are missing in the payload.
    """

    required = ["name", "phone_number", "on_call_availability", "enabled"]
    if missing := [k for k in required if k not in payload]:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")

    record = AddressBook(
        name=payload.get("name", ""),
        surname=payload.get("surname", ""),
        address=payload.get("address", ""),
        zip_code=payload.get("zip_code", ""),
        city=payload.get("city", ""),
        state=payload.get("state", ""),
        country=payload.get("country", ""),
        phone_number=payload["phone_number"],
        on_call_availability=payload["on_call_availability"],
        created_time=datetime.now(UTC).replace(tzinfo=None),
        enabled=bool(payload["enabled"]),
        annotations=payload.get("annotations", ""),
    )

    await AddressBook.insert(record)
    return str(record.id)


async def modify_contact(contact_id: str, changes: Dict[str, Any]) -> int:
    """
    Modify an existing contact in the AddressBook database based on the provided changes.
    This function updates specific fields in the database for the contact with the given
    `contact_id`. Only the fields present in the `changes` dictionary and defined in the
    `updatable` map will be updated. If no valid fields are provided or updated, the function
    returns 0.

    :param contact_id: Unique identifier of the contact to update.
    :type contact_id: str
    :param changes: Dictionary where keys represent fields to modify and values are the
        new data to apply for those fields.
    :type changes: Dict[str, Any]
    :return: The number of rows affected by the update operation.
    :rtype: int
    """

    if not changes:
        return 0

    updatable = {
        "name": AddressBook.name,
        "surname": AddressBook.surname,
        "address": AddressBook.address,
        "zip_code": AddressBook.zip_code,
        "city": AddressBook.city,
        "state": AddressBook.state,
        "country": AddressBook.country,
        "phone_number": AddressBook.phone_number,
        "on_call_availability": AddressBook.on_call_availability,
        "enabled": AddressBook.enabled,
        "annotations": AddressBook.annotations,
    }

    update_dict = {}
    for k, v in changes.items():
        col = updatable.get(k)
        if col is not None:
            update_dict[col] = v

    if not update_dict:
        return 0

    result = await AddressBook.update(update_dict).where(AddressBook.id == contact_id)
    if isinstance(result, int):
        return result
    if isinstance(result, list):
        return len(result)
    try:
        return int(result)
    except Exception:
        return 0


async def delete_contacts(contact_ids: Iterable[str]) -> int:
    """
    Deletes contacts from the address book based on the provided contact IDs. This
    is an asynchronous function designed to work with a database model for the
    AddressBook.

    :param contact_ids: An iterable of contact ID strings that represent the unique
        identifiers of the contacts to be deleted.
    :return: The number of contacts successfully deleted as an integer.
    """

    ids = list(contact_ids)
    if not ids:
        return 0
    result = await AddressBook.delete().where(AddressBook.id.is_in(ids))
    if isinstance(result, int):
        return result
    if isinstance(result, list):
        return len(result)
    try:
        return int(result)
    except Exception:
        return 0


def _availability_windows(
    contact: Dict[str, Any],
) -> List[Tuple[datetime, datetime, int]]:
    """
    Parses and validates availability windows from the provided contact information.
    Extracts on-call availability data for a contact, ensuring proper decoding,
    validation, and formatting into a list of time window tuples.

    :param contact: Dictionary containing contact details, which may include
        on-call availability data under the "on_call_availability" key.
    :type contact: Dict[str, Any]
    :return: A list of tuples, each containing the start time, end time, and
        priority level of an availability window.
    :rtype: List[Tuple[datetime, datetime, int]]
    """

    windows: List[Tuple[datetime, datetime, int]] = []
    raw = contact.get("on_call_availability") or []
    if isinstance(raw, str):
        try:
            import json

            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        raw = []
    for item in raw:
        try:
            start = _parse_iso_utc(str(item.get("start_at")))
            end = _parse_iso_utc(str(item.get("end_at")))
            prio = int(item.get("priority"))
            if start and end and start <= end:
                windows.append((start, end, prio))
        except Exception:
            continue
    return windows


async def get_on_call_contacts(
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Fetches all currently on-call contacts, ordered by priority and other criteria.

    :param now: The current datetime to evaluate on-call availability.
    :return: A list of dictionaries containing the on-call contacts' details.
    """
    now = now or datetime.now(UTC)

    rows = await AddressBook.select(
        AddressBook.id,
        AddressBook.name,
        AddressBook.surname,
        AddressBook.phone_number,
        AddressBook.created_time,
        AddressBook.on_call_availability,
    ).where(AddressBook.enabled == True)

    contacts_with_keys = []
    for row in rows:
        windows = _availability_windows(row)
        for start, end, prio in windows:
            if start <= now <= end:
                key = (
                    prio,
                    start,
                    row.get("created_time") or datetime.min,
                    f"{row.get('name', '')}{row.get('surname', '')}",
                )
                contacts_with_keys.append({
                    "key": key,
                    "contact": {
                        "id": str(row.get("id")),
                        "name": row.get("name"),
                        "surname": row.get("surname"),
                        "phone_number": row.get("phone_number"),
                        "created_time": row.get("created_time"),
                        "priority": prio,
                    }
                })

    contacts_with_keys.sort(key=lambda x: x["key"])
    return [x["contact"] for x in contacts_with_keys]


async def get_on_call_contact(
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetches the best on-call contact information based on the current datetime.

    This function retrieves the list of all currently on-call contacts and
    returns the one with the highest priority (the first one in the sorted list).

    :param now: The current datetime to evaluate on-call availability.
    :return: A dictionary containing the on-call contact's details, or None.
    """
    contacts = await get_on_call_contacts(now)
    return contacts[0] if contacts else None
