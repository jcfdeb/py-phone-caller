import asyncio
import logging
from concurrent.futures.thread import ThreadPoolExecutor

import aiologger
from aiohttp import ClientSession, ClientTimeout, web
from aiologger.formatters.base import Formatter
from aiologger.levels import LogLevel

import local_utils.caller_configuration as conf
from local_utils.sms.twilio_sms import sms_twilio

LOG_FORMATTER = conf.get_log_formatter()
CALLER_SMS_PORT = conf.get_caller_sms_port()
CALLER_SMS_APP_ROUTE = conf.get_caller_sms_app_route()
CALLER_SMS_CARRIER = conf.get_caller_sms_carrier()
CALLER_SMS_ERROR = conf.get_caller_sms_error()
TWILIO_ACCOUNT_SID = conf.get_twilio_account_sid()
TWILIO_AUTH_TOKEN = conf.get_twilio_auth_token()
TWILIO_SMS_FROM = conf.get_twilio_sms_from()
CLIENT_TIMEOUT_TOTAL = ClientTimeout(total=conf.get_client_timeout_total())
NUM_OF_CPUS = conf.get_num_of_cpus()
LOGGER = aiologger.Logger.with_default_handlers(
    name="caller_sms",
    level=LogLevel.INFO,
    formatter=Formatter(fmt=LOG_FORMATTER),
)


async def sms_sender_async(message, phone_number):
    """Trying to send a SMS text message through Twilio"""
    inner_loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=NUM_OF_CPUS)
    LOGGER.info(f"Sending the SMS message '{message}' to '{phone_number}'")
    if CALLER_SMS_CARRIER == "twilio":
        return inner_loop.run_in_executor(
            executor,
            sms_twilio,
            message,
            phone_number,
            TWILIO_ACCOUNT_SID,
            TWILIO_AUTH_TOKEN,
            TWILIO_SMS_FROM,
        )


async def send_the_sms(request):
    """Used to process the POST request"""

    try:
        message = request.rel_url.query["message"]
    except KeyError:
        message = None
        LOGGER.error(f"No 'message' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=CALLER_SMS_ERROR, body=None, text=None, content_type=None
        )

    try:
        phone = request.rel_url.query["phone"]
    except KeyError:
        phone = None
        LOGGER.error(f"No 'phone' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=CALLER_SMS_ERROR, body=None, text=None, content_type=None
        )

    futures = await sms_sender_async(message, phone)

    try:
        await asyncio.ensure_future(futures)
        status_code = 200
    except Exception as e:
        status_code = 500
        LOGGER.error(f"Unable to send the SMS: '{e}'")

    return web.json_response({"status": status_code})


async def init_app():
    """Start the Application Web Server."""
    app = web.Application()

    # And... here our routes
    app.router.add_route("POST", f"/{CALLER_SMS_APP_ROUTE}", send_the_sms)
    return app


loop = asyncio.get_event_loop()
app = loop.run_until_complete(init_app())
logging.basicConfig(level=logging.INFO)
web.run_app(app, port=CALLER_SMS_PORT)
