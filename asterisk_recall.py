import asyncio
import datetime
import logging as sync_logger

import aiologger
import asyncpg
from aiohttp import ClientSession, client_exceptions, web, web_exceptions
from aiologger.formatters.base import Formatter
from aiologger.levels import LogLevel

import local_utils.caller_configuration as conf
import local_utils.db_conn as db_conn

LOG_FORMATTER = conf.get_log_formatter()
ASTERISK_CALL_HTTP_SCHEME = conf.get_asterisk_call_http_scheme()
ASTERISK_CALL_HOST = conf.get_asterisk_call_host()
ASTERISK_CALL_PORT = conf.get_asterisk_call_port()
ASTERISK_CALL_APP_ROUTE_ASTERISK_INIT = conf.get_asterisk_call_app_route_asterisk_init()
ASTERISK_CALL_URL = (
    f"{ASTERISK_CALL_HTTP_SCHEME}://{ASTERISK_CALL_HOST}:{ASTERISK_CALL_PORT}"
)
TIMES_TO_DIAL = conf.get_times_to_dial()
SECONDS_TO_FORGET = conf.get_seconds_to_forget()
SLEEP_AND_RETRY = SECONDS_TO_FORGET / (TIMES_TO_DIAL + 1)
DB_HOST = conf.get_db_host()
DB_NAME = conf.get_db_name()
DB_USER = conf.get_db_user()
DB_PASSWORD = conf.get_db_password()
DB_MAX_SIZE = conf.get_db_max_size()
DB_MAX_INACTIVE_CONNECTION_LIFETIME = conf.get_db_max_inactive_connection_lifetime()

LOGGER = aiologger.Logger.with_default_handlers(
    name="asterisk_recall",
    level=LogLevel.INFO,
    formatter=Formatter(fmt=LOG_FORMATTER),
)


async def recall_post(phone, message):
    """Makes the POST against the 'asterisk_call' service in order to call again"""
    try:
        session = ClientSession()
        callregister_resp = await session.post(
            url=ASTERISK_CALL_URL
            + f"/{ASTERISK_CALL_APP_ROUTE_ASTERISK_INIT}"
            + f"?phone={phone}&message={message}",
            data=None,
        )
        message = await callregister_resp.text()
        await session.close()
    except client_exceptions.ClientConnectorError as e:
        await session.close()
        LOGGER.error(f"Unable to connect to the Asterisk Call service: '{e}'")


async def asterisk_recall():
    """Recall no answered calls following the number of retries and configured time frame
    to contact the callee again. Using the information stored in PostgreSQL by 'call_register.py'"""
    recall_pool = await db_conn.pool_init(
        DB_HOST,
        DB_NAME,
        DB_USER,
        DB_PASSWORD,
        DB_MAX_SIZE,
        DB_MAX_INACTIVE_CONNECTION_LIFETIME,
    )

    while True:
        try:
            # Take a connection from the pool.
            async with recall_pool.acquire() as connection:
                async with connection.transaction():
                    select_recall = await connection.fetch(
                        """
                        SELECT * FROM calls WHERE dialed_times < $1 AND  first_dial >= $2 AND first_dial <= $3 AND cycle_done = FALSE
                        """,
                        TIMES_TO_DIAL,
                        (
                            datetime.datetime.utcnow()
                            - datetime.timedelta(seconds=SECONDS_TO_FORGET)
                        ),
                        (
                            datetime.datetime.utcnow()
                            - datetime.timedelta(seconds=SLEEP_AND_RETRY)
                        ),
                    )

                    for i, _ in enumerate(select_recall):
                        await LOGGER.info(
                            f"Retry to call phone number: '{select_recall[i].get('phone')}' to play the message: "
                            + f"'{select_recall[i].get('message')}' "
                            + f"- Total retry period: '{select_recall[i].get('seconds_to_forget')}' seconds"
                        )
                        await recall_post(
                            select_recall[i].get("phone"),
                            select_recall[i].get("message"),
                        )
                        # Sleep some seconds a retry...
                        await asyncio.sleep(SLEEP_AND_RETRY)

                    await asyncio.sleep(0.1)  # Don't stress the CPU...

        except asyncpg.exceptions.ConnectionDoesNotExistError as e:
            await LOGGER.error(f"Problem with the PostgreSQL connection: '{e}'")
            exit(1)


try:
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asterisk_recall())
    loop.run_forever()
except OSError as e:
    sync_logger.basicConfig(format=LOG_FORMATTER)
    sync_logger.error(f"Error when starting the event loop... {e}")
    exit(1)
except web_exceptions.HTTPClientError as e:
    sync_logger.basicConfig(format=LOG_FORMATTER)
    sync_logger.error(f"Can't generate the audio file... {e}")
    exit(1)
except KeyboardInterrupt as e:
    sync_logger.basicConfig(format=LOG_FORMATTER)
    sync_logger.error(f"Process terminated due Interrupt. {e}")
    exit(0)
