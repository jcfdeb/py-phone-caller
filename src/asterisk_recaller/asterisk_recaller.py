import asyncio
import datetime
import logging

from aiohttp import ClientSession, client_exceptions, web, web_exceptions

import caller_utils.caller_configuration as conf
from caller_utils.db.db_asterisk_recaller import select_to_recall

logging.basicConfig(format=conf.get_log_formatter())

SLEEP_BEFORE_QUERYING = 10
times_to_dial = conf.get_times_to_dial()
seconds_to_forget = conf.get_seconds_to_forget()
sleep_and_retry = seconds_to_forget / (times_to_dial + 1)


async def recall_post(phone, message):
    """Makes the POST against the 'asterisk_call' service in order to call again"""
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
    """Recall no answered calls following the number of retries and configured time frame
    to contact the callee again. Using the information stored in PostgreSQL by 'caller_register.py'"""

    while True:
        try:

            lesser_seconds_to_forget = datetime.datetime.utcnow() - datetime.timedelta(
                seconds=seconds_to_forget
            )
            greater_sleep_and_retry = datetime.datetime.utcnow() - datetime.timedelta(
                seconds=sleep_and_retry
            )
            select_recall = await select_to_recall(
                times_to_dial, lesser_seconds_to_forget, greater_sleep_and_retry
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
                    # Sleep some seconds a retry...

                    await asyncio.sleep(sleep_and_retry)

            await asyncio.sleep(SLEEP_BEFORE_QUERYING)  # Don't stress the CPU...

        except Exception as err:
            logging.exception(f"Problem with the PostgreSQL connection: '{err}'")
            exit(1)


if __name__ == "__main__":
    try:
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
