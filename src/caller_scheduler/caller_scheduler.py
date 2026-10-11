"""
Caller Scheduler service.

Provides an endpoint to schedule future automated calls, converting requested
local times to UTC and enqueuing them via Celery background tasks with priority routing.
"""

from __future__ import annotations
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

from aiohttp import web
from py_phone_caller_utils.tasks.celery_task import do_this_call
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app

from caller_scheduler.constants import (
    LOCAL_TIMEZONE,
    LOG_FORMATTER,
    LOG_LEVEL,
    SCHEDULED_CALL_APP_ROUTE,
    SCHEDULED_CALL_ERROR,
    SCHEDULED_CALLS_PORT,
)
from caller_scheduler.dispatcher import CeleryTaskDispatcher
from caller_scheduler.exceptions import (
    CallerSchedulerError,
    InvalidScheduleTimeError,
    MissingScheduleParameterError,
    TaskEnqueueError,
)
from caller_scheduler.routes import schedule_this_call, setup_routes
from caller_scheduler.schemas import (
    PriorityQueue,
    ScheduleCallRequest,
    ScheduleCallResponse,
)
from caller_scheduler.services import (
    CallSchedulerService,
    TimezoneConverter,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
init_telemetry("caller_scheduler")


def _get_active_service() -> CallSchedulerService:
    """Builds a CallSchedulerService with the current Celery task and timezone."""
    dispatcher = CeleryTaskDispatcher(task_target=globals().get("do_this_call", do_this_call))
    tz_converter = TimezoneConverter(
        local_timezone_name=globals().get("LOCAL_TIMEZONE", LOCAL_TIMEZONE)
    )
    return CallSchedulerService(dispatcher=dispatcher, tz_converter=tz_converter)


async def init_app() -> web.Application:
    """
    Initializes and configures the aiohttp web application for scheduling calls.

    Returns:
        The configured aiohttp web.Application.
    """
    app = web.Application()
    instrument_aiohttp_app(app, "caller_scheduler")
    app["scheduler_service_factory"] = _get_active_service
    setup_routes(app)
    return app


if __name__ == "__main__":
    app = init_app()
    web.run_app(app, port=SCHEDULED_CALLS_PORT)
