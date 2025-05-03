import asyncio
import logging
import traceback
from datetime import UTC, datetime, timedelta

from aiohttp import web

import py_phone_caller_utils.caller_configuration as conf
from py_phone_caller_utils.checksums import (gen_call_chk_sum, gen_msg_chk_sum,
                                             gen_unique_chk_sum)
from py_phone_caller_utils.py_phone_caller_db.db_caller_register import (
    check_call_yet_present, get_current_call_id, get_dialed_times,
    get_first_dial_age, get_msg_chk_sum, insert_into_db,
    update_acknowledgement, update_heard_at, update_the_call_db_record)
from py_phone_caller_utils.py_phone_caller_db.db_scheduled_calls import \
    insert_scheduled_call
from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.piccolo_app import \
    APP_CONFIG

seconds_to_forget = conf.get_seconds_to_forget()
times_to_dial = conf.get_times_to_dial()

logging.basicConfig(level=logging.INFO)


async def run_piccolo_migrations():
    """
    Runs Piccolo migrations to set up or update the database schema for the application.

    This asynchronous function ensures a database connection, executes migrations, verifies tables, and logs the process.

    Returns:
        bool: True if migrations were successful, False otherwise.
    """

    logging.info("Running Piccolo migrations...")

    if not await _ensure_database_connection():
        return False

    try:
        logging.info(f"Found app config for {APP_CONFIG.app_name}")
        migration_success = await _execute_migrations()

        if migration_success:
            await _verify_tables()

        return migration_success
    except Exception as e:
        logging.error(f"Error in migration process: {e}")
        logging.error(traceback.format_exc())
        return False
    finally:
        logging.info("Piccolo migration process completed")


async def _ensure_database_connection():
    """
    Ensures that a connection pool to the database is established.

    This asynchronous function checks if the database connection pool exists and starts it if necessary, logging the connection status.

    Returns:
        bool: True if the connection is established successfully, False otherwise.
    """
    try:
        if DB.pool is None:
            await DB.start_connection_pool()
            logging.info("Connected to database")
        return True
    except Exception as e:
        logging.error(f"Error connecting to database: {e}")
        return False


async def _execute_migrations():
    """
    Executes Piccolo migrations for the application's database schema.

    This asynchronous function runs the migration commands and logs the outcome.

    Returns:
        bool: True if migrations were applied successfully, False otherwise.
    """
    try:

        from piccolo.apps.migrations.commands.forwards import forwards

        await forwards(app_name=APP_CONFIG.app_name)
        logging.info("Successfully applied migrations")
        return True
    except Exception as e:
        logging.error(f"Error running migrations: {e}")
        return False


async def _verify_tables():
    """
    Verifies the existence and status of all tables defined in the application configuration.

    This asynchronous function checks each table, logs the number of records if it exists, or logs an error if the table cannot be queried.

    Returns:
        None
    """
    tables = APP_CONFIG.table_classes
    if not tables:
        return

    logging.info(f"Verifying {len(tables)} tables...")
    tables_status = []

    for table_class in tables:
        try:
            count = await table_class.count()
            tables_status.append(
                f"{table_class.__name__}: exists (contains {count} records)"
            )
        except Exception as e:
            tables_status.append(
                f"{table_class.__name__}: error querying table - {str(e)}"
            )

    logging.info("Database tables status:")
    for status in tables_status:
        logging.info(f"{status}")


async def init_database():
    """
    Initializes the application's database by running migrations or creating tables directly if migrations fail.

    This asynchronous function attempts to run Piccolo migrations and, if unsuccessful, falls back to direct table creation, logging each step.

    Returns:
        None
    """
    logging.info("Initializing the database...")

    migration_success = await run_piccolo_migrations()

    if not migration_success:
        logging.warning("Migrations failed, falling back to direct table creation")

        try:

            for table_class in APP_CONFIG.table_classes:
                try:
                    logging.info(f"Creating table: {table_class.__name__}")
                    await table_class.create_table(if_not_exists=True)
                    logging.info(f"Table {table_class.__name__} created successfully")
                except Exception as e:
                    logging.error(f"Error creating table {table_class.__name__}: {e}")
        except Exception as e:
            logging.error(f"Error in fallback table creation: {e}")

    logging.info("Database initialization completed")


async def present_or_not_logger(phone, first_dial_time, message):
    """
    Logs whether a call for the given phone and message is within the retry period or if a new cycle will start.

    This asynchronous function checks the first dial time and logs the appropriate message about the call's retry status.

    Args:
        phone (str): The recipient's phone number.
        first_dial_time (timedelta or None): The time since the first dial attempt, or None if not available.
        message (str): The message associated with the call.

    Returns:
        None
    """

    if first_dial_time:
        return logging.info(
            (
                f"A call for '{phone}' was started '{first_dial_time}' ago, with the message '{message}' "
                + f"and is inside our retry period of '{seconds_to_forget}' seconds. "
                + "We're currently managing this call."
            )
        )

    else:
        return logging.info(
            f"A previous call was for '{phone}' with the message '{message}' is outside of our retry period "
            + f"('{seconds_to_forget}' seconds) we'll start a new cycle."
        )


async def get_request_parameters(request):
    """
    Extracts the 'phone', 'message', and 'asterisk_chan' parameters from the incoming request.

    This asynchronous function retrieves required query parameters from the request and raises an HTTP error if any are missing.

    Args:
        request: The incoming HTTP request containing query parameters.

    Returns:
        tuple: A tuple containing the phone, message, and asterisk_chan values.

    Raises:
        web.HTTPClientError: If any required parameter is missing from the request.
    """
    try:
        phone = request.rel_url.query["phone"]
        message = request.rel_url.query["message"]
        asterisk_chan = request.rel_url.query["asterisk_chan"]
        return phone, message, asterisk_chan
    except KeyError as err:
        logging.exception(
            f"No 'phone', 'message' or 'asterisk_chan' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason=conf.get_register_call_error(),
            body=None,
            text=None,
            content_type=None,
        ) from err


async def new_call_attempt(
    phone,
    message,
    asterisk_chan,
    msg_chk_sum,
    call_chk_sum,
    unique_chk_sum,
    first_dial,
):
    """
    Creates a new call attempt record in the database for the specified phone and message.

    This asynchronous function logs the attempt and inserts a new record, handling and logging any exceptions that occur.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message to be delivered during the call.
        asterisk_chan (str): The identifier of the Asterisk channel.
        msg_chk_sum (str): The checksum of the message.
        call_chk_sum (str): The checksum of the call.
        unique_chk_sum (str): The unique checksum for this call attempt.
        first_dial (datetime): The timestamp of the first dial attempt.

    Returns:
        None
    """
    logging.info(f"No active call cycles for '{phone}' with the message '{message}'.")
    try:
        await insert_into_db(
            phone,
            message,
            asterisk_chan,
            msg_chk_sum,
            call_chk_sum,
            unique_chk_sum,
            first_dial,
            seconds_to_forget,
            times_to_dial,
        )
    except Exception as err:
        logging.exception(
            (
                "Error during the creation of the first DB record for:"
                + f" phone -> {phone} | message -> {message} | cause -> {err}"
            )
        )


async def defining_first_dial_time(call_chk_sum, current_call_id, phone, message):
    """
    Determines the time since the first dial attempt for a given call and logs its status.

    This asynchronous function retrieves the first dial time from the database, logs whether the call is within the retry period, and returns the time.

    Args:
        call_chk_sum (str): The checksum of the call.
        current_call_id (int): The current call's database ID.
        phone (str): The recipient's phone number.
        message (str): The message associated with the call.

    Returns:
        timedelta or None: The time since the first dial attempt, or None if it cannot be determined.
    """
    try:
        first_dial_time = await get_first_dial_age(call_chk_sum, current_call_id)
        await present_or_not_logger(phone, first_dial_time, message)
        return first_dial_time
    except Exception as err:
        # It should only notify if there's no uncompleted cycles here
        # for a given round of calls
        logging.exception(
            f"We can't define the 'first_dial_time'  for '{phone}' with the message"
            + f" '{message}' due to the following error: '{err}'"
        )


async def updating_the_call_db_record(
    first_dial_time,
    call_chk_sum,
    current_call_id,
    current_dialed_times,
    asterisk_chan,
    phone,
    message,
    msg_chk_sum,
    unique_chk_sum,
    first_dial,
):
    """
    Updates the call database record if within the retry period, or creates a new record if not.

    This asynchronous function attempts to update the existing call record based on the first dial time, and inserts a new record if an update is not possible.

    Args:
        first_dial_time (timedelta): The time since the first dial attempt.
        call_chk_sum (str): The checksum of the call.
        current_call_id (int): The current call's database ID.
        current_dialed_times (int): The number of times the call has been dialed.
        asterisk_chan (str): The identifier of the Asterisk channel.
        phone (str): The recipient's phone number.
        message (str): The message to be delivered during the call.
        msg_chk_sum (str): The checksum of the message.
        unique_chk_sum (str): The unique checksum for this call attempt.
        first_dial (datetime): The timestamp of the first dial attempt.

    Returns:
        None
    """
    try:
        if first_dial_time < timedelta(seconds=seconds_to_forget):
            await update_the_call_db_record(
                call_chk_sum,
                current_call_id,
                current_dialed_times,
                asterisk_chan,
                phone,
                message,
            )
    except Exception as err:
        logging.info(
            (
                "No update done, creating a new record for:"
                + f" phone -> {phone} | message -> {message} | cause -> {err}"
            )
        )
        await insert_into_db(
            phone,
            message,
            asterisk_chan,
            msg_chk_sum,
            call_chk_sum,
            unique_chk_sum,
            first_dial,
            seconds_to_forget,
            times_to_dial,
        )


async def register_call(request):
    """
    Handles incoming requests to register a new call attempt or update an existing call record.

    This asynchronous function processes the request parameters, manages call control logic, and updates or creates call records as needed.

    Args:
        request: The incoming HTTP request containing call registration parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the operation.
    """

    phone, message, asterisk_chan = await get_request_parameters(request)

    # Used for the call control logics
    call_chk_sum = await gen_call_chk_sum(phone, message)
    msg_chk_sum = await gen_msg_chk_sum(message)
    first_dial = datetime.now(UTC).replace(tzinfo=None)
    unique_chk_sum = await gen_unique_chk_sum(phone, message, first_dial)
    call_yet_present = await check_call_yet_present(call_chk_sum, phone, message)

    if call_yet_present is None:
        await new_call_attempt(
            phone,
            message,
            asterisk_chan,
            msg_chk_sum,
            call_chk_sum,
            unique_chk_sum,
            first_dial,
        )

    else:
        current_call_id = await get_current_call_id(seconds_to_forget, call_chk_sum)

        # When there's no active call cycle (inside the period of 'seconds_to_forget'),
        # we'll start a new one. By creating a new record.
        if current_call_id is None:
            await new_call_attempt(
                phone,
                message,
                asterisk_chan,
                msg_chk_sum,
                call_chk_sum,
                unique_chk_sum,
                first_dial,
            )
            logging.info(
                f"There's no uncompleted cycle for '{phone}' with the message"
                + f" '{message}' in the last '{seconds_to_forget}' seconds."
                + " We'll start a new cycle."
            )
            return web.json_response({"status": 200})

        first_dial_time = await defining_first_dial_time(
            call_chk_sum, current_call_id, phone, message
        )

        current_dialed_times = await get_dialed_times(seconds_to_forget, call_chk_sum)

        await updating_the_call_db_record(
            first_dial_time,
            call_chk_sum,
            current_call_id,
            current_dialed_times,
            asterisk_chan,
            phone,
            message,
            msg_chk_sum,
            unique_chk_sum,
            first_dial,
        )

    return web.json_response({"status": 200})


async def acknowledge(request):
    """
    Handles incoming requests to acknowledge a call by updating the database record.

    This asynchronous function extracts the 'asterisk_chan' parameter from the request, updates the acknowledgement in the database, and returns a JSON response.

    Args:
        request: The incoming HTTP request containing the 'asterisk_chan' parameter.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the acknowledgement.

    Raises:
        web.HTTPClientError: If the 'asterisk_chan' parameter is missing from the request.
    """
    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
    except KeyError as err:
        asterisk_chan = None
        logging.exception(
            f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason=conf.get_acknowledge_error(),
            body=None,
            text=None,
            content_type=None,
        ) from err

    # Do the acknowledgement on the DB updating the record (the Asterisk channel ID is unique)
    await update_acknowledgement(asterisk_chan)

    return web.json_response({"status": 200})


async def heard(request):
    """
    Handles incoming requests to mark a call as heard by updating the database record.

    This asynchronous function extracts the 'asterisk_chan' parameter from the request, updates the 'heard' status in the database, and returns a JSON response.

    Args:
        request: The incoming HTTP request containing the 'asterisk_chan' parameter.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the update.

    Raises:
        web.HTTPClientError: If the 'asterisk_chan' parameter is missing from the request.
    """
    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
    except KeyError as err:
        asterisk_chan = None
        logging.exception(
            f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason=conf.get_heard_error(), body=None, text=None, content_type=None
        ) from err

    # Update the call DB record when the Asterisk PBX plays the audio message
    await update_heard_at(asterisk_chan)

    return web.json_response({"status": 200})


async def voice_message(request):
    """
    Handles incoming requests to retrieve the voice message and its checksum for a given Asterisk channel.

    This asynchronous function extracts the 'asterisk_chan' parameter from the request, fetches the message and checksum from the database, and returns them in a JSON response.

    Args:
        request: The incoming HTTP request containing the 'asterisk_chan' parameter.

    Returns:
        aiohttp.web.Response or dict: A JSON response with the message and checksum, or an empty response if no data is found.

    Raises:
        web.HTTPClientError: If the 'asterisk_chan' parameter is missing from the request.
    """
    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
    except KeyError as err:
        asterisk_chan = None
        logging.exception(
            f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason=conf.get_voice_message_error(),
            body=None,
            text=None,
            content_type=None,
        ) from err

    # Sending an empty response if no data is restored from the query
    try:
        message, msg_chk_sum = await get_msg_chk_sum(asterisk_chan)
        return web.json_response(
            {"message": f"{message}", "msg_chk_sum": f"{msg_chk_sum}"}
        )
    except Exception:
        logging.info(
            "No data retrieved from the database for the 'message' or 'msg_chk_sum'"
        )
        return {"message": "", "msg_chk_sum": ""}


async def scheduled_call(request):
    """
    Handles incoming requests to schedule a call at a specified time.

    This asynchronous function extracts the required parameters from the request, records the scheduled call in the database, and returns a JSON response.

    Args:
        request: The incoming HTTP request containing 'phone', 'message', and 'scheduled_at' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the scheduling operation.

    Raises:
        web.HTTPClientError: If any required parameter is missing from the request.
    """

    try:
        phone = request.rel_url.query["phone"]
        message = request.rel_url.query["message"]
        scheduled_at_str = request.rel_url.query["scheduled_at"]
    except KeyError as err:
        logging.exception(
            f"No 'phone', 'message', or 'scheduled_at' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason="Lost parameters 'phone', 'message', or 'scheduled_at'...",  # ToDo: use an error form the config module
            body=None,
            text=None,
            content_type=None,
        ) from err

    # Used to record useful data on the scheduled call into the DB
    scheduled_at = datetime.strptime(scheduled_at_str, "%Y-%m-%d %H:%M")
    call_chk_sum = await gen_call_chk_sum(phone, message)
    inserted_at = datetime.now(UTC).replace(tzinfo=None)

    await insert_scheduled_call(phone, message, call_chk_sum, inserted_at, scheduled_at)

    return web.json_response({"status": 200})


async def init_app():
    """
    Initializes and configures the aiohttp web application for call registration and management.

    This asynchronous function sets up the web application and registers routes for call registration, voice messages, scheduled calls, acknowledgements, and heard status.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """
    app = web.Application()

    # And... here our routes
    app.router.add_route(
        "POST", f"/{conf.get_call_register_app_route_register_call()}", register_call
    )
    app.router.add_route(
        "POST", f"/{conf.get_call_register_app_route_voice_message()}", voice_message
    )
    app.router.add_route(
        "POST", f"/{conf.get_call_register_scheduled_call_app_route()}", scheduled_call
    )
    app.router.add_route(
        "GET", f"/{conf.get_call_register_app_route_acknowledge()}", acknowledge
    )
    app.router.add_route("GET", f"/{conf.get_call_register_app_route_heard()}", heard)
    return app


def main():
    """
    Main entry point for the call register web application.

    This function initializes the event loop, starts the database setup, creates the aiohttp web application, and runs the web server.

    Returns:
        None
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(init_database())
    app = loop.run_until_complete(init_app())

    web.run_app(app, port=int(conf.get_call_register_port()))


if __name__ == "__main__":
    main()
