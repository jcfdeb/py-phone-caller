"""
Asterisk Recaller service orchestrator and entry point.

Periodically evaluates call attempts that require retries and orchestrates
escalation calls to on-call contacts when primary alerts are not acknowledged.
Provides backward-compatible facades delegating to modular schemas, client,
and services.
"""

from __future__ import annotations
import asyncio
import logging
import os
import signal
import sys
from typing import Any

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

from aiohttp import web_exceptions

from py_phone_caller_utils.py_phone_caller_db.db_asterisk_recaller import (
    increment_backup_call_count,
    select_backup_calls,
    select_to_recall,
)
from py_phone_caller_utils.py_phone_caller_db.db_address_book import (
    get_on_call_contacts,
)
from py_phone_caller_utils.telemetry import init_telemetry

from asterisk_recaller.constants import (
    ASTERISK_CALL_APP_ROUTE_PLACE_CALL,
    ASTERISK_CALL_URL,
    CALL_BACKUP_CALLEE_MAX_TIMES,
    CLIENT_TIMEOUT_TOTAL,
    LOG_FORMATTER,
    LOG_LEVEL,
    SECONDS_TO_FORGET,
    SLEEP_AND_RETRY,
    SLEEP_BEFORE_QUERYING,
    TIMES_TO_DIAL,
)
from asterisk_recaller.client import AsteriskCallClient
from asterisk_recaller.exceptions import (
    AsteriskRecallerError,
    NoOnCallContactsError,
    RecallerConnectionError,
)
from asterisk_recaller.schemas import (
    BackupCallItem,
    OnCallContact,
    RecallCycleResult,
    RecallItem,
)
from asterisk_recaller.services import RecallerService

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
init_telemetry("asterisk_recaller")


async def recall_post(
    phone: str,
    message: str,
    backup_callee: str = "false",
) -> None:
    """
    Sends a POST request to the Asterisk call service to initiate a recall.

    Backward-compatible facade delegating to AsteriskCallClient.

    Args:
        phone: Recipient telephone number.
        message: Alert message to deliver.
        backup_callee: Whether this is a backup escalation ("true" or "false").

    Returns:
        None
    """
    client = AsteriskCallClient(
        base_url=globals().get("ASTERISK_CALL_URL", ASTERISK_CALL_URL),
        place_call_route=globals().get(
            "ASTERISK_CALL_APP_ROUTE_PLACE_CALL", ASTERISK_CALL_APP_ROUTE_PLACE_CALL
        ),
        timeout_total=globals().get("CLIENT_TIMEOUT_TOTAL", CLIENT_TIMEOUT_TOTAL),
    )
    await client.place_call(phone, message, backup_callee=backup_callee)


async def run_single_recall_cycle() -> int:
    """
    Executes a single recall evaluation cycle.

    Orchestrates primary recall retry dispatching and backup escalations.
    Delegates to RecallerService using dynamically resolved module attributes
    for full compatibility with runtime monkeypatches and Celery beat tasks.

    Returns:
        Total number of recall actions performed.
    """
    service = RecallerService(
        call_client_fn=globals().get("recall_post", recall_post),
        select_to_recall_fn=globals().get("select_to_recall", select_to_recall),
        select_backup_calls_fn=globals().get("select_backup_calls", select_backup_calls),
        get_on_call_contacts_fn=globals().get("get_on_call_contacts", get_on_call_contacts),
        increment_backup_call_count_fn=globals().get(
            "increment_backup_call_count", increment_backup_call_count
        ),
        times_to_dial=globals().get("TIMES_TO_DIAL", TIMES_TO_DIAL),
        seconds_to_forget=globals().get("SECONDS_TO_FORGET", SECONDS_TO_FORGET),
        sleep_and_retry=globals().get("SLEEP_AND_RETRY", SLEEP_AND_RETRY),
        call_backup_callee_max_times=globals().get(
            "CALL_BACKUP_CALLEE_MAX_TIMES", CALL_BACKUP_CALLEE_MAX_TIMES
        ),
    )
    return await service.run_single_cycle()


async def asterisk_recaller() -> None:
    """
    Periodically checks for calls that need to be retried and initiates recall attempts.

    Maintains the persistent daemon loop with resilient error recovery.
    """
    while True:
        try:
            await run_single_recall_cycle()
            await asyncio.sleep(SLEEP_BEFORE_QUERYING)
        except Exception as err:
            logging.exception(f"Problem during recall cycle: '{err}'")
            logging.info("Retrying in 5 seconds...")
            await asyncio.sleep(5)


def receive_signal(signal_number: int, frame: Any) -> None:
    """
    Handles received system signals and exits the program gracefully.

    Args:
        signal_number: POSIX signal number (SIGINT=2, SIGTERM=15).
        frame: Current stack frame (unused).
    """
    print("Exiting On Signal:", signal_number)
    match signal_number:
        case 2:
            sys.exit(0)
        case 15:
            sys.exit(0)


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGTERM, receive_signal)
        signal.signal(signal.SIGINT, receive_signal)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(asterisk_recaller())
        loop.run_forever()
    except OSError as err:
        logging.exception(f"Error when starting the event loop -> {err}")
        sys.exit(1)
    except web_exceptions.HTTPClientError as err:
        logging.exception(f"Can't generate the audio file -> {err}")
        sys.exit(1)
    except KeyboardInterrupt as err:
        logging.exception(f"Process terminated due Interrupt -> {err}")
        sys.exit(0)
