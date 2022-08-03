import asyncio
import logging
import pathlib
from concurrent.futures.thread import ThreadPoolExecutor

from aiohttp import web

import caller_utils.caller_configuration as conf
from caller_utils.google_voice import create_audio_file

logging.basicConfig(format=conf.get_log_formatter())


async def create_audio_folder(folder_name):
    """Creating the 'audio' directory if not exists"""
    try:
        pathlib.Path(folder_name).mkdir(parents=True, exist_ok=True)
    except Exception as err:
        logging.exception(f"Unable to create the 'audio' folder: '{err}'")


async def create_audio(request):
    """Process the request from the 'asterisk_ws_monitor' and creates the audio file"""

    try:
        message = request.rel_url.query["message"]
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError as err:
        message = None
        msg_chk_sum = None
        logging.exception(
            f"No 'message' or 'msg_chk_sum' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason=conf.get_generate_audio_error(),
            body=None,
            text=None,
            content_type=None,
        ) from err

    inner_loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=conf.get_num_of_cpus())
    futures = inner_loop.run_in_executor(
        executor, create_audio_file, message, msg_chk_sum
    )
    try:
        await asyncio.ensure_future(futures)
        status_code = 200
    except Exception as err:
        status_code = 500
        logging.exception(f"Unable to generate the audio file: '{err}'")

    return web.json_response({"status": status_code})


async def init_app():
    """Start the Application Web Server."""
    app = web.Application()

    # Create the folder to hold the audio files
    await create_audio_folder(conf.get_serving_audio_folder())

    # And... here our routes
    app.router.add_route(
        "POST", f"/{conf.get_generate_audio_app_route()}", create_audio
    )

    # Self-serving audio files (use Nginx or a CDN when running in production)
    path_to_static_folder = (
        conf.get_serving_audio_folder()
    )  # Only for development proposes
    try:
        app.router.add_static(
            "/audio", path_to_static_folder, show_index=True
        )  # Only for development proposes
    except ValueError:
        await logging.exception(
            f"No '{path_to_static_folder}' folder present... I can't serve the audio files"
        )
        exit(1)

    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=conf.get_generate_audio_port())
