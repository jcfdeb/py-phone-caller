"""
Alert domain models and schemas for Prometheus webhooks and dispatch alerts.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    EMERGENCY = "emergency"
    UNKNOWN = "unknown"


class PrometheusAlertItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str = Field(default="firing", description="Alert status (firing, resolved)")
    labels: Dict[str, Any] = Field(default_factory=dict, description="Prometheus labels")
    annotations: Dict[str, Any] = Field(default_factory=dict, description="Prometheus annotations")
    startsAt: Optional[str] = Field(default=None, description="Start timestamp")
    endsAt: Optional[str] = Field(default=None, description="End timestamp")
    generatorURL: Optional[str] = Field(default=None, description="Alertmanager URL")
    fingerprint: Optional[str] = Field(default=None, description="Alert fingerprint")

    @property
    def severity(self) -> AlertSeverity:
        raw_sev = str(self.labels.get("severity", "unknown")).lower()
        try:
            return AlertSeverity(raw_sev)
        except ValueError:
            return AlertSeverity.UNKNOWN

    @property
    def alert_name(self) -> str:
        return str(self.labels.get("alertname", "UnknownAlert"))

    @property
    def summary(self) -> str:
        return str(
            self.annotations.get("summary")
            or self.annotations.get("message")
            or self.annotations.get("description")
            or self.alert_name
        )


class PrometheusWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: Optional[str] = Field(default="4")
    groupKey: Optional[str] = Field(default=None)
    status: str = Field(default="firing")
    receiver: Optional[str] = Field(default=None)
    groupLabels: Dict[str, Any] = Field(default_factory=dict)
    commonLabels: Dict[str, Any] = Field(default_factory=dict)
    commonAnnotations: Dict[str, Any] = Field(default_factory=dict)
    alerts: List[PrometheusAlertItem] = Field(default_factory=list)


class CallAlertRequest(BaseModel):
    """
    Standardized payload for scheduling or dispatching a call alert.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(..., min_length=1, description="Message text to synthesize and announce")
    phone: Optional[str] = Field(default=None, description="Direct target phone number")
    group: Optional[str] = Field(default=None, description="Address book on-call group name")
    language: str = Field(default="en", description="Target TTS language code (en, es, it, de, etc.)")
    voice: Optional[str] = Field(default=None, description="Voice identifier or speaker ID")
    speed: float = Field(default=1.0, ge=0.5, le=2.5, description="Audio playback speed multiplier")
    priority: int = Field(default=5, ge=0, le=9, description="0=highest emergency (P0), 9=lowest")
    seconds_to_forget: int = Field(default=300, ge=30, description="Window in seconds before call expires")
    caller_id: Optional[str] = Field(default=None, description="Outbound CLI/Caller ID")
