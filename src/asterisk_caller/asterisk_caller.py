"""
Asterisk Caller service.

This module exposes an aiohttp application to place outbound calls through the
Asterisk ARI API, enqueue calls for later processing, and play audio to active
channels. It also manages a background queue worker for immediate calling.

Phone numbers are expected to be in the format '00391234567890'. If a phone
number is provided with a '+' prefix (e.g., '+391234567890'), it will be
automatically converted to the '00' format to meet Asterisk PBX standards.

Key routes:
- `/{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}`: place a call immediately
- `/{ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE}`: enqueue a call to be placed later
- `/{ASTERISK_CALL_APP_ROUTE_PLAY}`: play an audio file to an existing channel

Environment/configuration is provided via `asterisk_caller.constants`.
"""

import asyncio
import logging
import os
import sys
import threading
import time
from base64 import b64encode

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

from datetime import timedelta
from aiohttp import ClientSession, ClientTimeout, client_exceptions, web
from aiobreaker import CircuitBreaker, CircuitBreakerError

from py_phone_caller_utils.web.readiness import (
    ReadinessRegistry,
    check_asterisk_ari,
    check_asterisk_pjsip_trunk,
)

from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app
from py_phone_caller_utils.web import extract_params, create_service_catalog, setup_swagger_routes

from asterisk_caller.constants import (
    ASTERISK_ARI_CHANNELS,
    ASTERISK_ARI_PLAY,
    ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE,
    ASTERISK_CALL_APP_ROUTE_PLACE_CALL,
    ASTERISK_CALL_APP_ROUTE_PLAY,
    ASTERISK_CALL_ERROR,
    ASTERISK_CALL_PORT,
    ASTERISK_CALLER_ID,
    ASTERISK_CHAN_TYPE,
    ASTERISK_CONTEXT,
    ASTERISK_EXTENSION,
    ASTERISK_PASS,
    ASTERISK_PLAY_ERROR,
    ASTERISK_URL,
    ASTERISK_USER,
    CALL_QUEUE,
    CALL_REGISTER_APP_ROUTE_REGISTER_CALL,
    CALL_REGISTER_URL,
    CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT,
    CALLER_ADDRESS_BOOK_URL,
    CLIENT_TIMEOUT_TOTAL,
    GENERATE_AUDIO_URL,
    LOG_FORMATTER,
    LOG_LEVEL,
    SERVING_AUDIO_FOLDER,
    WAIT_FOR_CALL_CYCLE,
    close_call_queue,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("asterisk_caller")

ari_circuit_breaker = CircuitBreaker(
    fail_max=3,
    timeout_duration=timedelta(seconds=30),
    name="asterisk_ari_circuit_breaker",
)


class OnCallPhoneUnavailable(RuntimeError):
    """
    Raised when the special 'oncall' phone alias can't be resolved.
    """


def manage_call_queue():
    """
    Continuously manages the call queue, initiating calls as they are enqueued.

    This function intentionally uses multiprocessing.Queue, but it runs in a
    thread instead of a child process. That avoids child-process imports creating
    or tracking extra semaphore objects during shutdown.
    """

    while True:
        try:
            call_payload = CALL_QUEUE.get()
        except Exception as err:
            logging.exception(f"Call queue worker failed while reading the queue: '{err}'")
            break

        if call_payload is None:
            logging.info("Call queue worker received shutdown sentinel. Exiting.")
            break

        phone = call_payload.get("phone")
        message = call_payload.get("message")

        async def start_calling():
            """
            Initiates an asynchronous calling process by starting an Asterisk call.
            """

            await asterisk_call_start(phone, message)

        try:
            asyncio.run(start_calling())
        except OnCallPhoneUnavailable as err:
            logging.warning(
                "Call queue item skipped because the on-call phone is unavailable: "
                f"phone='{phone}', message='{message}', reason='{err}'"
            )
        except CircuitBreakerError as err:
            logging.warning(
                f"Call queue item skipped because Asterisk ARI circuit breaker is open: {err}"
            )
        except Exception as err:
            logging.exception(
                "Unable to process call queue payload: "
                f"phone='{phone}', message='{message}', error='{err}'"
            )

        time.sleep(WAIT_FOR_CALL_CYCLE)


async def gen_headers(auth_string):
    """
    Generates HTTP Basic Authorization headers for use with the Asterisk ARI API.

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
        async with ClientSession(
            timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
        ) as session:
            play_audio_resp = await session.post(
                url=asterisk_continue_addr, data=None, headers=headers
            )
            if play_audio_resp.status == 204:
                logging.info(
                    f"Restoring the call control to the PBX on the channel '{asterisk_chan}'"
                )
                return play_audio_resp.status

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

    The phone number is formatted to meet Asterisk PBX standards by replacing a
    leading '+' with '00'.

    Args:
        the_asterisk_chan_type (str): The configured Asterisk channel type.
        phone (str): The phone number to call.

    Returns:
        str: The constructed query string for the ARI API call.
    """

    phone = _format_phone(phone)

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

    return (
            f"endpoint={the_asterisk_chan_type}/{phone}&extension={ASTERISK_EXTENSION}"
            + f"&context={ASTERISK_CONTEXT}&callerId={ASTERISK_CALLER_ID}"
    )


async def validate_parameters(parameter, rel_url):
    """
    Validates the presence of a required parameter in the request.

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


async def _raw_post_ari_call(asterisk_call_init, headers):
    async with ClientSession(
        timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
    ) as session:
        call_resp = await session.post(
            url=asterisk_call_init, data=None, headers=headers
        )
        if call_resp.status >= 500:
            raise client_exceptions.ClientResponseError(
                request_info=call_resp.request_info,
                history=call_resp.history,
                status=call_resp.status,
                message=f"Asterisk ARI server error: {call_resp.status}",
            )
        return call_resp


async def initiate_asterisk_call(
        asterisk_call_init, phone, resolved_phone, message, headers, backup_callee="false"
):
    """
    Initiates a call through the Asterisk ARI API and registers the call in the call register service.
    Protected by ari_circuit_breaker to fail-fast when PBX is down.

    Args:
        asterisk_call_init (str): The ARI endpoint URL to initiate the call.
        phone (str): The original phone number or alias.
        resolved_phone (str): The resolved real phone number.
        message (str): The message to be delivered during the call.
        headers (dict): HTTP headers including authorization.
        backup_callee (str): Whether this is a backup call.

    Returns:
        aiohttp.ClientResponse: The response object from the ARI call initiation request.

    Raises:
        web.HTTPBadRequest: If unable to connect to the Asterisk system or call register service.
        web.HTTPServiceUnavailable: If the Asterisk ARI circuit breaker is open.
    """

    try:
        oncall = "true" if phone.lower() == "oncall" else "false"

        call_resp = await ari_circuit_breaker.call_async(
            _raw_post_ari_call, asterisk_call_init, headers
        )

        if call_resp.status == 200:
            response_data = await call_resp.json()
            asterisk_chan = response_data["id"]

            async with ClientSession(
                timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
            ) as reg_session:
                await reg_session.post(
                    url=f"{CALL_REGISTER_URL}/{CALL_REGISTER_APP_ROUTE_REGISTER_CALL}",
                    params={
                        "phone": resolved_phone,
                        "message": message,
                        "asterisk_chan": asterisk_chan,
                        "oncall": oncall,
                        "backup_callee": backup_callee,
                    },
                    data=None,
                    headers=headers,
                )
            return call_resp

        logging.error(
            f"Asterisk server '{ASTERISK_URL}' response: {call_resp.status}. Unable to initialize the call."
        )
        return call_resp

    except CircuitBreakerError as breaker_err:
        logging.error(f"Asterisk ARI Circuit Breaker is OPEN: {breaker_err}")
        raise web.HTTPServiceUnavailable(
            reason="Asterisk ARI Circuit Breaker OPEN (PBX outage)",
            text='{"status": 503, "error": "Asterisk PBX circuit breaker open"}'
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
    Generates HTTP Basic Authorization headers for the Asterisk ARI API.

    Returns:
        dict: A dictionary containing the Authorization header.
    """

    return await gen_headers(f"{ASTERISK_USER}:{ASTERISK_PASS}")


def _format_phone(phone: str) -> str:
    """
    Formats the phone number to meet Asterisk PBX standards.

    Args:
        phone (str): The phone number to format.

    Returns:
        str: The formatted phone number.
    """

    if isinstance(phone, str) and phone.startswith("+"):
        return "00" + phone[1:]

    return phone


async def _resolve_oncall_phone(phone: str) -> str:
    """
    Resolves the 'oncall' phone alias to the actual phone number if needed.

    Args:
        phone (str): The phone identifier.

    Returns:
        str: The resolved and formatted phone number.
    """

    if isinstance(phone, str) and phone.lower() == "oncall":
        url = f"{CALLER_ADDRESS_BOOK_URL}/{CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT}"

        async with ClientSession(
                timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
        ) as session:
            resp = await session.get(url)

            try:
                data = await resp.json(content_type=None)
            except Exception:
                data = None
                text = await resp.text()

            if resp.status == 404:
                detail = data.get("error") if isinstance(data, dict) else text[:200]
                detail = detail.strip() if isinstance(detail, str) else detail
                detail_suffix = f" Address book detail: {detail}" if detail else ""
                raise OnCallPhoneUnavailable(
                    "No on-call contact is available in the address book. "
                    "Add an enabled on-call contact before using phone='oncall'."
                    + detail_suffix
                )

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

            return _format_phone(resolved)

    return _format_phone(phone)


async def asterisk_call_start(phone, message, backup_callee="false"):
    """
    Initiates an outbound call using the Asterisk ARI API.

    Args:
        phone (str): The phone number to call.
        message (str): The message to be delivered during the call.
        backup_callee (str): Whether this is a backup call.

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

    Args:
        request: The incoming HTTP request containing 'phone' and 'message' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the call initiation.
    """

    params = await extract_params(request)
    raw_phone = params.get("phone")
    raw_message = params.get("message")
    if not raw_phone or not raw_message:
        logging.exception(
            f"No 'phone' or 'message' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=ASTERISK_CALL_ERROR, body=None, text=None, content_type=None
        )
    phone = await validate_parameters(raw_phone, request.rel_url)
    message = await validate_parameters(raw_message, request.rel_url)
    backup_callee = str(params.get("backup_callee", "false")).lower()

    try:
        call_resp = await asterisk_call_start(phone, message, backup_callee)
    except OnCallPhoneUnavailable as err:
        logging.warning(f"Unable to place call: {err}")
        return web.json_response({"status": 400, "error": str(err)}, status=400)
    except web.HTTPServiceUnavailable:
        return web.json_response(
            {"status": 503, "error": "Asterisk PBX circuit breaker open"},
            status=503,
        )

    return web.json_response({"status": call_resp.status})


async def call_to_queue(request):
    """
    Handles incoming requests to enqueue a call for later processing by the call queue manager.

    Args:
        request: The incoming HTTP request containing 'phone' and 'message' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the enqueue operation.
    """

    params = await extract_params(request)
    raw_phone = params.get("phone")
    raw_message = params.get("message")
    if not raw_phone or not raw_message:
        logging.exception(
            f"No 'phone' or 'message' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=ASTERISK_CALL_ERROR, body=None, text=None, content_type=None
        )
    phone = await validate_parameters(raw_phone, request.rel_url)
    message = await validate_parameters(raw_message, request.rel_url)

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

    Args:
        request: The incoming HTTP request containing 'asterisk_chan' and 'msg_chk_sum' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status of the play operation.

    Raises:
        web.HTTPBadRequest: If required parameters are missing or the connection to Asterisk fails.
    """

    params = await extract_params(request)
    asterisk_chan = params.get("asterisk_chan")
    msg_chk_sum = params.get("msg_chk_sum")
    lang = params.get("lang") or params.get("language")
    if not asterisk_chan or not msg_chk_sum:
        logging.exception(
            f"No 'asterisk_chan' or 'msg_chk_sum' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=ASTERISK_PLAY_ERROR,
            body=None,
            text=None,
            content_type=None,
        )

    audio_file = f"{msg_chk_sum}_{lang}.wav" if lang else f"{msg_chk_sum}.wav"
    generate_audio_url = f"{GENERATE_AUDIO_URL}/{SERVING_AUDIO_FOLDER}"
    asterisk_play_addr = (
            f"{ASTERISK_URL}/{ASTERISK_ARI_CHANNELS}/{asterisk_chan}/"
            + f"{ASTERISK_ARI_PLAY}:{generate_audio_url}/{audio_file}"
    )
    headers = await gen_headers(f"{ASTERISK_USER}:{ASTERISK_PASS}")

    try:
        async with ClientSession(
            timeout=ClientTimeout(total=CLIENT_TIMEOUT_TOTAL)
        ) as session:
            play_audio_resp = await session.post(
                url=asterisk_play_addr, data=None, headers=headers
            )
            if play_audio_resp.status == 201:
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

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """

    app = web.Application()

    registry = ReadinessRegistry("asterisk_caller")
    registry.register(
        "asterisk_ari",
        lambda: check_asterisk_ari(ASTERISK_URL, ASTERISK_USER, ASTERISK_PASS),
    )

    trunk_resource = (
        ASTERISK_CHAN_TYPE.split("/")[1]
        if "/" in ASTERISK_CHAN_TYPE
        else ASTERISK_CHAN_TYPE
    )
    registry.register(
        "pjsip_trunk",
        lambda: check_asterisk_pjsip_trunk(
            ASTERISK_URL, ASTERISK_USER, ASTERISK_PASS, trunk_resource
        ),
    )

    async def asterisk_caller_ready(request):
        all_ready, details = await registry.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    app.router.add_route("GET", "/ready", asterisk_caller_ready)

    instrument_aiohttp_app(app, "asterisk_caller")

    async def root_catalog(request):
        catalog = create_service_catalog(
            service_name="asterisk_caller",
            description="Asterisk Caller outbound telephony service for py-phone-caller",
            version="1.0.0",
            docs_url="/docs",
            openapi_spec="/docs/swagger.json",
            endpoints={
                f"POST /{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}": "Initiates immediate outbound call via ARI (JSON body or query: phone, message, backup_callee)",
                f"POST /{ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE}": "Enqueues outbound call (JSON body or query: phone, message)",
                f"POST /{ASTERISK_CALL_APP_ROUTE_PLAY}": "Plays audio to channel (JSON body or query: asterisk_chan, msg_chk_sum)",
                "GET /live": "Liveness health check",
                "GET /ready": "Readiness probe",
                "GET /metrics": "Prometheus telemetry metrics",
            },
        )
        return web.json_response(catalog)

    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route("POST", f"/{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}", place_call)
    app.router.add_route(
        "POST", f"/{ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE}", call_to_queue
    )
    app.router.add_route("POST", f"/{ASTERISK_CALL_APP_ROUTE_PLAY}", asterisk_play)

    setup_swagger_routes(
        app=app,
        service_name="asterisk_caller",
        description="Asterisk ARI Call Placement and Audio Dispatch Service",
        paths={
            f"/{ASTERISK_CALL_APP_ROUTE_PLACE_CALL}": {
                "post": {
                    "summary": "Place immediate call via ARI",
                    "description": "Initiates an outbound phone call through Asterisk ARI.",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "phone": {"type": "string", "example": "0039123456789"},
                                        "message": {"type": "string", "example": "Critical alert"},
                                        "backup_callee": {"type": "boolean", "default": False},
                                    },
                                    "required": ["phone", "message"],
                                }
                            }
                        }
                    },
                    "responses": {"200": {"description": "Call successfully placed"}},
                }
            },
            f"/{ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE}": {
                "post": {
                    "summary": "Enqueue call for background dialing",
                    "description": "Places call onto internal worker queue.",
                    "responses": {"200": {"description": "Enqueued successfully"}},
                }
            },
            f"/{ASTERISK_CALL_APP_ROUTE_PLAY}": {
                "post": {
                    "summary": "Play audio to active channel",
                    "description": "Dispatches audio playback command to active channel in Stasis.",
                    "responses": {"200": {"description": "Playback started"}},
                }
            },
        },
    )

    return app


if __name__ == "__main__":
    queue_thread = None

    try:
        queue_thread = threading.Thread(
            target=manage_call_queue,
            name="asterisk-call-queue-worker",
            daemon=False,
        )
        queue_thread.start()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        app = loop.run_until_complete(init_app())
        web.run_app(app, port=int(ASTERISK_CALL_PORT), loop=loop)

    except KeyboardInterrupt:
        logging.info("Asterisk caller interrupted. Shutting down.")

    finally:
        try:
            CALL_QUEUE.put_nowait(None)
        except Exception:
            pass

        if queue_thread is not None and queue_thread.is_alive():
            queue_thread.join(timeout=10)

        close_call_queue()