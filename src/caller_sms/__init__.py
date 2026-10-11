"""
caller_sms package.

Modular architecture exposing schemas, carriers, services, routes, and entrypoints.
"""

from __future__ import annotations

from caller_sms.carriers import (
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
)
from caller_sms.caller_sms import init_app

__all__ = [
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
    "receive_inbound_sms",
    "send_the_sms",
    "setup_routes",
]
