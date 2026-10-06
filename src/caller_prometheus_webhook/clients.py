"""
HTTP clients for outgoing notification dispatch to Asterisk Caller and Caller SMS services.

Encapsulates network communication, connection pooling, and trace context propagation.
"""

from __future__ import annotations
import logging
from typing import Final
from aiohttp import ClientSession, ClientTimeout

from py_phone_caller_utils.telemetry import inject_trace_context

DEFAULT_CLIENT_TIMEOUT: Final[float] = 30.0


class AsteriskCallClient:
    """
    Client for triggering phone call dispatches through the Asterisk Caller REST API.

    Attributes:
        base_url: Base URL of the Asterisk caller service.
        route: Endpoint route to place a call.
        timeout_total: Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        route: str = "place_call",
        timeout_total: float = DEFAULT_CLIENT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.route = route.lstrip("/")
        self.timeout_total = timeout_total

    @property
    def target_url(self) -> str:
        """Full URL for the call placement endpoint."""
        return f"{self.base_url}/{self.route}"

    async def place_call(self, phone: str, message: str) -> bool:
        """
        Sends an HTTP POST to place an outbound phone call.

        Args:
            phone: Target phone number.
            message: Voice prompt message.

        Returns:
            True if the call was accepted, False otherwise.
        """
        formatted_phone = phone.replace("+", "00") if isinstance(phone, str) else str(phone)
        try:
            async with ClientSession(
                timeout=ClientTimeout(total=self.timeout_total)
            ) as session:
                async with session.post(
                    url=self.target_url,
                    params={"phone": formatted_phone, "message": message},
                    data=None,
                    headers=inject_trace_context(),
                ) as resp:
                    return resp.status < 400
        except Exception as err:
            logging.error(f"Error calling Asterisk call service at {self.target_url}: {err}")
            return False


class CallerSmsClient:
    """
    Client for triggering SMS text alerts through the Caller SMS REST API.

    Attributes:
        base_url: Base URL of the Caller SMS service.
        route: Endpoint route to deliver SMS.
        timeout_total: Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        route: str = "send_sms",
        timeout_total: float = DEFAULT_CLIENT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.route = route.lstrip("/")
        self.timeout_total = timeout_total

    @property
    def target_url(self) -> str:
        """Full URL for the SMS delivery endpoint."""
        return f"{self.base_url}/{self.route}"

    async def send_sms(self, phone: str, message: str) -> bool:
        """
        Sends an HTTP POST to dispatch an SMS message.

        Args:
            phone: Target phone number.
            message: Text message content.

        Returns:
            True if SMS was accepted, False otherwise.
        """
        try:
            async with ClientSession(
                timeout=ClientTimeout(total=self.timeout_total)
            ) as session:
                async with session.post(
                    url=self.target_url,
                    params={"phone": phone, "message": message},
                    data=None,
                    headers=inject_trace_context(),
                ) as resp:
                    return resp.status < 400
        except Exception as err:
            logging.error(f"Error calling Caller SMS service at {self.target_url}: {err}")
            return False
