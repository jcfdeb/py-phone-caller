"""
Asterisk Caller service orchestrator and entry point.

Exposes an aiohttp application to place outbound calls through the
Asterisk ARI API, enqueue calls for background processing, and play audio to active
channels. Provides backward-compatible facades delegating to ari_client,
services, and routes.
"""

import asyncio
from datetime import timedelta
import logging
import os
import sys
import threading

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

from aiobreaker import CircuitBreaker
from aiohttp import ClientSession, web

from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app

# Re-exported constants for backward compatibility
from asterisk_caller.constants import (  # noqa: F401
    ASTERISK_ARI_CHANNELS,
    ASTERISK_ARI_PLAY,
    ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE,
    ASTERISK_CALL_APP_ROUTE_PLACE_CALL,
    ASTERISK_CALL_APP_ROUTE_PLAY,
    ASTERISK_CALL_ERROR,
    ASTERISK_CALL_PORT,
    ASTERISK_CALLER_ID,
    ASTERISK_CHAN_TYPE,
    ASTERISK_CONTEXT,
    ASTERISK_EXTENSION,
    ASTERISK_PASS,
    ASTERISK_PLAY_ERROR,
    ASTERISK_URL,
    ASTERISK_USER,
    CALL_QUEUE,
    CALL_REGISTER_APP_ROUTE_REGISTER_CALL,
    CALL_REGISTER_URL,
    CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT,
    CALLER_ADDRESS_BOOK_URL,
    CLIENT_TIMEOUT_TOTAL,
    GENERATE_AUDIO_URL,
    LOG_FORMATTER,
    LOG_LEVEL,
    SERVING_AUDIO_FOLDER,
    WAIT_FOR_CALL_CYCLE,
    close_call_queue,
)

from asterisk_caller.ari_client import (
    AriClient,
    build_asterisk_query_string,
    gen_headers,
    raw_post_ari_call as _raw_post_ari_call,
    send_ari_continue,
)
from asterisk_caller.exceptions import OnCallPhoneUnavailable  # noqa: F401
from asterisk_caller.routes import (
    asterisk_play,
    call_to_queue,
    place_call,
    setup_routes,
)
from asterisk_caller.schemas import PlaceCallPayload
from asterisk_caller.services import (
    AsteriskCallerService,
    format_phone as _format_phone,
    manage_call_queue as _service_manage_call_queue,
    resolve_oncall_phone as _resolve_oncall_phone,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
init_telemetry("asterisk_caller")

ari_circuit_breaker = CircuitBreaker(
    fail_max=3,
    timeout_duration=timedelta(seconds=30),
    name="asterisk_ari_circuit_breaker",
)

the_asterisk_chan_type = ASTERISK_CHAN_TYPE


def _build_default_service() -> AsteriskCallerService:
    ari_client = AriClient(
        base_url=ASTERISK_URL,
        user=ASTERISK_USER,
        password=ASTERISK_PASS,
        circuit_breaker=ari_circuit_breaker,
        timeout_total=CLIENT_TIMEOUT_TOTAL,
    )
    return AsteriskCallerService(
        ari_client=ari_client,
        asterisk_url=ASTERISK_URL,
        chan_type=the_asterisk_chan_type,
        extension=ASTERISK_EXTENSION,
        context=ASTERISK_CONTEXT,
        caller_id=ASTERISK_CALLER_ID,
        call_register_url=CALL_REGISTER_URL,
        call_register_route=CALL_REGISTER_APP_ROUTE_REGISTER_CALL,
        audio_service_url=GENERATE_AUDIO_URL,
        audio_folder=SERVING_AUDIO_FOLDER,
        timeout_total=CLIENT_TIMEOUT_TOTAL,
    )


_default_service = _build_default_service()


# ---------------------------------------------------------------------------
# Backward-compatible function facades
# ---------------------------------------------------------------------------

async def get_asterisk_query_string(chan_type: str, phone: str) -> str:
    """Constructs the query string for initiating a call via the Asterisk ARI API."""
    formatted = _format_phone(phone)
    return build_asterisk_query_string(
        chan_type, formatted, ASTERISK_EXTENSION, ASTERISK_CONTEXT, ASTERISK_CALLER_ID
    )


async def validate_parameters(parameter: str, rel_url: str) -> str:
    """Validates the presence of a required parameter in the request."""
    if not parameter:
        logging.exception(f"No parameter passed on: '{rel_url}'")
        raise web.HTTPBadRequest(reason=ASTERISK_CALL_ERROR)
    return parameter


async def initiate_asterisk_call(
    asterisk_call_init: str,
    phone: str,
    resolved_phone: str,
    message: str,
    headers: dict[str, str],
    backup_callee: str = "false",
):
    """Initiates an ARI call and registers it in the call register service."""
    service = _build_default_service()
    return await service.initiate_asterisk_call(
        asterisk_call_init=asterisk_call_init,
        phone=phone,
        resolved_phone=resolved_phone,
        message=message,
        headers=headers,
        backup_callee=backup_callee,
    )


async def get_headers() -> dict[str, str]:
    """Generates HTTP Basic Authorization headers for the Asterisk ARI API."""
    return await gen_headers(f"{ASTERISK_USER}:{ASTERISK_PASS}")


async def asterisk_call_start(phone: str, message: str, backup_callee: str = "false"):
    """Initiates an outbound call using the Asterisk ARI API."""
    service = _build_default_service()
    payload = PlaceCallPayload(
        phone=phone,
        message=message,
        backup_callee=backup_callee,
    )
    return await service.start_call(payload)


def manage_call_queue() -> None:
    """Continuously manages the call queue in a dedicated thread."""
    _service_manage_call_queue(
        queue=CALL_QUEUE,
        call_start_fn=asterisk_call_start,
        wait_cycle=WAIT_FOR_CALL_CYCLE,
    )


async def init_app() -> web.Application:
    """Initializes and configures the aiohttp web application for Asterisk call operations."""
    app = web.Application()
    service = _build_default_service()
    setup_routes(app, service)
    instrument_aiohttp_app(app, "asterisk_caller")
    return app


if __name__ == "__main__":
    queue_thread = None

    try:
        queue_thread = threading.Thread(
            target=manage_call_queue,
            name="asterisk-call-queue-worker",
            daemon=False,
        )
        queue_thread.start()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        web_app = loop.run_until_complete(init_app())
        web.run_app(web_app, port=int(ASTERISK_CALL_PORT), loop=loop)

    except KeyboardInterrupt:
        logging.info("Asterisk caller interrupted. Shutting down.")

    finally:
        try:
            CALL_QUEUE.put_nowait(None)
        except Exception:
            pass

        if queue_thread is not None and queue_thread.is_alive():
            queue_thread.join(timeout=10)
