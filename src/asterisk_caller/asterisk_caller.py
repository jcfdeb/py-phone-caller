import asyncio
import concurrent.futures
import logging
import time
from base64 import b64encode
from multiprocessing import Queue

import py_phone_caller_utils.caller_configuration as conf
from aiohttp import ClientSession, ClientTimeout, client_exceptions, web

logging.basicConfig(format=conf.get_log_formatter())

ASTERISK_URL = conf.get_asterisk_url()
WAIT_FOR_CALL_CYCLE = conf.get_seconds_to_forget()
CALL_QUEUE = Queue()


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
        web.HTTPClientError: If unable to connect to the Asterisk system.
    """
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
        ) from err


async def get_asterisk_query_string(the_asterisk_chan_type, phone):
    """
    Constructs the query string for initiating a call via the Asterisk ARI API.

    This asynchronous function builds the endpoint, extension, context, and caller ID parameters based on the channel type and phone number.

    Args:
        the_asterisk_chan_type (str): The type of Asterisk channel (e.g., "PJSIP/endpoint").
        phone (str): The phone number to call.

    Returns:
        str: The constructed query string for the ARI API call.
    """

    if the_asterisk_chan_type.startswith("PJSIP"):
        return (
            f"endpoint={the_asterisk_chan_type.split('/')[0]}/{phone}@{the_asterisk_chan_type.split('/')[1]}&extension={conf.get_asterisk_extension()}"
            + f"&context={conf.get_asterisk_context()}&callerId={conf.get_asterisk_caller_id()}"
        )
    else:
        return (
            f"endpoint={the_asterisk_chan_type}/{phone}&extension={conf.get_asterisk_extension()}"
            + f"&context={conf.get_asterisk_context()}&callerId={conf.get_asterisk_caller_id()}"
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
        web.HTTPClientError: If the parameter is missing from the request.
    """
    try:
        return parameter
    except KeyError as err:
        logging.exception(f"No 'phone' or 'message' parameters passed on: '{rel_url}'")
        raise web.HTTPClientError(
            reason=conf.get_asterisk_call_error(),
            body=None,
            text=None,
            content_type=None,
        ) from err


async def initiate_asterisk_call(asterisk_call_init, phone, message, headers):
    """
    Initiates a call through the Asterisk ARI API and registers the call in the call register service.

    This asynchronous function sends a POST request to the ARI endpoint to start the call, then registers the call with the call register service.
    It logs errors and raises an HTTPClientError if the connection fails.

    Args:
        asterisk_call_init (str): The ARI endpoint URL to initiate the call.
        phone (str): The phone number to call.
        message (str): The message to be delivered during the call.
        headers (dict): The HTTP headers including authorization.

    Returns:
        aiohttp.ClientResponse: The response object from the ARI call initiation request.

    Raises:
        web.HTTPClientError: If unable to connect to the Asterisk system or call register service.
    """
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
            return call_resp
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
        ) from err


# Prepare the URL to 'call' the Asterisk ARI
the_asterisk_chan_type = conf.get_asterisk_chan_type()


# Get the generated HTTP Basic Auth to place a call through the Asterisk system
async def get_headers():
    """
    Generates HTTP Basic Authorization headers for the Asterisk ARI API using configured credentials.

    This asynchronous function combines the Asterisk user and password from configuration and returns the authorization headers.

    Returns:
        dict: A dictionary containing the 'Authorization' header for HTTP requests.
    """
    return await gen_headers(f"{conf.get_asterisk_user()}:{conf.get_asterisk_pass()}")


async def asterisk_call_start(phone, message):
    """
    Initiates an outbound call using the Asterisk ARI API with the provided phone number and message.

    This asynchronous function constructs the ARI query string, prepares the call initiation URL and headers,
    and calls the ARI endpoint to start the call.

    Args:
        phone (str): The phone number to call.
        message (str): The message to be delivered during the call.

    Returns:
        aiohttp.ClientResponse: The response object from the ARI call initiation request.
    """
    asterisk_query_string = await get_asterisk_query_string(
        the_asterisk_chan_type, phone
    )

    asterisk_call_init = (
        f"{ASTERISK_URL}/{conf.get_asterisk_ari_channels()}?{asterisk_query_string}"
    )

    headers = await get_headers()

    return await initiate_asterisk_call(asterisk_call_init, phone, message, headers)


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

    call_resp = await asterisk_call_start(phone, message)

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
        raise web.HTTPClientError(
            reason=str(err), body=None, text=None, content_type=None
        ) from err

    return web.json_response({"status": 200})


# Handle requests to play audio
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
        web.HTTPClientError: If required parameters are missing or the connection to Asterisk fails.
    """
    try:
        asterisk_chan = request.rel_url.query["asterisk_chan"]
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError as err:
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
        f"{conf.get_generate_audio_url()}/{conf.get_serving_audio_folder()}"
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
        ) from err

    # Send the 'continue' command to restore the flow control to the PBX
    asterisk_play_addr = (
        f"{ASTERISK_URL}/{conf.get_asterisk_ari_channels()}/{asterisk_chan}/continue"
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

    # And... here our routes
    app.router.add_route(
        "POST", f"/{conf.get_asterisk_call_app_route_place_call()}", place_call
    )
    app.router.add_route(
        "POST", f"/{conf.get_asterisk_call_app_route_call_to_queue()}", call_to_queue
    )
    app.router.add_route(
        "POST", f"/{conf.get_asterisk_call_app_route_play()}", asterisk_play
    )
    return app


if __name__ == "__main__":
    try:
        loop = asyncio.new_event_loop()
        queue_executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)
        queue_task = loop.run_in_executor(
            executor=queue_executor, func=manage_call_queue
        )
        app = loop.run_until_complete(init_app())
        web.run_app(app, port=int(conf.get_asterisk_call_port()))
    finally:
        ...
        # Todo: Some future actions to be done when the application is shutting down...
