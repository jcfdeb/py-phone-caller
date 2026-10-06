"""
External integration clients for the asterisk_ws_monitor service.

Encapsulates network communication with Call Register, Generate Audio,
Asterisk Caller, and Redis Pub/Sub event broadcasting.
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Mapping

from aiohttp import ClientSession, ClientTimeout, client_exceptions, web

from py_phone_caller_utils.telemetry import inject_trace_context
from py_phone_caller_utils.config import settings


class CallRegisterClient:
    """
    Client for retrieving voice message information associated with an Asterisk channel.

    Attributes:
        base_url: Base URL of the caller register service.
        route: Relative route endpoint for fetching voice message metadata.
        timeout_total: Request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        route: str = "voice_message",
        timeout_total: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.route = route.lstrip("/")
        self.timeout_total = timeout_total

    @property
    def target_url(self) -> str:
        """Full endpoint URL for voice message query."""
        return f"{self.base_url}/{self.route}"

    async def query_voice_message(self, asterisk_chan: str) -> dict[str, Any]:
        """
        Queries call register for voice message content and checksum.

        Args:
            asterisk_chan: Identifier of the active Asterisk channel.

        Returns:
            Dictionary containing voice message metadata (e.g. message, msg_chk_sum).

        Raises:
            web.HTTPBadRequest: If connection to the Asterisk system/call register fails.
        """
        try:
            async with ClientSession(
                timeout=ClientTimeout(total=self.timeout_total)
            ) as session:
                resp = await session.post(
                    url=self.target_url,
                    params={"asterisk_chan": asterisk_chan},
                    headers=inject_trace_context(),
                    data=None,
                )
                text = await resp.text()
                return json.loads(text)
        except client_exceptions.ClientConnectorError as err:
            logging.exception(f"Unable to connect to the Asterisk system: '{err}'")
            raise web.HTTPBadRequest(
                reason=str(err), body=None, text=None, content_type=None
            ) from err


class AudioServiceClient:
    """
    Client for requesting speech synthesis and polling readiness status.

    Attributes:
        base_url: Base URL of the audio generation service.
        generate_route: Route for requesting TTS generation.
        ready_route: Route for polling audio readiness.
        timeout_total: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        generate_route: str = "make_audio",
        ready_route: str = "is_audio_ready",
        timeout_total: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.generate_route = generate_route.lstrip("/")
        self.ready_route = ready_route.lstrip("/")
        self.timeout_total = timeout_total

    @property
    def generate_url(self) -> str:
        """Full endpoint URL for initiating audio creation."""
        return f"{self.base_url}/{self.generate_route}"

    @property
    def ready_url(self) -> str:
        """Full endpoint URL for polling audio file readiness."""
        return f"{self.base_url}/{self.ready_route}"

    async def generate_and_wait(
        self,
        response_data: Mapping[str, Any],
        max_retries: int = 12,
        retry_delay: float = 5.0,
    ) -> dict[str, Any]:
        """
        Requests audio synthesis and polls until the wav file is generated.

        Args:
            response_data: Metadata with message, msg_chk_sum, lang, speed.
            max_retries: Maximum polling iterations before logging an error.
            retry_delay: Delay in seconds between polling attempts.

        Returns:
            Dictionary containing audio generation response JSON.

        Raises:
            web.HTTPBadRequest: If connection to audio generation service fails.
        """
        try:
            audio_params: dict[str, Any] = {
                "message": response_data.get("message"),
                "msg_chk_sum": response_data.get("msg_chk_sum"),
            }
            target_lang = response_data.get("lang") or response_data.get("language")
            if target_lang:
                audio_params["lang"] = target_lang
            if response_data.get("speed"):
                audio_params["speed"] = response_data.get("speed")

            async with ClientSession(
                timeout=ClientTimeout(total=self.timeout_total)
            ) as session:
                resp = await session.post(
                    url=self.generate_url,
                    headers=inject_trace_context(),
                    params=audio_params,
                )
                generate_resp_json = await resp.json()

                msg_chk_sum = response_data.get("msg_chk_sum")
                audio_ready = False
                retry_count = 0

                while not audio_ready and retry_count < max_retries:
                    try:
                        ready_params = {"msg_chk_sum": msg_chk_sum}
                        if target_lang:
                            ready_params["lang"] = target_lang
                        ready_resp = await session.get(
                            url=self.ready_url,
                            params=ready_params,
                        )
                        ready_json = await ready_resp.json()

                        if ready_json.get("exists", False):
                            audio_ready = True
                            logging.info(
                                f"Audio file for message checksum {msg_chk_sum} is ready"
                            )
                        else:
                            logging.info(
                                f"Audio file for message checksum {msg_chk_sum} is not ready yet. Retrying in {retry_delay} seconds..."
                            )
                            await asyncio.sleep(retry_delay)
                            retry_count += 1
                    except client_exceptions.ClientConnectorError as err:
                        logging.warning(
                            f"Error checking audio readiness: {err}. Retrying in {retry_delay} seconds..."
                        )
                        await asyncio.sleep(retry_delay)
                        retry_count += 1

                if not audio_ready:
                    logging.error(
                        f"Audio file for message checksum {msg_chk_sum} is not ready after maximum retries"
                    )

                return generate_resp_json

        except client_exceptions.ClientConnectorError as err:
            logging.exception(f"Unable to connect to the GenerateAudio Process: '{err}'")
            raise web.HTTPBadRequest(
                reason=str(err), body=None, text=None, content_type=None
            ) from err


class AsteriskPlaybackClient:
    """
    Client for triggering playback on an Asterisk channel via the Asterisk Caller service.

    Attributes:
        base_url: Base URL of the Asterisk caller service.
        play_route: Relative route endpoint for initiating playback.
        timeout_total: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        play_route: str = "play",
        timeout_total: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.play_route = play_route.lstrip("/")
        self.timeout_total = timeout_total

    @property
    def target_url(self) -> str:
        """Full endpoint URL for audio playback."""
        return f"{self.base_url}/{self.play_route}"

    async def play_audio_to_channel(
        self, asterisk_chan: str, response_data: Mapping[str, Any]
    ) -> str:
        """
        Dispatches a playback request to the Asterisk Caller service.

        Args:
            asterisk_chan: Target Asterisk channel identifier.
            response_data: Metadata containing msg_chk_sum, lang, etc.

        Returns:
            The raw text response from the playback service.
        """
        try:
            async with ClientSession(
                timeout=ClientTimeout(total=self.timeout_total)
            ) as session:
                play_params = {
                    "asterisk_chan": asterisk_chan,
                    "msg_chk_sum": response_data.get("msg_chk_sum"),
                }
                p_lang = response_data.get("lang") or response_data.get("language")
                if p_lang:
                    play_params["lang"] = p_lang

                resp = await session.post(
                    url=self.target_url,
                    headers=inject_trace_context(),
                    params=play_params,
                    data=None,
                )
                msg = await resp.text()
                logging.info(
                    f"Response for the playing audio '{response_data.get('msg_chk_sum')}.wav' "
                    f"on the Asterisk channel '{asterisk_chan}': '{msg}'"
                )
                return msg
        except client_exceptions.ClientConnectorError as err:
            logging.exception(f"Unable to connect to the Asterisk system: '{err}'")
            return ""


class EventBroadcaster:
    """
    Decoupled Redis Pub/Sub broadcaster for real-time telephony and Stasis events.
    """

    @staticmethod
    async def broadcast(
        event_type: str, asterisk_chan: str, response_json: Mapping[str, Any]
    ) -> None:
        """
        Publishes Stasis lifecycle events to Redis channels.

        Args:
            event_type: Name/type of the event.
            asterisk_chan: Channel identifier if applicable.
            response_json: Raw event payload dictionary.
        """
        try:
            import redis.asyncio as aioredis

            queue_url = settings.get("QUEUE", {}).get(
                "QUEUE_URL", "redis://redis.lan:6379/7"
            )
            r = aioredis.from_url(queue_url, socket_connect_timeout=0.5)
            payload = json.dumps(
                {
                    "event_type": event_type,
                    "asterisk_chan": asterisk_chan,
                    "timestamp": response_json.get("timestamp"),
                    "channel_state": (
                        response_json.get("channel", {}).get("state")
                        if isinstance(response_json.get("channel"), dict)
                        else None
                    ),
                }
            )
            await r.publish("telephony.stasis.events", payload)
            await r.publish("py_phone_caller:events:telephony", payload)
            if asterisk_chan:
                await r.publish(f"stasis:events:{asterisk_chan}", payload)
            await r.aclose()
        except Exception as redis_err:
            logging.debug(f"Event broadcast skipped (Redis unavailable): {redis_err}")
