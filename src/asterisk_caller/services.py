"""
Core business logic and service orchestration for asterisk_caller.

Provides the AsteriskCallerService and background queue manager, eliminating
cyclomatic complexity with early exits, phone normalization, and typed payloads.
"""

import asyncio
import logging
import sys
import time
from typing import Any
from aiohttp import ClientResponse, ClientSession, ClientTimeout, client_exceptions, web
from aiobreaker import CircuitBreaker, CircuitBreakerError

from asterisk_caller.ari_client import (
    AriClient,
    build_asterisk_query_string,
    send_ari_continue,
)
from asterisk_caller.constants import (
    ASTERISK_ARI_CHANNELS,
    ASTERISK_ARI_PLAY,
    ASTERISK_CALLER_ID,
    ASTERISK_CHAN_TYPE,
    ASTERISK_CONTEXT,
    ASTERISK_EXTENSION,
    ASTERISK_URL,
    CALL_QUEUE,
    CALL_REGISTER_APP_ROUTE_REGISTER_CALL,
    CALL_REGISTER_URL,
    CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT,
    CALLER_ADDRESS_BOOK_URL,
    CLIENT_TIMEOUT_TOTAL,
    GENERATE_AUDIO_URL,
    SERVING_AUDIO_FOLDER,
    WAIT_FOR_CALL_CYCLE,
)
from asterisk_caller.exceptions import (
    AriConnectionError,
    CircuitBreakerOpenError,
    OnCallPhoneUnavailable,
)
from asterisk_caller.schemas import (
    PlaceCallPayload,
    PlayAudioPayload,
    QueueCallPayload,
)


def format_phone(phone: str) -> str:
    """Formats phone number to meet Asterisk PBX standards by replacing '+' with '00'.

    Args:
        phone: Raw phone number string.

    Returns:
        str: Normalized phone number starting with '00' or unchanged digits.
    """
    if isinstance(phone, str) and phone.startswith("+"):
        return "00" + phone[1:]
    return phone


async def resolve_oncall_phone(
    phone: str,
    address_book_url: str | None = None,
    route: str | None = None,
    timeout_total: float = CLIENT_TIMEOUT_TOTAL,
) -> str:
    """Resolves 'oncall' phone alias to the active on-call staff number if needed.

    Args:
        phone: Phone number or 'oncall' alias.
        address_book_url: Base URL of the caller_address_book service.
        route: API endpoint route for on-call contact query.
        timeout_total: HTTP request timeout in seconds.

    Returns:
        str: Resolved and normalized phone number.

    Raises:
        OnCallPhoneUnavailable: If no contact is available or phone is missing.
        RuntimeError: If the address book service responds with invalid data.
    """
    if not (isinstance(phone, str) and phone.lower() == "oncall"):
        return format_phone(phone)

    mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
    base_url = (
        address_book_url
        or (getattr(mod, "CALLER_ADDRESS_BOOK_URL", None) if mod else None)
        or CALLER_ADDRESS_BOOK_URL
    )
    ep_route = (
        route
        or (getattr(mod, "CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT", None) if mod else None)
        or CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT
    )

    url = f"{base_url}/{ep_route}"

    session_cls = getattr(mod, "ClientSession", ClientSession) if mod else ClientSession

    try:
        async with session_cls(timeout=ClientTimeout(total=timeout_total)) as session:
            async with session.get(url) as resp:
                text = await resp.text()
                data = None
                try:
                    data = await resp.json()
                except Exception:
                    data = None
    except client_exceptions.ClientConnectorError as err:
        raise OnCallPhoneUnavailable(f"Cannot connect to caller_address_book at {url}: {err}") from err

    if resp.status == 404:
        if data and isinstance(data, dict):
            raise OnCallPhoneUnavailable("No on-call contact is available in the address book.")
        raise OnCallPhoneUnavailable(f"No on-call contact found: {text[:200]}")

    if data is None:
        raise RuntimeError(
            f"Address book returned non-JSON body (status {resp.status}): {text[:200]}"
        )

    if resp.status != 200 or not isinstance(data, dict):
        raise RuntimeError(f"Address book returned status {resp.status}")

    resolved = data.get("phone_number")
    if not resolved:
        raise OnCallPhoneUnavailable(
            "The address book returned an on-call contact without a phone number. "
            "Update the contact before using phone='oncall'."
        )

    return format_phone(resolved)


class AsteriskCallerService:
    """High-level service orchestrating outbound dialing, call registration, and playback."""

    def __init__(
        self,
        ari_client: AriClient,
        asterisk_url: str = ASTERISK_URL,
        chan_type: str = ASTERISK_CHAN_TYPE,
        extension: str = ASTERISK_EXTENSION,
        context: str = ASTERISK_CONTEXT,
        caller_id: str = ASTERISK_CALLER_ID,
        call_register_url: str = CALL_REGISTER_URL,
        call_register_route: str = CALL_REGISTER_APP_ROUTE_REGISTER_CALL,
        audio_service_url: str = GENERATE_AUDIO_URL,
        audio_folder: str = SERVING_AUDIO_FOLDER,
        timeout_total: float = CLIENT_TIMEOUT_TOTAL,
    ) -> None:
        self.ari_client = ari_client
        self.asterisk_url = asterisk_url
        self.chan_type = chan_type
        self.extension = extension
        self.context = context
        self.caller_id = caller_id
        self.call_register_url = call_register_url
        self.call_register_route = call_register_route
        self.audio_service_url = audio_service_url
        self.audio_folder = audio_folder
        self.timeout_total = timeout_total

    @property
    def current_asterisk_url(self) -> str:
        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        return getattr(mod, "ASTERISK_URL", self.asterisk_url) if mod else self.asterisk_url

    @property
    def current_chan_type(self) -> str:
        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        return getattr(mod, "ASTERISK_CHAN_TYPE", self.chan_type) if mod else self.chan_type

    @property
    def current_call_register_url(self) -> str:
        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        return getattr(mod, "CALL_REGISTER_URL", self.call_register_url) if mod else self.call_register_url

    @property
    def current_call_register_route(self) -> str:
        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        return getattr(mod, "CALL_REGISTER_APP_ROUTE_REGISTER_CALL", self.call_register_route) if mod else self.call_register_route

    async def initiate_asterisk_call(
        self,
        asterisk_call_init: str,
        phone: str,
        resolved_phone: str,
        message: str,
        headers: dict[str, str],
        backup_callee: str = "false",
        lang: str | None = None,
    ) -> ClientResponse:
        """Originates an ARI call and immediately records it with the call_register service.

        Args:
            asterisk_call_init: Full ARI channels URL with query parameters.
            phone: Original requested phone or alias.
            resolved_phone: Resolved real phone number.
            message: Alert message text.
            headers: Authorization headers.
            backup_callee: Backup callee flag.
            lang: Optional target voice language code.

        Returns:
            ClientResponse: Response from Asterisk ARI.

        Raises:
            web.HTTPServiceUnavailable: If circuit breaker is open.
            web.HTTPBadRequest: If PBX or call register connection fails.
        """
        oncall = "true" if phone.lower() == "oncall" else "false"

        try:
            call_resp = await self.ari_client.originate_channel(asterisk_call_init, headers)
        except CircuitBreakerOpenError as err:
            raise web.HTTPServiceUnavailable(
                reason="Asterisk ARI Circuit Breaker OPEN (PBX outage)",
                text='{"status\": 503, "error\": "Asterisk PBX circuit breaker open"}',
            ) from err
        except AriConnectionError as err:
            raise web.HTTPBadRequest(reason=str(err)) from err

        if call_resp.status != 200:
            logging.error(
                f"Asterisk server '{self.current_asterisk_url}' response: {call_resp.status}. Unable to initialize call."
            )
            return call_resp

        try:
            response_data = await call_resp.json()
            asterisk_chan = response_data["id"]

            # Dynamic import of ClientSession so unittest.mock.patch("src.asterisk_caller.asterisk_caller.ClientSession") works
            mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
            session_cls = getattr(mod, "ClientSession", ClientSession) if mod else ClientSession

            reg_params = {
                "phone": resolved_phone,
                "message": message,
                "asterisk_chan": asterisk_chan,
                "oncall": oncall,
                "backup_callee": backup_callee,
            }
            if lang:
                reg_params["lang"] = lang
                reg_params["language"] = lang

            async with session_cls(
                timeout=ClientTimeout(total=self.timeout_total)
            ) as reg_session:
                await reg_session.post(
                    url=f"{self.current_call_register_url}/{self.current_call_register_route}",
                    params=reg_params,
                    data=None,
                    headers=headers,
                )
            return call_resp

        except client_exceptions.ClientConnectorError as err:
            logging.exception(
                f"Unable to connect to 'call_register' service: '{err}'"
            )
            raise web.HTTPBadRequest(reason=str(err)) from err

    async def start_call(self, payload: PlaceCallPayload) -> ClientResponse:
        """Resolves recipient, builds ARI query, and executes call placement.

        Args:
            payload: Validated call request details.

        Returns:
            ClientResponse: The HTTP response from Asterisk.
        """
        resolved_phone = await resolve_oncall_phone(payload.phone)
        query_string = build_asterisk_query_string(
            self.current_chan_type,
            resolved_phone,
            self.extension,
            self.context,
            self.caller_id,
        )
        call_init_url = f"{self.current_asterisk_url}/{ASTERISK_ARI_CHANNELS}?{query_string}"
        headers = self.ari_client.get_auth_headers()

        return await self.initiate_asterisk_call(
            call_init_url,
            payload.phone,
            resolved_phone,
            payload.message,
            headers,
            payload.backup_callee,
            lang=payload.lang,
        )

    def enqueue_call(self, payload: QueueCallPayload, queue: Any = None) -> None:
        """Puts a call item onto the multiprocessing queue for worker execution.

        Args:
            payload: Queue item with phone, message, and optional lang.
            queue: The worker queue.
        """
        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        target_queue = queue or (getattr(mod, "CALL_QUEUE", None) if mod else None) or CALL_QUEUE
        data = {"phone": payload.phone, "message": payload.message}
        if payload.lang:
            data["lang"] = payload.lang
        target_queue.put_nowait(data)

    async def play_audio_to_channel(self, payload: PlayAudioPayload) -> int:
        """Plays an audio file to an active Asterisk channel and executes ARI continue.

        Args:
            payload: Audio playback parameters (channel, checksum, language).

        Returns:
            int: HTTP status code from the Asterisk play request.

        Raises:
            web.HTTPBadRequest: If Asterisk is unreachable.
        """
        audio_file = (
            f"{payload.msg_chk_sum}_{payload.lang}.wav"
            if payload.lang
            else f"{payload.msg_chk_sum}.wav"
        )
        audio_url = f"{self.audio_service_url}/{self.audio_folder}"
        play_url = (
            f"{self.current_asterisk_url}/{ASTERISK_ARI_CHANNELS}/{payload.asterisk_chan}/"
            f"{ASTERISK_ARI_PLAY}:{audio_url}/{audio_file}"
        )
        headers = self.ari_client.get_auth_headers()

        mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
        session_cls = getattr(mod, "ClientSession", ClientSession) if mod else ClientSession

        try:
            async with session_cls(
                timeout=ClientTimeout(total=self.timeout_total)
            ) as session:
                play_resp = await session.post(url=play_url, data=None, headers=headers)
                if play_resp.status == 201:
                    logging.info(
                        f"Asterisk server response: 201. Playing audio '{audio_file}' to channel '{payload.asterisk_chan}'"
                    )
                else:
                    logging.error(
                        f"Asterisk server response: {play_resp.status}. Unable to play audio '{audio_file}'"
                    )
        except client_exceptions.ClientConnectorError as err:
            logging.exception(f"Unable to connect to Asterisk system: '{err}'")
            raise web.HTTPBadRequest(reason=str(err)) from err

        continue_url = f"{self.current_asterisk_url}/{ASTERISK_ARI_CHANNELS}/{payload.asterisk_chan}/continue"
        send_continue_fn = getattr(mod, "send_ari_continue", send_ari_continue) if mod else send_ari_continue
        await send_continue_fn(headers, payload.asterisk_chan, continue_url)
        return play_resp.status


def manage_call_queue(
    queue: Any = None,
    call_start_fn: Any | None = None,
    wait_cycle: float = WAIT_FOR_CALL_CYCLE,
) -> None:
    """Continuously processes items from the call queue in a dedicated thread.

    Args:
        queue: The queue instance to read from.
        call_start_fn: Async callable taking (phone, message). If None, resolves from asterisk_caller.
        wait_cycle: Sleep interval between queue processing cycles in seconds.
    """
    mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
    target_queue = queue or (getattr(mod, "CALL_QUEUE", None) if mod else None) or CALL_QUEUE

    while True:
        try:
            call_payload = target_queue.get()
        except Exception as err:
            logging.exception(f"Call queue worker failed reading queue: '{err}'")
            break

        if call_payload is None:
            logging.info("Call queue worker received shutdown sentinel. Exiting.")
            break

        phone = call_payload.get("phone")
        message = call_payload.get("message")
        lang = call_payload.get("lang")

        async def _call() -> None:
            if call_start_fn is not None:
                try:
                    await call_start_fn(phone, message, lang=lang)
                except TypeError:
                    await call_start_fn(phone, message)
            else:
                caller_mod = sys.modules.get("src.asterisk_caller.asterisk_caller") or sys.modules.get("asterisk_caller.asterisk_caller")
                if caller_mod and hasattr(caller_mod, "asterisk_call_start"):
                    try:
                        await caller_mod.asterisk_call_start(phone, message, lang=lang)
                    except TypeError:
                        await caller_mod.asterisk_call_start(phone, message)

        try:
            asyncio.run(_call())
        except OnCallPhoneUnavailable as err:
            logging.warning(
                f"Call queue item skipped because the on-call phone is unavailable: "
                f"phone='{phone}', message='{message}', reason='{err}'"
            )
        except CircuitBreakerError as err:
            logging.warning(f"Call queue item skipped because Asterisk ARI circuit breaker is open: {err}")
        except Exception as err:
            logging.exception(
                f"Unable to process call queue payload: phone='{phone}', message='{message}', error='{err}'"
            )

        time.sleep(wait_cycle)
