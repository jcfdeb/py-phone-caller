"""
Core business logic and services for the caller_sms service.
"""

from __future__ import annotations
import logging
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Sequence

from py_phone_caller_utils.py_phone_caller_db.db_sms import insert_sms, select_sms
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import Calls
from py_phone_caller_utils.redis_lock import call_mutex

from caller_sms.carriers import RustOnPremiseCarrier, TwilioCarrier
from caller_sms.constants import (
    CALLER_SMS_CARRIER,
    SMS_SAAS_FALLBACK,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_SMS_FROM,
)
from caller_sms.exceptions import SmsDeliveryError, UnsupportedCarrierError
from caller_sms.schemas import (
    InboundSmsRequest,
    InboundSmsResult,
    SendSmsRequest,
    SendSmsResult,
    SmsCarrier,
    SmsQueryFilter,
    SmsStatus,
)


class SmsDispatchService:
    """
    Orchestration service for outbound SMS notifications.

    Dispatches messages to the configured carrier (Twilio or On-Premise) and executes
    SaaS fallback when sovereign on-premise hardware fails.
    """

    def __init__(
        self,
        default_carrier: str = CALLER_SMS_CARRIER,
        saas_fallback: bool = SMS_SAAS_FALLBACK,
        twilio_carrier: TwilioCarrier | None = None,
        on_premise_carrier: RustOnPremiseCarrier | None = None,
        insert_sms_fn: Callable[..., Awaitable[Any]] | None = None,
        has_twilio_creds: bool | None = None,
    ) -> None:
        """
        Initializes the SmsDispatchService.

        Args:
            default_carrier: Default carrier name.
            saas_fallback: Whether SaaS fallback to Twilio is enabled.
            twilio_carrier: Twilio carrier dispatch wrapper.
            on_premise_carrier: On-premise GSM modem dispatch wrapper.
            insert_sms_fn: Database insertion callback.
            has_twilio_creds: Override for Twilio credential availability.
        """
        self.default_carrier = default_carrier
        self.saas_fallback = saas_fallback
        self.twilio_carrier = twilio_carrier or TwilioCarrier()
        self.on_premise_carrier = on_premise_carrier or RustOnPremiseCarrier()
        self.insert_sms_fn = insert_sms_fn or insert_sms
        self._has_twilio_creds = (
            has_twilio_creds
            if has_twilio_creds is not None
            else bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_SMS_FROM)
        )

    async def _publish_event_safe(
        self, phone: str, carrier: str, status: str, error_msg: str
    ) -> None:
        """Safely publishes sms_dispatched event without crashing the request."""
        try:
            from py_phone_caller_utils.event_bus import publish_event
            await publish_event(
                "sms_dispatched",
                {
                    "phone": phone,
                    "carrier": carrier,
                    "status": status,
                    "error": error_msg,
                },
            )
        except Exception:
            pass

    async def _record_sms_safe(
        self, phone: str, message: str, carrier: str, status: str, error_msg: str
    ) -> None:
        """Safely writes SMS dispatch attempt to the Piccolo database."""
        try:
            await self.insert_sms_fn(
                phone=phone,
                message=message,
                carrier=carrier,
                status=status,
                error=error_msg,
            )
        except Exception as db_err:
            logging.error(f"Error recording SMS in database: {db_err}")

    async def send_sms(
        self, request: SendSmsRequest, carrier_override: str | None = None
    ) -> SendSmsResult:
        """
        Dispatches an SMS through the appropriate carrier backend.

        Args:
            request: Validated SendSmsRequest.
            carrier_override: Optional carrier override.

        Returns:
            SendSmsResult containing status code and error details.
        """
        carrier = carrier_override or self.default_carrier
        phone = request.phone
        message = request.message

        if carrier == SmsCarrier.TWILIO.value:
            try:
                await self.twilio_carrier.send(phone, message)
                status_code = 200
                status = SmsStatus.SENT.value
                error_msg = ""
            except (SmsDeliveryError, Exception) as err:
                status_code = 500
                status = SmsStatus.FAILED.value
                error_msg = str(err)
                logging.exception(f"Unable to send SMS via Twilio: '{err}'")

        elif carrier == SmsCarrier.ON_PREMISE.value:
            try:
                await self.on_premise_carrier.send(phone, message)
                status_code = 200
                status = SmsStatus.SENT.value
                error_msg = ""
            except (SmsDeliveryError, Exception) as on_prem_err:
                logging.warning(f"On-premise GSM modem failed to send SMS: {on_prem_err}")

                if self.saas_fallback and self._has_twilio_creds:
                    logging.info("sms_saas_fallback is enabled. Attempting SaaS fallback via Twilio...")
                    try:
                        await self.twilio_carrier.send(phone, message)
                        carrier = SmsCarrier.TWILIO_FALLBACK.value
                        status_code = 200
                        status = SmsStatus.SENT.value
                        error_msg = ""
                    except (SmsDeliveryError, Exception) as fallback_err:
                        status_code = 500
                        status = SmsStatus.FAILED.value
                        error_msg = f"On-premise error: {on_prem_err}; Twilio fallback error: {fallback_err}"
                        logging.exception(error_msg)
                else:
                    if self.saas_fallback and not self._has_twilio_creds:
                        logging.warning(
                            "sms_saas_fallback enabled but Twilio credentials missing. Staying sovereign/failing fast."
                        )
                    else:
                        logging.info("sms_saas_fallback is disabled (sovereign mode). Failing fast without SaaS fallback.")
                    status_code = 500
                    status = SmsStatus.FAILED.value
                    error_msg = str(on_prem_err)

        else:
            error_msg = f"Carrier '{carrier}' not supported."
            logging.error(error_msg)
            await self._record_sms_safe(
                phone=phone,
                message=message,
                carrier=carrier,
                status=SmsStatus.FAILED.value,
                error_msg=error_msg,
            )
            return SendSmsResult(
                status_code=500,
                status=SmsStatus.FAILED.value,
                carrier=carrier,
                error_msg=error_msg,
            )

        await self._record_sms_safe(
            phone=phone,
            message=message,
            carrier=carrier,
            status=status,
            error_msg=error_msg,
        )
        await self._publish_event_safe(phone, carrier, status, error_msg)

        return SendSmsResult(
            status_code=status_code,
            status=status,
            carrier=carrier,
            error_msg=error_msg,
        )


class InboundSmsService:
    """Service to process incoming SMS messages and match acknowledgment tokens to active calls."""

    ACK_TOKENS: frozenset[str] = frozenset({"ACK", "OK", "1", "CONFIRM", "YES"})

    def __init__(self, insert_sms_fn: Callable[..., Awaitable[Any]] | None = None) -> None:
        self.insert_sms_fn = insert_sms_fn or insert_sms

    async def handle_inbound(self, request: InboundSmsRequest) -> InboundSmsResult:
        """
        Evaluates inbound message body for acknowledgment tokens and updates active unacknowledged calls.

        Args:
            request: Validated InboundSmsRequest.

        Returns:
            InboundSmsResult indicating acknowledgment match.
        """
        sender_phone = request.sender_phone
        body_text = request.body_text
        is_ack = any(token in body_text.split() or body_text == token for token in self.ACK_TOKENS)

        matched_calls = 0
        now_utc = datetime.now(UTC).replace(tzinfo=None)

        if is_ack:
            clean_phone = sender_phone.replace("+", "00")
            phone_patterns = [sender_phone, clean_phone]
            if clean_phone.startswith("00"):
                phone_patterns.append("+" + clean_phone[2:])

            active_calls = await Calls.select().where(
                Calls.phone.is_in(phone_patterns) & (Calls.cycle_done == False)
            ).run()

            for c in active_calls:
                call_id = str(c.get("id"))
                chan = c.get("asterisk_chan")
                async with call_mutex(call_id):
                    await Calls.update({
                        Calls.acknowledge_at: now_utc,
                        Calls.cycle_done: True,
                    }).where(Calls.id == c.get("id")).run()
                    matched_calls += 1
                    logging.info(
                        f"Inbound SMS ACK from {sender_phone} matched call {call_id} (chan: {chan}). Marked acknowledged."
                    )

        inbound_status = (
            SmsStatus.RECEIVED_ACK.value
            if is_ack and matched_calls > 0
            else SmsStatus.RECEIVED.value
        )
        try:
            await self.insert_sms_fn(
                phone=sender_phone,
                message=request.raw_body,
                carrier=SmsCarrier.INBOUND.value,
                status=inbound_status,
                error="",
            )
        except Exception as db_err:
            logging.error(f"Error storing inbound SMS: {db_err}")

        return InboundSmsResult(
            status=200,
            acknowledged=is_ack and matched_calls > 0,
            matched_calls=matched_calls,
        )


class SmsQueryService:
    """Service to query and format SMS database history."""

    def __init__(self, select_sms_fn: Callable[..., Awaitable[Sequence[Any]]] | None = None) -> None:
        self.select_sms_fn = select_sms_fn or select_sms

    async def get_records(self, query_filter: SmsQueryFilter) -> list[dict[str, Any]]:
        """
        Retrieves and formats SMS records matching the specified filter.

        Args:
            query_filter: SmsQueryFilter containing limit, phone, and status criteria.

        Returns:
            List of serialized SMS log dictionaries.
        """
        records = await self.select_sms_fn(
            limit=query_filter.limit,
            phone=query_filter.phone,
            status=query_filter.status,
        )
        formatted: list[dict[str, Any]] = []
        for r in records:
            if isinstance(r, dict):
                item = dict(r)
                if "id" in item:
                    item["id"] = str(item["id"])
                if "created_at" in item and item["created_at"]:
                    item["created_at"] = str(item["created_at"])
                formatted.append(item)
            else:
                formatted.append(r)
        return formatted
