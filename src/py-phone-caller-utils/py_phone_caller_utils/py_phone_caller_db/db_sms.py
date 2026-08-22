import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from py_phone_caller_utils.config import settings
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    Sms,
)

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)

RUNTIME_LOOP_IN_ERROR = "got Future attached to a different loop"
RUNTIME_LOOP_ERROR_MESSAGE = (
    "This may indicate that database operations are being performed in different event loops."
)


async def insert_sms(
    phone: str,
    message: str,
    carrier: str = "",
    status: str = "queued",
    error: str = "",
    created_at: Optional[datetime] = None,
) -> str:
    """
    Inserts a new SMS record into the sms table.

    :param phone: The recipient's phone number.
    :param message: The SMS message content.
    :param carrier: The carrier backend used (e.g., 'on_premise', 'twilio').
    :param status: The delivery status (e.g., 'queued', 'sent', 'failed', 'duplicate_ignored').
    :param error: Any error message if delivery failed.
    :param created_at: Optional timestamp; defaults to UTC now.
    :return: The UUID string of the created record.
    """
    if created_at is None:
        created_at = datetime.now(UTC).replace(tzinfo=None)

    record = Sms(
        phone=phone or "",
        message=message or "",
        carrier=carrier or "",
        status=status or "",
        error=error or "",
        created_at=created_at,
    )
    try:
        await Sms.insert(record)
        return str(record.id)
    except RuntimeError as e:
        if RUNTIME_LOOP_IN_ERROR in str(e):
            logging.error(f"Event loop error in insert_sms: {e}")
            logging.error(RUNTIME_LOOP_ERROR_MESSAGE)
        raise
    except Exception as e:
        logging.error(f"Error in insert_sms: {e}")
        raise


def insert_sms_sync(
    phone: str,
    message: str,
    carrier: str = "",
    status: str = "queued",
    error: str = "",
    created_at: Optional[datetime] = None,
) -> str:
    """
    Synchronously inserts a new SMS record into the Sms table.
    """
    if created_at is None:
        created_at = datetime.now(UTC).replace(tzinfo=None)

    record = Sms(
        phone=phone or "",
        message=message or "",
        carrier=carrier or "",
        status=status or "",
        error=error or "",
        created_at=created_at,
    )
    Sms.insert(record).run_sync()
    return str(record.id)


async def select_sms(
    limit: Optional[int] = None,
    phone: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Retrieves SMS records from the Sms table, ordered by creation time descending.

    :param limit: Optional limit on the number of records returned.
    :param phone: Optional phone number filter.
    :param status: Optional status filter.
    :return: List of SMS records.
    """
    try:
        query = Sms.select().order_by(Sms.created_at, ascending=False)
        if phone:
            query = query.where(Sms.phone == phone)
        if status:
            query = query.where(Sms.status == status)
        if limit:
            query = query.limit(limit)
        return await query
    except RuntimeError as e:
        if RUNTIME_LOOP_IN_ERROR in str(e):
            logging.error(f"Event loop error in select_sms: {e}")
            logging.error(RUNTIME_LOOP_ERROR_MESSAGE)
        raise
    except Exception as e:
        logging.error(f"Error in select_sms: {e}")
        return []


def select_sms_sync(
    limit: Optional[int] = None,
    phone: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Synchronously retrieves SMS records from the Sms table.
    """
    query = Sms.select().order_by(Sms.created_at, ascending=False)
    if phone:
        query = query.where(Sms.phone == phone)
    if status:
        query = query.where(Sms.status == status)
    if limit:
        query = query.limit(limit)
    return query.run_sync()
