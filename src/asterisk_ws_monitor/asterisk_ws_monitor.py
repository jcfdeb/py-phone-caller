import asyncio
import json
import logging
import signal

import py_phone_caller_utils.caller_configuration as conf
import websockets
from aiohttp import ClientSession, client_exceptions, web, web_exceptions
from py_phone_caller_utils.py_phone_caller_db.db_asterisk_ws_monitor import \
    insert_ws_event

logging.basicConfig(format=conf.get_log_formatter())

EVENT_TYPE = "StasisStart"
CHANNEL_STATE = "Up"
IS_AUDIO_READY_ENDPOINT = conf.get_is_audio_ready_endpoint()


async def get_asterisk_chan(response_json):
    """
    Extracts the Asterisk channel identifier from a WebSocket event response.

    This asynchronous function returns the channel ID for standard events or extracts it from the playback target URI for playback events.

    Args:
        response_json (dict): The JSON response from the Asterisk WebSocket event.

    Returns:
        str: The identifier of the Asterisk channel.
    """
    if response_json["type"] in ["PlaybackStarted", "PlaybackFinished"]:
        return str(response_json.get("playback", {}).get("target_uri")).split(":")[1]
    else:
        return response_json.get("channel", {}).get("id")


async def querying_call_register(asterisk_chan):
    """
    Queries the call register service for information about a specific Asterisk channel.

    This asynchronous function sends a POST request to the call register endpoint and returns the response as a JSON object.

    Args:
        asterisk_chan (str): The identifier of the Asterisk channel.

    Returns:
        dict: The JSON response from the call register service.

    Raises:
        web.HTTPClientError: If there is a connection error with the Asterisk system.
    """
    call_register_session = ClientSession()
    try:
        call_register_resp = await call_register_session.post(
            url=conf.get_call_register_url()
            + f"/{conf.get_call_register_app_route_voice_message()}"
            + f"?asterisk_chan={asterisk_chan}",
            data=None,
        )
        return json.loads(await call_register_resp.text())
    except client_exceptions.ClientConnectorError as err:
        logging.exception(f"Unable to connect to the Asterisk system: '{err}'")
        raise web.HTTPClientError(
            reason=str(err), body=None, text=None, content_type=None
        ) from err
    finally:
        await call_register_session.close()


async def generate_the_audio_file(response_data):
    """
    Generates an audio file for a given message and waits until the file is ready.

    This asynchronous function sends a request to generate an audio file based on the provided response data,
    then polls the server to check if the audio file is ready, retrying for up to one minute.

    Args:
        response_data (dict): The data containing the message and its checksum.

    Returns:
        dict: The JSON response from the audio generation endpoint.

    Raises:
        web.HTTPClientError: If there is a connection error with the audio generation process.
    """
    try:
        generate_audio_session = ClientSession()

        generate_audio_resp = await generate_audio_session.post(
            url=conf.get_generate_audio_url()
            + f"/{conf.get_generate_audio_app_route()}"
            + f"?message={response_data.get('message')}"
            + f"&msg_chk_sum={response_data.get('msg_chk_sum')}"
        )
        generate_audio_resp_json = await generate_audio_resp.json()

        msg_chk_sum = response_data.get("msg_chk_sum")
        audio_ready = False
        max_retries = 12
        retry_count = 0

        while not audio_ready and retry_count < max_retries:
            try:
                audio_ready_resp = await generate_audio_session.get(
                    url=conf.get_generate_audio_url()
                    + f"/{IS_AUDIO_READY_ENDPOINT}"
                    + f"?msg_chk_sum={msg_chk_sum}"
                )
                audio_ready_json = await audio_ready_resp.json()

                if audio_ready_json.get("exists", False):
                    audio_ready = True
                    logging.info(
                        f"Audio file for message checksum {msg_chk_sum} is ready"
                    )
                else:
                    logging.info(
                        f"Audio file for message checksum {msg_chk_sum} is not ready yet. Retrying in 5 seconds..."
                    )
                    await asyncio.sleep(5)
                    retry_count += 1
            except client_exceptions.ClientConnectorError as err:
                logging.warning(
                    f"Error checking audio readiness: {err}. Retrying in 5 seconds..."
                )
                await asyncio.sleep(5)
                retry_count += 1

        if not audio_ready:
            logging.error(
                f"Audio file for message checksum {msg_chk_sum} is not ready after maximum retries"
            )

        return generate_audio_resp_json
    except client_exceptions.ClientConnectorError as err:
        logging.exception(f"Unable to connect to the GenerateAudio Process: '{err}'")
        # Send the 'continue' here to the websocket to _hangup_ the call
        raise web.HTTPClientError(
            reason=str(err), body=None, text=None, content_type=None
        ) from err
    finally:
        await generate_audio_session.close()


async def audio_play_status_log(response_data, asterisk_chan, audio_play_resp_message):
    """
    Logs the status of audio playback on a specified Asterisk channel.

    This function records the response message for the audio file played on the given channel.

    Args:
        response_data (dict): The data containing the message checksum.
        asterisk_chan (str): The identifier of the Asterisk channel.
        audio_play_resp_message (str): The response message from the audio playback request.

    Returns:
        None
    """
    logging.info(
        f"Response for the playing audio '{response_data.get('msg_chk_sum')}.wav' "
        + "on the Asterisk channel "
        + f"'{asterisk_chan}': '{audio_play_resp_message}'"
    )


async def play_audio_to_channel(asterisk_chan, response_data):
    """
    Plays an audio message to a specified Asterisk channel.

    This asynchronous function sends a request to the Asterisk system to play an audio file
    associated with the provided channel and message checksum, and logs the playback status.

    Args:
        asterisk_chan (str): The identifier of the Asterisk channel.
        response_data (dict): The data containing the message checksum.

    Returns:
        None
    """
    asterisk_call_session = ClientSession()
    try:
        audio_play_resp = await asterisk_call_session.post(
            url=conf.get_asterisk_call_url()
            + f"/{conf.get_asterisk_call_app_route_play()}"
            + f"?asterisk_chan={asterisk_chan}"
            + f"&msg_chk_sum={response_data.get('msg_chk_sum')}",
            data=None,
        )
        audio_play_resp_message = await audio_play_resp.text()

        await audio_play_status_log(
            response_data, asterisk_chan, audio_play_resp_message
        )

    except client_exceptions.ClientConnectorError as err:
        logging.exception(f"Unable to connect to the Asterisk system: '{err}'")
    finally:
        await asterisk_call_session.close()


async def audio_operations(generate_audio_resp_json, asterisk_chan, response_data):
    """
    Handles the process of playing an audio message to a callee through the Stasis application.

    If the audio generation response indicates success, this function initiates playback of the audio file to the specified channel.

    Args:
        generate_audio_resp_json (dict): The response JSON from the audio generation process.
        asterisk_chan (str): The identifier of the Asterisk channel.
        response_data (dict): The data containing the message checksum.

    Returns:
        None
    """
    # Try to play the audio message to the callee through the Stasis application...
    if generate_audio_resp_json["status"] == 200:
        # Try to play the audio file to the channel
        await play_audio_to_channel(asterisk_chan, response_data)


async def take_control_of_dialplan(event_type, response_json, asterisk_chan):
    """
    Orchestrates the dialplan control flow for an incoming Asterisk event.

    This function checks if the event type and channel state match the expected values,
    retrieves the message data, generates the audio file, and initiates audio playback operations.

    Args:
        event_type (str): The type of the Asterisk event.
        response_json (dict): The JSON response from the Asterisk event.
        asterisk_chan (str): The identifier of the Asterisk channel.

    Returns:
        None
    """
    if (
        event_type == EVENT_TYPE
        and response_json.get("channel", {}).get("state") == CHANNEL_STATE
    ):
        # Get the message text and the ID
        response_data = await querying_call_register(asterisk_chan)

        generate_audio_resp_json = await generate_the_audio_file(response_data)

        await audio_operations(generate_audio_resp_json, asterisk_chan, response_data)


async def ws_connection_log(
    asterisk_host, asterisk_web_port, asterisk_user, asterisk_stasis_app
):
    """
    Logs the details of the WebSocket connection to the Asterisk PBX.

    This function records the host, port, user, and Stasis application used for the connection.

    Args:
        asterisk_host (str): The hostname of the Asterisk PBX.
        asterisk_web_port (str): The web port used for the connection.
        asterisk_user (str): The username used for authentication.
        asterisk_stasis_app (str): The name of the Stasis application.

    Returns:
        None
    """
    logging.info(
        "WebSocket connection to the Asterisk PBX at "
        + f"'{asterisk_host}:{asterisk_web_port}'. "
        + f"Authenticated as '{asterisk_user}' "
        + f"and using the '{asterisk_stasis_app}' Stasis App"
    )


async def asterisk_ws_client():
    """
    Establishes and manages a WebSocket connection to the Asterisk PBX for event monitoring.

    This asynchronous function connects to the Asterisk PBX via WebSocket, logs connection details, receives events,
    stores them in the database, and triggers dialplan control logic for each event.

    Returns:
        None
    """

    try:
        async with websockets.connect(conf.get_ws_url()) as websocket:
            await ws_connection_log(
                conf.get_asterisk_host(),
                conf.get_asterisk_web_port(),
                conf.get_asterisk_user(),
                conf.get_asterisk_stasis_app(),
            )

            while True:
                response = await websocket.recv()
                response_json = json.loads(response)
                asterisk_chan = await get_asterisk_chan(response_json)
                event_type = response_json["type"]

                # Insert the Asterisk WebSocket events into the DB
                try:
                    await insert_ws_event(
                        asterisk_chan, event_type, json.dumps(response_json)
                    )

                    await take_control_of_dialplan(
                        event_type, response_json, asterisk_chan
                    )

                except Exception as err:
                    logging.exception(
                        f"Problem with the PostgreSQL connection: '{err}'"
                    )
                    exit(1)

    except (
        websockets.exceptions.ConnectionClosedError
    ) as err:  # TODO: check what's happen when Asterisk is stopped
        logging.exception(f"Connection to the Asterisk PBX lost!: '{err}'")
        exit(1)
    except ConnectionRefusedError as err:
        logging.exception(
            f"Unable to establish a connection with the Asterisk PBX: '{err}'"
        )
        exit(1)


def receive_signal(signal_number, frame):
    """
    Handles received system signals and exits the program gracefully.

    This function prints the received signal number and exits the process for SIGINT (2) or SIGTERM (15).

    Args:
        signal_number (int): The signal number received.
        frame: The current stack frame (unused).

    Returns:
        None
    """
    print("Exiting On Signal:", signal_number)
    match signal_number:
        case 2:
            exit(0)
        case 15:
            exit(0)


async def main():
    """
    Main Function
    -------------

    ```python
    async def main() -> None:
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
    ```

    This is the main function of the program. It is an asynchronous function that orchestrates the execution of the `asterisk_ws_client` function.

    Returns:
        None
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
        logging.exception(f"Error when starting the event loop...  {err}")
        exit(1)
    except web_exceptions.HTTPClientError as err:
        logging.exception(f"Can't generate the audio file...  {err}")
        exit(1)
    except KeyboardInterrupt as err:
        logging.info(f"Process terminated due Interrupt. {err}")
        exit(0)
