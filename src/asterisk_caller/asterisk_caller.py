import asyncio
import logging
from base64 import b64encode

from aiohttp import ClientSession, ClientTimeout, client_exceptions, web

import caller_utils.caller_configuration as conf

logging.basicConfig(format=conf.get_log_formatter())

ASTERISK_URL = conf.get_asterisk_url()


async def gen_headers(auth_string):
    """Prepare the HTTP headers for the basic auth against the Asterisk PBX"""
    return {
        "Authorization": f"Basic {str(b64encode(bytearray(auth_string, 'utf8')), 'utf-8')}"
    }


async def send_ari_continue(headers, asterisk_chan, asterisk_continue_addr):
    """Restores the call control to the Asterisk PBX when our operations are done. Needed in order to
    exit of the 'Stasis' application and continue walking through the dialplan."""
    try:
        session = ClientSession(
            timeout=ClientTimeout(total=conf.get_client_timeout_total())
        )
        play_audio_resp = await session.post(
            url=asterisk_continue_addr, data=None, headers=headers
        )
        await session.close()
        if play_audio_resp.status == 204:  # Asterisk returns a '204' code
            logging.info(
                f"Restoring the call control to the PBX on the channel '{asterisk_chan}'"
            )
            return play_audio_resp.status
        else:
            logging.error(
                f"Unable to restore to the PBX the call control on the channel '{asterisk_chan}'"
            )
    except client_exceptions.ClientConnectorError as err:
        logging.exception(f"Unable to connect to the Asterisk system: '{err}'")
        raise web.HTTPClientError(
            reason=str(err), body=None, text=None, content_type=None
        )


async def place_call(request):
    """Handles incoming requests coming to '/asterisk' endpoint and start the calls
    using the Asterisk ARI interface."""

    try:
        phone = request.rel_url.query["phone"]
        message = request.rel_url.query["message"]
    except KeyError as err:
        phone = None
        message = None
        logging.exception(
            f"No 'phone' or 'message' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason=conf.get_asterisk_call_error(),
            body=None,
            text=None,
            content_type=None,
        ) from err

    # Prepare the URL to 'call' the Asterisk ARI
    asterisk_query_string = (
        f"endpoint={conf.get_asterisk_chan_type()}/{phone}&extension={conf.get_asterisk_extension()}"
        + f"&context={conf.get_asterisk_context()}&callerId={conf.get_asterisk_caller_id()}"
    )
    asterisk_call_init = (
        f"{ASTERISK_URL}/{conf.get_asterisk_ari_channels()}?{asterisk_query_string}"
    )
    # Place a call on the Asterisk system using HTTP Basic Auth on the PBX
    headers = await gen_headers(
        f"{conf.get_asterisk_user()}:{conf.get_asterisk_pass()}"
    )

    try:
        session = ClientSession(
            timeout=ClientTimeout(total=conf.get_client_timeout_total())
        )
        call_resp = await session.post(
            url=asterisk_call_init, data=None, headers=headers
        )
        await session.close()
        if call_resp.status == 200:
            response_data = await call_resp.json()
            asterisk_chan = response_data["id"]
            session = ClientSession(
                timeout=ClientTimeout(total=conf.get_client_timeout_total())
            )
            await session.post(
                url=conf.get_call_register_url()
                + f"/{conf.get_call_register_app_route_register_call()}"
                + f"?phone={phone}&message={message}&asterisk_chan={asterisk_chan}",
                data=None,
                headers=headers,
            )
            await session.close()
        else:
            logging.error(
                f"Asterisk server '{ASTERISK_URL}' response: {call_resp.status}. Unable to initialize the call."
            )

    except client_exceptions.ClientConnectorError as err:
        logging.exception(
            f"Unable to connect to the Asterisk system or the 'call_register' service: '{err}'"
        )
        raise web.HTTPClientError(
            reason=str(err), body=None, text=None, content_type=None
        )

    return web.json_response({"status": call_resp.status})


# Handle requests to play audio
async def asterisk_play(request):
    """Play audio for incoming requests coming to '/play'"""
    # Params: asterisk_chan, msg_chk_sum
    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError as err:
        asterisk_chan = None
        msg_chk_sum = None
        logging.exception(
            f"No 'asterisk_chan' or 'msg_chk_sum' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason=conf.get_asterisk_play_error(),
            body=None,
            text=None,
            content_type=None,
        ) from err

    # Play audio to the Asterisk system channel using HTTP Basic Auth against the PBX
    generate_audio_url = (
        conf.get_generate_audio_url() + f"/{conf.get_serving_audio_folder()}"
    )
    asterisk_play_addr = (
        f"{ASTERISK_URL}/{conf.get_asterisk_ari_channels()}/{asterisk_chan}/"
        + f"{conf.get_asterisk_ari_play()}:{generate_audio_url}/{msg_chk_sum}.wav"
    )
    headers = await gen_headers(
        f"{conf.get_asterisk_user()}:{conf.get_asterisk_pass()}"
    )

    try:
        session = ClientSession(
            timeout=ClientTimeout(total=conf.get_client_timeout_total())
        )
        play_audio_resp = await session.post(
            url=asterisk_play_addr, data=None, headers=headers
        )
        await session.close()
        if play_audio_resp.status == 201:  # Asterisk returns a '201' code
            logging.info(
                f"Asterisk server '{ASTERISK_URL}' response: {play_audio_resp.status}. Playing audio"
                + f" '{msg_chk_sum}.wav' to the channel '{asterisk_chan}'"
            )
        else:
            logging.error(
                f"Asterisk server '{ASTERISK_URL}' response: {play_audio_resp.status}."
                + f"Unable to play audio '{msg_chk_sum}.wav' to the channel '{asterisk_chan}'"
            )

    except client_exceptions.ClientConnectorError as err:
        logging.exception(f"Unable to connect to the Asterisk system: '{err}'")
        raise web.HTTPClientError(
            reason=str(err), body=None, text=None, content_type=None
        )

    # Send the 'continue' command in order to restore the flow control to the PBX
    asterisk_play_addr = (
        f"{ASTERISK_URL}/{conf.get_asterisk_ari_channels()}/{asterisk_chan}/continue"
    )
    await send_ari_continue(headers, asterisk_chan, asterisk_play_addr)
    return web.json_response({"status": play_audio_resp.status})


async def init_app():
    """Start the Application Web Server."""
    app = web.Application()

    # And... here our routes
    app.router.add_route(
        "POST", f"/{conf.get_asterisk_call_app_route_place_call()}", place_call
    )
    app.router.add_route(
        "POST", f"/{conf.get_asterisk_call_app_route_play()}", asterisk_play
    )
    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=conf.get_asterisk_call_port())
