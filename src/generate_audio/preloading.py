"""
Pre-trained model verification and automatic downloader on service startup.
"""

import logging
import os
import sys
from typing import Any, Awaitable, Callable, Dict

from py_phone_caller_utils.config import settings

try:
    from .constants import (
        FACEBOOK_MMS_LANGUAGE_CODE,
        FACEBOOK_MMS_MODELS_FOLDER,
        KOKORO_MODEL_FILENAME,
        KOKORO_MODELS_FOLDER,
        PIPER_LANGUAGE_CODE,
        PIPER_MODELS_FOLDER,
        PRE_TRAINED_MODELS_FOLDER,
        SILERO_LANG,
        SILERO_MODELS_FOLDER,
    )
    from .enums import TTSEngine, TTS_ENGINE
except ImportError:
    from constants import (
        FACEBOOK_MMS_LANGUAGE_CODE,
        FACEBOOK_MMS_MODELS_FOLDER,
        KOKORO_MODEL_FILENAME,
        KOKORO_MODELS_FOLDER,
        PIPER_LANGUAGE_CODE,
        PIPER_MODELS_FOLDER,
        PRE_TRAINED_MODELS_FOLDER,
        SILERO_LANG,
        SILERO_MODELS_FOLDER,
    )
    from enums import TTSEngine, TTS_ENGINE


def _get_current_tts_engine() -> TTSEngine:
    for mod_name in (
        "src.generate_audio.generate_audio",
        "generate_audio.generate_audio",
        "generate_audio",
    ):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "TTS_ENGINE"):
            return getattr(mod, "TTS_ENGINE")
    return TTS_ENGINE


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

    current_engine = _get_current_tts_engine()
    preloader = _PRELOAD_STRATEGIES.get(current_engine)
    if preloader:
        try:
            await preloader(abs_pre_trained_models, preload_cfg)
        except Exception as e:
            logging.error(f"Failed to ensure models are present: {e}")
