"""
HTTP request controllers and router registration for asterisk_caller.

Maps incoming REST endpoints to AsteriskCallerService methods, validates
payload parameters, and returns standardized JSON responses.
"""

import logging
import sys
from aiohttp import web
from py_phone_caller_utils.web import (
    create_service_catalog,
    extract_params,
    setup_swagger_routes,
)
from py_phone_caller_utils.web.readiness import (
    ReadinessRegistry,
    check_asterisk_ari,
    check_asterisk_pjsip_trunk,
)

from asterisk_caller.constants import (
    ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE,
    ASTERISK_CALL_APP_ROUTE_PLACE_CALL,
    ASTERISK_CALL_APP_ROUTE_PLAY,
    ASTERISK_CALL_ERROR,
    ASTERISK_CHAN_TYPE,
    ASTERISK_PASS,
    ASTERISK_PLAY_ERROR,
    ASTERISK_URL,
    ASTERISK_USER,
)
from asterisk_caller.exceptions import OnCallPhoneUnavailable
from asterisk_caller.schemas import (
    PlaceCallPayload,
    PlayAudioPayload,
    QueueCallPayload,
)
from asterisk_caller.services import AsteriskCallerService


def _resolve_service(service: AsteriskCallerService | None, app: web.Application) -> AsteriskCallerService:
    """Resolves the active service instance from parameter, application context, or default module."""
    if service is not None:
        return service
    app_srv = app.get("service")
    if app_srv is not None:
        return app_srv
    mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
    default_srv = getattr(mod, "_default_service", None) if mod else None
    if default_srv is not None:
        return default_srv
    from asterisk_caller.asterisk_caller import _build_default_service
    return _build_default_service()


async def extract_place_call_payload(request: web.Request) -> PlaceCallPayload:
    """Extracts and validates phone call parameters from query or body."""
    params = await extract_params(request)
    phone = params.get("phone")
    message = params.get("message")
    if not phone or not message:
        logging.exception(f"Missing 'phone' or 'message' on '{request.rel_url}'")
        raise web.HTTPBadRequest(reason=ASTERISK_CALL_ERROR)

    backup_callee = str(params.get("backup_callee", "false")).lower()
    lang = params.get("lang") or params.get("language")

    return PlaceCallPayload(
        phone=str(phone),
        message=str(message),
        backup_callee=backup_callee,
        lang=str(lang).strip() if lang else None,
    )


async def extract_queue_call_payload(request: web.Request) -> QueueCallPayload:
    """Extracts and validates enqueue call parameters."""
    params = await extract_params(request)
    phone = params.get("phone")
    message = params.get("message")
    if not phone or not message:
        logging.exception(f"Missing 'phone' or 'message' on '{request.rel_url}'")
        raise web.HTTPBadRequest(reason=ASTERISK_CALL_ERROR)

    lang = params.get("lang") or params.get("language")

    return QueueCallPayload(
        phone=str(phone),
        message=str(message),
        lang=str(lang).strip() if lang else None,
    )


async def extract_play_payload(request: web.Request) -> PlayAudioPayload:
    """Extracts and validates audio playback parameters."""
    params = await extract_params(request)
    asterisk_chan = params.get("asterisk_chan")
    msg_chk_sum = params.get("msg_chk_sum")
    lang = params.get("lang") or params.get("language")

    if not asterisk_chan or not msg_chk_sum:
        logging.exception(f"Missing channel or checksum parameters on '{request.rel_url}'")
        raise web.HTTPBadRequest(reason=ASTERISK_PLAY_ERROR)

    return PlayAudioPayload(
        asterisk_chan=str(asterisk_chan),
        msg_chk_sum=str(msg_chk_sum),
        lang=str(lang) if lang else None,
    )


async def place_call(
    request: web.Request, service: AsteriskCallerService | None = None
) -> web.Response:
    """Handles POST /place_call requests to trigger immediate Asterisk outbound dialing."""
    srv = _resolve_service(service, request.app)
    payload = await extract_place_call_payload(request)

    try:
        call_resp = await srv.start_call(payload)
    except OnCallPhoneUnavailable as err:
        logging.warning(f"Unable to place call: {err}")
        return web.json_response({"status": 400, "error": str(err)}, status=400)
    except web.HTTPServiceUnavailable:
        return web.json_response(
            {"status": 503, "error": "Asterisk PBX circuit breaker open"},
            status=503,
        )

    return web.json_response({"status": call_resp.status})


async def call_to_queue(
    request: web.Request, service: AsteriskCallerService | None = None
) -> web.Response:
    """Handles POST /call_to_queue requests to buffer calls for the worker thread."""
    srv = _resolve_service(service, request.app)
    payload = await extract_queue_call_payload(request)
    srv.enqueue_call(payload)
    return web.json_response({"status": 200})


async def asterisk_play(
    request: web.Request, service: AsteriskCallerService | None = None
) -> web.Response:
    """Handles POST /play requests to play generated audio to an active channel."""
    srv = _resolve_service(service, request.app)
    payload = await extract_play_payload(request)
    status_code = await srv.play_audio_to_channel(payload)
    return web.json_response({"status": status_code})


async def root_catalog(request: web.Request) -> web.Response:
    """Returns discovery metadata and route catalog for asterisk_caller."""
    catalog = create_service_catalog(
        service_name="asterisk_caller",
        description="Asterisk ARI Call Placement and Audio Dispatch Service for py-phone-caller",
        version="1.0.1",
        docs_url="/docs",
        openapi_spec="/docs/swagger.json",
        endpoints={
            f"POST /{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}": "Places immediate outbound call via ARI (phone, message, lang)",
            f"POST /{ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE}": "Enqueues call for background worker (phone, message, lang)",
            f"POST /{ASTERISK_CALL_APP_ROUTE_PLAY}": "Plays audio to channel (asterisk_chan, msg_chk_sum, lang)",
            "GET /live": "Liveness health check",
            "GET /ready": "Readiness probe verifying Asterisk ARI and PJSIP trunk",
            "GET /metrics": "Prometheus telemetry metrics",
        },
    )
    return web.json_response(catalog)


def setup_routes(app: web.Application, service: AsteriskCallerService) -> None:
    """Configures application routes, readiness probes, and Swagger specifications."""
    app["service"] = service

    def _get_ari_url():
        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        return getattr(mod, "ASTERISK_URL", ASTERISK_URL) if mod else ASTERISK_URL

    def _get_chan_type():
        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        return getattr(mod, "ASTERISK_CHAN_TYPE", ASTERISK_CHAN_TYPE) if mod else ASTERISK_CHAN_TYPE

    def _get_user():
        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        return getattr(mod, "ASTERISK_USER", ASTERISK_USER) if mod else ASTERISK_USER

    def _get_pass():
        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        return getattr(mod, "ASTERISK_PASS", ASTERISK_PASS) if mod else ASTERISK_PASS

    registry = ReadinessRegistry("asterisk_caller")
    registry.register("asterisk_ari", lambda: check_asterisk_ari(_get_ari_url(), _get_user(), _get_pass()))
    registry.register("pjsip_trunk", lambda: check_asterisk_pjsip_trunk(_get_ari_url(), _get_user(), _get_pass(), _get_chan_type()))

    async def asterisk_caller_ready(request: web.Request) -> web.Response:
        all_ready, details = await registry.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    app.router.add_route("GET", "/ready", asterisk_caller_ready)
    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route("POST", f"/{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}", place_call)
    app.router.add_route("POST", f"/{ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE}", call_to_queue)
    app.router.add_route("POST", f"/{ASTERISK_CALL_APP_ROUTE_PLAY}", asterisk_play)

    setup_swagger_routes(
        app=app,
        service_name="asterisk_caller",
        description="Asterisk ARI Call Placement and Audio Dispatch Service",
        paths={
            f"/{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}": {
                "post": {
                    "summary": "Place immediate call via ARI",
                    "description": "Initiates an outbound phone call through Asterisk ARI.",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "phone": {"type": "string", "example": "0039123456789"},
                                        "message": {"type": "string", "example": "Critical alert"},
                                        "backup_callee": {"type": "boolean", "default": False},
                                        "lang": {"type": "string", "example": "en"},
                                    },
                                    "required": ["phone", "message"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Call successfully placed"}},
                }
            },
            f"/{ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE}": {
                "post": {
                    "summary": "Enqueue call for background dialing",
                    "description": "Places call onto internal worker queue.",
                    "responses": {"200": {"description": "Enqueued successfully"}},
                }
            },
            f"/{ASTERISK_CALL_APP_ROUTE_PLAY}": {
                "post": {
                    "summary": "Play audio to active channel",
                    "description": "Dispatches audio playback command to active channel in Stasis.",
                    "responses": {"200": {"description": "Playback started"}},
                }
            },
        },
    )
