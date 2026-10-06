"""
Core business logic and service orchestration for asterisk_ws_monitor.

Coordinates the reception of Asterisk WebSocket events, database storage,
querying of call metadata, speech synthesis triggering, and audio playback.
"""

from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Mapping

import websockets

from asterisk_ws_monitor.clients import (
    AsteriskPlaybackClient,
    AudioServiceClient,
    CallRegisterClient,
    EventBroadcaster,
)
from asterisk_ws_monitor.schemas import StasisEvent


class WsMonitorService:
    """
    Service coordinating Asterisk WebSocket event monitoring and dialplan actions.

    Attributes:
        call_register_client: Client for querying voice message data.
        audio_service_client: Client for generating TTS audio files.
        playback_client: Client for requesting playback on Asterisk channels.
        broadcaster: Broadcaster for Redis Pub/Sub event streaming.
        insert_ws_event_fn: Database persistence callable for incoming events.
        target_event_type: The triggering event type (default: 'StasisStart').
        target_channel_state: The required channel state (default: 'Up').
    """

    def __init__(
        self,
        call_register_client: CallRegisterClient,
        audio_service_client: AudioServiceClient,
        playback_client: AsteriskPlaybackClient,
        broadcaster: EventBroadcaster,
        insert_ws_event_fn: Callable[[str, str, str], Awaitable[Any]],
        target_event_type: str = "StasisStart",
        target_channel_state: str = "Up",
    ) -> None:
        self.call_register_client = call_register_client
        self.audio_service_client = audio_service_client
        self.playback_client = playback_client
        self.broadcaster = broadcaster
        self.insert_ws_event_fn = insert_ws_event_fn
        self.target_event_type = target_event_type
        self.target_channel_state = target_channel_state

    @staticmethod
    def extract_channel_id(response_json: Mapping[str, Any]) -> str:
        """
        Extracts channel ID from Asterisk event payload.

        Args:
            response_json: Raw event JSON dictionary.

        Returns:
            The channel identifier string, or empty string if not found.
        """
        event = StasisEvent.from_dict(response_json)
        return event.channel_id

    async def take_control_of_dialplan(
        self,
        event_type: str,
        response_json: Mapping[str, Any],
        asterisk_chan: str,
    ) -> None:
        """
        Evaluates dialplan conditions and executes the playback pipeline.

        Uses guard clauses to exit immediately if event criteria are not met.

        Args:
            event_type: Event type string.
            response_json: Full event payload mapping.
            asterisk_chan: Target channel identifier.
        """
        channel_data = response_json.get("channel")
        channel_state = (
            channel_data.get("state") if isinstance(channel_data, dict) else ""
        )

        # Early return guard clause
        if (
            event_type != self.target_event_type
            or channel_state != self.target_channel_state
        ):
            return

        # Step 1: Query call register for message payload and checksum
        response_data = await self.call_register_client.query_voice_message(
            asterisk_chan
        )

        # Step 2: Request audio generation and wait until wave file is ready
        generate_audio_resp = await self.audio_service_client.generate_and_wait(
            response_data
        )

        # Step 3: Trigger playback if audio generation succeeded
        if generate_audio_resp.get("status") == 200:
            await self.playback_client.play_audio_to_channel(
                asterisk_chan, response_data
            )

    async def process_event_message(self, raw_message: str | bytes) -> None:
        """
        Parses and dispatches a single WebSocket event message.

        Args:
            raw_message: Raw text or bytes received from the WebSocket.
        """
        response_json = json.loads(raw_message)
        asterisk_chan = self.extract_channel_id(response_json)
        event_type = response_json.get("type", "")

        # Persist event to database
        try:
            await self.insert_ws_event_fn(
                asterisk_chan, event_type, json.dumps(response_json)
            )
        except Exception as err:
            logging.exception(f"Problem with the PostgreSQL connection: '{err}'")

        # Execute dialplan actions
        try:
            await self.take_control_of_dialplan(
                event_type, response_json, asterisk_chan
            )
        except Exception as dialplan_err:
            logging.exception(
                f"Error during dialplan control execution: '{dialplan_err}'"
            )

        # Non-blocking async broadcast
        asyncio.create_task(
            self.broadcaster.broadcast(event_type, asterisk_chan, response_json)
        )

    async def run_client(
        self,
        ws_url: str,
        host: str,
        web_port: int,
        user: str,
        stasis_app: str,
    ) -> None:
        """
        Maintains an active WebSocket connection to Asterisk ARI with auto-reconnect.

        Args:
            ws_url: WebSocket URL to connect to.
            host: Asterisk hostname.
            web_port: Asterisk web port.
            user: Authenticated username.
            stasis_app: Monitored Stasis application name.
        """
        while True:
            try:
                async with websockets.connect(ws_url) as websocket:
                    logging.info(
                        f"WebSocket connection to the Asterisk PBX at '{host}:{web_port}'. "
                        f"Authenticated as '{user}' and using the '{stasis_app}' Stasis App"
                    )

                    while True:
                        response = await websocket.recv()
                        await self.process_event_message(response)

            except websockets.exceptions.ConnectionClosedError as err:
                logging.exception(f"Connection to the Asterisk PBX lost!: '{err}'")
                logging.info("Retrying connection in 5 seconds...")
                await asyncio.sleep(5)
            except ConnectionRefusedError as err:
                logging.exception(
                    f"Unable to establish a connection with the Asterisk PBX: '{err}'"
                )
                logging.info("Retrying connection in 5 seconds...")
                await asyncio.sleep(5)
            except Exception as err:
                logging.exception(f"Unexpected error in WebSocket client: '{err}'")
                logging.info("Retrying connection in 5 seconds...")
                await asyncio.sleep(5)
