import asyncio
import logging
from datetime import datetime

import pytz
from aiohttp import web

import caller_utils.caller_configuration as conf
from caller_utils.tasks.celery_task import do_this_call


async def schedule_this_call(request):
    """Handle incoming requests coming to '/schedule_call'"""

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
    """Start the Application Web Server."""
    app = web.Application()

    # And... here our routes
    app.router.add_route(
        "POST", f"/{conf.get_scheduled_call_app_route()}", schedule_this_call
    )
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=conf.get_scheduled_calls_port())
