import asyncio
import json
import logging as sync_logger

import aiologger
import asyncpg
import websockets
from aiohttp import ClientSession, client_exceptions, web, web_exceptions
from aiologger.formatters.base import Formatter
from aiologger.levels import LogLevel

import local_utils.caller_configuration as conf
import local_utils.db_conn as db_conn

LOG_FORMATTER = conf.get_log_formatter()

LOGGER = aiologger.Logger.with_default_handlers(
    name="asterisk_ws_monitor",
    level=LogLevel.INFO,
    formatter=Formatter(fmt=LOG_FORMATTER),
)


ASTERISK_USER = conf.get_asterisk_user()
ASTERISK_PASS = conf.get_asterisk_pass()
ASTERISK_HOST = conf.get_asterisk_host()
ASTERISK_WEB_PORT = conf.get_asterisk_web_port()
ASTERISK_STASIS_APP = conf.get_asterisk_stasis_app()
WS_URL = (
    f"ws://{ASTERISK_HOST}:{ASTERISK_WEB_PORT}/ari/events"
    + f"?api_key={ASTERISK_USER}:{ASTERISK_PASS}&app={ASTERISK_STASIS_APP}"
)
WS_URL_LOG = (
    f"ws://{ASTERISK_HOST}:{ASTERISK_WEB_PORT}/ari/events"
    + f"?api_key={ASTERISK_USER}:*******&app={ASTERISK_STASIS_APP}"
)
CALL_REGISTER_HTTP_SCHEME = conf.call_register_http_scheme()
CALL_REGISTER_HOST = conf.get_call_register_host()
CALL_REGISTER_PORT = conf.get_call_register_port()
CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE = conf.get_call_register_app_route_voice_message()
CALL_REGISTER_URL = (
    f"{CALL_REGISTER_HTTP_SCHEME}://{CALL_REGISTER_HOST}:{CALL_REGISTER_PORT}"
)
ASTERISK_CALL_HTTP_SCHEME = conf.get_asterisk_call_http_scheme()
ASTERISK_CALL_HOST = conf.get_asterisk_call_host()
ASTERISK_CALL_PORT = conf.get_asterisk_call_port()
ASTERISK_CALL_APP_ROUTE_PLAY = conf.get_asterisk_call_app_route_play()
ASTERISK_CALL_URL = (
    f"{ASTERISK_CALL_HTTP_SCHEME}://{ASTERISK_CALL_HOST}:{ASTERISK_CALL_PORT}"
)
GENERATE_AUDIO_HTTP_SCHEME = conf.get_generate_audio_http_scheme()
GENERATE_AUDIO_HOST = conf.get_generate_audio_host()
GENERATE_AUDIO_PORT = conf.get_generate_audio_port()
GENERATE_AUDIO_APP_ROUTE = conf.get_generate_audio_app_route()
GENERATE_AUDIO_URL = (
    f"{GENERATE_AUDIO_HTTP_SCHEME}://{GENERATE_AUDIO_HOST}:{GENERATE_AUDIO_PORT}"
)
DB_HOST = conf.get_db_host()
DB_NAME = conf.get_db_name()
DB_USER = conf.get_db_user()
DB_PASSWORD = conf.get_db_password()
DB_MAX_SIZE = conf.get_db_max_size()
DB_MAX_INACTIVE_CONNECTION_LIFETIME = conf.get_db_max_inactive_connection_lifetime()


# ToDo: Refactoring needed here, longer functions. Many can be taken out avoiding the 'nesting everything'
async def get_asterisk_chan(response_json):
    """Get the Asterisk Channel from the JSON responses"""
    if response_json["type"] in ["PlaybackStarted", "PlaybackFinished"]:
        return str(response_json.get("playback", {}).get("target_uri")).split(":")[1]
    else:
        return response_json.get("channel", {}).get("id")


async def asterisk_ws_client():
    """Connection to the Asterisk WebSocket Server"""
    ws_pool = await db_conn.pool_init(
        DB_HOST,
        DB_NAME,
        DB_USER,
        DB_PASSWORD,
        DB_MAX_SIZE,
        DB_MAX_INACTIVE_CONNECTION_LIFETIME,
    )

    try:
        async with websockets.connect(WS_URL) as websocket:
            LOGGER.info(f"WebSocket connection to the Asterisk PBX at '{WS_URL_LOG}'.")
            while True:
                response = await websocket.recv()
                response_json = json.loads(response)
                asterisk_chan = await get_asterisk_chan(response_json)
                event_type = response_json["type"]

                # Take a connection from the pool.
                try:
                    async with ws_pool.acquire() as connection:
                        async with connection.transaction():
                            await connection.execute(
                                """
                                INSERT INTO asterisk_ws_events(asterisk_chan,event_type,json_data) VALUES($1, $2, $3)
                                """,
                                asterisk_chan,
                                event_type,
                                json.dumps(response_json),
                            )

                    # Get the message text and the ID
                    if (
                        event_type == "StasisStart"
                        and response_json.get("channel", {}).get("state") == "Up"
                    ):
                        try:
                            session = ClientSession()
                            callregister_resp = await session.post(
                                url=CALL_REGISTER_URL
                                + f"/{CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE}"
                                + f"?asterisk_chan={asterisk_chan}",
                                data=None,
                            )
                            message = await callregister_resp.text()
                            response_data = json.loads(message)
                            await session.close()
                        except client_exceptions.ClientConnectorError as e:
                            LOGGER.error(
                                f"Unable to connect to the Asterisk system: '{e}'"
                            )
                            raise web.HTTPClientError(
                                reason=str(e), body=None, text=None, content_type=None
                            )

                        # Create the audio file
                        try:
                            session = ClientSession()
                            generateaudio_resp = await session.post(
                                url=GENERATE_AUDIO_URL
                                + f"/{GENERATE_AUDIO_APP_ROUTE}"
                                + f"?message={response_data.get('message')}"
                                + f"&msg_chk_sum={response_data.get('msg_chk_sum')}"
                            )
                            message = await generateaudio_resp.json()
                            await session.close()

                            # Try to play the audio message...
                            if message["status"] == 200:

                                async def play_audio_to_channel():
                                    try:
                                        session = ClientSession()
                                        audioplay_resp = await session.post(
                                            url=ASTERISK_CALL_URL
                                            + f"/{ASTERISK_CALL_APP_ROUTE_PLAY}"
                                            + f"?asterisk_chan={asterisk_chan}"
                                            + f"&msg_chk_sum={response_data.get('msg_chk_sum')}",
                                            data=None,
                                        )
                                        # TODO change the name of the 'message' variable used twice...
                                        message = await audioplay_resp.text()
                                        await session.close()
                                        LOGGER.info(
                                            f"Response for the playing audio '{response_data.get('msg_chk_sum')}.wav' "
                                            + f"on the Asterisk channel "
                                            + f"'{asterisk_chan}': '{message}'"
                                        )
                                    except client_exceptions.ClientConnectorError as e:
                                        LOGGER.error(
                                            f"Unable to connect to the Asterisk system: '{e}'"
                                        )

                                # Try to play the audio file to the channel
                                await play_audio_to_channel()

                        except client_exceptions.ClientConnectorError as e:
                            await session.close()
                            LOGGER.error(
                                f"Unable to connect to the GenerateAudio Process: '{e}'"
                            )
                            # Send the continue here to the websocket in order to hangup the call
                            raise web.HTTPClientError(
                                reason=str(e), body=None, text=None, content_type=None
                            )

                except asyncpg.exceptions.ConnectionDoesNotExistError as e:
                    await LOGGER.error(f"Problem with the PostgreSQL connection: '{e}'")
                    exit(1)

    except websockets.exceptions.ConnectionClosedError as e:
        await LOGGER.error(f"Lost connection to the Asterisk PBX: '{e}'")
        exit(1)
    except ConnectionRefusedError as e:
        await LOGGER.error(
            f"Unable to establish a connection with the Asterisk PBX: '{e}'"
        )
        exit(1)


try:
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asterisk_ws_client())
    loop.run_forever()
except OSError as e:
    sync_logger.basicConfig(format=LOG_FORMATTER)
    sync_logger.error(f"Error when starting the event loop...  {e}")
    exit(1)
except web_exceptions.HTTPClientError as e:
    sync_logger.basicConfig(format=LOG_FORMATTER)
    sync_logger.error(f"Can't generate the audio file...  {e}")
    exit(1)
except KeyboardInterrupt as e:
    sync_logger.basicConfig(format=LOG_FORMATTER)
    sync_logger.error(f"Process terminated due Interrupt. {e}")
    exit(0)
