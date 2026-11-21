"""
Carrier backend dispatchers and protocols for caller_sms.
"""

from __future__ import annotations
import asyncio
from base64 import b64encode
import logging
import re
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout

import caller_sms.backend.rust_on_premise as rust_on_premise
import caller_sms.backend.twilio as twilio_backend
from caller_sms.constants import (
    ASTERISK_CALLER_ID,
    ASTERISK_CHAN_TYPE,
    ASTERISK_PASS,
    ASTERISK_URL,
    ASTERISK_USER,
)
from caller_sms.exceptions import SmsDeliveryError


class CarrierSenderProtocol(Protocol):
    """Protocol for SMS carrier senders."""

    async def send(self, phone: str, message: str) -> None:
        """Sends an SMS message to the destination phone number."""
        ...


class TwilioCarrier:
    """Dispatches SMS via Twilio API."""

    def __init__(
        self,
        sender_fn: Callable[[str, str], Awaitable[Any]] | None = None,
    ) -> None:
        self._sender_fn = sender_fn or twilio_backend.sms_sender_async

    async def send(self, phone: str, message: str) -> None:
        """
        Sends an SMS message via Twilio.

        Args:
            phone: Destination phone number.
            message: Text message content.

        Raises:
            SmsDeliveryError: If dispatching fails.
        """
        try:
            future = await self._sender_fn(message, phone)
            if future is not None:
                await asyncio.ensure_future(future)
        except Exception as err:
            raise SmsDeliveryError(str(err)) from err


class RustOnPremiseCarrier:
    """Dispatches SMS via on-premise GSM modem engine."""

    def __init__(
        self,
        sender_fn: Callable[[str, str], Awaitable[Any]] | None = None,
    ) -> None:
        self._sender_fn = sender_fn or rust_on_premise.sms_sender_async

    async def send(self, phone: str, message: str) -> None:
        """
        Sends an SMS message via on-premise GSM modem.

        Args:
            phone: Destination phone number.
            message: Text message content.

        Raises:
            SmsDeliveryError: If dispatching fails.
        """
        try:
            future = await self._sender_fn(message, phone)
            if future is not None:
                await asyncio.ensure_future(future)
        except Exception as err:
            raise SmsDeliveryError(str(err)) from err


class AsteriskSipMessageCarrier:
    """Dispatches air-gapped RFC 3428 SIP MESSAGE text alerts via Asterisk ARI."""

    def __init__(
        self,
        asterisk_url: str = ASTERISK_URL,
        asterisk_user: str = ASTERISK_USER,
        asterisk_pass: str = ASTERISK_PASS,
        chan_type: str = ASTERISK_CHAN_TYPE,
        caller_id: str = ASTERISK_CALLER_ID,
        timeout_total: float = 10.0,
        sender_fn: Callable[[str, str], Awaitable[Any]] | None = None,
    ) -> None:
        self.asterisk_url = asterisk_url.rstrip("/")
        self.asterisk_user = asterisk_user
        self.asterisk_pass = asterisk_pass
        self.chan_type = chan_type
        self.caller_id = caller_id
        self.timeout_total = timeout_total
        self._sender_fn = sender_fn

    def _resolve_tech_and_resource(self, target: str) -> tuple[str, str]:
        """Normalizes a SIP extension or URI into an Asterisk ARI (tech, resource) pair."""
        cleaned = target.strip()
        default_tech = (self.chan_type.split("/", 1)[0] or "PJSIP").strip().upper()
        if ":" in cleaned:
            prefix, rest = cleaned.split(":", 1)
            prefix_lower = prefix.lower()
            if prefix_lower in ("pjsip", "sip"):
                tech = "PJSIP" if prefix_lower == "pjsip" else default_tech
                resource = rest.split("@", 1)[0].strip()
                return tech, resource
        return default_tech, cleaned

    def _build_from_uri(self) -> str:
        """Builds a valid SIP From identity accepted by Asterisk PJSIP messaging."""
        safe_user = re.sub(r"[^A-Za-z0-9._-]", "-", (self.caller_id or "py-phone-caller").strip())
        safe_user = safe_user.strip("-") or "py-phone-caller"
        return f"sip:{safe_user}@py-phone-caller"

    async def send(self, phone: str, message: str) -> None:
        """
        Sends a SIP MESSAGE to a registered Asterisk SIP/PJSIP endpoint via ARI.

        Args:
            phone: Local SIP extension (e.g. '1000') or SIP URI ('pjsip:1000').
            message: Plain-text alert body.

        Raises:
            SmsDeliveryError: If Asterisk ARI rejects or cannot deliver the SIP MESSAGE.
        """
        if self._sender_fn is not None:
            try:
                future = await self._sender_fn(message, phone)
                if future is not None:
                    await asyncio.ensure_future(future)
                return
            except Exception as err:
                raise SmsDeliveryError(str(err)) from err

        tech, resource = self._resolve_tech_and_resource(phone)
        if not resource:
            raise SmsDeliveryError(f"Invalid SIP MESSAGE target: '{phone}'")

        url = (
            f"{self.asterisk_url}/ari/endpoints/"
            f"{quote(tech, safe='')}/{quote(resource, safe='')}/sendMessage"
        )
        auth_bytes = f"{self.asterisk_user}:{self.asterisk_pass}".encode("utf-8")
        headers = {
            "Authorization": f"Basic {b64encode(auth_bytes).decode('ascii')}",
        }
        params = {
            "from": self._build_from_uri(),
            "body": message,
        }

        try:
            async with ClientSession(
                timeout=ClientTimeout(total=self.timeout_total)
            ) as session:
                async with session.put(url, params=params, headers=headers) as resp:
                    if resp.status in (200, 202, 204):
                        logging.info(
                            f"SIP MESSAGE sent via Asterisk ARI to {tech}/{resource} (HTTP {resp.status})"
                        )
                        return
                    detail = (await resp.text()).strip()
                    raise SmsDeliveryError(
                        f"Asterisk ARI SIP MESSAGE failed for {tech}/{resource}: "
                        f"HTTP {resp.status}" + (f" ({detail})" if detail else "")
                    )
        except SmsDeliveryError:
            raise
        except Exception as err:
            raise SmsDeliveryError(
                f"Asterisk ARI SIP MESSAGE connection error for {tech}/{resource}: {err}"
            ) from err
