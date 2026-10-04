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
from typing import Any, Callable, Dict, List, Optional, Set

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

LANGUAGE_FLAGS: Dict[str, str] = {
    "en": "🇬🇧",
    "eng": "🇬🇧",
    "en_US": "🇺🇸",
    "en-US": "🇺🇸",
    "en_GB": "🇬🇧",
    "en-GB": "🇬🇧",
    "a": "🇺🇸",
    "b": "🇬🇧",
    "es": "🇪🇸",
    "spa": "🇪🇸",
    "e": "🇪🇸",
    "es_ES": "🇪🇸",
    "es-ES": "🇪🇸",
    "es_MX": "🇲🇽",
    "it": "🇮🇹",
    "ita": "🇮🇹",
    "i": "🇮🇹",
    "it_IT": "🇮🇹",
    "it-IT": "🇮🇹",
    "fr": "🇫🇷",
    "fra": "🇫🇷",
    "f": "🇫🇷",
    "fr_FR": "🇫🇷",
    "fr-FR": "🇫🇷",
    "de": "🇩🇪",
    "deu": "🇩🇪",
    "de_DE": "🇩🇪",
    "de-DE": "🇩🇪",
    "ru": "🇷🇺",
    "rus": "🇷🇺",
    "ru_RU": "🇷🇺",
    "ru-RU": "🇷🇺",
    "zh": "🇨🇳",
    "cmn": "🇨🇳",
    "z": "🇨🇳",
    "zh_CN": "🇨🇳",
    "cmn-CN": "🇨🇳",
    "hi": "🇮🇳",
    "hin": "🇮🇳",
    "h": "🇮🇳",
    "hi_IN": "🇮🇳",
    "hi-IN": "🇮🇳",
    "indic": "🇮🇳",
    "he": "🇮🇱",
    "heb": "🇮🇱",
    "he_IL": "🇮🇱",
    "he-IL": "🇮🇱",
    "ar": "🇸🇦",
    "ara": "🇸🇦",
    "arb": "🇸🇦",
    "ar_JO": "🇯🇴",
    "pt": "🇵🇹",
    "por": "🇵🇹",
    "p": "🇧🇷",
    "pt_BR": "🇧🇷",
    "ja": "🇯🇵",
    "jpn": "🇯🇵",
    "j": "🇯🇵",
}

LANGUAGE_ALIASES: Dict[str, str] = {
    "a": "en",
    "b": "en",
    "eng": "en",
    "en_us": "en",
    "en-us": "en",
    "en_gb": "en",
    "en-gb": "en",
    "e": "es",
    "spa": "es",
    "es_es": "es",
    "es-es": "es",
    "es_mx": "es",
    "i": "it",
    "ita": "it",
    "it_it": "it",
    "it-it": "it",
    "f": "fr",
    "fra": "fr",
    "fr_fr": "fr",
    "fr-fr": "fr",
    "deu": "de",
    "de_de": "de",
    "de-de": "de",
    "rus": "ru",
    "ru_ru": "ru",
    "ru-ru": "ru",
    "z": "zh",
    "cmn": "zh",
    "zh_cn": "zh",
    "cmn-cn": "zh",
    "h": "hi",
    "hin": "hi",
    "hi_in": "hi",
    "hi-in": "hi",
}


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


def resolve_engine_for_language(
    language: str = None, base_models_dir: str = None
) -> TTSEngine:
    """
    Resolves the best TTS engine for a requested language code.
    If no language is requested, or if the active TTS_ENGINE supports the requested
    language, returns TTS_ENGINE. Otherwise, checks if another installed offline
    engine (silero_tts, piper_tts, facebook_mms, kokoro_tts) has weights for this language.
    """
    clean_lang = str(language).strip() if language else ""
    if not clean_lang:
        return TTS_ENGINE

    # Cloud engines support everything online
    if TTS_ENGINE in (TTSEngine.GOOGLE_GTTS, TTSEngine.AWS_POLLY):
        return TTS_ENGINE

    if base_models_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_models_dir = os.path.join(script_dir, PRE_TRAINED_MODELS_FOLDER)

    norm = LANGUAGE_ALIASES.get(clean_lang.lower(), clean_lang.lower())

    # 1. Does the active engine support it?
    if TTS_ENGINE == TTSEngine.KOKORO:
        active_norm = LANGUAGE_ALIASES.get(KOKORO_LANG.lower(), KOKORO_LANG.lower())
        if clean_lang == KOKORO_LANG or norm == active_norm:
            return TTSEngine.KOKORO
        voice_map = {
            "a": "af_heart", "en": "af_heart", "b": "bf_emma",
            "e": "ef_dora", "es": "ef_dora", "f": "ff_siwis", "fr": "ff_siwis",
            "h": "hf_alpha", "hi": "hf_alpha", "i": "if_sara", "it": "if_sara",
            "j": "jf_alpha", "ja": "jf_alpha", "p": "pf_dora", "pt": "pf_dora",
            "z": "zf_xiaobei", "zh": "zf_xiaobei"
        }
        voice_name = voice_map.get(clean_lang) or voice_map.get(norm)
        if voice_name:
            voice_file = os.path.join(
                base_models_dir, KOKORO_MODELS_FOLDER, "voices", f"{voice_name}.pt"
            )
            if os.path.exists(voice_file):
                return TTSEngine.KOKORO

    elif TTS_ENGINE == TTSEngine.SILERO:
        active_norm = LANGUAGE_ALIASES.get(SILERO_LANG.lower(), SILERO_LANG.lower())
        if clean_lang == SILERO_LANG or norm == active_norm:
            return TTSEngine.SILERO
        silero_file = os.path.join(base_models_dir, SILERO_MODELS_FOLDER, norm, f"v3_{norm}.pt")
        direct_file = os.path.join(base_models_dir, SILERO_MODELS_FOLDER, f"v3_{norm}.pt")
        if os.path.exists(silero_file) or os.path.exists(direct_file):
            return TTSEngine.SILERO

    elif TTS_ENGINE == TTSEngine.PIPER:
        active_norm = LANGUAGE_ALIASES.get(PIPER_LANGUAGE_CODE.lower(), PIPER_LANGUAGE_CODE.lower())
        if clean_lang == PIPER_LANGUAGE_CODE or norm == active_norm:
            return TTSEngine.PIPER
        piper_dir = os.path.join(base_models_dir, PIPER_MODELS_FOLDER)
        if os.path.isdir(piper_dir):
            for entry in os.listdir(piper_dir):
                if entry == clean_lang or LANGUAGE_ALIASES.get(entry.lower(), entry.lower()) == norm:
                    return TTSEngine.PIPER

    elif TTS_ENGINE == TTSEngine.FACEBOOK_MMS:
        active_norm = LANGUAGE_ALIASES.get(FACEBOOK_MMS_LANGUAGE_CODE.lower(), FACEBOOK_MMS_LANGUAGE_CODE.lower())
        if clean_lang == FACEBOOK_MMS_LANGUAGE_CODE or norm == active_norm:
            return TTSEngine.FACEBOOK_MMS
        mms_dir = os.path.join(base_models_dir, FACEBOOK_MMS_MODELS_FOLDER)
        if os.path.isdir(mms_dir):
            for entry in os.listdir(mms_dir):
                if entry.startswith("mms-tts-"):
                    sub = entry.replace("mms-tts-", "")
                    if sub == clean_lang or LANGUAGE_ALIASES.get(sub.lower(), sub.lower()) == norm:
                        return TTSEngine.FACEBOOK_MMS

    # 2. Check other offline engines on disk:
    # Check Silero
    silero_dir = os.path.join(base_models_dir, SILERO_MODELS_FOLDER)
    if os.path.isdir(silero_dir):
        for entry in os.listdir(silero_dir):
            sub_path = os.path.join(silero_dir, entry)
            if os.path.isdir(sub_path):
                if entry == clean_lang or LANGUAGE_ALIASES.get(entry.lower(), entry.lower()) == norm:
                    if any(f.endswith(".pt") for f in os.listdir(sub_path)):
                        return TTSEngine.SILERO
            elif entry.endswith(".pt") and entry.startswith("v"):
                parts = entry[:-3].split("_")
                if len(parts) >= 2:
                    sub = parts[1]
                    if sub == clean_lang or LANGUAGE_ALIASES.get(sub.lower(), sub.lower()) == norm:
                        return TTSEngine.SILERO

    # Check Piper
    piper_dir = os.path.join(base_models_dir, PIPER_MODELS_FOLDER)
    if os.path.isdir(piper_dir):
        for entry in os.listdir(piper_dir):
            sub_path = os.path.join(piper_dir, entry)
            if os.path.isdir(sub_path):
                if entry == clean_lang or LANGUAGE_ALIASES.get(entry.lower(), entry.lower()) == norm:
                    if os.path.exists(os.path.join(sub_path, f"{entry}.onnx")):
                        return TTSEngine.PIPER
            elif entry.endswith(".onnx"):
                c = entry[:-5]
                if c == clean_lang or LANGUAGE_ALIASES.get(c.lower(), c.lower()) == norm:
                    return TTSEngine.PIPER

    # Check Facebook MMS
    mms_dir = os.path.join(base_models_dir, FACEBOOK_MMS_MODELS_FOLDER)
    if os.path.isdir(mms_dir):
        for entry in os.listdir(mms_dir):
            if entry.startswith("mms-tts-"):
                sub = entry.replace("mms-tts-", "")
                if sub == clean_lang or LANGUAGE_ALIASES.get(sub.lower(), sub.lower()) == norm:
                    if os.path.exists(os.path.join(mms_dir, entry, "config.json")):
                        return TTSEngine.FACEBOOK_MMS

    # Check Kokoro
    kokoro_dir = os.path.join(base_models_dir, KOKORO_MODELS_FOLDER)
    if os.path.isdir(kokoro_dir) and (
        os.path.exists(os.path.join(kokoro_dir, KOKORO_MODEL_FILENAME))
        or os.path.exists(os.path.join(kokoro_dir, "config.json"))
    ):
        v_map = {
            "a": "af_heart", "en": "af_heart", "b": "bf_emma",
            "e": "ef_dora", "es": "ef_dora", "f": "ff_siwis", "fr": "ff_siwis",
            "h": "hf_alpha", "hi": "hf_alpha", "i": "if_sara", "it": "if_sara",
            "j": "jf_alpha", "ja": "jf_alpha", "p": "pf_dora", "pt": "pf_dora",
            "z": "zf_xiaobei", "zh": "zf_xiaobei"
        }
        target_v = v_map.get(clean_lang) or v_map.get(norm)
        if target_v and os.path.exists(os.path.join(kokoro_dir, "voices", f"{target_v}.pt")):
            return TTSEngine.KOKORO
        if clean_lang == KOKORO_LANG or norm == LANGUAGE_ALIASES.get(KOKORO_LANG.lower(), KOKORO_LANG.lower()):
            return TTSEngine.KOKORO

    return TTS_ENGINE


def _handle_google_gtts(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    msg_chk_sum = os.path.basename(output_path).replace(".wav", "")
    create_audio_file(message, msg_chk_sum)


def _handle_facebook_mms(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    target_lang = language or FACEBOOK_MMS_LANGUAGE_CODE
    mms_alias = {
        "es": "spa",
        "e": "spa",
        "en": "eng",
        "a": "eng",
        "it": "ita",
        "i": "ita",
        "fr": "fra",
        "f": "fra",
        "de": "deu",
    }
    if target_lang in mms_alias:
        target_lang = mms_alias[target_lang]

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


def _handle_piper(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    text_to_speech_piper_tts(message, output_path, language=language, speed=speed)


def _handle_aws_polly(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    aws_polly_text_to_wave(message, output_path)


def _handle_kokoro(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    text_to_speech_kokoro_tts(message, output_path, language=language, speed=speed)


def _handle_silero(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    text_to_speech_silero_tts(message, output_path, language=language, speed=speed)


TTS_DISPATCH_STRATEGIES: Dict[
    TTSEngine, Callable[[str, str, Optional[str], float], None]
] = {
    TTSEngine.GOOGLE_GTTS: _handle_google_gtts,
    TTSEngine.FACEBOOK_MMS: _handle_facebook_mms,
    TTSEngine.PIPER: _handle_piper,
    TTSEngine.AWS_POLLY: _handle_aws_polly,
    TTSEngine.KOKORO: _handle_kokoro,
    TTSEngine.SILERO: _handle_silero,
}


def generate_tts_audio(
    message: str,
    output_path: str,
    engine: TTSEngine = None,
    language: str = None,
    speed: float = 1.0,
) -> None:
    """
    Generate audio file using the specified TTS engine, language, and speed.
    Dynamically resolves engine based on requested language and installed weights.
    Falls back gracefully to default language if requested language model is missing.
    """
    engine = engine or resolve_engine_for_language(language)

    strategy = TTS_DISPATCH_STRATEGIES.get(engine)
    if not strategy:
        raise ValueError(f"Unsupported TTS engine: {engine}")

    strategy(message, output_path, language, speed)


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
    piper_alias = {"it": "it_IT", "en": "en_US"}
    if target_lang in piper_alias:
        target_lang = piper_alias[target_lang]

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

    raw_lang = language or SILERO_LANG
    silero_map = {
        "spa": "es", "e": "es", "eng": "en", "a": "en", "b": "en",
        "fra": "fr", "f": "fr", "deu": "de", "ita": "it", "i": "it"
    }
    target_lang = silero_map.get(raw_lang, raw_lang)
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

    speaker = SILERO_SPEAKER
    # Adjust speaker if language differs from default
    if target_lang != "en" and speaker.startswith("en_"):
        speaker = f"{target_lang}_0"

    cmd = [
        python_interpreter,
        silero_script,
        message,
        "--lang",
        target_lang,
        "--speaker",
        speaker,
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


def scan_installed_languages(base_models_dir: str = None) -> Dict[str, Any]:
    """
    Scans the pre-trained models directory for installed weights and configs
    across all supported engines, and returns both active engine language options
    and full installed model inventories.
    Comprehensive multi-engine support: compiles all installed offline languages
    into the top-level 'languages' array so the Web UI can display and select them.
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
        kokoro_seen: Set[str] = set()
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
            elif v.startswith("pf_") or v.startswith("pm_"):
                lang_code = "pt"
            elif v.startswith("bf_") or v.startswith("bm_"):
                lang_code = "en"

            norm = LANGUAGE_ALIASES.get(lang_code.lower(), lang_code.lower())
            if norm not in kokoro_seen:
                kokoro_seen.add(norm)
                active_langs.append({
                    "code": lang_code,
                    "voice": v,
                    "name": LANGUAGE_NAMES.get(lang_code, lang_code.capitalize()),
                    "ready": installed["kokoro_tts"]["ready"],
                })

        def_norm = LANGUAGE_ALIASES.get(default_lang.lower(), default_lang.lower())
        if default_lang not in [item["code"] for item in active_langs]:
            existing = next(
                (item for item in active_langs if LANGUAGE_ALIASES.get(item["code"].lower(), item["code"].lower()) == def_norm),
                None
            )
            if existing:
                existing["code"] = default_lang
            else:
                active_langs.insert(0, {
                    "code": default_lang,
                    "name": LANGUAGE_NAMES.get(default_lang, "Spanish"),
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
        item["flag"] = LANGUAGE_FLAGS.get(item["code"], "")

    # Compile comprehensive languages list including all other installed offline models
    all_languages: List[Dict[str, Any]] = list(active_langs)
    seen_normalized = {
        LANGUAGE_ALIASES.get(item["code"].lower(), item["code"].lower())
        for item in active_langs
    }
    seen_codes = {item["code"] for item in active_langs}

    # Add installed Silero models
    if TTS_ENGINE != TTSEngine.SILERO:
        for s in installed["silero_tts"]:
            c = s["code"]
            norm = LANGUAGE_ALIASES.get(c.lower(), c.lower())
            if norm not in seen_normalized and c not in seen_codes:
                all_languages.append({
                    "code": c,
                    "name": s["name"],
                    "engine": "silero_tts",
                    "ready": s.get("ready", True),
                    "is_default": False,
                    "flag": LANGUAGE_FLAGS.get(c, ""),
                })
                seen_normalized.add(norm)
                seen_codes.add(c)

    # Add installed Piper models
    if TTS_ENGINE != TTSEngine.PIPER:
        for p in installed["piper_tts"]:
            c = p["code"]
            norm = LANGUAGE_ALIASES.get(c.lower(), c.lower())
            if norm not in seen_normalized and c not in seen_codes:
                all_languages.append({
                    "code": c,
                    "name": p["name"],
                    "engine": "piper_tts",
                    "ready": p.get("ready", True),
                    "is_default": False,
                    "flag": LANGUAGE_FLAGS.get(c, ""),
                })
                seen_normalized.add(norm)
                seen_codes.add(c)

    # Add installed Facebook MMS models
    if TTS_ENGINE != TTSEngine.FACEBOOK_MMS:
        for f in installed["facebook_mms"]:
            c = f["code"]
            norm = LANGUAGE_ALIASES.get(c.lower(), c.lower())
            if norm not in seen_normalized and c not in seen_codes:
                all_languages.append({
                    "code": c,
                    "name": f["name"],
                    "engine": "facebook_mms",
                    "ready": f.get("ready", True),
                    "is_default": False,
                    "flag": LANGUAGE_FLAGS.get(c, ""),
                })
                seen_normalized.add(norm)
                seen_codes.add(c)

    # Add installed Kokoro voices if Kokoro is not active engine
    if TTS_ENGINE != TTSEngine.KOKORO and installed["kokoro_tts"]["ready"]:
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
            elif v.startswith("pf_") or v.startswith("pm_"):
                lang_code = "pt"
            elif v.startswith("bf_") or v.startswith("bm_"):
                lang_code = "en"
            norm = LANGUAGE_ALIASES.get(lang_code.lower(), lang_code.lower())
            if norm not in seen_normalized and lang_code not in seen_codes:
                all_languages.append({
                    "code": lang_code,
                    "voice": v,
                    "name": LANGUAGE_NAMES.get(lang_code, lang_code.capitalize()),
                    "engine": "kokoro_tts",
                    "ready": True,
                    "is_default": False,
                    "flag": LANGUAGE_FLAGS.get(lang_code, ""),
                })
                seen_normalized.add(norm)
                seen_codes.add(lang_code)

    return {
        "active_engine": engine_val,
        "default_language": default_lang,
        "languages": all_languages,
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
            voices_dir = os.path.join(model_dir, "voices")

            has_voices = (
                os.path.isdir(voices_dir)
                and len([f for f in os.listdir(voices_dir) if f.endswith(".pt")]) > 0
            )

            if not os.path.exists(model_path) or not os.path.exists(config_path) or not has_voices:
                logging.info(f"Kokoro TTS model or voices not fully present in {model_dir}. Downloading...")
                try:
                    from py_phone_caller_utils.py_phone_caller_voices.get_kokoro_tts_model import (
                        download_kokoro_model_async,
                    )
                    await download_kokoro_model_async(model_dir)
                except Exception as k_err:
                    logging.warning(f"Could not preload Kokoro TTS model/voices: {k_err}")
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
