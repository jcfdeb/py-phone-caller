"""
Asterisk ARI (Asterisk REST Interface) HTTP client adapter.

Encapsulates low-level communication with the Asterisk PBX REST endpoints,
authentication header formatting, query string generation, and circuit breaker
fail-fast protection.
"""

from base64 import b64encode
import logging
from aiohttp import ClientResponse, ClientSession, ClientTimeout, client_exceptions, web
from aiobreaker import CircuitBreaker, CircuitBreakerError

from asterisk_caller.constants import CLIENT_TIMEOUT_TOTAL
from asterisk_caller.exceptions import AriConnectionError, CircuitBreakerOpenError


def gen_headers_sync(auth_string: str) -> dict[str, str]:
    """Generates HTTP Basic Authorization headers synchronously."""
    encoded = str(b64encode(bytearray(auth_string, "utf8")), "utf-8")
    return {"Authorization": f"Basic {encoded}"}


async def gen_headers(auth_string: str) -> dict[str, str]:
    """Generates HTTP Basic Authorization headers for the Asterisk ARI API.

    Args:
        auth_string: Credentials in 'username:password' format.

    Returns:
        dict[str, str]: Authorization header dictionary.
    """
    return gen_headers_sync(auth_string)


def build_asterisk_query_string(
    chan_type: str,
    phone: str,
    extension: str,
    context: str,
    caller_id: str,
) -> str:
    """Constructs the query string for initiating a call via the Asterisk ARI API.

    Args:
        chan_type: Configured channel type (e.g. 'PJSIP/trunk' or template with '{phone}').
        phone: Destination phone number (already normalized with leading '00').
        extension: Destination PBX extension.
        context: PBX dialplan context.
        caller_id: Caller ID string.

    Returns:
        str: Encoded URL query string for the ARI channels endpoint.
    """
    if "{phone}" in chan_type:
        endpoint = chan_type.replace("{phone}", phone)
        return f"endpoint={endpoint}&extension={extension}&context={context}&callerId={caller_id}"

    if chan_type.startswith("PJSIP") and "/" in chan_type:
        tech, trunk = chan_type.split("/", 1)
        return f"endpoint={tech}/{phone}@{trunk}&extension={extension}&context={context}&callerId={caller_id}"

    return f"endpoint={chan_type}/{phone}&extension={extension}&context={context}&callerId={caller_id}"


async def raw_post_ari_call(
    asterisk_call_init: str,
    headers: dict[str, str],
    timeout_total: float = CLIENT_TIMEOUT_TOTAL,
) -> ClientResponse:
    """Executes raw HTTP POST to initiate an ARI channel.

    Args:
        asterisk_call_init: Full ARI channel endpoint URL with query parameters.
        headers: Authorization headers.
        timeout_total: HTTP timeout in seconds.

    Returns:
        ClientResponse: The HTTP response.

    Raises:
        ClientResponseError: If server responds with 5xx status code.
    """
    async with ClientSession(timeout=ClientTimeout(total=timeout_total)) as session:
        resp = await session.post(url=asterisk_call_init, data=None, headers=headers)
        if resp.status >= 500:
            raise client_exceptions.ClientResponseError(
                request_info=resp.request_info,
                history=resp.history,
                status=resp.status,
                message=f"Asterisk ARI server error: {resp.status}",
            )
        return resp


async def send_ari_continue(
    headers: dict[str, str],
    asterisk_chan: str,
    asterisk_continue_addr: str,
    timeout_total: float = CLIENT_TIMEOUT_TOTAL,
) -> int | None:
    """Sends a 'continue' command to Asterisk ARI to restore PBX dialplan control.

    Args:
        headers: HTTP headers with authentication.
        asterisk_chan: Target Asterisk channel ID.
        asterisk_continue_addr: ARI continue URL.
        timeout_total: HTTP timeout in seconds.

    Returns:
        int | None: 204 status code if successful, or None on failure.

    Raises:
        web.HTTPBadRequest: If network connector fails.
    """
    try:
        async with ClientSession(timeout=ClientTimeout(total=timeout_total)) as session:
            resp = await session.post(
                url=asterisk_continue_addr, data=None, headers=headers
            )
            if resp.status == 204:
                logging.info(f"Restoring call control to PBX on channel '{asterisk_chan}'")
                return resp.status

            logging.error(
                f"Unable to restore call control to PBX on channel '{asterisk_chan}' (status {resp.status})"
            )
            return None

    except client_exceptions.ClientConnectorError as err:
        logging.exception(f"Unable to connect to Asterisk system: '{err}'")
        raise web.HTTPBadRequest(reason=str(err)) from err


class AriClient:
    """High-level client for Asterisk REST Interface operations."""

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        circuit_breaker: CircuitBreaker,
        timeout_total: float = CLIENT_TIMEOUT_TOTAL,
    ) -> None:
        self.base_url = base_url
        self.user = user
        self.password = password
        self.circuit_breaker = circuit_breaker
        self.timeout_total = timeout_total

    def get_auth_headers(self) -> dict[str, str]:
        """Returns Basic Auth headers for the configured user credentials."""
        return gen_headers_sync(f"{self.user}:{self.password}")

    async def originate_channel(
        self, asterisk_call_init: str, headers: dict[str, str]
    ) -> ClientResponse:
        """Originates a new Asterisk channel wrapped by the circuit breaker.

        Args:
            asterisk_call_init: Full ARI endpoint URL with query parameters.
            headers: HTTP authorization headers.

        Returns:
            ClientResponse: Raw aiohttp client response.

        Raises:
            CircuitBreakerOpenError: If the circuit breaker is open.
            AriConnectionError: If network connection to Asterisk fails.
        """
        try:
            return await self.circuit_breaker.call_async(
                raw_post_ari_call, asterisk_call_init, headers
            )
        except CircuitBreakerError as err:
            logging.error(f"Asterisk ARI circuit breaker is OPEN: {err}")
            raise CircuitBreakerOpenError("Asterisk ARI Circuit Breaker OPEN (PBX outage)") from err
        except client_exceptions.ClientConnectorError as err:
            logging.exception(f"Connection failure to Asterisk system: {err}")
            raise AriConnectionError(f"Unable to connect to Asterisk system: {err}") from err
