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
import pathlib
import site
import subprocess
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from aiohttp import web
from py_phone_caller_utils.config import settings
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
    CONFIG_TTS_ENGINE,
    FACEBOOK_MMS_LANGUAGE_CODE,
    FACEBOOK_MMS_MODELS_FOLDER,
    GENERATE_AUDIO_APP_ROUTE,
    GENERATE_AUDIO_ERROR,
    GENERATE_AUDIO_PORT,
    IS_AUDIO_READY_ENDPOINT,
    KOKORO_LANG,
    KOKORO_MODEL_FILENAME,
    KOKORO_MODELS_FOLDER,
    KOKORO_PYTHON_INTERPRETER,
    LANGUAGES_ENDPOINT,
    LOG_FORMATTER,
    LOG_LEVEL,
    PIPER_LANGUAGE_CODE,
    PIPER_MODELS_FOLDER,
    PIPER_PYTHON_INTERPRETER,
    PRE_TRAINED_MODELS_FOLDER,
    SERVING_AUDIO_FOLDER,
    SILERO_LANG,
    SILERO_MODELS_FOLDER,
    SILERO_PYTHON_INTERPRETER,
    SILERO_SAMPLE_RATE,
    SILERO_SPEAKER,
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

KOKORO_VOICE_PREFIX_TO_LANG: Dict[str, str] = {
    "ff": "fr",
    "ef": "es",
    "em": "es",
    "if": "it",
    "im": "it",
    "zf": "zh",
    "zm": "zh",
    "jf": "ja",
    "jm": "ja",
    "hf": "hi",
    "hm": "hi",
    "pf": "pt",
    "pm": "pt",
    "bf": "en",
    "bm": "en",
    "af": "en",
    "am": "en",
}


def _kokoro_voice_to_lang(voice_name: str) -> str:
    return KOKORO_VOICE_PREFIX_TO_LANG.get(voice_name[:2], "en")


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


def file_not_found_error(error_text, file_location):
    error_msg = f"{error_text}{file_location}"
    logging.error(error_msg)
    raise FileNotFoundError(error_msg)


def _find_voice_script(script_filename: str) -> str:
    """
    Discovers the path of an offline voice runner script using flat candidate checks.
    """
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    local_script = os.path.abspath(
        os.path.join(
            current_file_dir,
            "..",
            "py-phone-caller-utils",
            "py_phone_caller_utils",
            "py_phone_caller_voices",
            script_filename,
        )
    )
    if os.path.exists(local_script):
        return local_script

    module_name = f"py_phone_caller_utils.py_phone_caller_voices.{script_filename.replace('.py', '')}"
    spec = importlib.util.find_spec(module_name)
    if spec and spec.origin and os.path.exists(spec.origin):
        return spec.origin

    site_script = os.path.join(
        site.getsitepackages()[0],
        "py_phone_caller_utils",
        "py_phone_caller_voices",
        script_filename,
    )
    if os.path.exists(site_script):
        return site_script

    file_not_found_error(f"{script_filename} script not found at: ", local_script)


# =========================================================================
# MODEL DISCOVERY HELPERS
# =========================================================================

def _scan_facebook_mms(base_dir: str) -> List[Dict[str, Any]]:
    fb_dir = os.path.join(base_dir, FACEBOOK_MMS_MODELS_FOLDER)
    if not os.path.isdir(fb_dir):
        return []

    models = []
    for entry in sorted(os.listdir(fb_dir)):
        sub = os.path.join(fb_dir, entry)
        if not (os.path.isdir(sub) and entry.startswith("mms-tts-")):
            continue
        code = entry.replace("mms-tts-", "").strip()
        if os.path.exists(os.path.join(sub, "config.json")):
            models.append({
                "code": code,
                "name": LANGUAGE_NAMES.get(code, code.capitalize()),
                "model": entry,
                "ready": True,
            })
    return models


def _scan_piper(base_dir: str) -> List[Dict[str, Any]]:
    piper_dir = os.path.join(base_dir, PIPER_MODELS_FOLDER)
    if not os.path.isdir(piper_dir):
        return []

    models = []
    for entry in sorted(os.listdir(piper_dir)):
        sub = os.path.join(piper_dir, entry)
        if os.path.isdir(sub):
            onnx_file = os.path.join(sub, f"{entry}.onnx")
            if os.path.exists(onnx_file):
                models.append({
                    "code": entry,
                    "name": LANGUAGE_NAMES.get(entry, entry),
                    "model": f"{entry}.onnx",
                    "ready": True,
                })
        elif entry.endswith(".onnx"):
            code = entry[:-5]
            models.append({
                "code": code,
                "name": LANGUAGE_NAMES.get(code, code),
                "model": entry,
                "ready": True,
            })
    return models


def _scan_kokoro(base_dir: str) -> Dict[str, Any]:
    kokoro_dir = os.path.join(base_dir, KOKORO_MODELS_FOLDER)
    if not os.path.isdir(kokoro_dir):
        return {"ready": False, "voices": []}

    pth = os.path.join(kokoro_dir, KOKORO_MODEL_FILENAME)
    cfg = os.path.join(kokoro_dir, "config.json")
    is_ready = os.path.exists(pth) or os.path.exists(cfg)

    voices_dir = os.path.join(kokoro_dir, "voices")
    voices = (
        [v[:-3] for v in sorted(os.listdir(voices_dir)) if v.endswith(".pt")]
        if os.path.isdir(voices_dir)
        else []
    )
    return {
        "model": KOKORO_MODEL_FILENAME,
        "ready": is_ready,
        "voices": voices,
    }


def _scan_silero(base_dir: str) -> List[Dict[str, Any]]:
    silero_dir = os.path.join(base_dir, SILERO_MODELS_FOLDER)
    if not os.path.isdir(silero_dir):
        return []

    models = []
    for entry in sorted(os.listdir(silero_dir)):
        sub = os.path.join(silero_dir, entry)
        if os.path.isdir(sub):
            pt_files = [f for f in os.listdir(sub) if f.endswith(".pt")]
            if pt_files:
                models.append({
                    "code": entry,
                    "name": LANGUAGE_NAMES.get(entry, entry.capitalize()),
                    "model": pt_files[0],
                    "ready": True,
                })
        elif entry.endswith(".pt") and entry.startswith("v"):
            parts = entry[:-3].split("_")
            if len(parts) >= 2:
                code = parts[1]
                models.append({
                    "code": code,
                    "name": LANGUAGE_NAMES.get(code, code.capitalize()),
                    "model": entry,
                    "ready": True,
                })
    return models


# =========================================================================
# ACTIVE ENGINE LANGUAGE BUILDERS (Strategy Pattern)
# =========================================================================

def _build_mms_active_langs(installed: Dict[str, Any], default_lang: str) -> List[Dict[str, Any]]:
    langs = list(installed["facebook_mms"])
    if not any(item["code"] == default_lang for item in langs):
        langs.insert(0, {
            "code": default_lang,
            "name": LANGUAGE_NAMES.get(default_lang, default_lang.capitalize()),
            "model": f"mms-tts-{default_lang}",
            "ready": True,
        })
    return langs


def _build_piper_active_langs(installed: Dict[str, Any], default_lang: str) -> List[Dict[str, Any]]:
    langs = list(installed["piper_tts"])
    if not any(item["code"] == default_lang for item in langs):
        langs.insert(0, {
            "code": default_lang,
            "name": LANGUAGE_NAMES.get(default_lang, default_lang),
            "model": f"{default_lang}.onnx",
            "ready": True,
        })
    return langs


def _build_kokoro_active_langs(installed: Dict[str, Any], default_lang: str) -> List[Dict[str, Any]]:
    langs = []
    seen = set()
    for v in installed["kokoro_tts"]["voices"]:
        lang_code = _kokoro_voice_to_lang(v)
        norm = LANGUAGE_ALIASES.get(lang_code.lower(), lang_code.lower())
        if norm not in seen:
            seen.add(norm)
            langs.append({
                "code": lang_code,
                "voice": v,
                "name": LANGUAGE_NAMES.get(lang_code, lang_code.capitalize()),
                "ready": installed["kokoro_tts"]["ready"],
            })

    def_norm = LANGUAGE_ALIASES.get(default_lang.lower(), default_lang.lower())
    if default_lang not in [item["code"] for item in langs]:
        existing = next(
            (item for item in langs if LANGUAGE_ALIASES.get(item["code"].lower(), item["code"].lower()) == def_norm),
            None,
        )
        if existing:
            existing["code"] = default_lang
        else:
            langs.insert(0, {
                "code": default_lang,
                "name": LANGUAGE_NAMES.get(default_lang, "Spanish"),
                "ready": installed["kokoro_tts"]["ready"],
            })
    return langs


def _build_silero_active_langs(installed: Dict[str, Any], default_lang: str) -> List[Dict[str, Any]]:
    langs = list(installed["silero_tts"])
    if not any(item["code"] == default_lang for item in langs):
        langs.insert(0, {
            "code": default_lang,
            "name": LANGUAGE_NAMES.get(default_lang, default_lang.capitalize()),
            "model": f"v3_{default_lang}.pt",
            "ready": True,
        })
    return langs


def _build_google_active_langs(installed: Dict[str, Any], default_lang: str) -> List[Dict[str, Any]]:
    return [
        {"code": c, "name": LANGUAGE_NAMES.get(c, c.capitalize()), "ready": True}
        for c in ["en", "es", "it", "fr", "de", "ru", "zh", "hi", "he", "ar"]
    ]


def _build_polly_active_langs(installed: Dict[str, Any], default_lang: str) -> List[Dict[str, Any]]:
    return [
        {"code": c, "name": LANGUAGE_NAMES.get(c, c), "ready": True}
        for c in ["en-US", "es-ES", "it-IT", "fr-FR", "de-DE", "ru-RU", "cmn-CN", "hi-IN", "he-IL", "arb"]
    ]


_ACTIVE_LANG_BUILDERS: Dict[TTSEngine, Callable[[Dict[str, Any], str], List[Dict[str, Any]]]] = {
    TTSEngine.FACEBOOK_MMS: _build_mms_active_langs,
    TTSEngine.PIPER: _build_piper_active_langs,
    TTSEngine.KOKORO: _build_kokoro_active_langs,
    TTSEngine.SILERO: _build_silero_active_langs,
    TTSEngine.GOOGLE_GTTS: _build_google_active_langs,
    TTSEngine.AWS_POLLY: _build_polly_active_langs,
}

_DEFAULT_LANG_MAP: Dict[TTSEngine, str] = {
    TTSEngine.FACEBOOK_MMS: FACEBOOK_MMS_LANGUAGE_CODE,
    TTSEngine.PIPER: PIPER_LANGUAGE_CODE,
    TTSEngine.KOKORO: KOKORO_LANG,
    TTSEngine.SILERO: SILERO_LANG,
    TTSEngine.GOOGLE_GTTS: "en",
    TTSEngine.AWS_POLLY: "en-US",
}


def scan_installed_languages(base_models_dir: str = None) -> Dict[str, Any]:
    """
    Scans the pre-trained models directory for installed weights and configs
    across all supported engines, returning active language options and the
    complete multi-engine language inventory.
    """
    if base_models_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_models_dir = os.path.join(script_dir, PRE_TRAINED_MODELS_FOLDER)

    installed: Dict[str, Any] = {
        "facebook_mms": _scan_facebook_mms(base_models_dir),
        "piper_tts": _scan_piper(base_models_dir),
        "kokoro_tts": _scan_kokoro(base_models_dir),
        "silero_tts": _scan_silero(base_models_dir),
    }

    default_lang = _DEFAULT_LANG_MAP.get(TTS_ENGINE, "")
    builder = _ACTIVE_LANG_BUILDERS.get(TTS_ENGINE, _build_google_active_langs)
    active_langs = builder(installed, default_lang)

    for item in active_langs:
        item["engine"] = TTS_ENGINE.value
        item["is_default"] = (item["code"] == default_lang)
        item["flag"] = LANGUAGE_FLAGS.get(item["code"], "")

    all_languages: List[Dict[str, Any]] = list(active_langs)
    seen_normalized = {
        LANGUAGE_ALIASES.get(item["code"].lower(), item["code"].lower())
        for item in active_langs
    }
    seen_codes = {item["code"] for item in active_langs}

    # Add installed models from other offline engines if not already present
    offline_engines = [
        (TTSEngine.SILERO, "silero_tts"),
        (TTSEngine.PIPER, "piper_tts"),
        (TTSEngine.FACEBOOK_MMS, "facebook_mms"),
    ]
    for eng_enum, eng_key in offline_engines:
        if TTS_ENGINE == eng_enum:
            continue
        for m in installed[eng_key]:
            c = m["code"]
            norm = LANGUAGE_ALIASES.get(c.lower(), c.lower())
            if norm not in seen_normalized and c not in seen_codes:
                all_languages.append({
                    "code": c,
                    "name": m["name"],
                    "engine": eng_key,
                    "ready": m.get("ready", True),
                    "is_default": False,
                    "flag": LANGUAGE_FLAGS.get(c, ""),
                })
                seen_normalized.add(norm)
                seen_codes.add(c)

    if TTS_ENGINE != TTSEngine.KOKORO and installed["kokoro_tts"]["ready"]:
        for v in installed["kokoro_tts"]["voices"]:
            lang_code = _kokoro_voice_to_lang(v)
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
        "active_engine": TTS_ENGINE.value,
        "default_language": default_lang,
        "languages": all_languages,
        "installed_models": installed,
    }


def resolve_engine_for_language(
    language: str = None, base_models_dir: str = None
) -> TTSEngine:
    """
    Resolves the best TTS engine for a requested language code.
    If no language is requested, or if the active TTS_ENGINE supports the requested
    language, returns TTS_ENGINE. Otherwise, checks if another installed offline
    engine has weights for this language.
    """
    clean_lang = str(language).strip() if language else ""
    if not clean_lang or TTS_ENGINE in (TTSEngine.GOOGLE_GTTS, TTSEngine.AWS_POLLY):
        return TTS_ENGINE

    installed = scan_installed_languages(base_models_dir)["installed_models"]
    norm = LANGUAGE_ALIASES.get(clean_lang.lower(), clean_lang.lower())

    def _supports(eng: TTSEngine) -> bool:
        if eng == TTSEngine.KOKORO:
            kokoro_def = KOKORO_LANG.lower()
            if clean_lang == KOKORO_LANG or norm == LANGUAGE_ALIASES.get(kokoro_def, kokoro_def):
                return True
            voice_map = {
                "a": "af_heart", "en": "af_heart", "b": "bf_emma",
                "e": "ef_dora", "es": "ef_dora", "f": "ff_siwis", "fr": "ff_siwis",
                "h": "hf_alpha", "hi": "hf_alpha", "i": "if_sara", "it": "if_sara",
                "j": "jf_alpha", "ja": "jf_alpha", "p": "pf_dora", "pt": "pf_dora",
                "z": "zf_xiaobei", "zh": "zf_xiaobei"
            }
            target_v = voice_map.get(clean_lang) or voice_map.get(norm)
            if target_v and target_v in installed["kokoro_tts"].get("voices", []):
                return True
            return any(
                _kokoro_voice_to_lang(v) in (clean_lang, norm)
                for v in installed["kokoro_tts"].get("voices", [])
            )
        key = eng.value
        return any(
            m["code"] == clean_lang or LANGUAGE_ALIASES.get(m["code"].lower(), m["code"].lower()) == norm
            for m in installed.get(key, [])
        )

    # 1. Prefer active engine if it supports the requested language
    if _supports(TTS_ENGINE):
        return TTS_ENGINE

    # 2. Check offline fallback candidates in priority order
    for candidate in (TTSEngine.SILERO, TTSEngine.PIPER, TTSEngine.FACEBOOK_MMS, TTSEngine.KOKORO):
        if _supports(candidate):
            return candidate

    return TTS_ENGINE


# =========================================================================
# TTS ENGINE STRATEGY DISPATCH PATTERN
# =========================================================================

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
        "es": "spa", "e": "spa", "en": "eng", "a": "eng",
        "it": "ita", "i": "ita", "fr": "fra", "f": "fra", "de": "deu",
    }
    target_lang = mms_alias.get(target_lang, target_lang)

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


# =========================================================================
# OFFLINE TTS CLI SUBPROCESS RUNNERS
# =========================================================================

def text_to_speech_piper_tts(
    message: str, output_path: str, language: str = None, speed: float = 1.0
):
    piper_script = _find_voice_script("piper_tts.py")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_lang = language or PIPER_LANGUAGE_CODE
    piper_alias = {"it": "it_IT", "en": "en_US"}
    target_lang = piper_alias.get(target_lang, target_lang)

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
        PIPER_PYTHON_INTERPRETER,
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
        error_msg = f"Piper TTS process failed with exit code {e.returncode}: {e.stderr}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e
    except Exception as e:
        error_msg = f"Error running Piper TTS: {str(e)}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e


def text_to_speech_kokoro_tts(
    message: str, output_path: str, language: str = None, speed: float = 1.0
):
    kokoro_script = _find_voice_script("kokoro_tts.py")
    current_file_dir = os.path.dirname(os.path.abspath(__file__))

    voice_name_map = {
        "a": "af_heart", "b": "bf_emma", "e": "ef_dora", "f": "ff_siwis",
        "h": "hf_alpha", "i": "if_sara", "j": "jf_alpha", "p": "pf_dora", "z": "zf_xiaobei",
        "en": "af_heart", "es": "ef_dora", "fr": "ff_siwis", "hi": "hf_alpha",
        "it": "if_sara", "ja": "jf_alpha", "pt": "pf_dora", "zh": "zf_xiaobei",
    }

    target_lang = language or KOKORO_LANG
    if target_lang not in voice_name_map and target_lang != KOKORO_LANG:
        logging.warning(
            f"Kokoro language code '{target_lang}' unknown. Falling back to default '{KOKORO_LANG}'"
        )
        target_lang = KOKORO_LANG

    voice_name = voice_name_map.get(target_lang, "af_heart")
    local_model_dir = os.path.join(
        current_file_dir, PRE_TRAINED_MODELS_FOLDER, KOKORO_MODELS_FOLDER
    )

    kokoro_lang_reverse = {"en": "a", "es": "e", "fr": "f", "hi": "h", "it": "i", "ja": "j", "pt": "p", "zh": "z"}
    kokoro_cli_lang = kokoro_lang_reverse.get(target_lang, target_lang)

    cmd = [
        KOKORO_PYTHON_INTERPRETER,
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
        error_msg = f"Kokoro TTS process failed with exit code {e.returncode}: {e.stderr}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e
    except Exception as e:
        error_msg = f"Error running Kokoro TTS: {str(e)}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e


def text_to_speech_silero_tts(
    message: str, output_path: str, language: str = None, speed: float = 1.0
):
    silero_script = _find_voice_script("silero_tts.py")
    current_file_dir = os.path.dirname(os.path.abspath(__file__))

    raw_lang = language or SILERO_LANG
    silero_map = {
        "spa": "es", "e": "es", "eng": "en", "a": "en", "b": "en",
        "fra": "fr", "f": "fr", "deu": "de", "ita": "it", "i": "it",
    }
    target_lang = silero_map.get(raw_lang, raw_lang)
    supported_langs = ["en", "ru", "de", "es", "fr", "indic"]
    if target_lang not in supported_langs and target_lang != SILERO_LANG:
        logging.warning(
            f"Silero language '{target_lang}' not directly supported. Falling back to '{SILERO_LANG}'"
        )
        target_lang = SILERO_LANG

    local_models_base = os.path.join(
        current_file_dir, PRE_TRAINED_MODELS_FOLDER, SILERO_MODELS_FOLDER
    )

    speaker = SILERO_SPEAKER
    if target_lang != "en" and speaker.startswith("en_"):
        speaker = f"{target_lang}_0"

    cmd = [
        SILERO_PYTHON_INTERPRETER,
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
        error_msg = f"Silero TTS process failed with exit code {e.returncode}: {e.stderr}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e
    except Exception as e:
        error_msg = f"Error running Silero TTS: {str(e)}"
        logging.error(error_msg)
        raise RuntimeError(error_msg) from e


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


# =========================================================================
# MODEL PRELOADING STRATEGIES
# =========================================================================

async def _ensure_facebook_mms_models(base_dir: str, preload_cfg: Dict[str, Any]) -> None:
    from py_phone_caller_utils.py_phone_caller_voices.get_fb_mms_language_model import (
        download_mms_model_async,
    )
    mms_langs = preload_cfg.get("facebook_mms", [FACEBOOK_MMS_LANGUAGE_CODE])
    if FACEBOOK_MMS_LANGUAGE_CODE not in mms_langs:
        mms_langs.append(FACEBOOK_MMS_LANGUAGE_CODE)

    for lang in mms_langs:
        model_name = f"mms-tts-{lang}"
        model_dir = os.path.join(base_dir, FACEBOOK_MMS_MODELS_FOLDER, model_name)
        if not os.path.exists(os.path.join(model_dir, "config.json")):
            try:
                logging.info(f"Facebook MMS model for '{lang}' not found. Downloading...")
                await download_mms_model_async(
                    lang, os.path.join(base_dir, FACEBOOK_MMS_MODELS_FOLDER)
                )
            except Exception as dl_err:
                logging.warning(f"Could not preload Facebook MMS model '{lang}': {dl_err}")
        else:
            logging.info(f"Facebook MMS model for '{lang}' is present at {model_dir}")


async def _ensure_piper_models(base_dir: str, preload_cfg: Dict[str, Any]) -> None:
    from py_phone_caller_utils.py_phone_caller_voices.get_pipper_tts_language_model import (
        download_piper_model_async,
    )
    piper_langs = preload_cfg.get("piper_tts", [PIPER_LANGUAGE_CODE])
    if PIPER_LANGUAGE_CODE not in piper_langs:
        piper_langs.append(PIPER_LANGUAGE_CODE)

    for lang in piper_langs:
        model_dir = os.path.join(base_dir, PIPER_MODELS_FOLDER, lang)
        model_path = os.path.join(model_dir, f"{lang}.onnx")
        config_path = os.path.join(model_dir, f"{lang}.onnx.json")
        if not os.path.exists(model_path) or not os.path.exists(config_path):
            logging.info(f"Piper TTS model for '{lang}' not found. Downloading...")
            await download_piper_model_async(lang, base_dir)
        else:
            logging.info(f"Piper TTS model for '{lang}' is present at {model_path}")


async def _ensure_kokoro_models(base_dir: str, preload_cfg: Dict[str, Any]) -> None:
    model_dir = os.path.join(base_dir, KOKORO_MODELS_FOLDER)
    model_path = os.path.join(model_dir, KOKORO_MODEL_FILENAME)
    config_path = os.path.join(model_dir, "config.json")
    voices_dir = os.path.join(model_dir, "voices")

    has_voices = os.path.isdir(voices_dir) and any(f.endswith(".pt") for f in os.listdir(voices_dir))
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


async def _ensure_silero_models(base_dir: str, preload_cfg: Dict[str, Any]) -> None:
    from py_phone_caller_utils.py_phone_caller_voices.get_silero_tts_model import (
        MODEL_FILENAMES,
        download_silero_model_async,
    )
    silero_langs = preload_cfg.get("silero_tts", [SILERO_LANG])
    if SILERO_LANG not in silero_langs:
        silero_langs.append(SILERO_LANG)

    for lang in silero_langs:
        expected_fn = MODEL_FILENAMES.get(lang, f"v3_{lang}.pt")
        model_dir = os.path.join(base_dir, SILERO_MODELS_FOLDER, lang)
        model_path = os.path.join(model_dir, expected_fn)
        direct_path = os.path.join(base_dir, SILERO_MODELS_FOLDER, expected_fn)

        if not os.path.exists(model_path) and not os.path.exists(direct_path):
            try:
                logging.info(f"Silero TTS model for '{lang}' not found. Downloading...")
                await download_silero_model_async(lang, base_dir)
            except Exception as dl_err:
                logging.warning(f"Could not preload Silero TTS model '{lang}': {dl_err}")
        else:
            actual = model_path if os.path.exists(model_path) else direct_path
            logging.info(f"Silero TTS model for '{lang}' is present at {actual}")
    logging.info("Silero TTS model check completed.")


_PRELOAD_STRATEGIES: Dict[TTSEngine, Callable[[str, Dict[str, Any]], Awaitable[None]]] = {
    TTSEngine.FACEBOOK_MMS: _ensure_facebook_mms_models,
    TTSEngine.PIPER: _ensure_piper_models,
    TTSEngine.KOKORO: _ensure_kokoro_models,
    TTSEngine.SILERO: _ensure_silero_models,
}


async def ensure_models_present():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    abs_pre_trained_models = os.path.join(script_dir, PRE_TRAINED_MODELS_FOLDER)
    preload_cfg = settings.get("generate_audio", {}).get("preload", {})

    preloader = _PRELOAD_STRATEGIES.get(TTS_ENGINE)
    if preloader:
        try:
            await preloader(abs_pre_trained_models, preload_cfg)
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
