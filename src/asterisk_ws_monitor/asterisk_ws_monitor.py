import asyncio
import json
import logging

import websockets
from aiohttp import ClientSession, client_exceptions, web, web_exceptions

import caller_utils.caller_configuration as conf
from caller_utils.db.db_asterisk_ws_monitor import insert_ws_event

logging.basicConfig(format=conf.get_log_formatter())

EVENT_TYPE = "StasisStart"
CHANNEL_STATE = "Up"


async def get_asterisk_chan(response_json):
    """Get the Asterisk Channel from the JSON responses"""
    if response_json["type"] in ["PlaybackStarted", "PlaybackFinished"]:
        return str(response_json.get("playback", {}).get("target_uri")).split(":")[1]
    else:
        return response_json.get("channel", {}).get("id")


async def querying_call_register(asterisk_chan):
    """HTTP requests against the 'call_register' to get the checksum of the message"""
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
    try:
        # Generate the audio file function
        generate_audio_session = ClientSession()
        generate_audio_resp = await generate_audio_session.post(
            url=conf.get_generate_audio_url()
            + f"/{conf.get_generate_audio_app_route()}"
            + f"?message={response_data.get('message')}"
            + f"&msg_chk_sum={response_data.get('msg_chk_sum')}"
        )
        generate_audio_resp_json = await generate_audio_resp.json()
        return generate_audio_resp_json
    except client_exceptions.ClientConnectorError as err:
        logging.exception(f"Unable to connect to the GenerateAudio Process: '{err}'")
        # Send the 'continue' here to the websocket in order to _hangup_ the call
        raise web.HTTPClientError(
            reason=str(err), body=None, text=None, content_type=None
        ) from err
    finally:
        await generate_audio_session.close()


async def audio_play_status_log(response_data, asterisk_chan, audio_play_resp_message):
    """This function will show the status of the playing audio step"""
    logging.info(
        f"Response for the playing audio '{response_data.get('msg_chk_sum')}.wav' "
        + "on the Asterisk channel "
        + f"'{asterisk_chan}': '{audio_play_resp_message}'"
    )


async def play_audio_to_channel(asterisk_chan, response_data):
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
    """I do things with audio"""
    # Try to play the audio message to the callee through the Stasis application...
    if generate_audio_resp_json["status"] == 200:
        # Try to play the audio file to the channel
        await play_audio_to_channel(asterisk_chan, response_data)


async def take_control_of_dialplan(event_type, response_json, asterisk_chan):
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
    """Display a message when the WebSocket connection is established against the Asterisk PBX"""
    logging.info(
        "WebSocket connection to the Asterisk PBX at "
        + f"'{asterisk_host}:{asterisk_web_port}'. "
        + f"Authenticated as '{asterisk_user}' "
        + f"and using the '{asterisk_stasis_app}' Stasis App"
    )


async def asterisk_ws_client():
    """Connection to the Asterisk WebSocket Server"""

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

    except websockets.exceptions.ConnectionClosedError as err:  # TODO: check what's happen when Asterisk is stopped
        logging.exception(f"Connection to the Asterisk PBX lost!: '{err}'")
        exit(1)
    except ConnectionRefusedError as err:
        logging.exception(
            f"Unable to establish a connection with the Asterisk PBX: '{err}'"
        )
        exit(1)


if __name__ == "__main__":
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(asterisk_ws_client())
        loop.run_forever()
    except OSError as err:
        logging.exception(f"Error when starting the event loop...  {err}")
        exit(1)
    except web_exceptions.HTTPClientError as err:
        logging.exception(f"Can't generate the audio file...  {err}")
        exit(1)
    except KeyboardInterrupt as err:
        logging.info(f"Process terminated due Interrupt. {err}")
        exit(0)
