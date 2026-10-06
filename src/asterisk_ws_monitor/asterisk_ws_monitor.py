"""
Asterisk WebSocket Monitor service orchestrator and entry point.

Connects to the Asterisk ARI WebSocket, listens to telephony lifecycle events,
triggers audio generation and manages active channel playback.
Provides backward-compatible facades delegating to modular schemas, clients,
and services.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import signal
import sys
from typing import Any

import websockets

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

from aiohttp import web_exceptions
from py_phone_caller_utils.py_phone_caller_db.db_asterisk_ws_monitor import (
    insert_ws_event,
)
from py_phone_caller_utils.telemetry import init_telemetry

from asterisk_ws_monitor.constants import (
    ASTERISK_CALL_APP_ROUTE_PLAY,
    ASTERISK_CALL_URL,
    ASTERISK_HOST,
    ASTERISK_PASS,
    ASTERISK_STASIS_APP,
    ASTERISK_USER,
    ASTERISK_WEB_PORT,
    CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE,
    CALL_REGISTER_URL,
    CHANNEL_STATE,
    CLIENT_TIMEOUT_TOTAL,
    EVENT_TYPE,
    GENERATE_AUDIO_APP_ROUTE,
    GENERATE_AUDIO_URL,
    IS_AUDIO_READY_ENDPOINT,
    LOG_FORMATTER,
    LOG_LEVEL,
    WS_URL,
)
from asterisk_ws_monitor.clients import (
    AsteriskPlaybackClient,
    AudioServiceClient,
    CallRegisterClient,
    EventBroadcaster,
)
from asterisk_ws_monitor.exceptions import (
    AsteriskWsMonitorError,
    AudioGenerationError,
    AudioNotReadyError,
    CallRegisterQueryError,
    PlaybackError,
    WsConnectionError,
)
from asterisk_ws_monitor.schemas import (
    AudioGenerationResult,
    AudioReadyStatus,
    StasisEvent,
    VoiceMessageInfo,
)
from asterisk_ws_monitor.services import WsMonitorService

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
init_telemetry("asterisk_ws_monitor")


async def broadcast_stasis_event(
    event_type: str, asterisk_chan: str, response_json: dict[str, Any]
) -> None:
    """
    Decoupled Redis Pub/Sub event broadcaster.

    Publishes real-time telephony and Stasis lifecycle events for external consumers
    without blocking active call playback.

    Args:
        event_type: Type of Stasis event.
        asterisk_chan: Target Asterisk channel identifier.
        response_json: Raw event payload dictionary.
    """
    await EventBroadcaster.broadcast(event_type, asterisk_chan, response_json)


async def get_asterisk_chan(response_json: dict[str, Any]) -> str:
    """
    Extracts the Asterisk channel identifier from a WebSocket event response.

    Args:
        response_json: The JSON response from the Asterisk WebSocket event.

    Returns:
        The identifier of the Asterisk channel.
    """
    return WsMonitorService.extract_channel_id(response_json)


async def querying_call_register(asterisk_chan: str) -> dict[str, Any]:
    """
    Queries the call register service for voice message details of an Asterisk channel.

    Args:
        asterisk_chan: The identifier of the Asterisk channel.

    Returns:
        The JSON response from the call register service.

    Raises:
        web_exceptions.HTTPBadRequest: If connection to Asterisk system fails.
    """
    client = CallRegisterClient(
        base_url=globals().get("CALL_REGISTER_URL", CALL_REGISTER_URL),
        route=globals().get(
            "CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE",
            CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE,
        ),
        timeout_total=globals().get("CLIENT_TIMEOUT_TOTAL", CLIENT_TIMEOUT_TOTAL),
    )
    return await client.query_voice_message(asterisk_chan)


async def generate_the_audio_file(response_data: dict[str, Any]) -> dict[str, Any]:
    """
    Generates an audio file for a given message and waits until ready.

    Args:
        response_data: Data containing the message, msg_chk_sum, language, speed.

    Returns:
        The JSON response from the audio generation endpoint.

    Raises:
        web_exceptions.HTTPBadRequest: If connection to audio generation fails.
    """
    client = AudioServiceClient(
        base_url=globals().get("GENERATE_AUDIO_URL", GENERATE_AUDIO_URL),
        generate_route=globals().get(
            "GENERATE_AUDIO_APP_ROUTE", GENERATE_AUDIO_APP_ROUTE
        ),
        ready_route=globals().get(
            "IS_AUDIO_READY_ENDPOINT", IS_AUDIO_READY_ENDPOINT
        ),
        timeout_total=globals().get("CLIENT_TIMEOUT_TOTAL", CLIENT_TIMEOUT_TOTAL),
    )
    return await client.generate_and_wait(response_data)


async def audio_play_status_log(
    response_data: dict[str, Any],
    asterisk_chan: str,
    audio_play_resp_message: str,
) -> None:
    """
    Logs the status of audio playback on a specified Asterisk channel.

    Args:
        response_data: Data containing the message checksum.
        asterisk_chan: Identifier of the Asterisk channel.
        audio_play_resp_message: Response string from the audio playback service.
    """
    logging.info(
        f"Response for the playing audio '{response_data.get('msg_chk_sum')}.wav' "
        f"on the Asterisk channel '{asterisk_chan}': '{audio_play_resp_message}'"
    )


async def play_audio_to_channel(
    asterisk_chan: str, response_data: dict[str, Any]
) -> None:
    """
    Plays an audio message to a specified Asterisk channel.

    Args:
        asterisk_chan: The identifier of the Asterisk channel.
        response_data: The data containing the message checksum and language.
    """
    client = AsteriskPlaybackClient(
        base_url=globals().get("ASTERISK_CALL_URL", ASTERISK_CALL_URL),
        play_route=globals().get(
            "ASTERISK_CALL_APP_ROUTE_PLAY", ASTERISK_CALL_APP_ROUTE_PLAY
        ),
        timeout_total=globals().get("CLIENT_TIMEOUT_TOTAL", CLIENT_TIMEOUT_TOTAL),
    )
    await client.play_audio_to_channel(asterisk_chan, response_data)


async def audio_operations(
    generate_audio_resp_json: dict[str, Any],
    asterisk_chan: str,
    response_data: dict[str, Any],
) -> None:
    """
    Handles playing the audio message to the channel if generation succeeded.

    Args:
        generate_audio_resp_json: Response JSON from the audio generation process.
        asterisk_chan: Identifier of the Asterisk channel.
        response_data: Data containing the message checksum.
    """
    if generate_audio_resp_json.get("status") == 200:
        play_fn = globals().get("play_audio_to_channel", play_audio_to_channel)
        await play_fn(asterisk_chan, response_data)


async def take_control_of_dialplan(
    event_type: str, response_json: dict[str, Any], asterisk_chan: str
) -> None:
    """
    Orchestrates the dialplan control flow for an incoming Asterisk event.

    Uses guard clauses to ensure event matching, then triggers query,
    generation, and playback sequence.

    Args:
        event_type: Type of Asterisk event received.
        response_json: Raw event payload JSON.
        asterisk_chan: Identifier of the Asterisk channel.
    """
    target_event = globals().get("EVENT_TYPE", EVENT_TYPE)
    target_state = globals().get("CHANNEL_STATE", CHANNEL_STATE)

    channel_info = response_json.get("channel")
    channel_state = (
        channel_info.get("state") if isinstance(channel_info, dict) else ""
    )

    # Early return guard clause
    if event_type != target_event or channel_state != target_state:
        return

    query_fn = globals().get("querying_call_register", querying_call_register)
    gen_fn = globals().get("generate_the_audio_file", generate_the_audio_file)
    ops_fn = globals().get("audio_operations", audio_operations)

    response_data = await query_fn(asterisk_chan)
    generate_audio_resp_json = await gen_fn(response_data)
    await ops_fn(generate_audio_resp_json, asterisk_chan, response_data)


async def ws_connection_log(
    asterisk_host: str,
    asterisk_web_port: int,
    asterisk_user: str,
    asterisk_stasis_app: str,
) -> None:
    """
    Logs details of the WebSocket connection to the Asterisk PBX.

    Args:
        asterisk_host: Hostname or IP of the Asterisk PBX.
        asterisk_web_port: Port number for ARI WebSocket.
        asterisk_user: Authenticated user.
        asterisk_stasis_app: Name of the Stasis application.
    """
    logging.info(
        f"WebSocket connection to the Asterisk PBX at '{asterisk_host}:{asterisk_web_port}'. "
        f"Authenticated as '{asterisk_user}' and using the '{asterisk_stasis_app}' Stasis App"
    )


async def asterisk_ws_client() -> None:
    """
    Establishes and manages the persistent WebSocket connection to Asterisk PBX.
    """
    while True:
        try:
            ws_url = globals().get("WS_URL", WS_URL)
            async with websockets.connect(ws_url) as websocket:
                await ws_connection_log(
                    globals().get("ASTERISK_HOST", ASTERISK_HOST),
                    globals().get("ASTERISK_WEB_PORT", ASTERISK_WEB_PORT),
                    globals().get("ASTERISK_USER", ASTERISK_USER),
                    globals().get("ASTERISK_STASIS_APP", ASTERISK_STASIS_APP),
                )

                while True:
                    response = await websocket.recv()
                    response_json = json.loads(response)
                    get_chan_fn = globals().get("get_asterisk_chan", get_asterisk_chan)
                    asterisk_chan = await get_chan_fn(response_json)
                    event_type = response_json.get("type", "")

                    try:
                        await insert_ws_event(
                            asterisk_chan, event_type, json.dumps(response_json)
                        )
                    except Exception as err:
                        logging.exception(
                            f"Problem with the PostgreSQL connection: '{err}'"
                        )

                    try:
                        dialplan_fn = globals().get(
                            "take_control_of_dialplan", take_control_of_dialplan
                        )
                        await dialplan_fn(event_type, response_json, asterisk_chan)
                    except Exception as dialplan_err:
                        logging.exception(
                            f"Error during dialplan control execution: '{dialplan_err}'"
                        )

                    broadcast_fn = globals().get(
                        "broadcast_stasis_event", broadcast_stasis_event
                    )
                    asyncio.create_task(
                        broadcast_fn(event_type, asterisk_chan, response_json)
                    )

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


def receive_signal(signal_number: int, frame: Any) -> None:
    """
    Handles received system signals and exits the program gracefully.

    Args:
        signal_number: Received POSIX signal number.
        frame: Current execution frame.
    """
    print("Exiting On Signal:", signal_number)
    match signal_number:
        case 2:
            sys.exit(0)
        case 15:
            sys.exit(0)


async def main() -> None:
    """
    Main entry point managing the asynchronous task lifecycle.
    """
    task = asyncio.create_task(asterisk_ws_client())

    try:
        await task
    except asyncio.CancelledError:
        logging.info("The task was cancelled.")

    if not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            logging.info("The task was cancelled.")


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGTERM, receive_signal)
        signal.signal(signal.SIGINT, receive_signal)
        asyncio.run(main())
    except OSError as err:
        logging.exception(f"Error when starting the event loop... {err}")
        sys.exit(1)
    except web_exceptions.HTTPClientError as err:
        logging.exception(f"Can't generate the audio file... {err}")
        sys.exit(1)
    except KeyboardInterrupt as err:
        logging.info(f"Process terminated due Interrupt. {err}")
        sys.exit(0)
