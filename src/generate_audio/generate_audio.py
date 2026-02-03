"""
Generate Audio service.

Provides endpoints to generate and serve audio files from text using various
TTS engines (Google gTTS, Facebook MMS, Piper, AWS Polly, Kokoro) and to verify
when an audio file is ready to be played.
"""

import asyncio
import importlib
import importlib.util
import logging
import os
import sys
import pathlib
import site
import subprocess

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)


from concurrent.futures.thread import ThreadPoolExecutor
from enum import Enum

from aiohttp import web
from py_phone_caller_utils.py_phone_caller_voices.aws_polly import (
    aws_polly_text_to_wave,
)
from py_phone_caller_utils.py_phone_caller_voices.facebook_mms import (
    text_to_speech_facebook_mms,
)
from py_phone_caller_utils.py_phone_caller_voices.google_gtts import create_audio_file
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app

from generate_audio.constants import (
    GENERATE_AUDIO_APP_ROUTE,
    GENERATE_AUDIO_PORT,
    LOG_FORMATTER,
    LOG_LEVEL,
    NUM_OF_CPUS,
    SERVING_AUDIO_FOLDER,
    IS_AUDIO_READY_ENDPOINT,
    PRE_TRAINED_MODELS_FOLDER,
    FACEBOOK_MMS_MODELS_FOLDER,
    FACEBOOK_MMS_LANGUAGE_CODE,
    PIPER_MODELS_FOLDER,
    PIPER_LANGUAGE_CODE,
    CONFIG_TTS_ENGINE,
    PIPER_PYTHON_INTERPRETER,
    GENERATE_AUDIO_ERROR,
    KOKORO_MODELS_FOLDER,
    KOKORO_LANG,
    KOKORO_PYTHON_INTERPRETER,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("generate_audio")


class TTSEngine(Enum):
    """
    Enumeration of supported Text-to-Speech (TTS) engines for audio generation.

    This enum provides a method to convert a string configuration value to a TTSEngine member.

    Attributes:
        GOOGLE_GTTS: Google Text-to-Speech engine.
        FACEBOOK_MMS: Facebook MMS TTS engine.
        PIPER: Piper TTS engine.
        AWS_POLLY: Amazon Polly TTS engine.
        KOKORO: Kokoro TTS engine (on-premise ONNX model).
    """

    GOOGLE_GTTS = "google_gtts"
    FACEBOOK_MMS = "facebook_mms"
    PIPER = "piper_tts"
    AWS_POLLY = "aws_polly"
    KOKORO = "kokoro_tts"

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
    TTS_ENGINE = TTSEngine.GOOGLE_GTTS


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
        logging.exception(f"Unable to create the folder '{folder_name}': '{err}'")


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
    elif engine == TTSEngine.KOKORO:
        text_to_speech_kokoro_tts(message, output_path)
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
    python_interpreter = PIPER_PYTHON_INTERPRETER
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    local_script = os.path.join(
        current_file_dir,
        "..",
        "py_phone_caller_utils",
        "py_phone_caller_voices",
        "piper_tts.py",
    )

    if os.path.exists(local_script):
        piper_script = os.path.abspath(local_script)
    else:
        spec = importlib.util.find_spec(
            "py_phone_caller_utils.py_phone_caller_voices.piper_tts"
        )
        if spec and spec.origin:
            piper_script = spec.origin
        else:
            piper_script = os.path.join(
                site.getsitepackages()[0],
                "py_phone_caller_utils",
                "py_phone_caller_voices",
                "piper_tts.py",
            )

    if not os.path.exists(piper_script):
        file_not_found_error("Piper TTS script not found at: ", piper_script)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    model_dir = os.path.join(
        script_dir, PRE_TRAINED_MODELS_FOLDER, PIPER_MODELS_FOLDER, PIPER_LANGUAGE_CODE
    )
    model_path = os.path.join(model_dir, f"{PIPER_LANGUAGE_CODE}.onnx")
    config_path = os.path.join(model_dir, f"{PIPER_LANGUAGE_CODE}.onnx.json")

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


def text_to_speech_kokoro_tts(message, output_path):
    """
    Generates an audio file from text using the Kokoro TTS engine.

    This function constructs the command to run the Kokoro TTS script with the appropriate model and voices files,
    executes the command, and logs the process. It raises an error if any required file is missing or if the TTS process fails.

    Supported language codes (configured via kokoro_lang in settings.toml):
        'a' => American English
        'b' => British English
        'e' => Spanish (es)
        'f' => French (fr-fr)
        'h' => Hindi (hi)
        'i' => Italian (it)
        'j' => Japanese (requires: pip install misaki[ja])
        'p' => Brazilian Portuguese (pt-br)
        'z' => Mandarin Chinese (requires: pip install misaki[zh])

    Args:
        message (str): The text to convert to speech.
        output_path (str): The path where the generated audio file will be saved.

    Returns:
        None

    Raises:
        FileNotFoundError: If the Python interpreter, Kokoro script, model, or voices file is missing.
        RuntimeError: If the Kokoro TTS process fails to execute successfully.
    """
    python_interpreter = KOKORO_PYTHON_INTERPRETER
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    local_script = os.path.join(
        current_file_dir,
        "..",
        "py_phone_caller_utils",
        "py_phone_caller_voices",
        "kokoro_tts.py",
    )

    if os.path.exists(local_script):
        kokoro_script = os.path.abspath(local_script)
    else:
        spec = importlib.util.find_spec(
            "py_phone_caller_utils.py_phone_caller_voices.kokoro_tts"
        )
        if spec and spec.origin:
            kokoro_script = spec.origin
        else:
            # Fallback to the old method
            kokoro_script = os.path.join(
                site.getsitepackages()[0],
                "py_phone_caller_utils",
                "py_phone_caller_voices",
                "kokoro_tts.py",
            )

    if not os.path.exists(kokoro_script):
        file_not_found_error("Kokoro TTS script not found at: ", kokoro_script)

    # Voice name mapping based on language code (matches get_kokoro_tts_model.py)
    voice_name_map = {
        "a": "af_heart",  # American English
        "b": "bf_emma",  # British English
        "e": "ef_dora",  # Spanish
        "f": "ff_siwis",  # French
        "h": "hf_alpha",  # Hindi
        "i": "if_sara",  # Italian
        "j": "jf_alpha",  # Japanese
        "p": "pf_dora",  # Brazilian Portuguese
        "z": "zf_xiaobei",  # Mandarin Chinese
    }
    voice_name = voice_name_map.get(KOKORO_LANG, "af_heart")

    cmd = [
        python_interpreter,
        kokoro_script,
        message,
        "--voice-name",
        voice_name,
        "--lang",
        KOKORO_LANG,
        "--output",
        output_path,
    ]

    logging.info(f"Running Kokoro TTS with command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info(f"Kokoro TTS completed successfully for output: {output_path}")
        if result.stdout:
            logging.debug(f"Kokoro TTS output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        error_msg = (
            f"Kokoro TTS process failed with exit code {e.returncode}: {e.stderr}"
        )
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e
    except Exception as e:
        error_msg = f"Error running Kokoro TTS: {str(e)}"
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
        web.HTTPBadRequest: If the 'msg_chk_sum' parameter is missing from the request.
    """
    try:
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError as err:
        logging.exception(f"No 'msg_chk_sum' parameter passed on: '{request.rel_url}'")
        raise web.HTTPBadRequest(
            reason="Missing msg_chk_sum parameter",
            body=None,
            text=None,
            content_type=None,
        ) from err

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, SERVING_AUDIO_FOLDER, f"{msg_chk_sum}.wav")
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
        web.HTTPBadRequest: If any required parameter is missing from the request.
    """
    try:
        message = request.rel_url.query["message"]
        msg_chk_sum = request.rel_url.query["msg_chk_sum"]
    except KeyError as err:
        logging.exception(
            f"No 'message' or 'msg_chk_sum' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=GENERATE_AUDIO_ERROR,
            body=None,
            text=None,
            content_type=None,
        ) from err

    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, SERVING_AUDIO_FOLDER, f"{msg_chk_sum}.wav")

    exists = await asyncio.to_thread(wave_file_exists, output_path)
    if exists:
        logging.info(
            f"Audio file already exists for message checksum {msg_chk_sum}, skipping generation"
        )
        return web.json_response({"status": 200, "cached": True})

    inner_loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=NUM_OF_CPUS)

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


async def ensure_models_present():
    """
    Ensures that the pre-trained models for the configured TTS engine are present.
    If not, it attempts to download them.

    Uses absolute paths based on the script's directory to ensure consistency
    with the paths used by the TTS functions during audio generation.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    abs_pre_trained_models = os.path.join(script_dir, PRE_TRAINED_MODELS_FOLDER)

    try:
        if TTS_ENGINE == TTSEngine.FACEBOOK_MMS:
            model_name = f"mms-tts-{FACEBOOK_MMS_LANGUAGE_CODE}"
            model_dir = os.path.join(
                abs_pre_trained_models, FACEBOOK_MMS_MODELS_FOLDER, model_name
            )
            config_path = os.path.join(model_dir, "config.json")
            if not os.path.exists(config_path):
                logging.info(
                    f"Facebook MMS model for '{FACEBOOK_MMS_LANGUAGE_CODE}' not found. Downloading..."
                )
                from py_phone_caller_utils.py_phone_caller_voices.get_fb_mms_language_model import (
                    download_mms_model_async,
                )

                await download_mms_model_async(
                    FACEBOOK_MMS_LANGUAGE_CODE,
                    os.path.join(abs_pre_trained_models, FACEBOOK_MMS_MODELS_FOLDER),
                )
            else:
                logging.info(
                    f"Facebook MMS model for '{FACEBOOK_MMS_LANGUAGE_CODE}' is present."
                )

        elif TTS_ENGINE == TTSEngine.PIPER:
            model_dir = os.path.join(
                abs_pre_trained_models, PIPER_MODELS_FOLDER, PIPER_LANGUAGE_CODE
            )
            model_path = os.path.join(model_dir, f"{PIPER_LANGUAGE_CODE}.onnx")
            config_path = os.path.join(model_dir, f"{PIPER_LANGUAGE_CODE}.onnx.json")

            if not os.path.exists(model_path) or not os.path.exists(config_path):
                logging.info(
                    f"Piper TTS model for '{PIPER_LANGUAGE_CODE}' not found. Downloading..."
                )
                from py_phone_caller_utils.py_phone_caller_voices.get_pipper_tts_language_model import (
                    download_piper_model_async,
                )

                await download_piper_model_async(
                    PIPER_LANGUAGE_CODE, abs_pre_trained_models
                )
            else:
                logging.info(
                    f"Piper TTS model for '{PIPER_LANGUAGE_CODE}' is present at {model_path}"
                )

        elif TTS_ENGINE == TTSEngine.KOKORO:
            logging.info("Ensuring Kokoro TTS model is present (checking HF cache)...")
            from py_phone_caller_utils.py_phone_caller_voices.get_kokoro_tts_model import (
                download_kokoro_model_async,
            )

            await download_kokoro_model_async(
                os.path.join(abs_pre_trained_models, KOKORO_MODELS_FOLDER)
            )
            logging.info("Kokoro TTS model check completed.")
    except Exception as e:
        logging.error(f"Failed to ensure models are present: {e}")


async def init_app():
    """
    Initializes and configures the aiohttp web application for audio generation and serving.

    This asynchronous function creates necessary folders, registers routes for audio generation and readiness checks,
    and sets up static file serving for development purposes.

    Uses absolute paths based on the script's directory to ensure consistency
    regardless of the current working directory when the service starts.

    Returns:
        aiohttp.web.Application: The configured aiohttp web application instance.
    """
    app = web.Application()

    instrument_aiohttp_app(app)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    abs_serving_audio = os.path.join(script_dir, SERVING_AUDIO_FOLDER)
    abs_pre_trained_models = os.path.join(script_dir, PRE_TRAINED_MODELS_FOLDER)

    folders_to_create = [abs_serving_audio]

    if TTS_ENGINE == TTSEngine.FACEBOOK_MMS:
        folders_to_create.extend(
            [
                abs_pre_trained_models,
                os.path.join(abs_pre_trained_models, FACEBOOK_MMS_MODELS_FOLDER),
                os.path.join(
                    abs_pre_trained_models,
                    FACEBOOK_MMS_MODELS_FOLDER,
                    f"mms-tts-{FACEBOOK_MMS_LANGUAGE_CODE}",
                ),
            ]
        )
    elif TTS_ENGINE == TTSEngine.PIPER:
        folders_to_create.extend(
            [
                abs_pre_trained_models,
                os.path.join(abs_pre_trained_models, PIPER_MODELS_FOLDER),
                os.path.join(
                    abs_pre_trained_models, PIPER_MODELS_FOLDER, PIPER_LANGUAGE_CODE
                ),
            ]
        )
    elif TTS_ENGINE == TTSEngine.KOKORO:
        folders_to_create.extend(
            [
                abs_pre_trained_models,
                os.path.join(abs_pre_trained_models, KOKORO_MODELS_FOLDER),
            ]
        )

    for folder in folders_to_create:
        await create_audio_folder(folder)

    await ensure_models_present()

    app.router.add_route("POST", f"/{GENERATE_AUDIO_APP_ROUTE}", create_audio)

    app.router.add_route("GET", f"/{IS_AUDIO_READY_ENDPOINT}", is_audio_ready)

    path_to_static_folder = abs_serving_audio
    try:
        app.router.add_static("/audio", path_to_static_folder, show_index=True)
    except ValueError:
        logging.exception(
            f"No '{path_to_static_folder}' folder present... I can't serve the audio files"
        )
        exit(1)

    return app


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    app = loop.run_until_complete(init_app())
    web.run_app(app, port=int(GENERATE_AUDIO_PORT))
