import asyncio
import datetime
import logging
from hashlib import blake2b

import aiologger
import asyncpg
from aiohttp import web
from aiologger.formatters.base import Formatter
from aiologger.levels import LogLevel

import local_utils.caller_configuration as conf

LOG_FORMATTER = conf.get_log_formatter()
ACKNOWLEDGE_ERROR = conf.get_acknowledge_error()
HEARD_ERROR = conf.get_heard_error()
CALL_REGISTER_PORT = conf.get_call_register_port()
CALL_REGISTER_APP_ROUTE_REGISTER_CALL = conf.get_call_register_app_route_register_call()
CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE = conf.get_call_register_app_route_voice_message()
CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE = conf.get_call_register_app_route_acknowledge()
CALL_REGISTER_APP_ROUTE_HEARD = conf.get_call_register_app_route_heard()
REGISTERCALL_ERROR = conf.get_registercall_error()
VOICE_MESSAGE_ERROR = conf.get_voice_message_error()
DB_HOST = conf.get_db_host()
DB_NAME = conf.get_db_name()
DB_USER = conf.get_db_user()
DB_PASSWORD = conf.get_db_password()
DB_MAX_SIZE = conf.get_db_max_size()
DB_MAX_INACTIVE_CONNECTION_LIFETIME = conf.get_db_max_inactive_connection_lifetime()
SECONDS_TO_FORGET = conf.get_seconds_to_forget()
TIMES_TO_DIAL = conf.get_times_to_dial()

LOGGER = aiologger.Logger.with_default_handlers(
    name="call_register",
    level=LogLevel.INFO,
    formatter=Formatter(fmt=LOG_FORMATTER),
)


async def present_or_not_logger(phone, first_dial_age, message):
    """Used for display a better indication of the call status"""
    if first_dial_age:
        return LOGGER.info(
            f"A call for '{phone}' was started '{first_dial_age}' ago, with the message '{message}' "
            + f"and is inside our retry period of '{SECONDS_TO_FORGET}' seconds. "
            + f"We're currently managing this call."
        )
    else:
        return LOGGER.info(
            f"A previous call was for '{phone}' with the message '{message}' is outside of our retry period "
            + f"('{SECONDS_TO_FORGET}' seconds) we'll start a new cycle."
        )


# Refactoring by pulling out several nested functions that can be taken out
async def insert_into_db(
    connection,
    phone,
    message,
    asterisk_chan,
    msg_chk_sum,
    call_chk_sum,
    unique_chk_sum,
    first_dial,
    SECONDS_TO_FORGET,
    TIMES_TO_DIAL,
):
    """Function to insert a 'new' record"""
    dialed_times = 0
    await connection.execute(
        """
        INSERT INTO calls(phone,message,asterisk_chan,msg_chk_sum,call_chk_sum,unique_chk_sum,first_dial,
        dialed_times,SECONDS_TO_FORGET,TIMES_TO_DIAL) VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """,
        phone,
        message,
        asterisk_chan,
        msg_chk_sum,
        call_chk_sum,
        unique_chk_sum,
        first_dial,
        dialed_times + 1,
        SECONDS_TO_FORGET,
        TIMES_TO_DIAL,
    )
    return LOGGER.info(
        f"New cycle for the number '{phone}' with the message '{message}' starting at '{first_dial}'."
    )


# DB Query operations
async def get_first_dial_age(connection, call_chk_sum, current_call_id):
    """Helper to calculate the call record age"""
    return await connection.fetchval(
        """SELECT AGE((SELECT timezone('utc', now())),first_dial) FROM calls WHERE call_chk_sum=$1 AND id=$2""",
        call_chk_sum,
        current_call_id,
    )


async def get_current_call_id(connection, SECONDS_TO_FORGET, call_chk_sum):
    """Getting the current call ID based on the 'SECONDS_TO_FORGET' parameter"""
    return await connection.fetchval(
        """SELECT id from calls where ((AGE((SELECT timezone('utc', now())),first_dial)) < (SELECT $1 * '1 seconds'::interval)) AND call_chk_sum=$2;""",
        SECONDS_TO_FORGET,
        str(call_chk_sum),
    )


async def get_dialed_times(connection, SECONDS_TO_FORGET, call_chk_sum):
    """Getting the number of dials of a given alert"""
    return await connection.fetchval(
        """SELECT dialed_times from calls where ((AGE((SELECT timezone('utc', now())),first_dial)) < (SELECT $1 * '1 seconds'::interval)) AND call_chk_sum=$2;""",
        SECONDS_TO_FORGET,
        call_chk_sum,
    )


# Checksums functions
async def gen_call_chk_sum(phone, message):
    """Generates a call checksum in order correlate a phone number and a message"""
    return blake2b(
        bytes(phone, encoding="utf-8") + bytes(message, encoding="utf-8"),
        digest_size=4,
    ).hexdigest()


async def gen_msg_chk_sum(message):
    """Generates a checksum in order to identify the message"""
    return blake2b(bytes(message, encoding="utf-8"), digest_size=4).hexdigest()


async def gen_unique_chk_sum(phone, message, first_dial):
    """Generates a checksum in order to identify every single call"""
    return blake2b(
        bytes(phone, encoding="utf-8")
        + bytes(message, encoding="utf-8")
        + bytes(str(first_dial), encoding="utf-8"),
        digest_size=4,
    ).hexdigest()


async def start_pool(request):
    """Prepare the connection pool with a fake 'request' to be shadowed with the right one"""
    return request.app["pool"]


async def register_call(request):
    """Handle incoming requests coming to '/CALL_REGISTER_APP_ROUTE_REGISTER_CALL'
    can be configured through an environmental variable or form the config file
    """
    try:
        pool = await start_pool(request)
    except KeyError:
        LOGGER.error(f"No PostgreSQL Connection 'pool' available.")

    # Take a connection from the pool.
    async with pool.acquire() as connection:
        async with connection.transaction():
            try:
                phone = request.rel_url.query["phone"]
            except KeyError:
                phone = None
                LOGGER.error(f"No 'phone' parameter passed on: '{request.rel_url}'")
                raise web.HTTPClientError(
                    reason=REGISTERCALL_ERROR,
                    body=None,
                    text=None,
                    content_type=None,
                )
            try:
                message = request.rel_url.query["message"]
            except KeyError:
                message = None
                LOGGER.error(f"No 'messagge' parameter passed on: '{request.rel_url}'")
                raise web.HTTPClientError(
                    reason=REGISTERCALL_ERROR,
                    body=None,
                    text=None,
                    content_type=None,
                )
            try:
                asterisk_chan = request.rel_url.query["asterisk_chan"]
            except KeyError:
                asterisk_chan = None

            # Used to for the call control logics
            call_chk_sum = await gen_call_chk_sum(phone, message)
            msg_chk_sum = await gen_msg_chk_sum(message)
            first_dial = datetime.datetime.utcnow()
            unique_chk_sum = await gen_unique_chk_sum(phone, message, first_dial)

            # Verify for record existence
            call_yet_present = await connection.fetchval(
                """SELECT call_chk_sum FROM calls WHERE call_chk_sum=$1;""",
                call_chk_sum,
            )
            LOGGER.info(
                f"Call received for the number '{phone}' with the message '{message}'."
            )

            if call_yet_present is None:
                LOGGER.info(
                    f"Is the first call for '{phone}' with the message '{message}'."
                )
                await insert_into_db(
                    connection,
                    phone,
                    message,
                    asterisk_chan,
                    msg_chk_sum,
                    call_chk_sum,
                    unique_chk_sum,
                    first_dial,
                    SECONDS_TO_FORGET,
                    TIMES_TO_DIAL,
                )
            else:
                current_call_id = await get_current_call_id(
                    connection, SECONDS_TO_FORGET, call_chk_sum
                )

                try:

                    first_dial_age = await get_first_dial_age(
                        connection, call_chk_sum, current_call_id
                    )
                    await present_or_not_logger(phone, first_dial_age, message)

                except TypeError:
                    LOGGER.info(
                        f"There's not uncompleted cycle for '{phone}' with the message"
                        + f" '{message}' in the last '{SECONDS_TO_FORGET}' seconds."
                    )
                    first_dial_age = None

                current_dialed_times = await get_dialed_times(
                    connection, SECONDS_TO_FORGET, call_chk_sum
                )

                try:
                    if first_dial_age < datetime.timedelta(seconds=SECONDS_TO_FORGET):

                        await connection.execute(
                            """UPDATE calls SET last_dial = $2, dialed_times = $4, asterisk_chan = $5 WHERE call_chk_sum=$1 AND id=$3 """,
                            call_chk_sum,
                            datetime.datetime.utcnow(),
                            current_call_id,
                            current_dialed_times + 1,
                            asterisk_chan,
                        )
                        LOGGER.info(
                            f"Updating the call status for the number '{phone}' with the message '{message}'."
                        )
                except TypeError:
                    await insert_into_db(
                        connection,
                        phone,
                        message,
                        asterisk_chan,
                        msg_chk_sum,
                        call_chk_sum,
                        unique_chk_sum,
                        first_dial,
                        SECONDS_TO_FORGET,
                        TIMES_TO_DIAL,
                    )

            return web.json_response({"status": 200})
    await LOGGER.shutdown()


async def acknowledge(request):
    """Handle incoming requests coming to '/ack'"""
    # TODO manage the acknowledge of the call, when the callee press a number
    # use in asterisk to call this endpoint "${CHANNEL(uniqueid)}"
    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
    except KeyError:
        asterisk_chan = None
        LOGGER.error(f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=ACKNOWLEDGE_ERROR, body=None, text=None, content_type=None
        )
    try:
        pool = await start_pool(request)
    except KeyError:
        LOGGER.error(f"No PostgreSQL Connection 'pool' available.")

    # Take a connection from the pool.
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                """UPDATE calls SET acknowledge_at = $2, cycle_done = TRUE WHERE asterisk_chan=$1""",
                asterisk_chan,
                datetime.datetime.utcnow(),
            )
    # TODO improve the status code reflecting the result of the query (call ack)
    return web.json_response({"status": 200})


async def heard(request):
    """Handle incoming requests coming to '/heard'"""
    # TODO if the massage was payed add a record with the timestamp
    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
    except KeyError:
        asterisk_chan = None
        LOGGER.error(f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=HEARD_ERROR, body=None, text=None, content_type=None
        )
    try:
        pool = await start_pool(request)
    except KeyError:
        LOGGER.error(f"No PostgreSQL Connection 'pool' available.")

    # Take a connection from the pool.
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute(
                """UPDATE calls SET heard_at = $2 WHERE asterisk_chan=$1""",
                asterisk_chan,
                datetime.datetime.utcnow(),
            )
    # TODO improve the status code reflecting the result of the query (call heard)
    return web.json_response({"status": 200})


async def voice_message(request):
    """Handle incoming requests coming to '/msg'"""
    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
    except KeyError:
        asterisk_chan = None
        LOGGER.error(f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=VOICE_MESSAGE_ERROR,
            body=None,
            text=None,
            content_type=None,
        )
    # Connection to the DB
    try:
        pool = await start_pool(request)
    except KeyError:
        LOGGER.error(f"No PostgreSQL Connection 'pool' available.")

    # Take a connection from the pool.
    async with pool.acquire() as connection:
        async with connection.transaction():
            get_msg = await connection.fetchrow(
                """SELECT message,msg_chk_sum FROM calls WHERE asterisk_chan = $1""",
                asterisk_chan,
            )
            # Sending an empty response if no data is restored from the query
            try:
                assert get_msg is None
                get_msg = {"message": "", "msg_chk_sum": ""}
            except AssertionError:
                pass
    return web.json_response(dict(get_msg))


async def init_app():
    """Start the Application Web Server."""
    app = web.Application()
    # Connection pool against PostgreSQL
    try:
        app["pool"] = await asyncpg.create_pool(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            max_size=DB_MAX_SIZE,
            max_inactive_connection_lifetime=DB_MAX_INACTIVE_CONNECTION_LIFETIME,
        )
    except OSError as e:
        LOGGER.fatal(f"Error during database connection: '{e}'")

    # And... here our routes
    app.router.add_route(
        "POST", f"/{CALL_REGISTER_APP_ROUTE_REGISTER_CALL}", register_call
    )
    app.router.add_route(
        "POST", f"/{CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE}", voice_message
    )
    app.router.add_route("GET", f"/{CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE}", acknowledge)
    app.router.add_route("GET", f"/{CALL_REGISTER_APP_ROUTE_HEARD}", heard)
    return app


loop = asyncio.get_event_loop()
app = loop.run_until_complete(init_app())
logging.basicConfig(level=logging.INFO)
web.run_app(app, port=CALL_REGISTER_PORT)
