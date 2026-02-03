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


from aiohttp import ClientSession, ClientTimeout, web

from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app

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
    session_start_the_asterisk_call = ClientSession(
        timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
    )
    await session_start_the_asterisk_call.post(
        url=asterisk_call_url + f"?phone={phone.replace('+', '00')}&message={message}",
        data=None,
        headers=None,
    )
    await session_start_the_asterisk_call.close()


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
    session_send_message_to_caller_sms = ClientSession(
        timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
    )
    await session_send_message_to_caller_sms.post(
        url=f"{caller_sms_url}?phone={phone.replace('+', '%2B')}&message={message}",
        data=None,
        headers=None,
    )

    await session_send_message_to_caller_sms.close()


async def the_alert_description(request_payload):
    """
    Extracts the description from the first firing alert in the request payload.

    This asynchronous function iterates through the alerts and returns the description annotation of the first alert with status 'firing'.

    Args:
        request_payload (dict): The payload containing alert information.

    Returns:
        list: A list containing the description string of the first firing alert, or "No data" if not present.
    """
    for alert_number, alert_payload in enumerate(request_payload["alerts"]):
        if alert_payload["status"] == "firing":
            return [alert_payload["annotations"].get("description", "No data")]


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
    for the_message in some_messages:
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

    instrument_aiohttp_app(app)

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
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=int(PROMETHEUS_WEBHOOK_PORT))
