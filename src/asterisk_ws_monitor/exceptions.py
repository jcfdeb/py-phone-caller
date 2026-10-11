"""
Domain exceptions for the asterisk_ws_monitor service.

Provides strongly-typed domain exception hierarchies to categorize
Asterisk WebSocket monitor failures, service queries, audio generation,
and channel playback errors.
"""


class AsteriskWsMonitorError(Exception):
    """Base exception for all asterisk_ws_monitor domain errors."""


class CallRegisterQueryError(AsteriskWsMonitorError):
    """Raised when querying the call register service fails."""


class AudioGenerationError(AsteriskWsMonitorError):
    """Raised when generating an audio file fails."""


class AudioNotReadyError(AudioGenerationError):
    """Raised when an audio file is not ready after polling timeout."""


class PlaybackError(AsteriskWsMonitorError):
    """Raised when initiating audio playback on a channel fails."""


class WsConnectionError(AsteriskWsMonitorError):
    """Raised when connecting to or communicating with the Asterisk WebSocket fails."""
