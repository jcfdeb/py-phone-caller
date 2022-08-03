import asyncio
import logging
from datetime import datetime, timedelta

from aiohttp import web

import caller_utils.caller_configuration as conf
from caller_utils.checksums import gen_call_chk_sum, gen_msg_chk_sum, gen_unique_chk_sum
from caller_utils.db.db_caller_register import (
    check_call_yet_present,
    get_current_call_id,
    get_dialed_times,
    get_first_dial_age,
    get_msg_chk_sum,
    insert_into_db,
    update_acknowledgement,
    update_heard_at,
    update_the_call_db_record,
)
from caller_utils.db.db_scheduled_calls import insert_scheduled_call

seconds_to_forget = conf.get_seconds_to_forget()
times_to_dial = conf.get_times_to_dial()

logging.basicConfig(level=logging.INFO)


async def present_or_not_logger(phone, first_dial_time, message):
    """
    Used for display a better indication of the call status
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
    """Getting the needed params from the 'request'"""
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


async def fist_call_attempt(
    phone,
    message,
    asterisk_chan,
    msg_chk_sum,
    call_chk_sum,
    unique_chk_sum,
    first_dial,
):
    """Creates the call DB record at the first dial attempt"""
    logging.info(f"Is the first call for '{phone}' with the message '{message}'.")
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
    """Trying to define the first dial time for a given 'call' and 'message'"""
    try:
        first_dial_time = await get_first_dial_age(call_chk_sum, current_call_id)
        await present_or_not_logger(phone, first_dial_time, message)
        return first_dial_time
    except TypeError:
        # It should only notify if there's no uncompleted cycles here
        # for a given round of calls
        logging.info(
            f"There's no uncompleted cycle for '{phone}' with the message"
            + f" '{message}' in the last '{seconds_to_forget}' seconds."
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
    """Updated the call DB record in order to keep trace of the cycle, also works as fallback
    if the operation fails"""
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
    except TypeError:
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
    """Handle incoming requests coming to '/CALL_REGISTER_APP_ROUTE_REGISTER_CALL'
    can be configured through an environmental variable or form the config file
    """

    phone, message, asterisk_chan = await get_request_parameters(request)

    # Used for the call control logics
    call_chk_sum = await gen_call_chk_sum(phone, message)
    msg_chk_sum = await gen_msg_chk_sum(message)
    first_dial = datetime.utcnow()
    unique_chk_sum = await gen_unique_chk_sum(phone, message, first_dial)
    call_yet_present = await check_call_yet_present(call_chk_sum, phone, message)

    if call_yet_present is None:
        await fist_call_attempt(
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

        first_dial_time = await defining_first_dial_time(
            call_chk_sum, current_call_id, phone, message
        )

        current_dialed_times = await get_dialed_times(seconds_to_forget, call_chk_sum)

        # Updating the call record on the DB
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
    """Handle incoming requests coming to '/ack'"""
    # TODO manage the acknowledge of the call, when the callee press a number
    # use in asterisk to call this endpoint "${CHANNEL(uniqueid)}"
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

    # TODO improve the status code reflecting the result of the query (call ack)...
    return web.json_response({"status": 200})


async def heard(request):
    """Handle incoming requests coming to '/heard'
    if the massage was played add a record with the timestamp
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

    # TODO improve the status code reflecting the result of the query (call heard)...
    return web.json_response({"status": 200})


async def voice_message(request):
    """Handle incoming requests coming to '/msg'"""
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
    """Handle incoming requests coming to '/SCHEDULED_CALL_APP_ROUTE_REGISTER_CALL'
    can be configured through an environmental variable or form the config file
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
    print(scheduled_at_str) # Debug
    print(scheduled_at) # Debug
    call_chk_sum = await gen_call_chk_sum(phone, message)
    inserted_at = datetime.utcnow()

    await insert_scheduled_call(phone, message, call_chk_sum, inserted_at, scheduled_at)

    return web.json_response({"status": 200})


async def init_app():
    """Start the Application Web Server."""
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


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=conf.get_call_register_port())
