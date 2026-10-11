"""
HTTP client for communicating with the Asterisk Caller service.

Handles outbound HTTP requests to the Asterisk Caller endpoint to trigger
primary and backup recall sequences.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Final

from aiohttp import ClientSession, ClientTimeout, client_exceptions

from asterisk_recaller.exceptions import RecallerConnectionError

DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0


class AsteriskCallClient:
    """
    Client for triggering outbound call retries via Asterisk Caller REST API.

    Attributes:
        base_url: Base HTTP endpoint for the Asterisk caller service.
        place_call_route: App route for placing calls.
        timeout_total: Maximum allowed timeout in seconds for client requests.
    """

    def __init__(
        self,
        base_url: str,
        place_call_route: str = "place_call",
        timeout_total: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        """
        Initializes the AsteriskCallClient.

        Args:
            base_url: Base URL of the Asterisk caller service.
            place_call_route: Relative route endpoint for initiating a call.
            timeout_total: Request timeout in seconds.
        """
        self.base_url = base_url
        self.place_call_route = place_call_route
        self.timeout_total = timeout_total

    @property
    def target_url(self) -> str:
        """Constructs the fully qualified call placement URL."""
        return f"{self.base_url.rstrip('/')}/{self.place_call_route.lstrip('/')}"

    async def place_call(
        self,
        phone: str,
        message: str,
        backup_callee: str = "false",
    ) -> bool:
        """
        Dispatches a POST request to place an outbound recall.

        Args:
            phone: Target telephone number.
            message: Voice prompt message content.
            backup_callee: Flag indicating whether this is a backup escalation ("true"|"false").

        Returns:
            True if the call request was successfully accepted, False otherwise.

        Raises:
            RecallerConnectionError: If network connectivity or server communication fails
                when non-suppressed.
        """
        timeout = ClientTimeout(total=self.timeout_total)
        url = self.target_url
        params = {
            "phone": phone,
            "message": message,
            "backup_callee": backup_callee,
        }

        try:
            async with ClientSession(timeout=timeout) as session:
                async with session.post(url=url, params=params, data=None) as response:
                    _ = await response.text()
                    return response.status < 400
        except client_exceptions.ClientConnectorError as err:
            logging.exception(
                f"Unable to connect to the Asterisk Call service: '{err}'"
            )
            return False
        except (client_exceptions.ClientError, asyncio.TimeoutError) as err:
            logging.error(f"Error communicating with Asterisk Caller at {url}: {err}")
            return False
