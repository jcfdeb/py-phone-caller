"""
Asterisk Recaller service.

This module periodically scans for call attempts that need to be retried and
optionally performs backup calls to on-call contacts when the original call is
not acknowledged.

It communicates with the Asterisk Caller service and the database via
`py_phone_caller_utils`.
"""

import asyncio
import datetime
import logging
import signal
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)


from aiohttp import ClientSession, client_exceptions, web_exceptions

from py_phone_caller_utils.py_phone_caller_db.db_asterisk_recaller import (
    select_to_recall,
    select_backup_calls,
    increment_backup_call_count,
)
from py_phone_caller_utils.py_phone_caller_db.db_address_book import (
    get_on_call_contacts,
)
from py_phone_caller_utils.telemetry import init_telemetry

from asterisk_recaller.constants import (
    ASTERISK_CALL_URL,
    ASTERISK_CALL_APP_ROUTE_PLACE_CALL,
    LOG_FORMATTER,
    LOG_LEVEL,
    TIMES_TO_DIAL,
    SECONDS_TO_FORGET,
    SLEEP_AND_RETRY,
    SLEEP_BEFORE_QUERYING,
    CALL_BACKUP_CALLEE_MAX_TIMES,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("asterisk_recaller")


async def recall_post(phone, message, backup_callee="false"):
    """
    Sends a POST request to the Asterisk call service to initiate a recall for the specified phone and message.

    This asynchronous function attempts to place a call using the configured Asterisk call endpoint and logs any connection errors.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message to be delivered during the call.
        backup_callee (str): Whether this is a backup call ("true" or "false").

    Returns:
        None
    """
    asterisk_call_url = ASTERISK_CALL_URL
    session_recall_post = ClientSession()
    try:
        call_register_resp = await session_recall_post.post(
            url=asterisk_call_url
            + f"/{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}"
            + f"?phone={phone}&message={message}&backup_callee={backup_callee}",
            data=None,
        )
        message = await call_register_resp.text()
    except client_exceptions.ClientConnectorError as err:
        logging.exception(f"Unable to connect to the Asterisk Call service: '{err}'")
    finally:
        await session_recall_post.close()


async def asterisk_recaller():
    """
    Periodically checks for calls that need to be retried and initiates recall attempts.

    This asynchronous function queries the database for eligible calls, attempts to recall them, and handles timing and error logging.

    Returns:
        None
    """

    while True:
        try:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            lesser_seconds_to_forget = now_utc - datetime.timedelta(
                seconds=SECONDS_TO_FORGET
            )
            greater_sleep_and_retry = now_utc - datetime.timedelta(
                seconds=SLEEP_AND_RETRY
            )

            select_recall = await select_to_recall(
                TIMES_TO_DIAL,
                lesser_seconds_to_forget.replace(tzinfo=None),
                greater_sleep_and_retry.replace(tzinfo=None),
            )

            if select_recall is not None:
                for _, item_to_recall in enumerate(select_recall):
                    phone = item_to_recall.get("phone")
                    message = item_to_recall.get("message")
                    on_db_seconds_to_forget = item_to_recall.get("seconds_to_forget")
                    logging.info(
                        f"Retry to call phone number: '{phone}' to play the message: "
                        + f"'{message}' "
                        + f"- Total retry period: '{on_db_seconds_to_forget}' seconds"
                    )

                    await recall_post(
                        phone,
                        message,
                    )

                    await asyncio.sleep(SLEEP_AND_RETRY)

            # Backup calls logic - only selects calls where the main retry window has expired
            backup_calls = await select_backup_calls(
                CALL_BACKUP_CALLEE_MAX_TIMES,
            )

            if backup_calls:
                on_call_contacts = await get_on_call_contacts()
                if on_call_contacts:
                    for call in backup_calls:
                        call_id = call.get("id")
                        message = call.get("message")
                        original_phone = call.get("phone")
                        backup_count = call.get("call_backup_callee_number_calls")

                        # Primary was contacts[0], so backup 1 is contacts[1], etc.
                        # We use modulo to cycle through available backup contacts.
                        backup_idx = (backup_count + 1) % len(on_call_contacts)
                        backup_contact = on_call_contacts[backup_idx]
                        backup_phone = backup_contact.get("phone_number")

                        logging.info(
                            f"Call not acknowledged for '{original_phone}'. "
                            f"Backup attempt {backup_count + 1}. "
                            f"Initiating backup call to '{backup_phone}'."
                        )

                        await recall_post(backup_phone, message, backup_callee="true")
                        await increment_backup_call_count(call_id)
                        await asyncio.sleep(SLEEP_AND_RETRY)
                else:
                    logging.warning("No on-call contacts found for backup calls.")

            await asyncio.sleep(SLEEP_BEFORE_QUERYING)

        except Exception as err:
            logging.exception(f"Problem with the PostgreSQL connection: '{err}'")
            logging.info("Retrying connection in 5 seconds...")
            await asyncio.sleep(5)


def receive_signal(signal_number, frame):
    """
    Handles received system signals and exits the program gracefully.

    This function prints the received signal number and exits the process for SIGINT (2) or SIGTERM (15).

    Args:
        signal_number (int): The signal number received.
        frame: The current stack frame (unused).

    Returns:
        None
    """
    print("Exiting On Signal:", signal_number)
    match signal_number:
        case 2:
            exit(0)
        case 15:
            exit(0)


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGTERM, receive_signal)
        signal.signal(signal.SIGINT, receive_signal)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(asterisk_recaller())
        loop.run_forever()
    except OSError as err:
        logging.exception(f"Error when starting the event loop -> {err}")
        exit(1)
    except web_exceptions.HTTPClientError as err:
        logging.exception(f"Can't generate the audio file -> {err}")
        exit(1)
    except KeyboardInterrupt as err:
        logging.exception(f"Process terminated due Interrupt -> {err}")
        exit(0)
