"""
Domain schemas and data contracts for the caller_sms service.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from caller_sms.exceptions import MissingSmsParameterError, InboundSmsParseError


class SmsCarrier(StrEnum):
    """Supported carrier backends and routing origins."""

    TWILIO = "twilio"
    ON_PREMISE = "on_premise"
    TWILIO_FALLBACK = "twilio_fallback"
    INBOUND = "inbound"


class SmsStatus(StrEnum):
    """SMS delivery and processing states."""

    SENT = "sent"
    FAILED = "failed"
    RECEIVED = "received"
    RECEIVED_ACK = "received_ack"


@dataclass(slots=True, frozen=True)
class SendSmsRequest:
    """
    Data contract representing an outbound SMS request.

    Attributes:
        phone: Target phone number.
        message: SMS body text.
    """

    phone: str
    message: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SendSmsRequest:
        """
        Parses and validates incoming parameters into a SendSmsRequest.

        Args:
            data: Dictionary of parameters from request.

        Returns:
            A validated SendSmsRequest.

        Raises:
            MissingSmsParameterError: If phone or message is absent.
        """
        phone = data.get("phone")
        message = data.get("message")

        if not phone or not message:
            raise MissingSmsParameterError("Missing required parameter: 'phone' or 'message'")

        return cls(
            phone=str(phone).strip(),
            message=str(message).strip(),
        )


@dataclass(slots=True, frozen=True)
class SendSmsResult:
    """
    Result contract representing the outcome of an outbound SMS dispatch attempt.

    Attributes:
        status_code: HTTP response status code (200 or 500).
        status: Delivery status string ('sent' or 'failed').
        carrier: Carrier used ('twilio', 'on_premise', 'twilio_fallback', or original carrier).
        error_msg: Error description if failed, else empty string.
    """

    status_code: int
    status: str
    carrier: str
    error_msg: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Converts result to JSON-serializable dictionary."""
        response_data: dict[str, Any] = {"status": self.status_code}
        if self.error_msg:
            response_data["error"] = self.error_msg
        return response_data


@dataclass(slots=True, frozen=True)
class InboundSmsRequest:
    """
    Data contract representing an incoming SMS webhook payload.

    Attributes:
        sender_phone: Sourced phone number.
        raw_body: Original unaltered SMS body.
        body_text: Normalized uppercase body string for token matching.
    """

    sender_phone: str
    raw_body: str
    body_text: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InboundSmsRequest:
        """
        Parses incoming webhook parameters.

        Args:
            data: Parameters dictionary.

        Returns:
            InboundSmsRequest instance.

        Raises:
            InboundSmsParseError: If sender or body is missing.
        """
        raw_from = data.get("From") or data.get("phone") or data.get("from", "")
        raw_body = data.get("Body") or data.get("message") or data.get("text", "")

        sender_phone = str(raw_from).strip()
        body_text = str(raw_body).strip().upper()

        if not sender_phone or not body_text:
            raise InboundSmsParseError("Missing sender phone or message body")

        return cls(
            sender_phone=sender_phone,
            raw_body=str(raw_body),
            body_text=body_text,
        )


@dataclass(slots=True, frozen=True)
class InboundSmsResult:
    """
    Result contract representing inbound SMS acknowledgment outcome.

    Attributes:
        status: Response status code (200 or 400).
        acknowledged: Whether an active call was acknowledged.
        matched_calls: Count of calls acknowledged.
        error: Optional error message.
    """

    status: int
    acknowledged: bool = False
    matched_calls: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Converts result to JSON-serializable dictionary."""
        data: dict[str, Any] = {
            "status": self.status,
            "acknowledged": self.acknowledged,
            "matched_calls": self.matched_calls,
        }
        if self.error:
            data["error"] = self.error
        return data


@dataclass(slots=True, frozen=True)
class SmsQueryFilter:
    """
    Query filter for retrieving SMS log records.

    Attributes:
        limit: Max records to return.
        phone: Optional phone filter.
        status: Optional status filter.
    """

    limit: int | None = None
    phone: str | None = None
    status: str | None = None
