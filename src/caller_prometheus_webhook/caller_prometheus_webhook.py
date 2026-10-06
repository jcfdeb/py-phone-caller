"""
Prometheus Webhook service orchestrator and entry point.

Exposes endpoints compatible with Prometheus Alertmanager to trigger phone calls
and SMS notifications. Provides backward-compatible facades delegating to
modular schemas, clients, services, and routes.
"""

from __future__ import annotations
import asyncio
import hashlib
import logging
import os
import sys
import time
from typing import Any, Sequence

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

from aiohttp import web
from py_phone_caller_utils.config import settings
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app

from caller_prometheus_webhook.constants import (
    ASTERISK_CALL_APP_ROUTE_PLACE_CALL,
    ASTERISK_CALL_URL,
    CALLER_SMS_APP_ROUTE,
    CALLER_SMS_URL,
    CLIENT_TIMEOUT_TOTAL,
    LOG_FORMATTER,
    LOG_LEVEL,
    PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS,
    PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY,
    PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL,
    PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY,
    PROMETHEUS_WEBHOOK_PORT,
    PROMETHEUS_WEBHOOK_RECEIVERS,
    SMS_BEFORE_CALL_WAIT_SECONDS,
)
from caller_prometheus_webhook.clients import AsteriskCallClient, CallerSmsClient
from caller_prometheus_webhook.exceptions import (
    DeduplicationError,
    InvalidAlertPayloadError,
    NotificationDispatchError,
    PrometheusWebhookError,
)
from caller_prometheus_webhook.routes import (
    call_and_sms,
    call_only,
    response_for_alert_manager,
    setup_routes,
    sms_before_call,
    sms_only,
)
from caller_prometheus_webhook.schemas import (
    DispatchItem,
    NotificationMode,
    PrometheusAlert,
    WebhookPayload,
)
from caller_prometheus_webhook.services import (
    AlertNotificationService,
    DeduplicationService,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
init_telemetry("caller_prometheus_webhook")

# Singleton deduplication service and backward-compatible module cache
_dedup_service = DeduplicationService()
_LOCAL_DEDUP_CACHE = _dedup_service._local_cache


def _get_active_service() -> AlertNotificationService:
    """Builds an AlertNotificationService using dynamic module-level parameters."""
    call_client = AsteriskCallClient(
        base_url=globals().get("ASTERISK_CALL_URL", ASTERISK_CALL_URL),
        route=globals().get(
            "ASTERISK_CALL_APP_ROUTE_PLACE_CALL", ASTERISK_CALL_APP_ROUTE_PLACE_CALL
        ),
        timeout_total=float(globals().get("CLIENT_TIMEOUT_TOTAL", CLIENT_TIMEOUT_TOTAL)),
    )
    sms_client = CallerSmsClient(
        base_url=globals().get("CALLER_SMS_URL", CALLER_SMS_URL),
        route=globals().get("CALLER_SMS_APP_ROUTE", CALLER_SMS_APP_ROUTE),
        timeout_total=float(globals().get("CLIENT_TIMEOUT_TOTAL", CLIENT_TIMEOUT_TOTAL)),
    )
    return AlertNotificationService(
        call_client=call_client,
        sms_client=sms_client,
        dedup_service=_dedup_service,
        sms_wait_seconds=float(
            globals().get("SMS_BEFORE_CALL_WAIT_SECONDS", SMS_BEFORE_CALL_WAIT_SECONDS)
        ),
    )


# ---------------------------------------------------------------------------
# Backward-compatible function facades
# ---------------------------------------------------------------------------

async def is_duplicate_alert(message: str, ttl_seconds: int = 180) -> bool:
    """Checks whether an alert message has been seen recently."""
    return await _dedup_service.is_duplicate(message, ttl_seconds=ttl_seconds)


async def producer(payload: Any, queue: asyncio.Queue) -> None:
    """Adds a payload to the provided asyncio queue."""
    await queue.put(payload)


async def do_call_only(our_receiver: str, our_message: str) -> None:
    """Initiates a phone call to the specified receiver."""
    svc = _get_active_service()
    await svc.do_call_only(our_receiver, our_message)


async def send_the_sms(the_number: str, the_message: str) -> None:
    """Sends an SMS message to the specified number."""
    svc = _get_active_service()
    await svc.do_sms_only(the_number, the_message)


async def schedule_sms_before_call(our_receiver: str, our_message: str) -> None:
    """Sends an SMS, waits for a delay, then initiates a call."""
    svc = _get_active_service()
    await svc._schedule_sms_before_call(our_receiver, our_message)


async def do_sms_before_call(our_receiver: str, our_message: str) -> None:
    """Schedules an SMS followed by phone call as a background task."""
    svc = _get_active_service()
    await svc.do_sms_before_call(our_receiver, our_message)


async def do_call_and_sms(our_receiver: str, our_message: str) -> None:
    """Dispatches simultaneous SMS and call to the receiver."""
    svc = _get_active_service()
    await svc.do_call_and_sms(our_receiver, our_message)


take_this_action = {
    "call_only": do_call_only,
    "sms_only": send_the_sms,
    "sms_before_call": do_sms_before_call,
    "call_and_sms": do_call_and_sms,
}


async def notification_actions(
    our_receiver: str, our_message: str, caller_func: str
) -> None:
    """Executes the notification action specified by caller_func key."""
    action_fn = globals().get("take_this_action", take_this_action).get(
        caller_func, do_call_only
    )
    await action_fn(our_receiver, our_message)


async def consumer(queue: asyncio.Queue, caller_func: str) -> None:
    """Consumes items from queue and processes notification actions."""
    while True:
        our_message, our_receiver = await queue.get()
        await asyncio.sleep(0.4)
        logging.info(
            f"Call/Message '{our_message}' for '{our_receiver}' through the endpoint '{caller_func}'"
        )
        actions_fn = globals().get("notification_actions", notification_actions)
        await actions_fn(our_receiver, our_message, caller_func)
        queue.task_done()


async def do_the_call(the_number: str, the_message: str) -> None:
    """Legacy alias initiating a call to the specified number."""
    start_call_fn = globals().get("start_the_asterisk_call", start_the_asterisk_call)
    await start_call_fn(the_number, the_message)


async def start_the_asterisk_call(phone: str, message: str) -> None:
    """Directly triggers outbound Asterisk call via AsteriskCallClient."""
    client = AsteriskCallClient(
        base_url=globals().get("ASTERISK_CALL_URL", ASTERISK_CALL_URL),
        route=globals().get(
            "ASTERISK_CALL_APP_ROUTE_PLACE_CALL", ASTERISK_CALL_APP_ROUTE_PLACE_CALL
        ),
        timeout_total=float(globals().get("CLIENT_TIMEOUT_TOTAL", CLIENT_TIMEOUT_TOTAL)),
    )
    await client.place_call(phone, message)


async def send_message_to_caller_sms(phone: str, message: str) -> None:
    """Directly triggers SMS message via CallerSmsClient."""
    client = CallerSmsClient(
        base_url=globals().get("CALLER_SMS_URL", CALLER_SMS_URL),
        route=globals().get("CALLER_SMS_APP_ROUTE", CALLER_SMS_APP_ROUTE),
        timeout_total=float(globals().get("CLIENT_TIMEOUT_TOTAL", CLIENT_TIMEOUT_TOTAL)),
    )
    await client.send_sms(phone, message)


async def the_alert_description(request_payload: dict[str, Any]) -> list[str]:
    """Extracts description from first firing alert in payload."""
    payload = WebhookPayload.from_dict(request_payload)
    return payload.firing_descriptions


async def process_the_queue(
    prometheus_message: str,
    receiver_nums: Sequence[str],
    caller_func: str,
) -> None:
    """Processes a queue of notification tasks across receivers."""
    queue: asyncio.Queue = asyncio.Queue()
    prod_fn = globals().get("producer", producer)
    cons_fn = globals().get("consumer", consumer)

    producers = [
        asyncio.create_task(prod_fn((prometheus_message, single_receiver), queue))
        for single_receiver in receiver_nums
    ]
    consumers = [asyncio.create_task(cons_fn(queue, caller_func))]
    await asyncio.gather(*producers)
    await queue.join()
    for a_consumer in consumers:
        a_consumer.cancel()


async def data_from_alert_manager(request: web.Request, caller_func: str) -> None:
    """Processes alert data from incoming request and dispatches notifications."""
    payload = await request.json()
    desc_fn = globals().get("the_alert_description", the_alert_description)
    some_messages = await desc_fn(payload)

    if some_messages:
        dedup_window = int(settings.get("DEDUPLICATION_WINDOW_SECONDS", 180))
        is_dup_fn = globals().get("is_duplicate_alert", is_duplicate_alert)
        queue_fn = globals().get("process_the_queue", process_the_queue)
        receivers = globals().get("PROMETHEUS_WEBHOOK_RECEIVERS", PROMETHEUS_WEBHOOK_RECEIVERS)

        for the_message in some_messages:
            if await is_dup_fn(the_message, ttl_seconds=dedup_window):
                logging.info(
                    f"Deduplicated repeating alert within {dedup_window}s window. Skipping duplicate calls."
                )
                continue
            await queue_fn(the_message, receivers, caller_func)


async def init_app() -> web.Application:
    """Initializes and configures the aiohttp application."""
    app = web.Application()
    instrument_aiohttp_app(app, "caller_prometheus_webhook")
    app["alert_service_factory"] = _get_active_service
    setup_routes(app)
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=int(PROMETHEUS_WEBHOOK_PORT))
