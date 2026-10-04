"""
Generate Audio service.

Provides endpoints to generate and serve audio files from text using various
TTS engines (Google gTTS, Facebook MMS, Piper, AWS Polly, Kokoro, Silero) and to verify
when an audio file is ready to be played.
"""

import asyncio
import logging
import os
import pathlib
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from aiohttp import web
from py_phone_caller_utils.py_phone_caller_voices.aws_polly import (
    aws_polly_text_to_wave,
)
from py_phone_caller_utils.py_phone_caller_voices.facebook_mms import (
    text_to_speech_facebook_mms,
)
from py_phone_caller_utils.py_phone_caller_voices.google_gtts import create_audio_file
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app
from py_phone_caller_utils.web import (
    create_service_catalog,
    extract_params,
    setup_swagger_routes,
)

from generate_audio.constants import (
    GENERATE_AUDIO_APP_ROUTE,
    GENERATE_AUDIO_ERROR,
    GENERATE_AUDIO_PORT,
    IS_AUDIO_READY_ENDPOINT,
    LANGUAGES_ENDPOINT,
    LOG_FORMATTER,
    LOG_LEVEL,
    SERVING_AUDIO_FOLDER,
)

try:
    from .enums import TTSEngine, TTS_ENGINE, _DEFAULT_LANG_MAP
    from .languages import (
        LANGUAGE_ALIASES,
        LANGUAGE_FLAGS,
        LANGUAGE_NAMES,
        KOKORO_VOICE_PREFIX_TO_LANG,
        _kokoro_voice_to_lang,
    )
    from .runners import (
        _find_voice_script,
        file_not_found_error,
        text_to_speech_kokoro_tts,
        text_to_speech_piper_tts,
        text_to_speech_silero_tts,
    )
    from .discovery import (
        _ACTIVE_LANG_BUILDERS,
        _scan_facebook_mms,
        _scan_kokoro,
        _scan_piper,
        _scan_silero,
        resolve_engine_for_language,
        scan_installed_languages,
    )
    from .strategies import (
        TTS_DISPATCH_STRATEGIES,
        _handle_aws_polly,
        _handle_facebook_mms,
        _handle_google_gtts,
        _handle_kokoro,
        _handle_piper,
        _handle_silero,
        generate_tts_audio,
    )
    from .preloading import (
        _PRELOAD_STRATEGIES,
        _ensure_facebook_mms_models,
        _ensure_kokoro_models,
        _ensure_piper_models,
        _ensure_silero_models,
        ensure_models_present,
    )
except ImportError:
    from enums import TTSEngine, TTS_ENGINE, _DEFAULT_LANG_MAP
    from languages import (
        LANGUAGE_ALIASES,
        LANGUAGE_FLAGS,
        LANGUAGE_NAMES,
        KOKORO_VOICE_PREFIX_TO_LANG,
        _kokoro_voice_to_lang,
    )
    from runners import (
        _find_voice_script,
        file_not_found_error,
        text_to_speech_kokoro_tts,
        text_to_speech_piper_tts,
        text_to_speech_silero_tts,
    )
    from discovery import (
        _ACTIVE_LANG_BUILDERS,
        _scan_facebook_mms,
        _scan_kokoro,
        _scan_piper,
        _scan_silero,
        resolve_engine_for_language,
        scan_installed_languages,
    )
    from strategies import (
        TTS_DISPATCH_STRATEGIES,
        _handle_aws_polly,
        _handle_facebook_mms,
        _handle_google_gtts,
        _handle_kokoro,
        _handle_piper,
        _handle_silero,
        generate_tts_audio,
    )
    from preloading import (
        _PRELOAD_STRATEGIES,
        _ensure_facebook_mms_models,
        _ensure_kokoro_models,
        _ensure_piper_models,
        _ensure_silero_models,
        ensure_models_present,
    )

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("generate_audio")


def resolve_audio_filename(msg_chk_sum: str, lang: str = None) -> str:
    """
    Returns filename for serving audio.
    When lang is provided and not empty, returns '{msg_chk_sum}_{lang}.wav'.
    Otherwise preserves exact backward-compatibility '{msg_chk_sum}.wav'.
    """
    clean_lang = str(lang).strip() if lang else ""
    return f"{msg_chk_sum}_{clean_lang}.wav" if clean_lang else f"{msg_chk_sum}.wav"


async def create_audio_folder(folder_name):
    try:
        pathlib.Path(folder_name).mkdir(parents=True, exist_ok=True)
    except Exception as err:
        logging.exception(f"Unable to create the folder '{folder_name}': '{err}'")


def wave_file_exists(file_path: str) -> bool:
    try:
        if not os.path.isfile(file_path) or os.path.getsize(file_path) == 0:
            return False
        with open(file_path, "rb") as f:
            header = f.read(44)
            return len(header) >= 44 and header.startswith(b"RIFF")
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
    engine_param = params.get("engine")
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

    selected_engine = None
    if engine_param:
        try:
            selected_engine = TTSEngine.from_string(engine_param)
        except ValueError:
            logging.warning(
                f"Invalid engine '{engine_param}' requested, resolving dynamically"
            )
    if not selected_engine:
        selected_engine = resolve_engine_for_language(lang)

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
            engine=selected_engine,
            language=lang,
            speed=speed,
        )
        status_code = 200
    except Exception as err:
        status_code = 500
        logging.exception(
            f"Unable to generate the audio file using {selected_engine.value}: '{err}'"
        )

    return web.json_response({"status": status_code, "cached": False})


async def get_languages(request: web.Request) -> web.Response:
    """
    Returns the list of available languages for the active TTS engine
    along with installed offline pre-trained models on disk.
    """
    result = await asyncio.to_thread(scan_installed_languages)
    return web.json_response(result)


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
