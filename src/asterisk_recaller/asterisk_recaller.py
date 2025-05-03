import asyncio
import datetime
import logging
import signal

from aiohttp import ClientSession, client_exceptions, web_exceptions

import py_phone_caller_utils.caller_configuration as conf
from py_phone_caller_utils.py_phone_caller_db.db_asterisk_recaller import \
    select_to_recall

logging.basicConfig(format=conf.get_log_formatter())

SLEEP_BEFORE_QUERYING = 10
times_to_dial = conf.get_times_to_dial()
seconds_to_forget = conf.get_seconds_to_forget()
sleep_and_retry = seconds_to_forget / (times_to_dial + 1)


async def recall_post(phone, message):
    """
    Sends a POST request to the Asterisk call service to initiate a recall for the specified phone and message.

    This asynchronous function attempts to place a call using the configured Asterisk call endpoint and logs any connection errors.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message to be delivered during the call.

    Returns:
        None
    """
    asterisk_call_url = conf.get_asterisk_call_url()
    session_recall_post = ClientSession()
    try:
        call_register_resp = await session_recall_post.post(
            url=asterisk_call_url
            + f"/{conf.get_asterisk_call_app_route_place_call()}"
            + f"?phone={phone}&message={message}",
            data=None,
        )
        message = await call_register_resp.text()
    except client_exceptions.ClientConnectorError as err:
        logging.exception(f"Unable to connect to the Asterisk Call service: '{err}'")
    finally:
        await session_recall_post.close()


async def asterisk_recall():
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
                seconds=seconds_to_forget
            )
            greater_sleep_and_retry = now_utc - datetime.timedelta(
                seconds=sleep_and_retry
            )

            select_recall = await select_to_recall(
                times_to_dial,
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

                    await asyncio.sleep(sleep_and_retry)

            await asyncio.sleep(SLEEP_BEFORE_QUERYING)

        except Exception as err:
            logging.exception(f"Problem with the PostgreSQL connection: '{err}'")
            exit(1)


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
        loop.run_until_complete(asterisk_recall())
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
