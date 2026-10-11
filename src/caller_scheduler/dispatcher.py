"""
Task dispatcher abstraction for enqueuing Celery background call tasks.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Protocol

from py_phone_caller_utils.tasks.celery_task import do_this_call
from caller_scheduler.exceptions import TaskEnqueueError


class TaskDispatcherProtocol(Protocol):
    """Protocol defining the task dispatching interface."""

    def dispatch(
        self,
        phone: str,
        message: str,
        eta: datetime,
        priority: int,
        queue: str,
        lang: str | None = None,
    ) -> Any:
        """Enqueues an asynchronous call task."""
        ...


class CeleryTaskDispatcher:
    """Dispatches call tasks via Celery background workers."""

    def __init__(self, task_target: Any = do_this_call) -> None:
        """
        Initializes the Celery dispatcher.

        Args:
            task_target: Celery task callable supporting .apply_async().
        """
        self.task_target = task_target

    def dispatch(
        self,
        phone: str,
        message: str,
        eta: datetime,
        priority: int,
        queue: str,
        lang: str | None = None,
    ) -> Any:
        """
        Dispatches a phone call task to Celery with ETA and priority routing.

        Args:
            phone: Destination phone number.
            message: Voice notification message.
            eta: UTC datetime when the call should be placed.
            priority: Integer priority level.
            queue: Celery queue name (e.g. telephony.p0 or telephony.p2).
            lang: Optional TTS language override.

        Returns:
            The Celery AsyncResult or task execution outcome.

        Raises:
            TaskEnqueueError: If dispatching fails.
        """
        apply_kwargs: dict[str, Any] = {
            "priority": priority,
            "queue": queue,
            "eta": eta,
        }
        if lang:
            apply_kwargs["kwargs"] = {"lang": lang}

        try:
            # Pass positional [phone, message] to maintain backward compatibility
            return self.task_target.apply_async(
                [phone, message],
                **apply_kwargs,
            )
        except Exception as err:
            raise TaskEnqueueError(f"Unable to enqueue call task: {err}") from err
