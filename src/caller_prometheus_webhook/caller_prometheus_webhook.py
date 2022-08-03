import asyncio
import logging

from aiohttp import ClientSession, ClientTimeout, web

import caller_utils.caller_configuration as conf

logging.basicConfig(format=conf.get_log_formatter())


async def producer(payload, queue):
    await queue.put(payload)


async def do_call_only(our_receiver, our_message):
    # https://docs.python.org/3/library/asyncio-task.html#running-tasks-concurrently
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
    await send_message_to_caller_sms(the_number, the_message)


async def schedule_sms_before_call(our_receiver, our_message):
    await send_the_sms(our_receiver, our_message)
    await asyncio.sleep(int(conf.get_sms_before_call_wait_seconds()))
    await do_call_only(our_receiver, our_message)


async def do_sms_before_call(our_receiver, our_message):
    asyncio.create_task(schedule_sms_before_call(our_receiver, our_message))


async def do_call_and_sms(our_receiver, our_message):
    await send_the_sms(our_receiver, our_message)
    await do_call_only(our_receiver, our_message)


take_this_action = {
    "call_only": do_call_only,
    "sms_only": send_the_sms,
    "sms_before_call": do_sms_before_call,
    "call_and_sms": do_call_and_sms,
}


async def notification_actions(our_receiver, our_message, caller_func):
    await take_this_action[caller_func](our_receiver, our_message)


async def consumer(queue, caller_func):
    while True:
        our_message, our_receiver = await queue.get()
        await asyncio.sleep(0.4)
        logging.info(
            f"Call/Message '{our_message}' for '{our_receiver}' through the endpoint '{caller_func}'"
        )
        await notification_actions(our_receiver, our_message, caller_func)
        queue.task_done()


async def do_the_call(the_number, the_message):
    await start_the_asterisk_call(the_number, the_message)  # Near working release test


async def process_the_queue(prometheus_message, receiver_nums, caller_func):
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
    Post the Prometheus incoming alert to 'asterisk_caller.py' (we're client now)
    """
    asterisk_call_url = f"{conf.get_asterisk_call_url()}/{conf.get_asterisk_call_app_route_place_call()}"
    session_start_the_asterisk_call = ClientSession(
        timeout=ClientTimeout(total=conf.get_client_timeout_total())
    )
    await session_start_the_asterisk_call.post(
        url=asterisk_call_url + f"?phone={phone.replace('+', '00')}&message={message}",
        data=None,
        headers=None,
    )
    await session_start_the_asterisk_call.close()


async def send_message_to_caller_sms(phone, message):
    """
    Post the Prometheus incoming alert to 'caller_sms.py' (we're client now)
    """
    caller_sms_url = f"{conf.get_caller_sms_url()}/{conf.get_caller_sms_app_route()}"
    session_send_message_to_caller_sms = ClientSession(
        timeout=ClientTimeout(total=conf.get_client_timeout_total())
    )
    await session_send_message_to_caller_sms.post(
        url=f'{caller_sms_url}?phone={phone.replace("+", "%2B")}&message={message}',
        data=None,
        headers=None,
    )

    await session_send_message_to_caller_sms.close()


async def the_alert_description(request_payload):
    for alert_number, alert_payload in enumerate(request_payload["alerts"]):
        if alert_payload["status"] == "firing":
            return [alert_payload["annotations"].get("description", "No data")]


async def data_from_alert_manager(request, caller_func):
    # https://docs.aiohttp.org/en/stable/web_reference.html#aiohttp.web.BaseRequest.json
    payload = await request.json()
    some_messages = await the_alert_description(payload)
    for the_message in some_messages:
        await process_the_queue(
            the_message, conf.get_prometheus_webhook_receivers(), caller_func
        )


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
        "POST", f"/{conf.get_prometheus_webhook_app_route_call_only()}", call_only
    )
    app.router.add_route(
        "POST", f"/{conf.get_prometheus_webhook_app_route_sms_only()}", sms_only
    )
    app.router.add_route(
        "POST",
        f"/{conf.get_prometheus_webhook_app_route_sms_before_call()}",
        sms_before_call,
    )
    app.router.add_route(
        "POST",
        f"/{conf.get_prometheus_webhook_app_route_call_and_sms()}",
        call_and_sms,
    )
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=conf.get_prometheus_webhook_port())
