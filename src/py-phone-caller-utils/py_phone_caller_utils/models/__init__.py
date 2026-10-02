"""
Shared domain models for py-phone-caller.

Provides strongly typed schemas with Pydantic v2 validation for alerts,
calls, SMS, contacts, and telemetry events across all microservices.
"""

from py_phone_caller_utils.models.alert import (
    AlertSeverity,
    PrometheusAlertItem,
    PrometheusWebhookPayload,
    CallAlertRequest,
)
from py_phone_caller_utils.models.telephony import (
    ChannelState,
    CallEvent,
    DtmfAckPayload,
    CallDispatchSpec,
)
from py_phone_caller_utils.models.sms import (
    SmsStatus,
    SmsCarrier,
    SmsPayload,
    SmsRecordModel,
)
from py_phone_caller_utils.models.contact import (
    ContactModel,
    ContactCreatePayload,
    ContactUpdatePayload,
)

__all__ = [
    "AlertSeverity",
    "PrometheusAlertItem",
    "PrometheusWebhookPayload",
    "CallAlertRequest",
    "ChannelState",
    "CallEvent",
    "DtmfAckPayload",
    "CallDispatchSpec",
    "SmsStatus",
    "SmsCarrier",
    "SmsPayload",
    "SmsRecordModel",
    "ContactModel",
    "ContactCreatePayload",
    "ContactUpdatePayload",
]
