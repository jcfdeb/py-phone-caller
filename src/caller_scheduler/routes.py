"""
Route handlers and endpoint registration for the caller_scheduler service.
"""

from __future__ import annotations
import logging
from aiohttp import web

from py_phone_caller_utils.web import (
    extract_params,
    create_service_catalog,
    setup_swagger_routes,
)
from py_phone_caller_utils.web.readiness import ReadinessRegistry, check_redis_broker

from caller_scheduler.constants import (
    SCHEDULED_CALL_APP_ROUTE,
    SCHEDULED_CALL_ERROR,
)
from caller_scheduler.exceptions import MissingScheduleParameterError
from caller_scheduler.schemas import ScheduleCallRequest
from caller_scheduler.services import CallSchedulerService


async def schedule_this_call(request: web.Request) -> web.Response:
    """
    Schedules a call task to be executed at a specified date and time.

    Args:
        request: Incoming aiohttp web request.

    Returns:
        JSON response with execution status.

    Raises:
        web.HTTPBadRequest: If required parameters ('phone', 'message', 'scheduled_at') are missing.
    """
    params = await extract_params(request)

    try:
        call_request = ScheduleCallRequest.from_dict(params)
    except MissingScheduleParameterError as err:
        logging.exception(
            f"No 'phone', 'message' or 'scheduled_at' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=SCHEDULED_CALL_ERROR,
            body=None,
            text=None,
            content_type=None,
        ) from err

    service_factory = request.app.get("scheduler_service_factory")
    service: CallSchedulerService = service_factory() if service_factory else CallSchedulerService()

    result = service.schedule(call_request)
    return web.json_response(result.to_dict())


def setup_routes(app: web.Application) -> None:
    """
    Configures HTTP routes, readiness checks, service catalog, and Swagger.

    Args:
        app: The aiohttp web Application.
    """
    registry = ReadinessRegistry("caller_scheduler")
    registry.register("redis_broker", check_redis_broker)

    async def scheduler_ready(request: web.Request) -> web.Response:
        all_ready, details = await registry.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    async def root_catalog(request: web.Request) -> web.Response:
        catalog = create_service_catalog(
            service_name="caller_scheduler",
            description="Call scheduling service backed by Celery background tasks",
            version="1.0.0",
            docs_url="/docs",
            openapi_spec="/docs/swagger.json",
            endpoints={
                f"POST /{SCHEDULED_CALL_APP_ROUTE}": (
                    "Schedules an outbound call (JSON body or query params: phone, message, scheduled_at, priority)"
                ),
                "GET /live": "Liveness health check",
                "GET /ready": "Readiness probe",
                "GET /metrics": "Prometheus telemetry metrics",
            },
        )
        return web.json_response(catalog)

    app.router.add_route("GET", "/ready", scheduler_ready)
    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route("POST", f"/{SCHEDULED_CALL_APP_ROUTE}", schedule_this_call)

    setup_swagger_routes(
        app=app,
        service_name="caller_scheduler",
        description="Call Scheduler Service powered by Celery background tasks",
        paths={
            f"/{SCHEDULED_CALL_APP_ROUTE}": {
                "post": {
                    "summary": "Schedule a call for future dispatch",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "phone": {"type": "string", "example": "0039123456789"},
                                        "message": {"type": "string", "example": "Scheduled notification"},
                                        "scheduled_at": {"type": "string", "example": "2026-10-01 15:30:00"},
                                        "priority": {
                                            "type": "integer",
                                            "default": 5,
                                            "description": "Priority 0-9 (>=8 routes to telephony.p0)",
                                        },
                                        "lang": {
                                            "type": "string",
                                            "example": "spa",
                                            "description": "Optional target language code for TTS audio",
                                        },
                                    },
                                    "required": ["phone", "message", "scheduled_at"],
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Call scheduled successfully"},
                        "400": {"description": "Missing parameters or invalid date"},
                        "500": {"description": "Queue submission failure"},
                    },
                }
            }
        },
    )
