"""
Route handlers and endpoint routing for caller_sms.
"""

from __future__ import annotations
import logging
from aiohttp import web

from py_phone_caller_utils.web import (
    create_service_catalog,
    extract_params,
    setup_swagger_routes,
)
from py_phone_caller_utils.web.readiness import ReadinessRegistry, check_database_pool

from caller_sms.constants import (
    CALLER_SMS_APP_ROUTE,
    CALLER_SMS_ERROR,
)
from caller_sms.exceptions import InboundSmsParseError, MissingSmsParameterError
from caller_sms.schemas import (
    InboundSmsRequest,
    SendSmsRequest,
    SmsQueryFilter,
)
from caller_sms.services import (
    InboundSmsService,
    SmsDispatchService,
    SmsQueryService,
)


async def send_the_sms(request: web.Request) -> web.Response:
    """
    Handles incoming requests to send an SMS message to a specified phone number.

    Args:
        request: Incoming HTTP request.

    Returns:
        JSON response indicating delivery status.

    Raises:
        web.HTTPBadRequest: If 'phone' or 'message' is missing.
    """
    params = await extract_params(request)
    try:
        sms_request = SendSmsRequest.from_dict(params)
    except MissingSmsParameterError as err:
        logging.exception(
            f"No 'message' or 'phone' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=CALLER_SMS_ERROR, body=None, text=None, content_type=None
        ) from err

    service_factory = request.app.get("sms_dispatch_service_factory")
    service: SmsDispatchService = (
        service_factory() if service_factory else SmsDispatchService()
    )

    result = await service.send_sms(sms_request)
    return web.json_response(result.to_dict(), status=result.status_code)


async def receive_inbound_sms(request: web.Request) -> web.Response:
    """
    Receives incoming SMS webhook and correlates ACK tokens with active calls.

    Args:
        request: Webhook HTTP request.

    Returns:
        JSON response with acknowledgment status.
    """
    params = await extract_params(request)
    try:
        inbound_req = InboundSmsRequest.from_dict(params)
    except InboundSmsParseError as err:
        return web.json_response(
            {"status": 400, "error": str(err)},
            status=400,
        )

    service_factory = request.app.get("inbound_sms_service_factory")
    service: InboundSmsService = (
        service_factory() if service_factory else InboundSmsService()
    )

    result = await service.handle_inbound(inbound_req)
    return web.json_response(result.to_dict(), status=result.status)


async def get_sms_records(request: web.Request) -> web.Response:
    """
    Handles incoming requests to retrieve SMS records from the database.

    Args:
        request: HTTP GET request with query params.

    Returns:
        JSON response with list of formatted SMS records.
    """
    limit_param = request.rel_url.query.get("limit")
    limit = int(limit_param) if limit_param and limit_param.isdigit() else None
    phone = request.rel_url.query.get("phone")
    status = request.rel_url.query.get("status")

    query_filter = SmsQueryFilter(limit=limit, phone=phone, status=status)

    service_factory = request.app.get("sms_query_service_factory")
    service: SmsQueryService = (
        service_factory() if service_factory else SmsQueryService()
    )

    records = await service.get_records(query_filter)
    return web.json_response({"status": 200, "records": records})


def setup_routes(app: web.Application) -> None:
    """
    Sets up routes, readiness check, service catalog, and Swagger.

    Args:
        app: aiohttp Application.
    """
    registry = ReadinessRegistry("caller_sms")
    registry.register("postgres_pool", check_database_pool)

    async def caller_sms_ready(request: web.Request) -> web.Response:
        all_ready, details = await registry.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    async def root_catalog(request: web.Request) -> web.Response:
        catalog = create_service_catalog(
            service_name="caller_sms",
            description="Caller SMS service for py-phone-caller",
            version="1.0.0",
            docs_url="/docs",
            openapi_spec="/docs/swagger.json",
            endpoints={
                f"POST /{CALLER_SMS_APP_ROUTE}": "Dispatches SMS notification (JSON body or query params: phone, message)",
                "GET /get_sms": "Retrieves recent SMS records (optional query params: limit, phone, status)",
                "GET /live": "Liveness health check",
                "GET /ready": "Readiness probe",
                "GET /metrics": "Prometheus telemetry metrics",
            },
        )
        return web.json_response(catalog)

    app.router.add_route("GET", "/ready", caller_sms_ready)
    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route("POST", f"/{CALLER_SMS_APP_ROUTE}", send_the_sms)
    app.router.add_route("GET", "/get_sms", get_sms_records)
    app.router.add_route("POST", "/sms/inbound", receive_inbound_sms)

    setup_swagger_routes(
        app=app,
        service_name="caller_sms",
        description="Caller SMS emergency alert dispatch service for py-phone-caller",
        paths={
            f"/{CALLER_SMS_APP_ROUTE}": {
                "post": {
                    "summary": "Send an SMS message",
                    "description": "Sends an SMS alert via configured carrier (Twilio or on-premise serial modem). Accepts JSON body or query parameters.",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "phone": {"type": "string", "example": "0039123456789"},
                                        "message": {"type": "string", "example": "Critical server room overheat"},
                                    },
                                    "required": ["phone", "message"],
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "SMS sent successfully"},
                        "400": {"description": "Missing required phone or message parameter"},
                        "500": {"description": "Carrier sending failure"},
                    },
                }
            },
            "/get_sms": {
                "get": {
                    "summary": "Retrieve SMS log records",
                    "description": "Fetches recent SMS delivery records from Piccolo database.",
                    "parameters": [
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
                        {"name": "phone", "in": "query", "schema": {"type": "string"}},
                        {"name": "status", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {"description": "List of SMS log records"},
                    },
                }
            },
        },
    )
