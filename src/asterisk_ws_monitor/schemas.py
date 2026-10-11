"""
Data schemas and contracts for the asterisk_ws_monitor service.

Adheres to Python 3.14 standards using immutable, slotted dataclasses
for high performance and strict type checking.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(slots=True, frozen=True)
class StasisEvent:
    """
    Represents an event received from the Asterisk ARI WebSocket stream.

    Attributes:
        event_type: Type of the Stasis event (e.g. 'StasisStart', 'PlaybackStarted').
        channel_id: Identifier of the Asterisk channel involved.
        channel_state: Operational state of the channel (e.g. 'Up', 'Ringing').
        timestamp: Event occurrence timestamp as ISO formatted string.
        raw_data: Unmodified event payload mapping.
    """

    event_type: str
    channel_id: str
    channel_state: str = ""
    timestamp: str | None = None
    raw_data: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StasisEvent:
        """
        Parses an incoming raw Asterisk WebSocket JSON dictionary.

        Args:
            data: Key-value dictionary received from Asterisk ARI WebSocket.

        Returns:
            A validated immutable StasisEvent instance.
        """
        event_type = str(data.get("type") or "")
        channel_data = data.get("channel")
        channel_state = ""
        channel_id = ""

        if event_type in ("PlaybackStarted", "PlaybackFinished"):
            playback = data.get("playback")
            if isinstance(playback, dict):
                target_uri = str(playback.get("target_uri") or "")
                if ":" in target_uri:
                    channel_id = target_uri.split(":", 1)[1]
        elif isinstance(channel_data, dict):
            channel_id = str(channel_data.get("id") or "")
            channel_state = str(channel_data.get("state") or "")

        return cls(
            event_type=event_type,
            channel_id=channel_id,
            channel_state=channel_state,
            timestamp=data.get("timestamp"),
            raw_data=data,
        )

    def is_actionable(
        self, target_event_type: str = "StasisStart", target_state: str = "Up"
    ) -> bool:
        """
        Evaluates whether this event requires dialplan intervention and playback.

        Args:
            target_event_type: The expected event type trigger.
            target_state: The expected channel state.

        Returns:
            True if the event matches actionable criteria, False otherwise.
        """
        return self.event_type == target_event_type and self.channel_state == target_state


@dataclass(slots=True, frozen=True)
class VoiceMessageInfo:
    """
    Metadata describing the audio message to play on an active channel.

    Attributes:
        message: Text content of the alert prompt.
        msg_chk_sum: MD5/SHA checksum identifying the generated wave file.
        lang: Optional ISO language code (e.g. 'en', 'es', 'it').
        speed: Optional speech rate factor (e.g. 1.0, 1.2).
    """

    message: str
    msg_chk_sum: str
    lang: str | None = None
    speed: float | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VoiceMessageInfo:
        """
        Constructs a VoiceMessageInfo instance from call register response data.

        Args:
            data: Dictionary returned by the call register service.

        Returns:
            Validated immutable VoiceMessageInfo.
        """
        raw_speed = data.get("speed")
        parsed_speed = float(raw_speed) if raw_speed is not None else None
        return cls(
            message=str(data.get("message") or ""),
            msg_chk_sum=str(data.get("msg_chk_sum") or ""),
            lang=data.get("lang") or data.get("language"),
            speed=parsed_speed,
        )


@dataclass(slots=True, frozen=True)
class AudioReadyStatus:
    """
    Status response from audio generation polling.

    Attributes:
        exists: Flag indicating whether the audio wave file is rendered and ready.
        msg_chk_sum: Checksum of the checked audio file.
    """

    exists: bool = False
    msg_chk_sum: str = ""


@dataclass(slots=True, frozen=True)
class AudioGenerationResult:
    """
    Outcome of an audio generation and caching pipeline execution.

    Attributes:
        status: HTTP or process status code.
        msg_chk_sum: Checksum of the generated audio.
        cached: True if the file already existed in the audio cache.
    """

    status: int
    msg_chk_sum: str
    cached: bool = False
