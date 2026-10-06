"""
Caller SMS service.

Provides an aiohttp endpoint to send SMS messages using a configured carrier
backend (e.g., Twilio or on-premise gateway). Modular facade maintaining backward compatibility.
"""

from __future__ import annotations
import asyncio
import logging
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

from aiohttp import web
from py_phone_caller_utils.py_phone_caller_db.db_sms import insert_sms, select_sms
from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app
import caller_sms.backend.rust_on_premise as rust_on_premise
import caller_sms.backend.twilio as twilio_backend

from caller_sms.carriers import RustOnPremiseCarrier, TwilioCarrier
from caller_sms.constants import (
    CALLER_SMS_APP_ROUTE,
    CALLER_SMS_CARRIER,
    CALLER_SMS_ERROR,
    CALLER_SMS_PORT,
    LOG_FORMATTER,
    LOG_LEVEL,
    SMS_SAAS_FALLBACK,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_SMS_FROM,
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

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
init_telemetry("caller_sms")


async def _ensure_db_pool() -> None:
    """Ensures the database connection pool is established for caller_sms."""
    if DB.pool is None:
        await DB.start_connection_pool()
        logging.info("Connected to database for caller_sms")


def _get_active_dispatch_service() -> SmsDispatchService:
    """Builds an SmsDispatchService using module-level globals to respect test patches."""
    mod = (
        sys.modules.get("src.caller_sms.caller_sms")
        or sys.modules.get("caller_sms.caller_sms")
        or globals()
    )

    carrier = getattr(mod, "CALLER_SMS_CARRIER", CALLER_SMS_CARRIER)
    saas_fallback = bool(getattr(mod, "SMS_SAAS_FALLBACK", SMS_SAAS_FALLBACK))
    sid = getattr(mod, "TWILIO_ACCOUNT_SID", TWILIO_ACCOUNT_SID)
    token = getattr(mod, "TWILIO_AUTH_TOKEN", TWILIO_AUTH_TOKEN)
    twilio_from = getattr(mod, "TWILIO_SMS_FROM", TWILIO_SMS_FROM)
    has_creds = bool(sid and token and twilio_from)

    tb = getattr(mod, "twilio_backend", twilio_backend)
    rp = getattr(mod, "rust_on_premise", rust_on_premise)

    twilio_c = TwilioCarrier(sender_fn=getattr(tb, "sms_sender_async", None))
    rust_c = RustOnPremiseCarrier(sender_fn=getattr(rp, "sms_sender_async", None))
    inserter = getattr(mod, "insert_sms", insert_sms)

    return SmsDispatchService(
        default_carrier=carrier,
        saas_fallback=saas_fallback,
        twilio_carrier=twilio_c,
        on_premise_carrier=rust_c,
        insert_sms_fn=inserter,
        has_twilio_creds=has_creds,
    )


def _get_active_inbound_service() -> InboundSmsService:
    """Builds an InboundSmsService using module-level globals."""
    mod = (
        sys.modules.get("src.caller_sms.caller_sms")
        or sys.modules.get("caller_sms.caller_sms")
        or globals()
    )
    inserter = getattr(mod, "insert_sms", insert_sms)
    return InboundSmsService(insert_sms_fn=inserter)


def _get_active_query_service() -> SmsQueryService:
    """Builds an SmsQueryService using module-level globals."""
    mod = (
        sys.modules.get("src.caller_sms.caller_sms")
        or sys.modules.get("caller_sms.caller_sms")
        or globals()
    )
    selector = getattr(mod, "select_sms", select_sms)
    return SmsQueryService(select_sms_fn=selector)


async def init_app() -> web.Application:
    """
    Initializes and configures the aiohttp web application for sending SMS messages.

    Returns:
        web.Application: The configured application instance.
    """
    mod = (
        sys.modules.get("src.caller_sms.caller_sms")
        or sys.modules.get("caller_sms.caller_sms")
        or globals()
    )
    ensure_db_fn = getattr(mod, "_ensure_db_pool", _ensure_db_pool)
    try:
        await ensure_db_fn()
    except Exception as db_err:
        logging.error(
            f"Database initial pool setup failed: {db_err}. Service starting degraded; /ready will indicate 503."
        )

    app = web.Application()
    instrument_aiohttp_app(app, "caller_sms")

    app["sms_dispatch_service_factory"] = _get_active_dispatch_service
    app["inbound_sms_service_factory"] = _get_active_inbound_service
    app["sms_query_service_factory"] = _get_active_query_service

    carrier = getattr(mod, "CALLER_SMS_CARRIER", CALLER_SMS_CARRIER)
    if carrier == "on_premise":
        rp = getattr(mod, "rust_on_premise", rust_on_premise)
        if hasattr(rp, "init_backend"):
            await rp.init_backend()

    async def cleanup_db(_app: web.Application) -> None:
        if DB.pool is not None:
            await DB.pool.close()
            logging.info("Database connection pool closed for caller_sms")

    app.on_cleanup.append(cleanup_db)
    setup_routes(app)
    return app


if __name__ == "__main__":
    web.run_app(init_app(), port=int(CALLER_SMS_PORT))
