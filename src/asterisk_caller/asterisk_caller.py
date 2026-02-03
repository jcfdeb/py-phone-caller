"""
Asterisk Caller service.

This module exposes an aiohttp application to place outbound calls through the
Asterisk ARI API, enqueue calls for later processing, and play audio to active
channels. It also manages a background queue worker for immediate calling.

Key routes:
- `/{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}`: place a call immediately
- `/{ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE}`: enqueue a call to be placed later
- `/{ASTERISK_CALL_APP_ROUTE_PLAY}`: play an audio file to an existing channel

Environment/configuration is provided via `asterisk_caller.constants`.
"""

import asyncio
import concurrent.futures
import logging
import time
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)


from base64 import b64encode

from aiohttp import ClientSession, ClientTimeout, client_exceptions, web

from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app

from asterisk_caller.constants import (
    ASTERISK_URL,
    ASTERISK_PASS,
    ASTERISK_CALLER_ID,
    ASTERISK_USER,
    ASTERISK_CONTEXT,
    ASTERISK_EXTENSION,
    ASTERISK_CALL_APP_ROUTE_PLACE_CALL,
    CALL_REGISTER_APP_ROUTE_REGISTER_CALL,
    ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE,
    CALL_QUEUE,
    ASTERISK_CALL_ERROR,
    ASTERISK_CALL_APP_ROUTE_PLAY,
    ASTERISK_ARI_PLAY,
    ASTERISK_ARI_CHANNELS,
    ASTERISK_PLAY_ERROR,
    ASTERISK_CALL_PORT,
    CALL_REGISTER_URL,
    CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT,
    CALLER_ADDRESS_BOOK_URL,
    ASTERISK_CHAN_TYPE,
    WAIT_FOR_CALL_CYCLE,
    GENERATE_AUDIO_URL,
    LOG_FORMATTER,
    LOG_LEVEL,
    SERVING_AUDIO_FOLDER,
    CLIENT_TIMEOUT_TOTAL,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("asterisk_caller")


def manage_call_queue():
    """
    Continuously manages the call queue, initiating calls as they are enqueued.

    This function checks the call queue in a loop, starts calls asynchronously when present, and waits between cycles.

    Returns:
        None
    """

    while True:
        queue = CALL_QUEUE
        if not queue.empty():
            call_payload = queue.get_nowait()

            async def start_calling():
                """
                Initiates an asynchronous calling process by starting an Asterisk call.

                This coroutine function triggers an external Asterisk calling process
                using phone and message information. It operates asynchronously and
                provides no return value or synchronous completion indication.

                :raises RuntimeError: Raised if the Asterisk call process fails.
                """

                await asterisk_call_start(
                    call_payload.get("phone"), call_payload.get("message")
                )

            asyncio.run(start_calling())

            time.sleep(WAIT_FOR_CALL_CYCLE)
        else:
            time.sleep(12)


async def gen_headers(auth_string):
    """
    Generates HTTP Basic Authorization headers for use with the Asterisk ARI API.

    This asynchronous function encodes the provided authentication string and returns a dictionary suitable for HTTP requests.

    Args:
        auth_string (str): The authentication string in the format 'username:password'.

    Returns:
        dict: A dictionary containing the 'Authorization' header.
    """

    return {
        "Authorization": f"Basic {str(b64encode(bytearray(auth_string, 'utf8')), 'utf-8')}"
    }


async def send_ari_continue(headers, asterisk_chan, asterisk_continue_addr):
    """
    Sends a 'continue' command to the Asterisk ARI to restore call control to the PBX on the specified channel.

    This asynchronous function posts to the ARI endpoint, logs the result, and raises an HTTP error if the connection fails.

    Args:
        headers (dict): The HTTP headers including authorization.
        asterisk_chan (str): The identifier of the Asterisk channel.
        asterisk_continue_addr (str): The ARI endpoint URL for the continue command.

    Returns:
        int or None: The HTTP status code if successful, or None if unsuccessful.

    Raises:
        web.HTTPBadRequest: If unable to connect to the Asterisk system.
    """

    try:
        session = ClientSession(timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL))
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
        raise web.HTTPBadRequest(
            reason=str(err), body=None, text=None, content_type=None
        ) from err


async def get_asterisk_query_string(the_asterisk_chan_type, phone):
    """
    Constructs the query string for initiating a call via the Asterisk ARI API.

    This asynchronous function builds the endpoint, extension, context, and caller ID parameters based on the channel type and phone number.

    Args:
        the_asterisk_chan_type (str): The type of Asterisk channel (e.g., "PJSIP/endpoint" or "Local/{phone}@context").
        phone (str): The phone number to call.

    Returns:
        str: The constructed query string for the ARI API call.
    """

    if "{phone}" in the_asterisk_chan_type:
        endpoint = the_asterisk_chan_type.replace("{phone}", phone)
        return (
            f"endpoint={endpoint}&extension={ASTERISK_EXTENSION}"
            + f"&context={ASTERISK_CONTEXT}&callerId={ASTERISK_CALLER_ID}"
        )

    if the_asterisk_chan_type.startswith("PJSIP") and "/" in the_asterisk_chan_type:
        return (
            f"endpoint={the_asterisk_chan_type.split('/')[0]}/{phone}@{the_asterisk_chan_type.split('/')[1]}&extension={ASTERISK_EXTENSION}"
            + f"&context={ASTERISK_CONTEXT}&callerId={ASTERISK_CALLER_ID}"
        )
    else:
        return (
            f"endpoint={the_asterisk_chan_type}/{phone}&extension={ASTERISK_EXTENSION}"
            + f"&context={ASTERISK_CONTEXT}&callerId={ASTERISK_CALLER_ID}"
        )


async def validate_parameters(parameter, rel_url):
    """
    Validates the presence of a required parameter in the request.

    This asynchronous function returns the parameter if present, or raises an HTTPClientError if missing.

    Args:
        parameter: The parameter value to validate.
        rel_url: The request URL for logging purposes.

    Returns:
        Any: The parameter value if present.

    Raises:
        web.HTTPBadRequest: If the parameter is missing from the request.
    """
    try:
        return parameter
    except KeyError as err:
        logging.exception(f"No 'phone' or 'message' parameters passed on: '{rel_url}'")
        raise web.HTTPBadRequest(
            reason=ASTERISK_CALL_ERROR,
            body=None,
            text=None,
            content_type=None,
        ) from err


async def initiate_asterisk_call(
    asterisk_call_init, phone, resolved_phone, message, headers, backup_callee="false"
):
    """
    Initiates a call through the Asterisk ARI API and registers the call in the call register service.

    This asynchronous function sends a POST request to the ARI endpoint to start the call, then registers the call with the call register service.
    It logs errors and raises an HTTPClientError if the connection fails.

    Args:
        asterisk_call_init (str): The ARI endpoint URL to initiate the call.
        phone (str): The original phone number or alias (e.g., "oncall").
        resolved_phone (str): The resolved real phone number.
        message (str): The message to be delivered during the call.
        headers (dict): The HTTP headers including authorization.
        backup_callee (str): Whether this is a backup call ("true" or "false").

    Returns:
        aiohttp.ClientResponse: The response object from the ARI call initiation request.

    Raises:
        web.HTTPBadRequest: If unable to connect to the Asterisk system or call register service.
    """

    try:
        oncall = "true" if phone.lower() == "oncall" else "false"
        session = ClientSession(timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL))
        call_resp = await session.post(
            url=asterisk_call_init, data=None, headers=headers
        )
        await session.close()
        if call_resp.status == 200:
            response_data = await call_resp.json()
            asterisk_chan = response_data["id"]
            session = ClientSession(timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL))
            await session.post(
                url=CALL_REGISTER_URL
                + f"/{CALL_REGISTER_APP_ROUTE_REGISTER_CALL}"
                + f"?phone={resolved_phone}&message={message}&asterisk_chan={asterisk_chan}&oncall={oncall}&backup_callee={backup_callee}",
                data=None,
                headers=headers,
            )
            await session.close()
            return call_resp
        else:
            logging.error(
                f"Asterisk server '{ASTERISK_URL}' response: {call_resp.status}. Unable to initialize the call."
            )

    except client_exceptions.ClientConnectorError as err:
        logging.exception(
            f"Unable to connect to the Asterisk system or the 'call_register' service: '{err}'"
        )
        raise web.HTTPBadRequest(
            reason=str(err), body=None, text=None, content_type=None
        ) from err


the_asterisk_chan_type = ASTERISK_CHAN_TYPE


async def get_headers():
    """
    Generates HTTP Basic Authorization headers for the Asterisk ARI API using configured credentials.

    This asynchronous function combines the Asterisk user and password from configuration and returns the authorization headers.

    Returns:
        dict: A dictionary containing the 'Authorization' header for HTTP requests.
    """

    return await gen_headers(f"{ASTERISK_USER}:{ASTERISK_PASS}")


async def _resolve_oncall_phone(phone: str) -> str:
    """
    Resolves the "oncall" phone to the actual phone number if the input phone is 'oncall'.
    The resolution is performed by querying an external address book service. If the
    phone is not "oncall", it returns the original phone value.

    :param phone: The phone identifier as a string. If set to "oncall", it will be resolved
                  to the current on-call phone number.
    :return: The resolved phone number as a string, or the original phone if it does not
             require resolution.
    """

    if isinstance(phone, str) and phone.lower() == "oncall":
        url = f"{CALLER_ADDRESS_BOOK_URL}/{CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT}"
        try:
            async with ClientSession(
                timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
            ) as session:
                resp = await session.get(url)
                try:
                    data = await resp.json(content_type=None)
                except Exception:
                    text = await resp.text()
                    raise RuntimeError(
                        f"Address book returned non-JSON body (status {resp.status}): {text[:200]}"
                    )
                if resp.status != 200 or not isinstance(data, dict):
                    raise RuntimeError(f"Address book returned status {resp.status}")
                resolved = data.get("phone_number")
                if not resolved:
                    raise RuntimeError("Address book returned no phone_number")
                return resolved
        except Exception as err:
            logging.exception(f"Unable to resolve 'oncall' phone: {err}")
            raise
    return phone


async def asterisk_call_start(phone, message, backup_callee="false"):
    """
    Initiates an outbound call using the Asterisk ARI API with the provided phone number and message.

    This asynchronous function constructs the ARI query string, prepares the call initiation URL and headers,
    and calls the ARI endpoint to start the call.

    Args:
        phone (str): The phone number to call.
        message (str): The message to be delivered during the call.
        backup_callee (str): Whether this is a backup call ("true" or "false").

    Returns:
        aiohttp.ClientResponse: The response object from the ARI call initiation request.
    """

    resolved_phone = await _resolve_oncall_phone(phone)

    asterisk_query_string = await get_asterisk_query_string(
        the_asterisk_chan_type, resolved_phone
    )

    asterisk_call_init = (
        f"{ASTERISK_URL}/{ASTERISK_ARI_CHANNELS}?{asterisk_query_string}"
    )

    headers = await get_headers()

    return await initiate_asterisk_call(
        asterisk_call_init, phone, resolved_phone, message, headers, backup_callee
    )


async def place_call(request):
    """
    Handles incoming requests to place a call via the Asterisk ARI API.

    This asynchronous function validates the required parameters, initiates the call, and returns a JSON response with the call status.

    Args:
        request: The incoming HTTP request containing 'phone' and 'message' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the call initiation.
    """

    phone = await validate_parameters(request.rel_url.query["phone"], request.rel_url)
    message = await validate_parameters(
        request.rel_url.query["message"], request.rel_url
    )
    backup_callee = request.rel_url.query.get("backup_callee", "false").lower()

    call_resp = await asterisk_call_start(phone, message, backup_callee)

    return web.json_response({"status": call_resp.status})


async def call_to_queue(request):
    """
    Handles incoming requests to enqueue a call for later processing by the call queue manager.

    This asynchronous function validates the required parameters, adds the call to the queue, and returns a JSON response indicating success or failure.

    Args:
        request: The incoming HTTP request containing 'phone' and 'message' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the enqueue operation.
    """

    phone = await validate_parameters(request.rel_url.query["phone"], request.rel_url)
    message = await validate_parameters(
        request.rel_url.query["message"], request.rel_url
    )

    try:
        CALL_QUEUE.put_nowait({"phone": phone, "message": message})

    except Exception as err:
        logging.exception(
            f"Unable to take the request on the 'asterisk_caller' queue: '{err}'"
        )
        raise web.HTTPBadRequest(
            reason=str(err), body=None, text=None, content_type=None
        ) from err

    return web.json_response({"status": 200})


async def asterisk_play(request):
    """
    Handles incoming requests to play an audio file to a specified Asterisk channel.

    This asynchronous function validates the required parameters, sends a request to play the audio file on the channel,
    and then sends a 'continue' command to restore call control to the PBX. It returns a JSON response with the play status.

    Args:
        request: The incoming HTTP request containing 'asterisk_chan' and 'msg_chk_sum' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the play operation.

    Raises:
        web.HTTPBadRequest: If required parameters are missing or the connection to Asterisk fails.
    """

    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError as err:
        logging.exception(
            f"No 'asterisk_chan' or 'msg_chk_sum' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=ASTERISK_PLAY_ERROR,
            body=None,
            text=None,
            content_type=None,
        ) from err

    generate_audio_url = f"{GENERATE_AUDIO_URL}/{SERVING_AUDIO_FOLDER}"
    asterisk_play_addr = (
        f"{ASTERISK_URL}/{ASTERISK_ARI_CHANNELS}/{asterisk_chan}/"
        + f"{ASTERISK_ARI_PLAY}:{generate_audio_url}/{msg_chk_sum}.wav"
    )
    headers = await gen_headers(f"{ASTERISK_USER}:{ASTERISK_PASS}")

    try:
        session = ClientSession(timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL))
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
        raise web.HTTPBadRequest(
            reason=str(err), body=None, text=None, content_type=None
        ) from err

    asterisk_play_addr = (
        f"{ASTERISK_URL}/{ASTERISK_ARI_CHANNELS}/{asterisk_chan}/continue"
    )
    await send_ari_continue(headers, asterisk_chan, asterisk_play_addr)
    return web.json_response({"status": play_audio_resp.status})


async def init_app():
    """
    Initializes and configures the aiohttp web application for handling Asterisk call operations.

    This asynchronous function sets up the web application and registers the routes for placing calls,
    enqueuing calls, and playing audio to Asterisk channels.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """

    app = web.Application()

    instrument_aiohttp_app(app)

    app.router.add_route("POST", f"/{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}", place_call)
    app.router.add_route(
        "POST", f"/{ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE}", call_to_queue
    )
    app.router.add_route("POST", f"/{ASTERISK_CALL_APP_ROUTE_PLAY}", asterisk_play)
    return app


if __name__ == "__main__":
    try:
        loop = asyncio.new_event_loop()
        queue_executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)
        queue_task = loop.run_in_executor(
            executor=queue_executor, func=manage_call_queue
        )
        app = loop.run_until_complete(init_app())
        web.run_app(app, port=int(ASTERISK_CALL_PORT))
    finally:
        ...
