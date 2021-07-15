import asyncio
import logging
import pathlib
from concurrent.futures.thread import ThreadPoolExecutor

import aiologger
from aiohttp import web
from aiologger.formatters.base import Formatter
from aiologger.levels import LogLevel

import local_utils.caller_configuration as conf
from local_utils.google_voice import create_audio_file

"""
TODO: Delete the mp3 file with something like...
if os.path.isfile(path):
    os.remove(path)
"""

LOG_FORMATTER = conf.get_log_formatter()
GENERATE_AUDIO_ERROR = conf.get_generate_audio_error()
SERVING_AUDIO_FOLDER = (
    conf.get_serving_audio_folder()
)  # was: serving_audio_folder = "audio/"
LOST_DIRECTORY_ERROR = conf.get_lost_directory_error()
NUM_OF_CPUS = conf.get_num_of_cpus()
GENERATE_AUDIO_PORT = conf.get_generate_audio_port()
GENERATE_AUDIO_APP_ROUTE = conf.get_generate_audio_app_route()


LOGGER = aiologger.Logger.with_default_handlers(
    name="generate_audio",
    level=LogLevel.INFO,
    formatter=Formatter(fmt=LOG_FORMATTER),
)

# Creating the 'audio' directory if not exists
try:
    pathlib.Path(SERVING_AUDIO_FOLDER).mkdir(parents=True, exist_ok=True)
except Exception as e:
    logging.error(f"Unable to create the 'audio' folder: '{e}'")


async def create_audio(request):
    """Process the request from the 'asterisk_ws_monitor' and creates the audio file"""

    try:
        message = request.rel_url.query["message"]
    except KeyError:
        message = None
        LOGGER.error(f"No 'message' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=GENERATE_AUDIO_ERROR, body=None, text=None, content_type=None
        )

    try:
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError:
        msg_chk_sum = None
        LOGGER.error(f"No 'msg_chk_sum' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason=GENERATE_AUDIO_ERROR, body=None, text=None, content_type=None
        )

    inner_loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=NUM_OF_CPUS)
    futures = inner_loop.run_in_executor(
        executor, create_audio_file, message, msg_chk_sum
    )
    try:
        await asyncio.ensure_future(futures)
        status_code = 200
    except Exception as e:
        status_code = 500
        LOGGER.error(f"Unable to generate the audio file: '{e}'")

    return web.json_response({"status": status_code})


async def init_app():
    """Start the Application Web Server."""
    app = web.Application()

    # And... here our routes
    app.router.add_route("POST", f"/{GENERATE_AUDIO_APP_ROUTE}", create_audio)
    # Self serving audio files (use Nginx or a CDN when running in production)
    path_to_static_folder = SERVING_AUDIO_FOLDER  # Only for development proposes
    try:
        app.router.add_static(
            "/audio", path_to_static_folder, show_index=True
        )  # Only for development proposes
    except ValueError:
        await LOGGER.error(
            f"No '{path_to_static_folder}' folder present... I can't serve the audio files"
        )
        exit(1)

    return app


loop = asyncio.get_event_loop()
app = loop.run_until_complete(init_app())
logging.basicConfig(level=logging.INFO)
web.run_app(app, port=GENERATE_AUDIO_PORT)
