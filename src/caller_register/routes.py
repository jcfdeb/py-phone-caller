"""
HTTP request handlers and router registration for caller_register.

Maps inbound REST API requests to CallRegistrationService methods, validates
payload parameters, and returns standardized JSON responses.
"""

import logging
from typing import Any
from aiohttp import web

from py_phone_caller_utils.web import (
    create_service_catalog,
    extract_params,
    setup_swagger_routes,
)
from py_phone_caller_utils.web.readiness import (
    ReadinessRegistry,
    check_database_pool,
)
from caller_register.constants import (
    ACKNOWLEDGE_ERROR,
    CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE,
    CALL_REGISTER_APP_ROUTE_HEARD,
    CALL_REGISTER_APP_ROUTE_REGISTER_CALL,
    CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE,
    CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE,
    HEARD_ERROR,
    LOST_PARAMETERS_ERROR,
    REGISTER_CALL_ERROR,
    VOICE_MESSAGE_ERROR,
)
from caller_register.exceptions import InvalidScheduledDateError
from caller_register.schemas import CallRegistrationPayload
from caller_register.services import CallRegistrationService


async def extract_registration_payload(request: web.Request) -> CallRegistrationPayload:
    """Extracts and validates call registration parameters from query or JSON body.

    Args:
        request: The incoming aiohttp request.

    Returns:
        CallRegistrationPayload: Slotted dataclass with validated fields.

    Raises:
        web.HTTPBadRequest: If required fields (phone, message, asterisk_chan) are missing.
    """
    params = await extract_params(request)
    phone = params.get("phone")
    message = params.get("message")
    asterisk_chan = params.get("asterisk_chan")

    oncall_raw = params.get("oncall", False)
    oncall = (
        (str(oncall_raw).lower() == "true")
        if not isinstance(oncall_raw, bool)
        else oncall_raw
    )

    backup_raw = params.get("backup_callee", False)
    backup_callee = (
        (str(backup_raw).lower() == "true")
        if not isinstance(backup_raw, bool)
        else backup_raw
    )

    lang = params.get("lang") or params.get("language")

    if not phone or not message or not asterisk_chan:
        logging.exception(
            f"Missing required parameters on '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(reason=REGISTER_CALL_ERROR)

    return CallRegistrationPayload(
        phone=str(phone),
        message=str(message),
        asterisk_chan=str(asterisk_chan),
        oncall=oncall,
        backup_callee=backup_callee,
        lang=str(lang).strip() if lang else None,
    )


async def register_call(
    request: web.Request, service: CallRegistrationService | None = None
) -> web.Response:
    """Handles POST /register_call requests to record or update an outbound call."""
    srv = service or request.app.get("service") or CallRegistrationService()
    payload = await extract_registration_payload(request)
    await srv.process_call_registration(payload)
    return web.json_response({"status": 200})


async def acknowledge(
    request: web.Request, service: CallRegistrationService | None = None
) -> web.Response:
    """Handles GET /acknowledge requests when a callee acknowledges a call."""
    srv = service or request.app.get("service") or CallRegistrationService()
    params = await extract_params(request)
    asterisk_chan = params.get("asterisk_chan")

    if not asterisk_chan:
        logging.exception(f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'")
        raise web.HTTPBadRequest(reason=ACKNOWLEDGE_ERROR)

    acknowledged = await srv.acknowledge_channel(str(asterisk_chan))
    if not acknowledged:
        return web.json_response(
            {"status": 400, "message": "Call is outside the firing period or not found"},
            status=400,
        )

    return web.json_response({"status": 200})


async def heard(
    request: web.Request, service: CallRegistrationService | None = None
) -> web.Response:
    """Handles GET /heard requests marking audio message playback start."""
    srv = service or request.app.get("service") or CallRegistrationService()
    params = await extract_params(request)
    asterisk_chan = params.get("asterisk_chan")

    if not asterisk_chan:
        logging.exception(f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'")
        raise web.HTTPBadRequest(reason=HEARD_ERROR)

    await srv.mark_channel_heard(str(asterisk_chan))
    return web.json_response({"status": 200})


async def voice_message(
    request: web.Request, service: CallRegistrationService | None = None
) -> web.Response:
    """Handles POST /voice_message requests to fetch the message text, checksum, and target language."""
    srv = service or request.app.get("service") or CallRegistrationService()
    params = await extract_params(request)
    asterisk_chan = params.get("asterisk_chan")

    if not asterisk_chan:
        logging.exception(f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'")
        raise web.HTTPBadRequest(reason=VOICE_MESSAGE_ERROR)

    result = await srv.get_voice_message_payload(str(asterisk_chan))
    resp: dict[str, Any] = {
        "message": result.message,
        "msg_chk_sum": result.msg_chk_sum,
    }
    if result.lang:
        resp["lang"] = result.lang
        resp["language"] = result.lang
    return web.json_response(resp)


async def scheduled_call(
    request: web.Request, service: CallRegistrationService | None = None
) -> web.Response:
    """Handles POST /scheduled_call requests to enqueue future call attempts."""
    srv = service or request.app.get("service") or CallRegistrationService()
    params = await extract_params(request)
    phone = params.get("phone")
    message = params.get("message")
    scheduled_at_str = params.get("scheduled_at")
    lang = params.get("lang") or params.get("language")

    if not phone or not message or not scheduled_at_str:
        logging.exception(f"Missing required parameters on '{request.rel_url}'")
        raise web.HTTPBadRequest(reason=LOST_PARAMETERS_ERROR)

    try:
        await srv.parse_and_schedule_call(
            phone=str(phone),
            message=str(message),
            scheduled_at_str=str(scheduled_at_str),
            lang=str(lang).strip() if lang else None,
        )
        return web.json_response({"status": 200})
    except InvalidScheduledDateError as err:
        logging.exception(f"Date conversion error: {err}")
        return web.json_response({"status": 400, "message": str(err)})


async def root_catalog(request: web.Request) -> web.Response:
    """Returns discovery metadata and route catalog for caller_register."""
    catalog = create_service_catalog(
        service_name="caller_register",
        description="Call register and tracking service for py-phone-caller",
        version="1.0.1",
        docs_url="/docs",
        openapi_spec="/docs/swagger.json",
        endpoints={
            f"POST /{CALL_REGISTER_APP_ROUTE_REGISTER_CALL}": "Registers an outbound call (phone, message, asterisk_chan, lang)",
            f"POST /{CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE}": "Retrieves voice message and checksum for channel (asterisk_chan)",
            f"POST /{CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE}": "Records scheduled call (phone, message, scheduled_at, lang)",
            f"GET /{CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE}": "Marks call as acknowledged (asterisk_chan)",
            f"GET /{CALL_REGISTER_APP_ROUTE_HEARD}": "Marks call as heard (asterisk_chan)",
            "GET /live": "Liveness health check",
            "GET /ready": "Readiness probe",
            "GET /metrics": "Prometheus telemetry metrics",
        },
    )
    return web.json_response(catalog)


def setup_routes(app: web.Application, service: CallRegistrationService) -> None:
    """Configures application routes, readiness probes, and Swagger specifications."""
    app["service"] = service

    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route(
        "POST", f"/{CALL_REGISTER_APP_ROUTE_REGISTER_CALL}", register_call
    )
    app.router.add_route(
        "POST", f"/{CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE}", voice_message
    )
    app.router.add_route(
        "POST", f"/{CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE}", scheduled_call
    )
    app.router.add_route("GET", f"/{CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE}", acknowledge)
    app.router.add_route("GET", f"/{CALL_REGISTER_APP_ROUTE_HEARD}", heard)

    registry = ReadinessRegistry("caller_register")
    registry.register("postgres_pool", check_database_pool)

    async def caller_register_ready(request: web.Request) -> web.Response:
        all_ready, details = await registry.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    app.router.add_route("GET", "/ready", caller_register_ready)

    setup_swagger_routes(
        app=app,
        service_name="caller_register",
        description="Call registration, lifecycle tracking, and DTMF acknowledgment registry",
        paths={
            f"/{CALL_REGISTER_APP_ROUTE_REGISTER_CALL}": {
                "post": {
                    "summary": "Register call attempt",
                    "description": "Registers or updates a phone call attempt in the Piccolo database.",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "phone": {"type": "string", "example": "0039123456789"},
                                        "message": {"type": "string", "example": "Alert payload"},
                                        "asterisk_chan": {"type": "string", "example": "PJSIP/trunk-00000001"},
                                        "oncall": {"type": "boolean", "default": False},
                                        "backup_callee": {"type": "boolean", "default": False},
                                        "lang": {"type": "string", "example": "en"},
                                    },
                                    "required": ["phone", "message", "asterisk_chan"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Call successfully registered"}},
                }
            },
            f"/{CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE}": {
                "post": {
                    "summary": "Retrieve voice message for channel",
                    "description": "Retrieves alert message and checksum associated with active channel.",
                    "responses": {"200": {"description": "Voice message details"}},
                }
            },
            f"/{CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE}": {
                "post": {
                    "summary": "Record future scheduled call",
                    "description": "Parses and records scheduled call attempt.",
                    "responses": {"200": {"description": "Call successfully scheduled"}},
                }
            },
        },
    )
