"""
Carrier backend dispatchers and protocols for caller_sms.
"""

from __future__ import annotations
import asyncio
from typing import Any, Awaitable, Callable, Protocol

import caller_sms.backend.rust_on_premise as rust_on_premise
import caller_sms.backend.twilio as twilio_backend
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
