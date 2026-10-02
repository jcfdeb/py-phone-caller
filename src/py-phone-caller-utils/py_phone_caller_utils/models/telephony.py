"""
Telephony, Asterisk events, and call dispatch domain models.
"""

from enum import Enum
from typing import Any, Dict, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


class ChannelState(str, Enum):
    DOWN = "Down"
    RESERVED = "Rsrved"
    OFFHOOK = "OffHook"
    DIALING = "Dialing"
    RING = "Ring"
    RINGING = "Ringing"
    UP = "Up"
    BUSY = "Busy"
    DIALING_OFFHOOK = "Dialing Offhook"
    PRE_RING = "Pre-ring"
    UNKNOWN = "Unknown"


class CallDispatchSpec(BaseModel):
    """
    Specification for Asterisk ARI call placement.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    endpoint: str = Field(..., description="Asterisk channel technology string, e.g. PJSIP/trunk/number")
    phone: str = Field(..., description="Normalized E.164 destination telephone number")
    audio_file: str = Field(..., description="Absolute path or relative playback sound file")
    context: str = Field(default="from-internal", description="Asterisk dialplan context")
    caller_id: Optional[str] = Field(default=None, description="Outbound Caller ID header")
    timeout_seconds: int = Field(default=60, ge=10, le=300, description="Ringing timeout")
    variables: Dict[str, Any] = Field(default_factory=dict, description="Channel variables")


class DtmfAckPayload(BaseModel):
    """
    Payload when a recipient acknowledges a call via DTMF.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    asterisk_chan: str = Field(..., min_length=1, description="Unique Asterisk channel or tracking identifier")
    digit: str = Field(default="1", min_length=1, max_length=4, description="DTMF digit pressed")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the acknowledgment")


class CallEvent(BaseModel):
    """
    Standardized telephony event published over WebSockets / Redis PubSub.
    """
    model_config = ConfigDict(extra="allow")

    event_type: str = Field(..., description="Event type: StasisStart, ChannelStateChange, DTMF, Hangup")
    channel_id: str = Field(..., description="Asterisk unique channel ID")
    channel_state: Optional[ChannelState] = Field(default=ChannelState.UNKNOWN)
    phone: Optional[str] = Field(default=None)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = Field(default_factory=dict)
