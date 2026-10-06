"""
Data structures and transfer models for the asterisk_caller service.

Uses lightweight Python 3.14 slotted immutable dataclasses for optimal memory layout,
strict attribute enforcement, and rapid JSON serialization.
"""

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class PlaceCallPayload:
    """Incoming request payload for placing an outbound phone call."""

    phone: str
    message: str
    backup_callee: str = "false"
    lang: str | None = None


@dataclass(slots=True, frozen=True)
class QueueCallPayload:
    """Incoming request payload for enqueueing a call to the background worker."""

    phone: str
    message: str
    lang: str | None = None


@dataclass(slots=True, frozen=True)
class PlayAudioPayload:
    """Incoming request payload for playing an audio file to an active channel."""

    asterisk_chan: str
    msg_chk_sum: str
    lang: str | None = None


@dataclass(slots=True, frozen=True)
class AriOriginateResult:
    """Result of an Asterisk ARI channel origination."""

    status: int
    channel_id: str | None = None
