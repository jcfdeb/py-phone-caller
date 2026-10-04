"""
Caller Scheduler service.

Provides an endpoint to schedule future automated calls, converting requested
local times to UTC and enqueuing them via Celery background tasks with priority routing.
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


import pytz
from dateutil import parser
from aiohttp import web

from py_phone_caller_utils.tasks.celery_task import do_this_call
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app
from py_phone_caller_utils.web import extract_params, create_service_catalog, setup_swagger_routes
from py_phone_caller_utils.web.readiness import ReadinessRegistry, check_redis_broker

from caller_scheduler.constants import (
    SCHEDULED_CALL_APP_ROUTE,
    SCHEDULED_CALLS_PORT,
    LOCAL_TIMEZONE,
    SCHEDULED_CALL_ERROR,
    LOG_FORMATTER,
    LOG_LEVEL,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("caller_scheduler")


async def schedule_this_call(request):
    """
    Schedules a call task to be executed at a specified date and time.
    """
    params = await extract_params(request)
    phone = params.get("phone")
    message = params.get("message")
    scheduled_at_str = params.get("scheduled_at")
    priority = int(params.get("priority", 5))
    lang = params.get("lang") or params.get("language")

    if not phone or not message or not scheduled_at_str:
        logging.exception(
            f"No 'phone', 'message' or 'scheduled_at' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=SCHEDULED_CALL_ERROR,
            body=None,
            text=None,
            content_type=None,
        )

    logging.info(
        f"Received a new call to '{phone}' with the message '{message}' to be scheduled at '{scheduled_at_str}'."
    )

    try:
        scheduled_at = parser.parse(scheduled_at_str)
        local_timezone = pytz.timezone(LOCAL_TIMEZONE)

        if scheduled_at.tzinfo is None:
            localized_time = local_timezone.localize(scheduled_at, is_dst=None)
        else:
            localized_time = scheduled_at

        scheduled_at_utc = localized_time.astimezone(pytz.utc)
        logging.info(
            f"Scheduling call for {scheduled_at_str} localized as {localized_time} and converted to UTC: {scheduled_at_utc}"
        )
    except Exception as err:
        logging.exception(f"Unable to do the date/time conversions to UTC due: {err}")
        return web.json_response({"status": 400, "message": str(err)})

    try:
        queue_name = "telephony.p0" if priority >= 8 else "telephony.p2"
        apply_kwargs = {
            "priority": priority,
            "queue": queue_name,
            "eta": scheduled_at_utc,
        }
        if lang:
            apply_kwargs["kwargs"] = {"lang": lang}

        # Pass positional [phone, message] to maintain backward compatibility with mocks
        do_this_call.apply_async(
            [phone, message],
            **apply_kwargs,
        )
    except Exception as err:
        logging.exception(f"Unable to place the call due: {err}")
        return web.json_response({"status": 500, "message": str(err)})

    return web.json_response({"status": 200})


async def init_app():
    """
    Initializes and configures the aiohttp web application for scheduling calls.
    """
    app = web.Application()

    instrument_aiohttp_app(app, "caller_scheduler")

    registry = ReadinessRegistry("caller_scheduler")
    registry.register("redis_broker", check_redis_broker)

    async def scheduler_ready(request):
        all_ready, details = await registry.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    app.router.add_route("GET", "/ready", scheduler_ready)

    async def root_catalog(request):
        catalog = create_service_catalog(
            service_name="caller_scheduler",
            description="Call scheduling service backed by Celery background tasks",
            version="1.0.0",
            docs_url="/docs",
            openapi_spec="/docs/swagger.json",
            endpoints={
                f"POST /{SCHEDULED_CALL_APP_ROUTE}": "Schedules an outbound call (JSON body or query params: phone, message, scheduled_at, priority)",
                "GET /live": "Liveness health check",
                "GET /ready": "Readiness probe",
                "GET /metrics": "Prometheus telemetry metrics",
            },
        )
        return web.json_response(catalog)

    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route(
        "POST", f"/{SCHEDULED_CALL_APP_ROUTE}", schedule_this_call
    )

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
                                        "priority": {"type": "integer", "default": 5, "description": "Priority 0-9 (>=8 routes to telephony.p0)"},
                                        "lang": {"type": "string", "example": "spa", "description": "Optional target language code for TTS audio"},
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

    return app


if __name__ == "__main__":
    app = init_app()
    web.run_app(app, port=SCHEDULED_CALLS_PORT)
