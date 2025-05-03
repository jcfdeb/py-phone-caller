import asyncio
import logging
from concurrent.futures.thread import ThreadPoolExecutor

from aiohttp import web

import py_phone_caller_utils.caller_configuration as conf
from py_phone_caller_utils.sms.twilio_sms import sms_twilio

logging.basicConfig(format=conf.get_log_formatter())


async def sms_sender_async(message, phone_number):
    """
    Sends an SMS message asynchronously using a thread pool executor.

    This asynchronous function delegates the SMS sending task to a thread pool, allowing non-blocking execution.

    Args:
        message (str): The SMS message content to be sent.
        phone_number (str): The recipient's phone number.

    Returns:
        concurrent.futures.Future: A future representing the execution of the SMS sending task.
    """
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
    """
    Handles incoming requests to send an SMS message to a specified phone number.

    This asynchronous function extracts the message and phone number from the request, sends the SMS asynchronously, and returns a JSON response indicating the status.

    Args:
        request: The incoming HTTP request containing 'message' and 'phone' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the SMS sending operation.

    Raises:
        web.HTTPClientError: If any required parameter is missing from the request.
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
    """
    Initializes and configures the aiohttp web application for sending SMS messages.

    This asynchronous function sets up the web application and registers the route for handling SMS sending requests.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """
    app = web.Application()

    # And... here our routes
    app.router.add_route("POST", f"/{conf.get_caller_sms_app_route()}", send_the_sms)
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=int(conf.get_caller_sms_port()))
