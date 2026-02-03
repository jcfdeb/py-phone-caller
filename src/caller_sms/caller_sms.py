"""
Caller SMS service.

Provides an aiohttp endpoint to send SMS messages using a configured carrier
backend (e.g., Twilio or on-premise gateway).
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

from aiohttp import web

from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app
import caller_sms.backend.twilio as twilio_backend
import caller_sms.backend.rust_on_premise as rust_on_premise

from caller_sms.constants import (
    CALLER_SMS_PORT,
    CALLER_SMS_APP_ROUTE,
    LOG_FORMATTER,
    CALLER_SMS_ERROR,
    LOG_LEVEL,
    CALLER_SMS_CARRIER,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("caller_sms")


async def send_the_sms(request):
    """
    Handles incoming requests to send an SMS message to a specified phone number.

    This asynchronous function extracts the message and phone number from the request, sends the SMS asynchronously, and returns a JSON response indicating the status.

    Args:
        request: The incoming HTTP request containing 'message' and 'phone' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the SMS sending operation.

    Raises:
        web.HTTPBadRequest: If any required parameter is missing from the request.
    """

    try:
        message = request.rel_url.query["message"]
        phone = request.rel_url.query["phone"]
    except KeyError as err:
        message = None
        phone = None
        logging.exception(
            f"No 'message' or 'phone' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=CALLER_SMS_ERROR, body=None, text=None, content_type=None
        ) from err

    match CALLER_SMS_CARRIER:
        case "twilio":
            futures = await twilio_backend.sms_sender_async(message, phone)
        case "on_premise":
            futures = await rust_on_premise.sms_sender_async(message, phone)
        case _:
            logging.error(f"Carrier '{CALLER_SMS_CARRIER}' not supported.")
            return web.json_response({"status": 500, "error": "Carrier not supported"})

    try:
        await asyncio.ensure_future(futures)
        status_code = 200
    except Exception as err:
        status_code = 500
        logging.exception(f"Unable to send the SMS: '{err}'")

    return web.json_response({"status": status_code})


async def init_app():
    """
    Initializes and configures the aiohttp web application for sending SMS messages.

    This asynchronous function sets up the web application and registers the route for handling SMS sending requests.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """
    app = web.Application()

    instrument_aiohttp_app(app)

    if CALLER_SMS_CARRIER == "on_premise":
        await rust_on_premise.init_backend()

    app.router.add_route("POST", f"/{CALLER_SMS_APP_ROUTE}", send_the_sms)
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=int(CALLER_SMS_PORT))
