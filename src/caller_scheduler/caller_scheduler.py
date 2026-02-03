"""
Caller Scheduler service.

Provides an aiohttp endpoint to schedule calls for future execution using Celery.
"""

import asyncio
import logging
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)


import pytz
from dateutil import parser
from aiohttp import web

from py_phone_caller_utils.tasks.celery_task import do_this_call
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app

from caller_scheduler.constants import (
    SCHEDULED_CALL_APP_ROUTE,
    SCHEDULED_CALLS_PORT,
    LOCAL_TIMEZONE,
    SCHEDULED_CALL_ERROR,
    LOG_FORMATTER,
    LOG_LEVEL,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("caller_scheduler")


async def schedule_this_call(request):
    """
    Handles incoming requests to schedule a call at a specified time.

    This asynchronous function extracts the required parameters from the request, converts the scheduled time to UTC,
    enqueues the call task using Celery, and returns a JSON response indicating the status.

    Args:
        request: The incoming HTTP request containing 'phone', 'message', and 'scheduled_at' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the scheduling operation.

    Raises:
        web.HTTPBadRequest: If any required parameter is missing from the request.
    """

    try:
        phone = request.rel_url.query["phone"]
        message = request.rel_url.query["message"]
        scheduled_at_str = request.rel_url.query["scheduled_at"]
    except KeyError as err:
        logging.exception(
            f"No 'phone', 'message' or 'scheduled_at' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=SCHEDULED_CALL_ERROR,
            body=None,
            text=None,
            content_type=None,
        ) from err

    logging.info(
        f"Received a new call to '{phone}' with the message '{message}' to be scheduled at '{scheduled_at_str}'."
    )

    try:
        scheduled_at = parser.parse(scheduled_at_str)
        local_timezone = pytz.timezone(LOCAL_TIMEZONE)

        if scheduled_at.tzinfo is None:
            localized_time = local_timezone.localize(scheduled_at, is_dst=None)
        else:
            localized_time = scheduled_at

        scheduled_at_utc = localized_time.astimezone(pytz.utc)
        logging.info(
            f"Scheduling call for {scheduled_at_str} localized as {localized_time} and converted to UTC: {scheduled_at_utc}"
        )
    except Exception as err:
        logging.exception(f"Unable to do the date/time conversions to UTC due: {err}")
        return web.json_response({"status": 400, "message": str(err)})

    try:
        do_this_call.apply_async([phone, message], eta=scheduled_at_utc)
    except Exception as err:
        logging.exception(f"Unable to place the call due: {err}")
        return web.json_response({"status": 500, "message": str(err)})

    return web.json_response({"status": 200})


async def init_app():
    """
    Initializes and configures the aiohttp web application for scheduling calls.

    This asynchronous function sets up the web application and registers the route for scheduling calls.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """
    app = web.Application()

    instrument_aiohttp_app(app)

    app.router.add_route("POST", f"/{SCHEDULED_CALL_APP_ROUTE}", schedule_this_call)
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=int(SCHEDULED_CALLS_PORT))
