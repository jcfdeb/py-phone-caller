import asyncio
import logging
import random

import aiologger
from aiohttp import ClientSession, ClientTimeout, web
from aiologger.formatters.base import Formatter
from aiologger.levels import LogLevel

import local_utils.caller_configuration as conf

LOG_FORMATTER = conf.get_log_formatter()
PROMETHEUS_WEBHOOK_PORT = conf.get_prometheus_webhook_port()
PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY = (
    conf.get_prometheus_webhook_app_route_call_only()
)
PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY = conf.get_prometheus_webhook_app_route_sms_only()
PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL = (
    conf.get_prometheus_webhook_app_route_sms_before_call()
)
PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS = (
    conf.get_prometheus_webhook_app_route_call_and_sms()
)
PROMETHEUS_WEBHOOK_RECEIVERS = conf.get_prometheus_webhook_receivers()
ASTERISK_CALL_HTTP_SCHEME = conf.get_asterisk_call_http_scheme()
ASTERISK_CALL_HOST = conf.get_asterisk_call_host()
ASTERISK_CALL_PORT = conf.get_asterisk_call_port()
ASTERISK_CALL_APP_ROUTE_ASTERISK_INIT = conf.get_asterisk_call_app_route_asterisk_init()
ASTERISK_CALL_URL = f"{ASTERISK_CALL_HTTP_SCHEME}://{ASTERISK_CALL_HOST}:{ASTERISK_CALL_PORT}/{ASTERISK_CALL_APP_ROUTE_ASTERISK_INIT}"
SMS_BEFORE_CALL_WAIT_SECONDS = conf.get_sms_before_call_wait_seconds()
CALLER_SMS_HTTP_SCHEME = conf.get_caller_sms_http_scheme()
CALLER_SMS_HOST = conf.get_caller_sms_host()
CALLER_SMS_PORT = conf.get_caller_sms_port()
CALLER_SMS_APP_ROUTE = conf.get_caller_sms_app_route()
CALLER_SMS_URL = f"{CALLER_SMS_HTTP_SCHEME}://{CALLER_SMS_HOST}:{CALLER_SMS_PORT}/{CALLER_SMS_APP_ROUTE}"
CLIENT_TIMEOUT_TOTAL = ClientTimeout(total=conf.get_client_timeout_total())


LOGGER = aiologger.Logger.with_default_handlers(
    name="caller_prometheus_webhook",
    level=LogLevel.INFO,
    formatter=Formatter(fmt=LOG_FORMATTER),
)


async def producer(payload, queue):
    await queue.put(payload)


async def do_call_only(our_receiver, our_message):
    # https://docs.python.org/3/library/asyncio-task.html#running-tasks-concurrently
    calling = await asyncio.gather(
        start_the_asterisk_call(our_receiver, our_message),
        return_exceptions=True,
    )

    if calling != [None]:
        LOGGER.info(
            f"Unable to start a call for '{our_receiver}'"
            + f"with the message '{our_message}' - Cause: '{calling}'"
        )


async def schedule_sms_before_call(our_receiver, our_message):
    await send_the_sms(our_receiver, our_message)
    await asyncio.sleep(int(SMS_BEFORE_CALL_WAIT_SECONDS))
    await do_call_only(our_receiver, our_message)


async def messaging_actions(our_receiver, our_message, caller_func):
    if caller_func == "call_only":
        await do_call_only(our_receiver, our_message)

    elif caller_func == "sms_only":
        await send_the_sms(our_receiver, our_message)

    elif caller_func == "sms_before_call":
        asyncio.create_task(schedule_sms_before_call(our_receiver, our_message))

    elif caller_func == "call_and_sms":
        await send_the_sms(our_receiver, our_message)
        await do_call_only(our_receiver, our_message)


async def consumer(queue, caller_func):
    while True:
        our_message, our_receiver = await queue.get()
        await asyncio.sleep(random.uniform(0.2, 0.6))
        LOGGER.info(
            f"Call/Message '{our_message}' for '{our_receiver}' through the endpoint '{caller_func}'"
        )
        await messaging_actions(our_receiver, our_message, caller_func)
        queue.task_done()


async def do_the_call(the_number, the_message):
    await start_the_asterisk_call(the_number, the_message)  # Near working release test


async def send_the_sms(the_number, the_message):
    await send_message_to_caller_sms(
        the_number, the_message
    )  # Near working release test


async def process_the_queue(prometheus_message, receiver_nums, caller_func):
    queue = asyncio.Queue()
    producers = [
        asyncio.create_task(producer((prometheus_message, single_receiver), queue))
        for single_receiver in receiver_nums
    ]
    consumers = [asyncio.create_task(consumer(queue, caller_func))]
    await asyncio.gather(*producers)
    await queue.join()
    for c in consumers:
        c.cancel()


# Post the Prometheus incoming alert to 'asterisk_call.py' (we're client now)
async def start_the_asterisk_call(phone, message):
    session = ClientSession(timeout=CLIENT_TIMEOUT_TOTAL)
    await session.post(
        url=ASTERISK_CALL_URL + f"?phone={phone.replace('+', '00')}&message={message}",
        data=None,
        headers=None,
    )
    await session.close()


# Post the Prometheus incoming alert to 'caller_sms.py' (we're client now)
async def send_message_to_caller_sms(phone, message):
    session = ClientSession(timeout=CLIENT_TIMEOUT_TOTAL)
    await session.post(
        url=CALLER_SMS_URL + f"?phone={phone.replace('+', '%2B')}&message={message}",
        data=None,
        headers=None,
    )
    await session.close()


async def the_alert_description(request_payload):
    for alert_number, alert_payload in enumerate(request_payload["alerts"]):
        if alert_payload["status"] == "firing":
            return [alert_payload["annotations"].get("description", "No data")]


async def data_from_alert_manager(request, caller_func):
    # https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.BaseRequest.json
    payload = await request.json()
    some_messages = await the_alert_description(payload)
    for the_message in some_messages:
        await process_the_queue(the_message, PROMETHEUS_WEBHOOK_RECEIVERS, caller_func)


async def response_for_alert_manager():
    return web.json_response({"status": "200"})


async def call_only(request):
    await data_from_alert_manager(request, call_only.__name__)
    return await response_for_alert_manager()


async def sms_only(request):
    await data_from_alert_manager(request, sms_only.__name__)
    return await response_for_alert_manager()


async def sms_before_call(request):
    await data_from_alert_manager(request, sms_before_call.__name__)
    return await response_for_alert_manager()


async def call_and_sms(request):
    await data_from_alert_manager(request, call_and_sms.__name__)
    return await response_for_alert_manager()


async def init_app():
    """Start the Application Web Server."""
    app = web.Application()

    # And... here our routes
    app.router.add_route(
        "POST", f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}", call_only
    )
    app.router.add_route("POST", f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY}", sms_only)
    app.router.add_route(
        "POST", f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL}", sms_before_call
    )
    app.router.add_route(
        "POST", f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS}", call_and_sms
    )
    return app


loop = asyncio.get_event_loop()
app = loop.run_until_complete(init_app())
logging.basicConfig(level=logging.INFO)
web.run_app(app, port=PROMETHEUS_WEBHOOK_PORT)
