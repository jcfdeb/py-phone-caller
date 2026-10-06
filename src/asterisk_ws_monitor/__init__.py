"""
asterisk_ws_monitor package.

Monitors Asterisk ARI WebSocket events, coordinates TTS audio generation,
and triggers audio playback to connected channels.
"""

from asterisk_ws_monitor.clients import (
    AsteriskPlaybackClient,
    AudioServiceClient,
    CallRegisterClient,
    EventBroadcaster,
)
from asterisk_ws_monitor.exceptions import (
    AsteriskWsMonitorError,
    AudioGenerationError,
    AudioNotReadyError,
    CallRegisterQueryError,
    PlaybackError,
    WsConnectionError,
)
from asterisk_ws_monitor.schemas import (
    AudioGenerationResult,
    AudioReadyStatus,
    StasisEvent,
    VoiceMessageInfo,
)
from asterisk_ws_monitor.services import WsMonitorService
from asterisk_ws_monitor.asterisk_ws_monitor import (
    audio_operations,
    audio_play_status_log,
    broadcast_stasis_event,
    generate_the_audio_file,
    get_asterisk_chan,
    play_audio_to_channel,
    querying_call_register,
    receive_signal,
    take_control_of_dialplan,
)

__all__ = [
    "AsteriskPlaybackClient",
    "AsteriskWsMonitorError",
    "AudioGenerationError",
    "AudioGenerationResult",
    "AudioNotReadyError",
    "AudioReadyStatus",
    "AudioServiceClient",
    "CallRegisterClient",
    "CallRegisterQueryError",
    "EventBroadcaster",
    "PlaybackError",
    "StasisEvent",
    "VoiceMessageInfo",
    "WsConnectionError",
    "WsMonitorService",
    "audio_operations",
    "audio_play_status_log",
    "broadcast_stasis_event",
    "generate_the_audio_file",
    "get_asterisk_chan",
    "play_audio_to_channel",
    "querying_call_register",
    "receive_signal",
    "take_control_of_dialplan",
]
