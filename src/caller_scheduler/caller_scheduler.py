import asyncio
import logging
from datetime import datetime

import pytz
from aiohttp import web

import py_phone_caller_utils.caller_configuration as conf
from py_phone_caller_utils.tasks.celery_task import do_this_call


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
        web.HTTPClientError: If any required parameter is missing from the request.
    """

    try:
        phone = request.rel_url.query["phone"]
        message = request.rel_url.query["message"]
        scheduled_at_str = request.rel_url.query["scheduled_at"]
    except KeyError as err:
        logging.exception(
            f"No 'phone', 'message' or 'scheduled_at' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason="No 'phone', 'message' or 'scheduled_at' parameters passed",  # TODO: Manage the error message from configuration
            body=None,
            text=None,
            content_type=None,
        ) from err

    logging.info(
        f"Received a new call to '{phone}' with the message '{message}' to be scheduled at '{scheduled_at_str}'."
    )

    try:
        scheduled_at = datetime.strptime(scheduled_at_str, "%Y-%m-%d %H:%M")
        local_timezone = pytz.timezone(conf.get_local_timezone())
        localized_time = local_timezone.localize(scheduled_at, is_dst=None)
        scheduled_at_utc = localized_time.astimezone(pytz.utc)
    except Exception as err:
        logging.exception(f"Unable to do the date/time conversions to UTC due: {err}")

    try:
        # Enqueue the task on Celery (converting the local time to UTC)
        do_this_call.apply_async([phone, message], eta=scheduled_at_utc)
    except Exception as err:
        logging.exception(f"Unable to place the call due: {err}")

    return web.json_response({"status": 200})


async def init_app():
    """
    Initializes and configures the aiohttp web application for scheduling calls.

    This asynchronous function sets up the web application and registers the route for scheduling calls.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """
    app = web.Application()

    # And... here our routes
    app.router.add_route(
        "POST", f"/{conf.get_scheduled_call_app_route()}", schedule_this_call
    )
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=int(conf.get_scheduled_calls_port()))
