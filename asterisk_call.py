import asyncio
import logging
from base64 import b64encode

import aiologger
from aiohttp import ClientSession, ClientTimeout, client_exceptions, web
from aiologger.formatters.base import Formatter
from aiologger.levels import LogLevel

import local_utils.caller_configuration as conf

ASTERISK_CALL_PORT = conf.get_asterisk_call_port()
ASTERISK_CALL_APP_ROUTE_ASTERISK_INIT = conf.get_asterisk_call_app_route_asterisk_init()
ASTERISK_CALL_APP_ROUTE_PLAY = conf.get_asterisk_call_app_route_play()
ASTERISK_USER = conf.get_asterisk_user()
ASTERISK_PASS = conf.get_asterisk_pass()
ASTERISK_HOST = conf.get_asterisk_host()
ASTERISK_WEB_PORT = conf.get_asterisk_web_port()
ASTERISK_HTTP_SCHEME = conf.get_asterisk_http_scheme()
ASTERISK_URL = f"{ASTERISK_HTTP_SCHEME}://{ASTERISK_HOST}:{ASTERISK_WEB_PORT}"
ASTERISK_ARI_CHANNELS = conf.get_asterisk_ari_channels()
ASTERISK_ARI_PLAY = conf.get_asterisk_ari_play()
ASTERISK_CONTEXT = conf.get_asterisk_context()
ASTERISK_EXTENSION = conf.get_asterisk_extension()
ASTERISK_CHAN_TYPE = conf.get_asterisk_chan_type()
ASTERISK_CALLERID = conf.get_asterisk_callerid()
CALL_REGISTER_HTTP_SCHEME = conf.call_register_http_scheme()
CALL_REGISTER_HOST = conf.get_call_register_host()
CALL_REGISTER_PORT = conf.get_call_register_port()
CALL_REGISTER_APP_ROUTE_REGISTER_CALL = conf.get_call_register_app_route_register_call()
CALL_REGISTER_URL = (
    f"{CALL_REGISTER_HTTP_SCHEME}://{CALL_REGISTER_HOST}:{CALL_REGISTER_PORT}"
)
GENERATE_AUDIO_HTTP_SCHEME = conf.get_generate_audio_http_scheme()
GENERATE_AUDIO_HOST = conf.get_generate_audio_host()
GENERATE_AUDIO_PORT = conf.get_generate_audio_port()
SERVING_AUDIO_FOLDER = conf.get_serving_audio_folder()
GENERATE_AUDIO_URL = (
    f"{GENERATE_AUDIO_HTTP_SCHEME}://{GENERATE_AUDIO_HOST}:{GENERATE_AUDIO_PORT}"
    + f"/{SERVING_AUDIO_FOLDER}"
)
ASTERISK_CALL_ERROR = conf.get_asterisk_call_error()
ASTERISK_PLAY_ERROR = conf.get_asterisk_play_error()
CLIENT_TIMEOUT_TOTAL = ClientTimeout(total=conf.get_client_timeout_total())

LOGGER = aiologger.Logger.with_default_handlers(
    name="asterisk_call",
    level=LogLevel.INFO,
    formatter=Formatter(fmt="%(asctime)s %(message)s"),
)


async def gen_auth_string():
    """Returns the authentication string"""
    return f"{ASTERISK_USER}:{ASTERISK_PASS}"


async def gen_headers(auth_string):
    """Prepare the HTTP headers for the basic auth against the Asterisk PBX"""
    return {
        "Authorization": f"Basic {str(b64encode(bytearray(auth_string, 'utf8')), 'utf-8')}"
    }


async def send_ari_continue(headers, asterisk_chan, asterisk_continue_addr):
    """Restores the call control to the Asterisk PBX when our operations are done. Needed in order to
    exit of the 'Stasis' application and continue walking through the dialplan."""
    try:
        session = ClientSession(timeout=CLIENT_TIMEOUT_TOTAL)
        play_audio_resp = await session.post(
            url=asterisk_continue_addr, data=None, headers=headers
        )
        await session.close()
        if play_audio_resp.status == 204:  # Asterisk returns a '204' code
            LOGGER.info(
                f"Restoring the call control to the PBX on the channel '{asterisk_chan}'"
            )
        else:
            LOGGER.error(
                f"Unable to restore to the PBX the call control on the channel '{asterisk_chan}'"
            )
    except client_exceptions.ClientConnectorError as e:
        LOGGER.error(f"Unable to connect to the Asterisk system: '{e}'")
        raise web.HTTPClientError(
            reason=str(e), body=None, text=None, content_type=None
        )


async def asterisk_init(request):
    """Handles incoming requests coming to '/asterisk' endpoint and start the calls
    using the Asterisk ARI interface."""

    try:
        phone = request.rel_url.query["phone"]
    except KeyError:
        phone = None
        LOGGER.error(f"No 'phone' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=ASTERISK_CALL_ERROR, body=None, text=None, content_type=None
        )
    try:
        message = request.rel_url.query["message"]
    except KeyError:
        message = None
        LOGGER.error(f"No 'message' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=ASTERISK_CALL_ERROR, body=None, text=None, content_type=None
        )

    # Prepare the URL to 'call' the Asterisk ARI
    asterisk_query_string = (
        f"endpoint={ASTERISK_CHAN_TYPE}/{phone}&extension={ASTERISK_EXTENSION}"
        + f"&context={ASTERISK_CONTEXT}&callerId={ASTERISK_CALLERID}"
    )
    asterisk_call_init = (
        f"{ASTERISK_URL}/{ASTERISK_ARI_CHANNELS}?{asterisk_query_string}"
    )
    # Place a call on the Asterisk system using HTTP Basic Auth on the PBX
    headers = await gen_headers(await gen_auth_string())

    try:
        session = ClientSession(timeout=CLIENT_TIMEOUT_TOTAL)
        call_resp = await session.post(
            url=asterisk_call_init, data=None, headers=headers
        )
        await session.close()
        if call_resp.status == 200:
            response_data = await call_resp.json()
            asterisk_chan = response_data["id"]
            session = ClientSession(timeout=CLIENT_TIMEOUT_TOTAL)
            await session.post(
                url=CALL_REGISTER_URL
                + f"/{CALL_REGISTER_APP_ROUTE_REGISTER_CALL}"
                + f"?phone={phone}&message={message}&asterisk_chan={asterisk_chan}",
                data=None,
                headers=headers,
            )
            await session.close()
        else:
            LOGGER.error(
                f"Asterisk server '{ASTERISK_URL}' response: {call_resp.status}. Unable to initialize the call."
            )

    except client_exceptions.ClientConnectorError as e:
        LOGGER.error(f"Unable to connect to the Asterisk system: '{e}'")
        raise web.HTTPClientError(
            reason=str(e), body=None, text=None, content_type=None
        )

    return web.json_response({"status": call_resp.status})


# Handle requests to play audio
async def asterisk_play(request):
    """Play audio for incoming requests coming to '/play'"""
    # Params: asterisk_chan, msg_chk_sum
    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
    except KeyError:
        asterisk_chan = None
        LOGGER.error(f"No 'asterisk_chan' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=ASTERISK_PLAY_ERROR, body=None, text=None, content_type=None
        )
    try:
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError:
        msg_chk_sum = None
        LOGGER.error(f"No 'msg_chk_sum' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=ASTERISK_PLAY_ERROR, body=None, text=None, content_type=None
        )

    # Play audio to the Asterisk system channel using HTTP Basic Auth against the PBX
    asterisk_play_addr = (
        f"{ASTERISK_URL}/{ASTERISK_ARI_CHANNELS}/{asterisk_chan}/"
        + f"{ASTERISK_ARI_PLAY}:{GENERATE_AUDIO_URL}/{msg_chk_sum}.wav"
    )
    headers = await gen_headers(await gen_auth_string())

    try:
        session = ClientSession(timeout=CLIENT_TIMEOUT_TOTAL)
        play_audio_resp = await session.post(
            url=asterisk_play_addr, data=None, headers=headers
        )
        await session.close()
        if play_audio_resp.status == 201:  # Asterisk returns a '201' code
            LOGGER.info(
                f"Asterisk server '{ASTERISK_URL}' response: {play_audio_resp.status}. Playing audio"
                + f" '{msg_chk_sum}.wav' to the channel '{asterisk_chan}'"
            )
        else:
            LOGGER.error(
                f"Asterisk server '{ASTERISK_URL}' response: {play_audio_resp.status}."
                + f"Unable to play audio '{msg_chk_sum}.wav' to the channel '{asterisk_chan}'"
            )

    except client_exceptions.ClientConnectorError as e:
        LOGGER.error(f"Unable to connect to the Asterisk system: '{e}'")
        raise web.HTTPClientError(
            reason=str(e), body=None, text=None, content_type=None
        )

    # Send the 'continue' command in order to restore the flow control to the PBX
    asterisk_play_addr = (
        f"{ASTERISK_URL}/{ASTERISK_ARI_CHANNELS}/{asterisk_chan}/continue"
    )
    await send_ari_continue(headers, asterisk_chan, asterisk_play_addr)
    return web.json_response({"status": play_audio_resp.status})


async def init_app():
    """Start the Application Web Server."""
    app = web.Application()

    # And... here our routes
    app.router.add_route(
        "POST", f"/{ASTERISK_CALL_APP_ROUTE_ASTERISK_INIT}", asterisk_init
    )
    app.router.add_route("POST", f"/{ASTERISK_CALL_APP_ROUTE_PLAY}", asterisk_play)
    return app


loop = asyncio.get_event_loop()
app = loop.run_until_complete(init_app())
logging.basicConfig(level=logging.INFO)
web.run_app(app, port=ASTERISK_CALL_PORT)
