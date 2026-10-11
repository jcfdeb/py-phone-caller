"""
Exception hierarchy for the caller_scheduler service.
"""

from __future__ import annotations


class CallerSchedulerError(Exception):
    """Base exception for all caller_scheduler errors."""


class MissingScheduleParameterError(CallerSchedulerError):
    """Raised when required schedule parameters (phone, message, scheduled_at) are missing."""


class InvalidScheduleTimeError(CallerSchedulerError):
    """Raised when the scheduled time cannot be parsed or localized."""


class TaskEnqueueError(CallerSchedulerError):
    """Raised when enqueuing the background Celery task fails."""
