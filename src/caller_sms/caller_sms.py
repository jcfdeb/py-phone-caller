import asyncio
import logging
from concurrent.futures.thread import ThreadPoolExecutor

from aiohttp import web

import caller_utils.caller_configuration as conf
from caller_utils.sms.twilio_sms import sms_twilio

logging.basicConfig(format=conf.get_log_formatter())


async def sms_sender_async(message, phone_number):
    """Trying to send a SMS text message through Twilio (maybe in future versions we can support more carriers)"""
    inner_loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=conf.get_num_of_cpus())
    logging.info(f"Sending the SMS message '{message}' to '{phone_number}'")
    return inner_loop.run_in_executor(
        executor,
        sms_twilio,
        message,
        phone_number,
        conf.get_twilio_account_sid(),
        conf.get_twilio_auth_token(),
        conf.get_twilio_sms_from(),
    )


async def send_the_sms(request):
    """Used to process the POST request"""

    try:
        message = request.rel_url.query["message"]
        phone = request.rel_url.query["phone"]
    except KeyError as err:
        message = None
        phone = None
        logging.exception(
            f"No 'message' or 'phone' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason=conf.get_caller_sms_error(), body=None, text=None, content_type=None
        ) from err

    futures = await sms_sender_async(message, phone)

    try:
        await asyncio.ensure_future(futures)
        status_code = 200
    except Exception as err:
        status_code = 500
        logging.exception(f"Unable to send the SMS: '{err}'")

    return web.json_response({"status": status_code})


async def init_app():
    """Start the Application Web Server."""
    app = web.Application()

    # And... here our routes
    app.router.add_route("POST", f"/{conf.get_caller_sms_app_route()}", send_the_sms)
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=conf.get_caller_sms_port())
