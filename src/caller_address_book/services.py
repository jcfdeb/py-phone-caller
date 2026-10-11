"""
Core business logic and services for caller_address_book.

Encapsulates CRUD operations, on-call contact retrieval, CSV serialization,
and batch CSV importing with chunked asynchronous execution and early-return
guard clauses.
"""

from __future__ import annotations
import asyncio
import csv
import io
import json
import logging
from typing import Any, Awaitable, Callable, Mapping, Sequence
from pydantic import ValidationError

from py_phone_caller_utils.py_phone_caller_db.db_address_book import (
    add_contact as db_add_contact,
    delete_contacts as db_delete_contacts,
    get_on_call_contact as db_get_on_call_contact,
    modify_contact as db_modify_contact,
)
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    AddressBook,
)

from caller_address_book.exceptions import (
    ContactNotFoundError,
    ContactValidationError,
)
from caller_address_book.schemas import ContactCSVRow, ImportSummary


def normalize_string(s: str | None) -> str:
    """Normalizes string by stripping whitespace and converting to lowercase."""
    return (s or "").strip().lower()


def serialize_json_field(val: Any) -> str:
    """Safely serializes on-call availability data to JSON string."""
    try:
        obj = val
        if isinstance(obj, str):
            try:
                obj = json.loads(obj)
            except Exception:
                obj = []
        if obj is None:
            obj = []
        return json.dumps(obj, separators=(",", ":"))
    except Exception:
        return "[]"


class AddressBookService:
    """
    Service for managing address book contacts and CSV data streams.

    Attributes:
        add_contact_fn: Hook to persist a new contact.
        modify_contact_fn: Hook to update an existing contact.
        delete_contacts_fn: Hook to delete contacts by list of IDs.
        get_on_call_contact_fn: Hook to retrieve the current active on-call responder.
        address_book_table: Table class or mock for AddressBook queries.
    """

    def __init__(
        self,
        add_contact_fn: Callable[[Mapping[str, Any]], Awaitable[str]] = db_add_contact,
        modify_contact_fn: Callable[[str, Mapping[str, Any]], Awaitable[int]] = db_modify_contact,
        delete_contacts_fn: Callable[[Sequence[str]], Awaitable[int]] = db_delete_contacts,
        get_on_call_contact_fn: Callable[[], Awaitable[Mapping[str, Any] | None]] = db_get_on_call_contact,
        address_book_table: Any = AddressBook,
    ) -> None:
        self.add_contact_fn = add_contact_fn
        self.modify_contact_fn = modify_contact_fn
        self.delete_contacts_fn = delete_contacts_fn
        self.get_on_call_contact_fn = get_on_call_contact_fn
        self.address_book_table = address_book_table

    async def add_new_contact(self, payload: Mapping[str, Any]) -> str:
        """
        Validates and adds a new contact.

        Args:
            payload: Contact dictionary.

        Returns:
            The generated contact identifier.

        Raises:
            ContactValidationError: If required data is invalid.
        """
        if not payload.get("name") or not str(payload.get("name")).strip():
            raise ContactValidationError("Contact name is required.")
        return await self.add_contact_fn(payload)

    async def update_contact(self, contact_id: str, changes: Mapping[str, Any]) -> int:
        """
        Updates an existing contact by ID.

        Args:
            contact_id: Target contact UUID.
            changes: Mapping of modified attributes.

        Returns:
            Number of rows updated (0 or 1).
        """
        clean_changes = {k: v for k, v in changes.items() if k != "id"}
        return await self.modify_contact_fn(contact_id, clean_changes)

    async def remove_contacts(self, ids: Sequence[str]) -> int:
        """
        Deletes contacts matching provided IDs.

        Args:
            ids: List of UUID strings.

        Returns:
            Count of deleted records.
        """
        if not ids:
            return 0
        return await self.delete_contacts_fn(ids)

    async def resolve_on_call_contact(self) -> Mapping[str, Any] | None:
        """
        Retrieves the current on-call contact phone number if active.

        Returns:
            Contact record mapping or None.
        """
        return await self.get_on_call_contact_fn()

    async def export_csv(self) -> str:
        """
        Serializes all AddressBook table rows into a CSV string.

        Returns:
            Full CSV content as string.
        """
        rows = await self.address_book_table.select()
        output = io.StringIO()
        writer = csv.writer(output)
        headers = [
            "id",
            "name",
            "surname",
            "address",
            "zip_code",
            "city",
            "state",
            "country",
            "phone_number",
            "enabled",
            "created_time",
            "annotations",
            "on_call_availability",
        ]
        writer.writerow(headers)
        for r in rows:
            writer.writerow(
                [
                    str(r.get("id")),
                    r.get("name") or "",
                    r.get("surname") or "",
                    r.get("address") or "",
                    r.get("zip_code") or "",
                    r.get("city") or "",
                    r.get("state") or "",
                    r.get("country") or "",
                    r.get("phone_number") or "",
                    "true" if r.get("enabled") else "false",
                    r.get("created_time") or "",
                    r.get("annotations") or "",
                    serialize_json_field(r.get("on_call_availability") or []),
                ]
            )
        output.seek(0)
        return output.getvalue()

    async def import_csv(self, content: str) -> ImportSummary:
        """
        Parses, validates, and imports contact records from CSV content.

        Args:
            content: Raw CSV string.

        Returns:
            An ImportSummary with counts of processed, created, updated, and errors.
        """
        reader = csv.DictReader(io.StringIO(content))
        processed = 0
        created = 0
        updated = 0
        errors: list[dict[str, Any]] = []
        batch_new: list[dict[str, Any]] = []
        batch_updates: list[tuple[str, dict[str, Any]]] = []

        table = self.address_book_table
        try:
            existing_rows = await table.select(
                getattr(table, "id", "id"),
                getattr(table, "name", "name"),
                getattr(table, "surname", "surname"),
                getattr(table, "phone_number", "phone_number"),
            )
        except Exception:
            existing_rows = await table.select()
        existing_ids = {str(r.get("id")) for r in existing_rows}

        by_pns = {
            (
                normalize_string(r.get("phone_number")),
                normalize_string(r.get("name")),
                normalize_string(r.get("surname")),
            ): str(r.get("id"))
            for r in existing_rows
        }

        for idx, row in enumerate(reader, start=2):
            try:
                processed += 1
                r = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
                cid = r.get("id") or None
                enabled_str = r.get("enabled", "").lower()
                enabled = (
                    True
                    if enabled_str in ("true", "1", "yes", "y")
                    else False
                    if enabled_str in ("false", "0", "no", "n")
                    else None
                )
                avail_raw = r.get("on_call_availability") or "[]"
                try:
                    s = (avail_raw or "").strip()
                    val = json.loads(s) if s else []
                    if isinstance(val, str):
                        try:
                            val2 = json.loads(val)
                            val = val2
                        except Exception:
                            pass
                    on_call_availability = val if isinstance(val, list) else []
                except Exception:
                    on_call_availability = []

                contact_raw_data = {
                    "id": cid,
                    "name": r.get("name", ""),
                    "surname": r.get("surname", ""),
                    "address": r.get("address", ""),
                    "zip_code": r.get("zip_code", ""),
                    "city": r.get("city", ""),
                    "state": r.get("state", ""),
                    "country": r.get("country", ""),
                    "phone_number": r.get("phone_number", ""),
                    "enabled": enabled,
                    "annotations": r.get("annotations", ""),
                    "on_call_availability": on_call_availability,
                }

                try:
                    validated = ContactCSVRow(**contact_raw_data)
                except ValidationError as val_err:
                    err_msgs = "; ".join(
                        [f"{e['loc'][0]}: {e['msg']}" for e in val_err.errors()]
                    )
                    errors.append(
                        {"row": idx, "error": f"Schema validation error: {err_msgs}"}
                    )
                    continue

                changes = {
                    "name": validated.name,
                    "surname": validated.surname,
                    "address": validated.address,
                    "zip_code": validated.zip_code,
                    "city": validated.city,
                    "state": validated.state,
                    "country": validated.country,
                    "phone_number": validated.phone_number,
                    "annotations": validated.annotations,
                    "on_call_availability": validated.on_call_availability,
                }
                if validated.enabled is not None:
                    changes["enabled"] = validated.enabled

                target_id = None
                if cid and cid in existing_ids:
                    target_id = cid
                else:
                    key = (
                        normalize_string(changes.get("phone_number")),
                        normalize_string(changes.get("name")),
                        normalize_string(changes.get("surname")),
                    )
                    target_id = by_pns.get(key)

                if target_id:
                    batch_updates.append((target_id, changes))
                else:
                    payload = changes.copy()
                    if "enabled" not in payload:
                        payload["enabled"] = False
                    batch_new.append(payload)
            except Exception as ex:
                errors.append({"row": idx, "error": str(ex)})

        # Chunked asynchronous processing of updates
        for i in range(0, len(batch_updates), 10):
            chunk = batch_updates[i : i + 10]
            for uid, ch in chunk:
                try:
                    await self.modify_contact_fn(uid, ch)
                    updated += 1
                except Exception as ex:
                    errors.append({"id": uid, "error": str(ex)})
            await asyncio.sleep(0)

        # Chunked asynchronous processing of creates
        for i in range(0, len(batch_new), 10):
            chunk = batch_new[i : i + 10]
            for item in chunk:
                try:
                    await self.add_contact_fn(item)
                    created += 1
                except Exception as ex:
                    errors.append({"name": item.get("name"), "error": str(ex)})
            await asyncio.sleep(0)

        return ImportSummary(
            processed_rows=processed,
            created=created,
            updated=updated,
            errors_count=len(errors),
            errors=errors[:10],
        )
