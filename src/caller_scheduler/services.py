"""
Business logic and services for call scheduling and timezone conversion.
"""

from __future__ import annotations
from datetime import datetime
import logging
import pytz
from dateutil import parser

from caller_scheduler.constants import LOCAL_TIMEZONE
from caller_scheduler.dispatcher import CeleryTaskDispatcher, TaskDispatcherProtocol
from caller_scheduler.exceptions import (
    InvalidScheduleTimeError,
    TaskEnqueueError,
)
from caller_scheduler.schemas import (
    PriorityQueue,
    ScheduleCallRequest,
    ScheduleCallResponse,
)


class TimezoneConverter:
    """Utility service to parse and convert local timestamps to UTC."""

    def __init__(self, local_timezone_name: str = LOCAL_TIMEZONE) -> None:
        """
        Initializes the TimezoneConverter.

        Args:
            local_timezone_name: Name of the local timezone (e.g. 'Europe/Rome').
        """
        self.local_timezone_name = local_timezone_name

    def to_utc(self, timestamp_str: str) -> datetime:
        """
        Parses a date string, applies local timezone if naive, and converts to UTC.

        Args:
            timestamp_str: String representation of date and time.

        Returns:
            A timezone-aware datetime in UTC.

        Raises:
            InvalidScheduleTimeError: If the timestamp cannot be parsed or converted.
        """
        try:
            scheduled_at = parser.parse(timestamp_str)
            tz = pytz.timezone(self.local_timezone_name)

            if scheduled_at.tzinfo is None:
                localized = tz.localize(scheduled_at, is_dst=None)
            else:
                localized = scheduled_at

            return localized.astimezone(pytz.utc)
        except Exception as err:
            logging.exception(f"Unable to convert timestamp '{timestamp_str}' to UTC: {err}")
            raise InvalidScheduleTimeError(str(err)) from err


class CallSchedulerService:
    """
    Orchestration service for scheduling outbound calls.

    Coordinates time conversion, priority queue determination, and Celery dispatch.
    """

    def __init__(
        self,
        dispatcher: TaskDispatcherProtocol | None = None,
        tz_converter: TimezoneConverter | None = None,
    ) -> None:
        """
        Initializes CallSchedulerService.

        Args:
            dispatcher: Task dispatcher instance. Defaults to CeleryTaskDispatcher().
            tz_converter: Timezone converter instance. Defaults to TimezoneConverter().
        """
        self.dispatcher = dispatcher or CeleryTaskDispatcher()
        self.tz_converter = tz_converter or TimezoneConverter()

    def schedule(self, request: ScheduleCallRequest) -> ScheduleCallResponse:
        """
        Schedules a call by localizing its target execution time and dispatching to Celery.

        Args:
            request: Validated ScheduleCallRequest DTO.

        Returns:
            ScheduleCallResponse indicating success (200) or error (400, 500).
        """
        logging.info(
            f"Received a new call to '{request.phone}' with the message '{request.message}' "
            f"to be scheduled at '{request.scheduled_at}'."
        )

        try:
            scheduled_at_utc = self.tz_converter.to_utc(request.scheduled_at)
            logging.info(
                f"Scheduling call for {request.scheduled_at} converted to UTC: {scheduled_at_utc}"
            )
        except InvalidScheduleTimeError as err:
            return ScheduleCallResponse(status=400, message=str(err))

        queue_name = PriorityQueue.from_priority(request.priority).value

        try:
            self.dispatcher.dispatch(
                phone=request.phone,
                message=request.message,
                eta=scheduled_at_utc,
                priority=request.priority,
                queue=queue_name,
                lang=request.lang,
            )
            return ScheduleCallResponse(status=200)
        except (TaskEnqueueError, Exception) as err:
            logging.exception(f"Unable to place the call due: {err}")
            return ScheduleCallResponse(status=500, message=str(err))
