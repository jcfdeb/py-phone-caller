"""
caller_sms package.

Modular architecture exposing schemas, carriers, services, routes, and entrypoints.
"""

from __future__ import annotations

from caller_sms.carriers import (
    AsteriskSipMessageCarrier,
    CarrierSenderProtocol,
    RustOnPremiseCarrier,
    TwilioCarrier,
)
from caller_sms.exceptions import (
    CallerSmsError,
    InboundSmsParseError,
    MissingSmsParameterError,
    SmsDeliveryError,
    UnsupportedCarrierError,
)
from caller_sms.routes import (
    get_sms_records,
    receive_inbound_sms,
    send_the_sms,
    setup_routes,
)
from caller_sms.schemas import (
    InboundSmsRequest,
    InboundSmsResult,
    SendSmsRequest,
    SendSmsResult,
    SmsCarrier,
    SmsQueryFilter,
    SmsStatus,
)
from caller_sms.services import (
    InboundSmsService,
    SmsDispatchService,
    SmsQueryService,
    is_sip_extension,
    resolve_oncall_sms_targets,
)
from caller_sms.caller_sms import init_app

__all__ = [
    "AsteriskSipMessageCarrier",
    "CallerSmsError",
    "CarrierSenderProtocol",
    "InboundSmsParseError",
    "InboundSmsRequest",
    "InboundSmsResult",
    "InboundSmsService",
    "MissingSmsParameterError",
    "RustOnPremiseCarrier",
    "SendSmsRequest",
    "SendSmsResult",
    "SmsCarrier",
    "SmsDeliveryError",
    "SmsDispatchService",
    "SmsQueryFilter",
    "SmsQueryService",
    "SmsStatus",
    "TwilioCarrier",
    "UnsupportedCarrierError",
    "get_sms_records",
    "init_app",
    "is_sip_extension",
    "receive_inbound_sms",
    "resolve_oncall_sms_targets",
    "send_the_sms",
    "setup_routes",
]
