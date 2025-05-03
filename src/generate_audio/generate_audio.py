import asyncio
import logging
import os
import pathlib
import site
import subprocess
from concurrent.futures.thread import ThreadPoolExecutor
from enum import Enum

import py_phone_caller_utils.caller_configuration as conf
from aiohttp import web
from py_phone_caller_utils.py_phone_caller_voices.aws_polly import \
    aws_polly_text_to_wave
from py_phone_caller_utils.py_phone_caller_voices.facebook_mms import \
    text_to_speech_facebook_mms
from py_phone_caller_utils.py_phone_caller_voices.google_gtts import \
    create_audio_file

SERVING_AUDIO_FOLDER = conf.get_serving_audio_folder()
IS_AUDIO_READY_ENDPOINT = conf.get_is_audio_ready_endpoint()
PRE_TRAINED_MODELS_FOLDER = conf.get_pre_trained_models_folder()
FACEBOOK_MMS_MODELS_FOLDER = conf.get_facebook_mms_models_folder()
FACEBOOK_MMS_LANGUAGE_CODE = conf.get_facebook_mms_language_code()
PIPER_MODELS_FOLDER = conf.get_piper_models_folder()
PIPER_LANGUAGE_CODE = conf.get_piper_language_code()
CONFIG_TTS_ENGINE = conf.get_tts_engine()
logging.basicConfig(format=conf.get_log_formatter())


class TTSEngine(Enum):
    """
    Enumeration of supported Text-to-Speech (TTS) engines for audio generation.

    This enum provides a method to convert a string configuration value to a TTSEngine member.

    Attributes:
        GOOGLE_GTTS: Google Text-to-Speech engine.
        FACEBOOK_MMS: Facebook MMS TTS engine.
        PIPER: Piper TTS engine.
        AWS_POLLY: Amazon Polly TTS engine.
    """

    GOOGLE_GTTS = "google_gtts"
    FACEBOOK_MMS = "facebook_mms"
    PIPER = "piper_tts"
    AWS_POLLY = "aws_polly"

    @classmethod
    def from_string(cls, value: str):
        """
        Converts a string configuration value to a TTSEngine enum member.

        This class method matches the provided string to a supported TTS engine, raising a ValueError if the value is invalid.

        Args:
            value (str): The string representation of the TTS engine.

        Returns:
            TTSEngine: The corresponding TTSEngine enum member.

        Raises:
            ValueError: If the provided value does not match any supported TTS engine.
        """
        try:
            return next(engine for engine in cls if engine.value == value.lower())
        except StopIteration:
            raise ValueError(
                f"Invalid TTS engine: {value}. Valid options are: {[e.value for e in cls]}"
            )


try:
    TTS_ENGINE = TTSEngine.from_string(CONFIG_TTS_ENGINE)
except ValueError as e:
    logging.error(f"Invalid TTS engine configuration: {e}")
    TTS_ENGINE = TTSEngine.GOOGLE_GTTS  # Default to Google if invalid config


async def create_audio_folder(folder_name):
    """
    Creates the specified folder for storing audio files if it does not already exist.

    This asynchronous function attempts to create the folder and logs an exception if the operation fails.

    Args:
        folder_name (str): The path of the folder to create.

    Returns:
        None
    """
    try:
        pathlib.Path(folder_name).mkdir(parents=True, exist_ok=True)
    except Exception as err:
        logging.exception(f"Unable to create the 'audio' folder: '{err}'")


def generate_tts_audio(
    message: str, output_path: str, engine: TTSEngine = None
) -> None:
    """
    Generate audio file using the specified TTS engine

    Args:
        message: Text to convert to speech
        output_path: Path where to save the audio file
        engine: TTS engine to use (defaults to configured TTS_ENGINE)
    """
    engine = engine or TTS_ENGINE

    if engine == TTSEngine.GOOGLE_GTTS:
        msg_chk_sum = output_path.split("/")[-1].replace(".wav", "")
        create_audio_file(message, msg_chk_sum)
    elif engine == TTSEngine.FACEBOOK_MMS:
        text_to_speech_facebook_mms(message, FACEBOOK_MMS_LANGUAGE_CODE, output_path)
    elif engine == TTSEngine.PIPER:
        text_to_speech_piper_tts(message, output_path)
    elif engine == TTSEngine.AWS_POLLY:
        aws_polly_text_to_wave(message, output_path)
    else:
        raise ValueError(f"Unsupported TTS engine: {engine}")


def file_not_found_error(error_text, file_location):
    """
    Raises a FileNotFoundError with a formatted error message and logs the error.

    This function constructs an error message from the provided text and file location, logs it, and raises the exception.

    Args:
        error_text (str): The error message prefix.
        file_location (str): The file path or location related to the error.

    Returns:
        None

    Raises:
        FileNotFoundError: Always raised with the constructed error message.
    """
    error_msg = f"{error_text}{file_location}"
    logging.error(error_msg)
    raise FileNotFoundError(error_msg)


def text_to_speech_piper_tts(message, output_path):
    """
    Generates an audio file from text using the Piper TTS engine.

    This function constructs the command to run the Piper TTS script with the appropriate model and configuration files,
    executes the command, and logs the process. It raises an error if any required file is missing or if the TTS process fails.

    Args:
        message (str): The text to convert to speech.
        output_path (str): The path where the generated audio file will be saved.

    Returns:
        None

    Raises:
        FileNotFoundError: If the Python interpreter, Piper script, model, or config file is missing.
        RuntimeError: If the Piper TTS process fails to execute successfully.
    """
    python_interpreter = conf.get_piper_python_interpreter()
    if not os.path.exists(python_interpreter):
        file_not_found_error(
            "Python 3.11 interpreter not found at: ", python_interpreter
        )
    piper_script = os.path.join(
        site.getsitepackages()[0],
        "py_phone_caller_utils",
        "py_phone_caller_voices",
        "piper_tts.py",
    )
    if not os.path.exists(piper_script):
        file_not_found_error("Piper TTS script not found at: ", piper_script)
    model_dir = os.path.abspath(
        f"{PRE_TRAINED_MODELS_FOLDER}/{PIPER_MODELS_FOLDER}/{PIPER_LANGUAGE_CODE}"
    )
    model_path = os.path.abspath(f"{model_dir}/{PIPER_LANGUAGE_CODE}.onnx")
    config_path = os.path.abspath(f"{model_dir}/{PIPER_LANGUAGE_CODE}.onnx.json")

    if not os.path.exists(model_path):
        file_not_found_error("Piper model file not found at: ", model_path)
    if not os.path.exists(config_path):
        file_not_found_error("Piper config file not found at: ", config_path)

    cmd = [
        python_interpreter,
        piper_script,
        message,
        "--model",
        model_path,
        "--config",
        config_path,
        "--output",
        output_path,
    ]

    logging.info(f"Running Piper TTS with command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info(f"Piper TTS completed successfully for output: {output_path}")
        if result.stdout:
            logging.debug(f"Piper TTS output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        error_msg = (
            f"Piper TTS process failed with exit code {e.returncode}: {e.stderr}"
        )
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e
    except Exception as e:
        error_msg = f"Error running Piper TTS: {str(e)}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e


def wave_file_exists(file_path: str) -> bool:
    """
    Check if a wave file exists and is valid

    Args:
        file_path: Path to the wave file
    Returns:
        bool: True if file exists and is valid
    """
    try:
        if not os.path.isfile(file_path):
            return False

        if os.path.getsize(file_path) == 0:
            return False

        with open(file_path, "rb") as f:
            header = f.read(44)  # Read WAV header
            if len(header) < 44 or not header.startswith(b"RIFF"):
                return False

        return True
    except (OSError, IOError):
        return False


async def is_audio_ready(request):
    """
    Checks if the audio file for the given message checksum exists and is ready to be served.

    This asynchronous function retrieves the 'msg_chk_sum' parameter from the request, checks for the existence and validity of the corresponding audio file, and returns a JSON response.

    Args:
        request: The incoming HTTP request containing the 'msg_chk_sum' parameter.

    Returns:
        aiohttp.web.Response: A JSON response indicating whether the audio file exists.

    Raises:
        web.HTTPClientError: If the 'msg_chk_sum' parameter is missing from the request.
    """
    try:
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError as err:
        logging.exception(f"No 'msg_chk_sum' parameter passed on: '{request.rel_url}'")
        raise web.HTTPClientError(
            reason="Missing msg_chk_sum parameter",
            body=None,
            text=None,
            content_type=None,
        ) from err

    output_path = f"{SERVING_AUDIO_FOLDER}/{msg_chk_sum}.wav"
    exists = await asyncio.to_thread(wave_file_exists, output_path)

    return web.json_response({"exists": exists})


async def create_audio(request):
    """
    Handles incoming requests to generate an audio file from text using the configured TTS engine.

    This asynchronous function extracts the message and checksum from the request, checks for an existing audio file,
    generates the audio if needed, and returns a JSON response indicating the status and cache state.

    Args:
        request: The incoming HTTP request containing 'message' and 'msg_chk_sum' parameters.

    Returns:
        aiohttp.web.Response: A JSON response indicating the status and whether the audio was cached.

    Raises:
        web.HTTPClientError: If any required parameter is missing from the request.
    """
    try:
        message = request.rel_url.query["message"]
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError as err:
        logging.exception(
            f"No 'message' or 'msg_chk_sum' parameters passed on: '{request.rel_url}'"
        )
        raise web.HTTPClientError(
            reason=conf.get_generate_audio_error(),
            body=None,
            text=None,
            content_type=None,
        ) from err

    output_path = f"{SERVING_AUDIO_FOLDER}/{msg_chk_sum}.wav"

    exists = await asyncio.to_thread(wave_file_exists, output_path)
    if exists:
        logging.info(
            f"Audio file already exists for message checksum {msg_chk_sum}, skipping generation"
        )
        return web.json_response({"status": 200, "cached": True})

    inner_loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=conf.get_num_of_cpus())

    try:
        futures = inner_loop.run_in_executor(
            executor, generate_tts_audio, message, output_path
        )
        await asyncio.ensure_future(futures)
        status_code = 200
    except Exception as err:
        status_code = 500
        logging.exception(
            f"Unable to generate the audio file using {TTS_ENGINE.value}: '{err}'"
        )

    return web.json_response({"status": status_code, "cached": False})


async def init_app():
    """
    Initializes and configures the aiohttp web application for audio generation and serving.

    This asynchronous function creates necessary folders, registers routes for audio generation and readiness checks,
    and sets up static file serving for development purposes.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """
    app = web.Application()

    folders_to_create = [
        SERVING_AUDIO_FOLDER,
        f"{PRE_TRAINED_MODELS_FOLDER}/{FACEBOOK_MMS_MODELS_FOLDER}",
        f"{PRE_TRAINED_MODELS_FOLDER}/{PIPER_MODELS_FOLDER}/{PIPER_LANGUAGE_CODE}",
    ]

    for folder in folders_to_create:
        await create_audio_folder(folder)

    app.router.add_route(
        "POST", f"/{conf.get_generate_audio_app_route()}", create_audio
    )

    app.router.add_route("GET", f"/{IS_AUDIO_READY_ENDPOINT}", is_audio_ready)

    # Self-serving audio files (use Nginx or a CDN when running in production)
    path_to_static_folder = SERVING_AUDIO_FOLDER  # Only for development proposes
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
    web.run_app(app, port=int(conf.get_generate_audio_port()))
