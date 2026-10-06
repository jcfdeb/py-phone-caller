"""
Domain schemas and data contracts for the caller_scheduler service.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from caller_scheduler.exceptions import MissingScheduleParameterError


class PriorityQueue(StrEnum):
    """Routing queues for telephony tasks based on priority."""

    P0 = "telephony.p0"
    P2 = "telephony.p2"

    @classmethod
    def from_priority(cls, priority: int) -> PriorityQueue:
        """
        Determines queue name based on priority threshold (>=8 routes to P0).

        Args:
            priority: Integer priority level (0-9).

        Returns:
            The appropriate PriorityQueue enum member.
        """
        return cls.P0 if priority >= 8 else cls.P2


@dataclass(slots=True, frozen=True)
class ScheduleCallRequest:
    """
    Data contract representing a validated call scheduling request.

    Attributes:
        phone: Target phone number.
        message: Text notification message.
        scheduled_at: Raw requested timestamp string.
        priority: Task priority level (default 5).
        lang: Optional target language code for TTS audio.
    """

    phone: str
    message: str
    scheduled_at: str
    priority: int = 5
    lang: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleCallRequest:
        """
        Parses and validates a dictionary into a ScheduleCallRequest.

        Args:
            data: Raw input parameters (JSON body or query dictionary).

        Returns:
            A frozen ScheduleCallRequest instance.

        Raises:
            MissingScheduleParameterError: If phone, message, or scheduled_at is missing.
        """
        phone = data.get("phone")
        message = data.get("message")
        scheduled_at = data.get("scheduled_at")

        if not phone or not message or not scheduled_at:
            raise MissingScheduleParameterError(
                "Missing required parameters: 'phone', 'message', or 'scheduled_at'"
            )

        raw_priority = data.get("priority", 5)
        try:
            priority = int(raw_priority)
        except (ValueError, TypeError):
            priority = 5

        lang = data.get("lang") or data.get("language")

        return cls(
            phone=str(phone).strip(),
            message=str(message).strip(),
            scheduled_at=str(scheduled_at).strip(),
            priority=priority,
            lang=str(lang).strip() if lang else None,
        )


@dataclass(slots=True, frozen=True)
class ScheduleCallResponse:
    """
    Response contract returned after attempting to schedule a call.

    Attributes:
        status: HTTP-equivalent status code (200, 400, 500).
        message: Optional human-readable message or error detail.
    """

    status: int
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Converts response to dictionary representation."""
        result: dict[str, Any] = {"status": self.status}
        if self.message is not None:
            result["message"] = self.message
        return result
