"""
Generate Audio service.

Provides endpoints to generate and serve audio files from text using various
TTS engines (Google gTTS, Facebook MMS, Piper, AWS Polly, Kokoro, Silero) and to verify
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
from typing import Any, Dict, List, Optional

from aiohttp import web
from py_phone_caller_utils.py_phone_caller_voices.aws_polly import (
    aws_polly_text_to_wave,
)
from py_phone_caller_utils.py_phone_caller_voices.facebook_mms import (
    text_to_speech_facebook_mms,
)
from py_phone_caller_utils.py_phone_caller_voices.google_gtts import create_audio_file
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app
from py_phone_caller_utils.web import extract_params, create_service_catalog, setup_swagger_routes
from py_phone_caller_utils.config import settings

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
    KOKORO_MODEL_FILENAME,
    SILERO_MODELS_FOLDER,
    SILERO_LANG,
    SILERO_SPEAKER,
    SILERO_SAMPLE_RATE,
    SILERO_PYTHON_INTERPRETER,
    LANGUAGES_ENDPOINT,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("generate_audio")


class TTSEngine(Enum):
    """
    Enumeration of supported Text-to-Speech (TTS) engines for audio generation.
    """

    GOOGLE_GTTS = "google_gtts"
    FACEBOOK_MMS = "facebook_mms"
    PIPER = "piper_tts"
    AWS_POLLY = "aws_polly"
    KOKORO = "kokoro_tts"
    SILERO = "silero_tts"

    @classmethod
    def from_string(cls, value: str):
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


def resolve_audio_filename(msg_chk_sum: str, lang: str = None) -> str:
    """
    Returns filename for serving audio.
    When lang is provided and not empty, returns '{msg_chk_sum}_{lang}.wav'.
    Otherwise preserves exact backward-compatibility '{msg_chk_sum}.wav'.
    """
    clean_lang = str(lang).strip() if lang else ""
    if clean_lang:
        return f"{msg_chk_sum}_{clean_lang}.wav"
    return f"{msg_chk_sum}.wav"


async def create_audio_folder(folder_name):
    try:
        pathlib.Path(folder_name).mkdir(parents=True, exist_ok=True)
    except Exception as err:
        logging.exception(f"Unable to create the folder '{folder_name}': '{err}'")


def generate_tts_audio(
    message: str,
    output_path: str,
    engine: TTSEngine = None,
    language: str = None,
    speed: float = 1.0,
) -> None:
    """
    Generate audio file using the specified TTS engine, language, and speed.
    Falls back gracefully to default language if requested language model is missing.
    """
    engine = engine or TTS_ENGINE

    if engine == TTSEngine.GOOGLE_GTTS:
        msg_chk_sum = os.path.basename(output_path).replace(".wav", "")
        create_audio_file(message, msg_chk_sum)
    elif engine == TTSEngine.FACEBOOK_MMS:
        target_lang = language or FACEBOOK_MMS_LANGUAGE_CODE
        script_dir = os.path.dirname(os.path.abspath(__file__))
        model_dir = os.path.join(
            script_dir,
            PRE_TRAINED_MODELS_FOLDER,
            FACEBOOK_MMS_MODELS_FOLDER,
            f"mms-tts-{target_lang}",
        )
        if not os.path.exists(model_dir) and target_lang != FACEBOOK_MMS_LANGUAGE_CODE:
            logging.warning(
                f"MMS language model for '{target_lang}' not found at {model_dir}. Falling back to default '{FACEBOOK_MMS_LANGUAGE_CODE}'"
            )
            target_lang = FACEBOOK_MMS_LANGUAGE_CODE
            model_dir = os.path.join(
                script_dir,
                PRE_TRAINED_MODELS_FOLDER,
                FACEBOOK_MMS_MODELS_FOLDER,
                f"mms-tts-{target_lang}",
            )
        text_to_speech_facebook_mms(
            message,
            target_lang,
            output_path,
            model_path=model_dir if os.path.exists(model_dir) else None,
            speed=speed,
        )
    elif engine == TTSEngine.PIPER:
        text_to_speech_piper_tts(message, output_path, language=language, speed=speed)
    elif engine == TTSEngine.AWS_POLLY:
        aws_polly_text_to_wave(message, output_path)
    elif engine == TTSEngine.KOKORO:
        text_to_speech_kokoro_tts(message, output_path, language=language, speed=speed)
    elif engine == TTSEngine.SILERO:
        text_to_speech_silero_tts(message, output_path, language=language, speed=speed)
    else:
        raise ValueError(f"Unsupported TTS engine: {engine}")


def file_not_found_error(error_text, file_location):
    error_msg = f"{error_text}{file_location}"
    logging.error(error_msg)
    raise FileNotFoundError(error_msg)


def text_to_speech_piper_tts(
    message: str, output_path: str, language: str = None, speed: float = 1.0
):
    python_interpreter = PIPER_PYTHON_INTERPRETER
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    local_script = os.path.join(
        current_file_dir,
        "..",
        "py-phone-caller-utils",
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
    target_lang = language or PIPER_LANGUAGE_CODE
    model_dir = os.path.join(
        script_dir, PRE_TRAINED_MODELS_FOLDER, PIPER_MODELS_FOLDER, target_lang
    )
    model_path = os.path.join(model_dir, f"{target_lang}.onnx")
    config_path = os.path.join(model_dir, f"{target_lang}.onnx.json")

    if not os.path.exists(model_path) and target_lang != PIPER_LANGUAGE_CODE:
        logging.warning(
            f"Piper model for '{target_lang}' not found at {model_path}. Falling back to default '{PIPER_LANGUAGE_CODE}'"
        )
        target_lang = PIPER_LANGUAGE_CODE
        model_dir = os.path.join(
            script_dir, PRE_TRAINED_MODELS_FOLDER, PIPER_MODELS_FOLDER, target_lang
        )
        model_path = os.path.join(model_dir, f"{target_lang}.onnx")
        config_path = os.path.join(model_dir, f"{target_lang}.onnx.json")

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
        "--speed",
        str(speed),
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


def text_to_speech_kokoro_tts(
    message: str, output_path: str, language: str = None, speed: float = 1.0
):
    python_interpreter = KOKORO_PYTHON_INTERPRETER
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    local_script = os.path.join(
        current_file_dir,
        "..",
        "py-phone-caller-utils",
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
            kokoro_script = os.path.join(
                site.getsitepackages()[0],
                "py_phone_caller_utils",
                "py_phone_caller_voices",
                "kokoro_tts.py",
            )

    if not os.path.exists(kokoro_script):
        file_not_found_error("Kokoro TTS script not found at: ", kokoro_script)

    voice_name_map = {
        "a": "af_heart",  # American English
        "b": "bf_emma",   # British English
        "e": "ef_dora",   # Spanish
        "f": "ff_siwis",  # French
        "h": "hf_alpha",  # Hindi
        "i": "if_sara",   # Italian
        "j": "jf_alpha",  # Japanese
        "p": "pf_dora",   # Brazilian Portuguese
        "z": "zf_xiaobei",# Mandarin Chinese
        # Also map standard 2-letter codes
        "en": "af_heart",
        "es": "ef_dora",
        "fr": "ff_siwis",
        "hi": "hf_alpha",
        "it": "if_sara",
        "ja": "jf_alpha",
        "pt": "pf_dora",
        "zh": "zf_xiaobei",
    }

    target_lang = language or KOKORO_LANG
    if target_lang not in voice_name_map and target_lang != KOKORO_LANG:
        logging.warning(
            f"Kokoro language code '{target_lang}' unknown. Falling back to default '{KOKORO_LANG}'"
        )
        target_lang = KOKORO_LANG

    voice_name = voice_name_map.get(target_lang, "af_heart")
    local_model_dir = os.path.join(
        current_file_dir,
        PRE_TRAINED_MODELS_FOLDER,
        KOKORO_MODELS_FOLDER,
    )

    # Convert 2-letter back to single letter for kokoro CLI if needed
    kokoro_cli_lang = target_lang
    kokoro_lang_reverse = {"en": "a", "es": "e", "fr": "f", "hi": "h", "it": "i", "ja": "j", "pt": "p", "zh": "z"}
    if kokoro_cli_lang in kokoro_lang_reverse:
        kokoro_cli_lang = kokoro_lang_reverse[kokoro_cli_lang]

    cmd = [
        python_interpreter,
        kokoro_script,
        message,
        "--voice-name",
        voice_name,
        "--lang",
        kokoro_cli_lang,
        "--speed",
        str(speed),
        "--output",
        output_path,
    ]
    if os.path.exists(local_model_dir):
        cmd.extend(["--model", local_model_dir])

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


def text_to_speech_silero_tts(
    message: str, output_path: str, language: str = None, speed: float = 1.0
):
    python_interpreter = SILERO_PYTHON_INTERPRETER
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    local_script = os.path.join(
        current_file_dir,
        "..",
        "py-phone-caller-utils",
        "py_phone_caller_utils",
        "py_phone_caller_voices",
        "silero_tts.py",
    )

    if os.path.exists(local_script):
        silero_script = os.path.abspath(local_script)
    else:
        spec = importlib.util.find_spec(
            "py_phone_caller_utils.py_phone_caller_voices.silero_tts"
        )
        if spec and spec.origin:
            silero_script = spec.origin
        else:
            silero_script = os.path.join(
                site.getsitepackages()[0],
                "py_phone_caller_utils",
                "py_phone_caller_voices",
                "silero_tts.py",
            )

    if not os.path.exists(silero_script):
        file_not_found_error("Silero TTS script not found at: ", silero_script)

    target_lang = language or SILERO_LANG
    supported_langs = ["en", "ru", "de", "es", "fr", "indic"]
    if target_lang not in supported_langs and target_lang != SILERO_LANG:
        logging.warning(
            f"Silero language '{target_lang}' not directly supported. Falling back to '{SILERO_LANG}'"
        )
        target_lang = SILERO_LANG

    local_models_base = os.path.join(
        current_file_dir,
        PRE_TRAINED_MODELS_FOLDER,
        SILERO_MODELS_FOLDER,
    )

    cmd = [
        python_interpreter,
        silero_script,
        message,
        "--lang",
        target_lang,
        "--speaker",
        SILERO_SPEAKER,
        "--sample-rate",
        str(SILERO_SAMPLE_RATE),
        "--speed",
        str(speed),
        "--output",
        output_path,
    ]
    if os.path.exists(local_models_base):
        cmd.extend(["--model", local_models_base])

    logging.info(f"Running Silero TTS with command: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info(f"Silero TTS completed successfully for output: {output_path}")
        if result.stdout:
            logging.debug(f"Silero TTS output: {result.stdout}")
    except subprocess.CalledProcessError as e:
        error_msg = (
            f"Silero TTS process failed with exit code {e.returncode}: {e.stderr}"
        )
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e
    except Exception as e:
        error_msg = f"Error running Silero TTS: {str(e)}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e


def wave_file_exists(file_path: str) -> bool:
    try:
        if not os.path.isfile(file_path):
            return False

        if os.path.getsize(file_path) == 0:
            return False

        with open(file_path, "rb") as f:
            header = f.read(44)
            if len(header) < 44 or not header.startswith(b"RIFF"):
                return False

        return True
    except (OSError, IOError):
        return False


async def is_audio_ready(request):
    params = await extract_params(request)
    msg_chk_sum = params.get("msg_chk_sum")
    lang = params.get("lang") or params.get("language")

    if not msg_chk_sum:
        logging.exception(f"No 'msg_chk_sum' parameter passed on: '{request.rel_url}'")
        raise web.HTTPBadRequest(
            reason="Missing msg_chk_sum parameter",
            body=None,
            text=None,
            content_type=None,
        )

    script_dir = os.path.dirname(os.path.abspath(__file__))
    filename = resolve_audio_filename(msg_chk_sum, lang)
    output_path = os.path.join(script_dir, SERVING_AUDIO_FOLDER, filename)
    exists = await asyncio.to_thread(wave_file_exists, output_path)

    return web.json_response({"exists": exists})


async def create_audio(request):
    params = await extract_params(request)
    message = params.get("message")
    msg_chk_sum = params.get("msg_chk_sum")
    lang = params.get("lang") or params.get("language")
    raw_speed = params.get("speed", 1.0)
    try:
        speed = float(raw_speed) if raw_speed is not None else 1.0
    except (ValueError, TypeError):
        speed = 1.0

    if not message or not msg_chk_sum:
        logging.exception(
            f"No 'message' or 'msg_chk_sum' parameter passed on: '{request.rel_url}'"
        )
        raise web.HTTPBadRequest(
            reason=GENERATE_AUDIO_ERROR,
            body=None,
            text=None,
            content_type=None,
        )

    script_dir = os.path.dirname(os.path.abspath(__file__))
    filename = resolve_audio_filename(msg_chk_sum, lang)
    output_path = os.path.join(script_dir, SERVING_AUDIO_FOLDER, filename)

    exists = await asyncio.to_thread(wave_file_exists, output_path)
    if exists:
        logging.info(
            f"Audio file already exists for {filename}, skipping generation"
        )
        return web.json_response({"status": 200, "cached": True})

    try:
        await asyncio.to_thread(
            generate_tts_audio,
            message,
            output_path,
            language=lang,
            speed=speed,
        )
        status_code = 200
    except Exception as err:
        status_code = 500
        logging.exception(
            f"Unable to generate the audio file using {TTS_ENGINE.value}: '{err}'"
        )

    return web.json_response({"status": status_code, "cached": False})


LANGUAGE_NAMES: Dict[str, str] = {
    "en": "English",
    "eng": "English",
    "en_US": "English (United States)",
    "en_GB": "English (United Kingdom)",
    "en-US": "English (United States)",
    "en-GB": "English (United Kingdom)",
    "es": "Spanish",
    "spa": "Spanish",
    "es_ES": "Spanish (Spain)",
    "es_MX": "Spanish (Mexico)",
    "es-ES": "Spanish (Spain)",
    "it": "Italian",
    "ita": "Italian",
    "it_IT": "Italian (Italy)",
    "it-IT": "Italian (Italy)",
    "fr": "French",
    "fra": "French",
    "fr_FR": "French (France)",
    "fr-FR": "French (France)",
    "de": "German",
    "deu": "German",
    "de_DE": "German (Germany)",
    "de-DE": "German (Germany)",
    "ru": "Russian",
    "rus": "Russian",
    "ru_RU": "Russian (Russia)",
    "ru-RU": "Russian (Russia)",
    "zh": "Chinese (Mandarin)",
    "cmn": "Chinese (Mandarin)",
    "zh_CN": "Chinese (Simplified)",
    "cmn-CN": "Chinese (Mandarin)",
    "hi": "Hindi",
    "hin": "Hindi",
    "hi_IN": "Hindi (India)",
    "hi-IN": "Hindi (India)",
    "indic": "Indic / Hindi",
    "he": "Hebrew",
    "heb": "Hebrew",
    "he_IL": "Hebrew (Israel)",
    "he-IL": "Hebrew (Israel)",
    "ar": "Arabic",
    "ara": "Arabic",
    "arb": "Arabic (Standard)",
    "ar_JO": "Arabic (Jordan)",
    "pt": "Portuguese",
    "por": "Portuguese",
    "pt_BR": "Portuguese (Brazil)",
    "ja": "Japanese",
    "jpn": "Japanese",
    "a": "English (American)",
    "b": "English (British)",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese",
    "p": "Portuguese (Brazil)",
    "z": "Chinese (Mandarin)",
}


def scan_installed_languages(base_models_dir: str = None) -> Dict[str, Any]:
    """
    Scans the pre-trained models directory for installed weights and configs
    across all supported engines, and returns both active engine language options
    and full installed model inventories.
    """
    if base_models_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_models_dir = os.path.join(script_dir, PRE_TRAINED_MODELS_FOLDER)

    installed: Dict[str, Any] = {
        "facebook_mms": [],
        "piper_tts": [],
        "kokoro_tts": {"ready": False, "voices": []},
        "silero_tts": [],
    }

    # 1. Facebook MMS
    fb_dir = os.path.join(base_models_dir, FACEBOOK_MMS_MODELS_FOLDER)
    if os.path.isdir(fb_dir):
        for entry in sorted(os.listdir(fb_dir)):
            sub = os.path.join(fb_dir, entry)
            if os.path.isdir(sub) and entry.startswith("mms-tts-"):
                code = entry.replace("mms-tts-", "").strip()
                cfg = os.path.join(sub, "config.json")
                if os.path.exists(cfg):
                    installed["facebook_mms"].append({
                        "code": code,
                        "name": LANGUAGE_NAMES.get(code, code.capitalize()),
                        "model": entry,
                        "ready": True,
                    })

    # 2. Piper TTS
    piper_dir = os.path.join(base_models_dir, PIPER_MODELS_FOLDER)
    if os.path.isdir(piper_dir):
        for entry in sorted(os.listdir(piper_dir)):
            sub = os.path.join(piper_dir, entry)
            if os.path.isdir(sub):
                onnx_file = os.path.join(sub, f"{entry}.onnx")
                if os.path.exists(onnx_file):
                    installed["piper_tts"].append({
                        "code": entry,
                        "name": LANGUAGE_NAMES.get(entry, entry),
                        "model": f"{entry}.onnx",
                        "ready": True,
                    })
            elif entry.endswith(".onnx"):
                code = entry[:-5]
                installed["piper_tts"].append({
                    "code": code,
                    "name": LANGUAGE_NAMES.get(code, code),
                    "model": entry,
                    "ready": True,
                })

    # 3. Kokoro TTS
    kokoro_dir = os.path.join(base_models_dir, KOKORO_MODELS_FOLDER)
    if os.path.isdir(kokoro_dir):
        pth = os.path.join(kokoro_dir, KOKORO_MODEL_FILENAME)
        cfg = os.path.join(kokoro_dir, "config.json")
        is_ready = os.path.exists(pth) or os.path.exists(cfg)
        voices: List[str] = []
        voices_dir = os.path.join(kokoro_dir, "voices")
        if os.path.isdir(voices_dir):
            for v in sorted(os.listdir(voices_dir)):
                if v.endswith(".pt"):
                    voices.append(v[:-3])
        installed["kokoro_tts"] = {
            "model": KOKORO_MODEL_FILENAME,
            "ready": is_ready,
            "voices": voices,
        }

    # 4. Silero TTS
    silero_dir = os.path.join(base_models_dir, SILERO_MODELS_FOLDER)
    if os.path.isdir(silero_dir):
        for entry in sorted(os.listdir(silero_dir)):
            sub = os.path.join(silero_dir, entry)
            if os.path.isdir(sub):
                pt_files = [f for f in os.listdir(sub) if f.endswith(".pt")]
                if pt_files:
                    installed["silero_tts"].append({
                        "code": entry,
                        "name": LANGUAGE_NAMES.get(entry, entry.capitalize()),
                        "model": pt_files[0],
                        "ready": True,
                    })
            elif entry.endswith(".pt") and entry.startswith("v"):
                parts = entry[:-3].split("_")
                if len(parts) >= 2:
                    code = parts[1]
                    installed["silero_tts"].append({
                        "code": code,
                        "name": LANGUAGE_NAMES.get(code, code.capitalize()),
                        "model": entry,
                        "ready": True,
                    })

    # Build active engine languages list
    engine_val = TTS_ENGINE.value
    active_langs: List[Dict[str, Any]] = []
    default_lang = ""

    if TTS_ENGINE == TTSEngine.FACEBOOK_MMS:
        default_lang = FACEBOOK_MMS_LANGUAGE_CODE
        active_langs = list(installed["facebook_mms"])
        if not any(item["code"] == default_lang for item in active_langs):
            active_langs.insert(0, {
                "code": default_lang,
                "name": LANGUAGE_NAMES.get(default_lang, default_lang.capitalize()),
                "model": f"mms-tts-{default_lang}",
                "ready": True,
            })
    elif TTS_ENGINE == TTSEngine.PIPER:
        default_lang = PIPER_LANGUAGE_CODE
        active_langs = list(installed["piper_tts"])
        if not any(item["code"] == default_lang for item in active_langs):
            active_langs.insert(0, {
                "code": default_lang,
                "name": LANGUAGE_NAMES.get(default_lang, default_lang),
                "model": f"{default_lang}.onnx",
                "ready": True,
            })
    elif TTS_ENGINE == TTSEngine.KOKORO:
        default_lang = KOKORO_LANG
        for v in installed["kokoro_tts"]["voices"]:
            lang_code = "en"
            if v.startswith("ff_"):
                lang_code = "fr"
            elif v.startswith("ef_") or v.startswith("em_"):
                lang_code = "es"
            elif v.startswith("if_") or v.startswith("im_"):
                lang_code = "it"
            elif v.startswith("zf_") or v.startswith("zm_"):
                lang_code = "zh"
            elif v.startswith("jf_") or v.startswith("jm_"):
                lang_code = "ja"
            elif v.startswith("hf_") or v.startswith("hm_"):
                lang_code = "hi"
            active_langs.append({
                "code": lang_code,
                "voice": v,
                "name": f"{LANGUAGE_NAMES.get(lang_code, lang_code.capitalize())} ({v})",
                "ready": installed["kokoro_tts"]["ready"],
            })
        if not active_langs:
            active_langs.append({
                "code": default_lang,
                "name": LANGUAGE_NAMES.get(default_lang, "English (American)"),
                "ready": installed["kokoro_tts"]["ready"],
            })
    elif TTS_ENGINE == TTSEngine.SILERO:
        default_lang = SILERO_LANG
        active_langs = list(installed["silero_tts"])
        if not any(item["code"] == default_lang for item in active_langs):
            active_langs.insert(0, {
                "code": default_lang,
                "name": LANGUAGE_NAMES.get(default_lang, default_lang.capitalize()),
                "model": f"v3_{default_lang}.pt",
                "ready": True,
            })
    elif TTS_ENGINE == TTSEngine.GOOGLE_GTTS:
        default_lang = "en"
        for c in ["en", "es", "it", "fr", "de", "ru", "zh", "hi", "he", "ar"]:
            active_langs.append({
                "code": c,
                "name": LANGUAGE_NAMES.get(c, c.capitalize()),
                "ready": True,
            })
    elif TTS_ENGINE == TTSEngine.AWS_POLLY:
        default_lang = "en-US"
        for c in ["en-US", "es-ES", "it-IT", "fr-FR", "de-DE", "ru-RU", "cmn-CN", "hi-IN", "he-IL", "arb"]:
            active_langs.append({
                "code": c,
                "name": LANGUAGE_NAMES.get(c, c),
                "ready": True,
            })

    for item in active_langs:
        item["engine"] = engine_val
        item["is_default"] = (item["code"] == default_lang)

    return {
        "active_engine": engine_val,
        "default_language": default_lang,
        "languages": active_langs,
        "installed_models": installed,
    }


async def get_languages(request: web.Request) -> web.Response:
    """
    Returns the list of available languages for the active TTS engine
    along with installed offline pre-trained models on disk.
    """
    result = await asyncio.to_thread(scan_installed_languages)
    return web.json_response(result)


async def ensure_models_present():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    abs_pre_trained_models = os.path.join(script_dir, PRE_TRAINED_MODELS_FOLDER)

    preload_cfg = settings.get("generate_audio", {}).get("preload", {})

    try:
        if TTS_ENGINE == TTSEngine.FACEBOOK_MMS:
            from py_phone_caller_utils.py_phone_caller_voices.get_fb_mms_language_model import (
                download_mms_model_async,
            )
            mms_langs = preload_cfg.get("facebook_mms", [FACEBOOK_MMS_LANGUAGE_CODE])
            if FACEBOOK_MMS_LANGUAGE_CODE not in mms_langs:
                mms_langs.append(FACEBOOK_MMS_LANGUAGE_CODE)

            for lang in mms_langs:
                model_name = f"mms-tts-{lang}"
                model_dir = os.path.join(
                    abs_pre_trained_models, FACEBOOK_MMS_MODELS_FOLDER, model_name
                )
                config_path = os.path.join(model_dir, "config.json")
                if not os.path.exists(config_path):
                    try:
                        logging.info(f"Facebook MMS model for '{lang}' not found. Downloading...")
                        await download_mms_model_async(
                            lang,
                            os.path.join(abs_pre_trained_models, FACEBOOK_MMS_MODELS_FOLDER),
                        )
                    except Exception as dl_err:
                        logging.warning(f"Could not preload Facebook MMS model '{lang}': {dl_err}")
                else:
                    logging.info(f"Facebook MMS model for '{lang}' is present at {model_dir}")

        elif TTS_ENGINE == TTSEngine.PIPER:
            from py_phone_caller_utils.py_phone_caller_voices.get_pipper_tts_language_model import (
                download_piper_model_async,
            )
            piper_langs = preload_cfg.get("piper_tts", [PIPER_LANGUAGE_CODE])
            if PIPER_LANGUAGE_CODE not in piper_langs:
                piper_langs.append(PIPER_LANGUAGE_CODE)

            for lang in piper_langs:
                model_dir = os.path.join(
                    abs_pre_trained_models, PIPER_MODELS_FOLDER, lang
                )
                model_path = os.path.join(model_dir, f"{lang}.onnx")
                config_path = os.path.join(model_dir, f"{lang}.onnx.json")

                if not os.path.exists(model_path) or not os.path.exists(config_path):
                    logging.info(f"Piper TTS model for '{lang}' not found. Downloading...")
                    await download_piper_model_async(lang, abs_pre_trained_models)
                else:
                    logging.info(f"Piper TTS model for '{lang}' is present at {model_path}")

        elif TTS_ENGINE == TTSEngine.KOKORO:
            model_dir = os.path.join(abs_pre_trained_models, KOKORO_MODELS_FOLDER)
            model_path = os.path.join(model_dir, KOKORO_MODEL_FILENAME)
            config_path = os.path.join(model_dir, "config.json")

            if not os.path.exists(model_path) or not os.path.exists(config_path):
                logging.info(f"Kokoro TTS model not found in {model_dir}. Downloading...")
                from py_phone_caller_utils.py_phone_caller_voices.get_kokoro_tts_model import (
                    download_kokoro_model_async,
                )
                await download_kokoro_model_async(model_dir)
            else:
                logging.info(f"Kokoro TTS model is present at {model_dir}")
            logging.info("Kokoro TTS model check completed.")

        elif TTS_ENGINE == TTSEngine.SILERO:
            from py_phone_caller_utils.py_phone_caller_voices.get_silero_tts_model import (
                download_silero_model_async,
                MODEL_FILENAMES,
            )
            silero_langs = preload_cfg.get("silero_tts", [SILERO_LANG])
            if SILERO_LANG not in silero_langs:
                silero_langs.append(SILERO_LANG)

            for lang in silero_langs:
                expected_fn = MODEL_FILENAMES.get(lang, f"v3_{lang}.pt")
                model_dir = os.path.join(
                    abs_pre_trained_models, SILERO_MODELS_FOLDER, lang
                )
                model_path = os.path.join(model_dir, expected_fn)
                direct_path = os.path.join(abs_pre_trained_models, SILERO_MODELS_FOLDER, expected_fn)

                if not os.path.exists(model_path) and not os.path.exists(direct_path):
                    try:
                        logging.info(f"Silero TTS model for '{lang}' not found. Downloading...")
                        await download_silero_model_async(lang, abs_pre_trained_models)
                    except Exception as dl_err:
                        logging.warning(f"Could not preload Silero TTS model '{lang}': {dl_err}")
                else:
                    actual = model_path if os.path.exists(model_path) else direct_path
                    logging.info(f"Silero TTS model for '{lang}' is present at {actual}")
            logging.info("Silero TTS model check completed.")
    except Exception as e:
        logging.error(f"Failed to ensure models are present: {e}")


async def init_app():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    abs_audio_folder = os.path.join(script_dir, SERVING_AUDIO_FOLDER)
    await create_audio_folder(abs_audio_folder)
    await ensure_models_present()

    app = web.Application()

    app.router.add_post(f"/{GENERATE_AUDIO_APP_ROUTE}", create_audio)
    app.router.add_get(f"/{IS_AUDIO_READY_ENDPOINT}", is_audio_ready)
    app.router.add_get(f"/{LANGUAGES_ENDPOINT}", get_languages)

    app.router.add_static(
        f"/{SERVING_AUDIO_FOLDER}/",
        path=abs_audio_folder,
        name=SERVING_AUDIO_FOLDER,
        show_index=True,
    )

    create_service_catalog(app, "generate_audio", GENERATE_AUDIO_PORT)
    setup_swagger_routes(app, "generate_audio", "Generate Audio Service", "1.0.0")
    instrument_aiohttp_app(app, "generate_audio")

    return app


if __name__ == "__main__":
    app = init_app()
    web.run_app(app, port=GENERATE_AUDIO_PORT)
