"""
Prometheus Webhook service.

Exposes endpoints compatible with Prometheus Alertmanager to trigger phone calls
and SMS notifications (call-only, SMS-only, SMS-before-call, call-and-SMS).
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


import hashlib
import time
from aiohttp import ClientSession, ClientTimeout, web
from py_phone_caller_utils.config import settings

from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app, inject_trace_context
from py_phone_caller_utils.web import create_service_catalog, setup_swagger_routes

from caller_prometheus_webhook.constants import (
    ASTERISK_CALL_URL,
    ASTERISK_CALL_APP_ROUTE_PLACE_CALL,
    SMS_BEFORE_CALL_WAIT_SECONDS,
    CALLER_SMS_URL,
    CALLER_SMS_APP_ROUTE,
    CLIENT_TIMEOUT_TOTAL,
    PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY,
    PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY,
    PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL,
    PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS,
    PROMETHEUS_WEBHOOK_PORT,
    PROMETHEUS_WEBHOOK_RECEIVERS,
    LOG_FORMATTER,
    LOG_LEVEL,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("caller_prometheus_webhook")

# Sliding-window in-memory and Redis-backed alert deduplication
_LOCAL_DEDUP_CACHE = {}

async def is_duplicate_alert(message: str, ttl_seconds: int = 180) -> bool:
    msg_hash = hashlib.sha256(message.strip().encode("utf-8")).hexdigest()[:16]
    now = time.time()

    # Try Redis sliding-window check first
    try:
        import redis.asyncio as aioredis
        queue_url = settings.get("QUEUE", {}).get("QUEUE_URL", "redis://redis:6379/7")
        r = aioredis.from_url(queue_url, socket_connect_timeout=1)
        key = f"alert:dedup:{msg_hash}"
        was_set = await r.set(key, "1", ex=ttl_seconds, nx=True)
        await r.aclose()
        if was_set is None:
            return True
        return False
    except Exception as redis_err:
        logging.debug(f"Redis deduplication unreachable ({redis_err}), using in-memory window")

    # Local fallback
    last_seen = _LOCAL_DEDUP_CACHE.get(msg_hash)
    if last_seen and (now - last_seen) < ttl_seconds:
        return True
    _LOCAL_DEDUP_CACHE[msg_hash] = now
    if len(_LOCAL_DEDUP_CACHE) > 500:
        cutoff = now - ttl_seconds
        for k in list(_LOCAL_DEDUP_CACHE.keys()):
            if _LOCAL_DEDUP_CACHE[k] < cutoff:
                del _LOCAL_DEDUP_CACHE[k]
    return False


async def producer(payload, queue):
    """
    Adds a payload to the provided asyncio queue.

    This asynchronous function enqueues the given payload for later processing.

    Args:
        payload: The data to be added to the queue.
        queue (asyncio.Queue): The queue to which the payload will be added.

    Returns:
        None
    """
    await queue.put(payload)


async def do_call_only(our_receiver, our_message):
    """
    Initiates a call to the specified receiver with the provided message.

    This asynchronous function attempts to start a call and logs an error if the call could not be initiated.

    Args:
        our_receiver: The recipient of the call.
        our_message: The message to be delivered during the call.

    Returns:
        None

    # https://docs.python.org/3/library/asyncio-task.html#running-tasks-concurrently
    """

    calling = await asyncio.gather(
        start_the_asterisk_call(our_receiver, our_message),
        return_exceptions=True,
    )

    if calling != [None]:
        logging.info(
            f"Unable to start a call for '{our_receiver}'"
            + f"with the message '{our_message}' - Cause: '{calling}'"
        )


async def send_the_sms(the_number, the_message):
    """
    Sends an SMS message to the specified number with the provided message.

    This asynchronous function delegates the actual sending to the SMS utility.

    Args:
        the_number: The recipient's phone number.
        the_message: The message content to be sent.

    Returns:
        None
    """
    await send_message_to_caller_sms(the_number, the_message)


async def schedule_sms_before_call(our_receiver, our_message):
    """
    Sends an SMS to the receiver, waits for a configured delay, and then initiates a call.

    This asynchronous function coordinates the process of sending an SMS before making a call to the same receiver.

    Args:
        our_receiver: The recipient of the SMS and call.
        our_message: The message content to be sent and spoken.

    Returns:
        None
    """
    await send_the_sms(our_receiver, our_message)
    await asyncio.sleep(int(SMS_BEFORE_CALL_WAIT_SECONDS))
    await do_call_only(our_receiver, our_message)


async def do_sms_before_call(our_receiver, our_message):
    """
    Schedules an SMS to be sent before making a call to the receiver.

    This asynchronous function creates a background task that sends an SMS and then initiates a call after a delay.

    Args:
        our_receiver: The recipient of the SMS and call.
        our_message: The message content to be sent and spoken.

    Returns:
        None
    """
    asyncio.create_task(schedule_sms_before_call(our_receiver, our_message))


async def do_call_and_sms(our_receiver, our_message):
    """
    Sends an SMS to the receiver and then initiates a call with the same message.

    This asynchronous function first sends an SMS and then makes a call to the specified receiver.

    Args:
        our_receiver: The recipient of the SMS and call.
        our_message: The message content to be sent and spoken.

    Returns:
        None
    """
    await send_the_sms(our_receiver, our_message)
    await do_call_only(our_receiver, our_message)


take_this_action = {
    "call_only": do_call_only,
    "sms_only": send_the_sms,
    "sms_before_call": do_sms_before_call,
    "call_and_sms": do_call_and_sms,
}


async def notification_actions(our_receiver, our_message, caller_func):
    """
    Executes the notification action specified by the caller function.

    This asynchronous function dispatches the appropriate notification action (call, SMS, or both) for the given receiver and message.

    Args:
        our_receiver: The recipient of the notification.
        our_message: The message content to be sent or spoken.
        caller_func (str): The key indicating which notification action to perform.

    Returns:
        None
    """
    await take_this_action[caller_func](our_receiver, our_message)


async def consumer(queue, caller_func):
    """
    Consumes items from the queue and processes notification actions.

    This asynchronous function retrieves messages and receivers from the queue, logs the action, and dispatches the appropriate notification.

    Args:
        queue (asyncio.Queue): The queue containing (message, receiver) tuples.
        caller_func (str): The key indicating which notification action to perform.

    Returns:
        None
    """
    while True:
        our_message, our_receiver = await queue.get()
        await asyncio.sleep(0.4)
        logging.info(
            f"Call/Message '{our_message}' for '{our_receiver}' through the endpoint '{caller_func}'"
        )
        await notification_actions(our_receiver, our_message, caller_func)
        queue.task_done()


async def do_the_call(the_number, the_message):
    """
    Initiates a call to the specified number with the provided message.

    This asynchronous function starts the Asterisk call process for the given recipient and message.

    Args:
        the_number: The recipient's phone number.
        the_message: The message content to be delivered during the call.

    Returns:
        None
    """
    await start_the_asterisk_call(the_number, the_message)  # Near working release test


async def process_the_queue(prometheus_message, receiver_nums, caller_func):
    """
    Processes a queue of notification tasks for multiple receivers.

    This asynchronous function creates producer tasks for each receiver and a consumer task to handle notifications, ensuring all messages are processed.

    Args:
        prometheus_message: The message to be sent to each receiver.
        receiver_nums (list): A list of receiver identifiers (e.g., phone numbers).
        caller_func (str): The key indicating which notification action to perform.

    Returns:
        None
    """
    queue = asyncio.Queue()
    producers = [
        asyncio.create_task(producer((prometheus_message, single_receiver), queue))
        for single_receiver in receiver_nums
    ]
    consumers = [asyncio.create_task(consumer(queue, caller_func))]
    await asyncio.gather(*producers)
    await queue.join()
    for a_consumer in consumers:
        a_consumer.cancel()


async def start_the_asterisk_call(phone, message):
    """
    Starts an Asterisk call to the specified phone number with the given message.

    This asynchronous function sends a POST request to the Asterisk call endpoint to initiate the call.

    Args:
        phone: The recipient's phone number.
        message: The message content to be delivered during the call.

    Returns:
        None
    """
    asterisk_call_url = f"{ASTERISK_CALL_URL}/{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}"
    formatted_phone = phone.replace("+", "00") if isinstance(phone, str) else str(phone)
    try:
        async with ClientSession(
            timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
        ) as session_start_the_asterisk_call:
            await session_start_the_asterisk_call.post(
                url=asterisk_call_url,
                params={"phone": formatted_phone, "message": message},
                data=None,
                headers=inject_trace_context(),
            )
    except Exception as e:
        logging.error(f"Error calling Asterisk call service: {e}")


async def send_message_to_caller_sms(phone, message):
    """
    Sends an SMS message to the specified phone number using the configured SMS service.

    This asynchronous function sends a POST request to the SMS endpoint to deliver the message.

    Args:
        phone: The recipient's phone number.
        message: The message content to be sent.

    Returns:
        None
    """
    caller_sms_url = f"{CALLER_SMS_URL}/{CALLER_SMS_APP_ROUTE}"
    try:
        async with ClientSession(
            timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
        ) as session_send_message_to_caller_sms:
            await session_send_message_to_caller_sms.post(
                url=caller_sms_url,
                params={"phone": phone, "message": message},
                data=None,
                headers=inject_trace_context(),
            )
    except Exception as e:
        logging.error(f"Error calling Caller SMS service: {e}")


async def the_alert_description(request_payload):
    """
    Extracts the description from the first firing alert in the request payload.

    This asynchronous function iterates through the alerts and returns the description annotation of the first alert with status 'firing'.

    Args:
        request_payload (dict): The payload containing alert information.

    Returns:
        list: A list containing the description string of the first firing alert, or [] if not present.
    """
    for alert_number, alert_payload in enumerate(request_payload.get("alerts", [])):
        if alert_payload.get("status") == "firing":
            return [alert_payload.get("annotations", {}).get("description", "No data")]
    return []


async def data_from_alert_manager(request, caller_func):
    """
    Processes alert data from an incoming request and dispatches notification tasks.
    Data arrives from Prometheus Alertmanager and processes it to send notifications.

    This asynchronous function extracts alert descriptions from the request payload and initiates notification processing for each message.

    Args:
        request: The incoming HTTP request containing alert data.
        caller_func (str): The key indicating which notification action to perform.

    Returns:
        None

    # https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.BaseRequest.json
    """

    payload = await request.json()
    some_messages = await the_alert_description(payload)
    if some_messages:
        dedup_window = int(settings.get("DEDUPLICATION_WINDOW_SECONDS", 180))
        for the_message in some_messages:
            if await is_duplicate_alert(the_message, ttl_seconds=dedup_window):
                logging.info(
                    f"Deduplicated repeating alert within {dedup_window}s window. Skipping duplicate calls."
                )
                continue
            await process_the_queue(the_message, PROMETHEUS_WEBHOOK_RECEIVERS, caller_func)


async def response_for_alert_manager():
    """
    Returns a standard JSON response for Prometheus Alertmanager requests.

    This asynchronous function generates a JSON response indicating a successful status.

    Returns:
        aiohttp.web.Response: A JSON response with status code 200.
    """
    return web.json_response({"status": "200"})


async def call_only(request):
    """
    Handles incoming requests to trigger a call-only notification action.

    This asynchronous function processes alert data and returns a standard response for Prometheus Alertmanager.

    Args:
        request: The incoming HTTP request containing alert data.

    Returns:
        aiohttp.web.Response: A JSON response with status code 200.
    """
    await data_from_alert_manager(request, call_only.__name__)
    return await response_for_alert_manager()


async def sms_only(request):
    """
    Handles incoming requests to trigger an SMS-only notification action.

    This asynchronous function processes alert data and returns a standard response for Prometheus Alertmanager.

    Args:
        request: The incoming HTTP request containing alert data.

    Returns:
        aiohttp.web.Response: A JSON response with status code 200.
    """
    await data_from_alert_manager(request, sms_only.__name__)
    return await response_for_alert_manager()


async def sms_before_call(request):
    """
    Handles incoming requests to trigger an SMS-before-call notification action.

    This asynchronous function processes alert data and returns a standard response for Prometheus Alertmanager.

    Args:
        request: The incoming HTTP request containing alert data.

    Returns:
        aiohttp.web.Response: A JSON response with status code 200.
    """
    await data_from_alert_manager(request, sms_before_call.__name__)
    return await response_for_alert_manager()


async def call_and_sms(request):
    """
    Handles incoming requests to trigger both call and SMS notification actions.

    This asynchronous function processes alert data and returns a standard response for Prometheus Alertmanager.

    Args:
        request: The incoming HTTP request containing alert data.

    Returns:
        aiohttp.web.Response: A JSON response with status code 200.
    """
    await data_from_alert_manager(request, call_and_sms.__name__)
    return await response_for_alert_manager()


async def init_app():
    """
    Initializes and configures the aiohttp web application for Prometheus Alertmanager notifications.

    This asynchronous function sets up the web application and registers routes for different notification actions.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """
    app = web.Application()

    instrument_aiohttp_app(app, "caller_prometheus_webhook")

    async def root_catalog(request):
        catalog = create_service_catalog(
            service_name="caller_prometheus_webhook",
            description="Prometheus Alertmanager webhook receiver for py-phone-caller",
            version="1.0.0",
            docs_url="/docs",
            openapi_spec="/docs/swagger.json",
            endpoints={
                f"POST /{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}": "Dispatches phone calls for firing Prometheus alerts",
                f"POST /{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY}": "Dispatches SMS for firing Prometheus alerts",
                f"POST /{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL}": "Sends SMS first, then calls after configurable delay",
                f"POST /{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS}": "Dispatches simultaneous call and SMS",
                "GET /live": "Liveness health check",
                "GET /ready": "Readiness probe",
                "GET /metrics": "Prometheus telemetry metrics",
            },
        )
        return web.json_response(catalog)

    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route(
        "POST", f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}", call_only
    )
    app.router.add_route("POST", f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY}", sms_only)
    app.router.add_route(
        "POST",
        f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL}",
        sms_before_call,
    )
    app.router.add_route(
        "POST",
        f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS}",
        call_and_sms,
    )

    setup_swagger_routes(
        app=app,
        service_name="caller_prometheus_webhook",
        description="Prometheus Alertmanager Webhook Ingestion Service",
        paths={
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}": {
                "post": {
                    "summary": "Process alert for phone call dispatch",
                    "description": "Receives standard Prometheus Alertmanager JSON payload and queues phone calls to configured receivers.",
                    "responses": {"200": {"description": "Webhook received"}},
                }
            },
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY}": {
                "post": {
                    "summary": "Process alert for SMS dispatch",
                    "responses": {"200": {"description": "Webhook received"}},
                }
            },
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL}": {
                "post": {
                    "summary": "Process alert with SMS followed by call",
                    "responses": {"200": {"description": "Webhook received"}},
                }
            },
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS}": {
                "post": {
                    "summary": "Process alert with concurrent call and SMS",
                    "responses": {"200": {"description": "Webhook received"}},
                }
            },
        },
    )

    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=int(PROMETHEUS_WEBHOOK_PORT))
