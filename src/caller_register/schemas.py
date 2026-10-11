"""
Data structures and transfer models for the caller_register service.

Uses lightweight Python 3.14 slotted dataclasses for optimal memory layout,
strict attribute enforcement, and rapid JSON serialization.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class CallRegistrationPayload:
    """Incoming request payload for registering an outbound call attempt."""

    phone: str
    message: str
    asterisk_chan: str
    oncall: bool = False
    backup_callee: bool = False
    lang: str | None = None


@dataclass(slots=True, frozen=True)
class CallChecksums:
    """Computed cryptographic and uniqueness hashes for a call attempt."""

    call_chk_sum: str
    msg_chk_sum: str
    unique_chk_sum: str
    first_dial: datetime


@dataclass(slots=True, frozen=True)
class VoiceMessagePayload:
    """Voice message text, integrity checksum, and optional language for an active channel."""

    message: str
    msg_chk_sum: str
    lang: str | None = None


@dataclass(slots=True, frozen=True)
class ScheduledCallPayload:
    """Payload representing a validated scheduled call converted to UTC."""

    phone: str
    message: str
    call_chk_sum: str
    inserted_at: datetime
    scheduled_at_utc: datetime
    lang: str | None = None
