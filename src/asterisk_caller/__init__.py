"""
asterisk_caller package.

Provides outbound telephony dispatch, Asterisk ARI channel control,
audio playback, and background dialing queue management.
"""

from asterisk_caller.ari_client import (
    AriClient,
    build_asterisk_query_string,
    gen_headers,
    send_ari_continue,
)
from asterisk_caller.exceptions import (
    AriConnectionError,
    AsteriskCallerError,
    CircuitBreakerOpenError,
    MissingParameterError,
    OnCallPhoneUnavailable,
)
from asterisk_caller.schemas import (
    AriOriginateResult,
    PlaceCallPayload,
    PlayAudioPayload,
    QueueCallPayload,
)
from asterisk_caller.services import (
    AsteriskCallerService,
    format_phone,
    manage_call_queue,
    resolve_oncall_phone,
)

__all__ = [
    "AriClient",
    "AriConnectionError",
    "AriOriginateResult",
    "AsteriskCallerError",
    "AsteriskCallerService",
    "CircuitBreakerOpenError",
    "MissingParameterError",
    "OnCallPhoneUnavailable",
    "PlaceCallPayload",
    "PlayAudioPayload",
    "QueueCallPayload",
    "build_asterisk_query_string",
    "format_phone",
    "gen_headers",
    "manage_call_queue",
    "resolve_oncall_phone",
    "send_ari_continue",
]
