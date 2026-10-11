"""
TTS Engine dispatch strategies and execution coordinator.
"""

import logging
import os
import sys
from typing import Callable, Dict, Optional

from py_phone_caller_utils.py_phone_caller_voices.aws_polly import (
    aws_polly_text_to_wave,
)
from py_phone_caller_utils.py_phone_caller_voices.facebook_mms import (
    text_to_speech_facebook_mms,
)
from py_phone_caller_utils.py_phone_caller_voices.google_gtts import create_audio_file

try:
    from .constants import (
        FACEBOOK_MMS_LANGUAGE_CODE,
        FACEBOOK_MMS_MODELS_FOLDER,
        PRE_TRAINED_MODELS_FOLDER,
    )
    from .discovery import resolve_engine_for_language
    from .enums import TTSEngine
    from .runners import (
        text_to_speech_kokoro_tts,
        text_to_speech_piper_tts,
        text_to_speech_silero_tts,
    )
except ImportError:
    from constants import (
        FACEBOOK_MMS_LANGUAGE_CODE,
        FACEBOOK_MMS_MODELS_FOLDER,
        PRE_TRAINED_MODELS_FOLDER,
    )
    from discovery import resolve_engine_for_language
    from enums import TTSEngine
    from runners import (
        text_to_speech_kokoro_tts,
        text_to_speech_piper_tts,
        text_to_speech_silero_tts,
    )


def _get_target_callable(name: str, fallback: Callable) -> Callable:
    for mod_name in (
        "src.generate_audio.generate_audio",
        "generate_audio.generate_audio",
        "generate_audio",
    ):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, name):
            return getattr(mod, name)
    return fallback


def _handle_google_gtts(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    msg_chk_sum = os.path.basename(output_path).replace(".wav", "")
    fn = _get_target_callable("create_audio_file", create_audio_file)
    fn(message, msg_chk_sum)


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
    fn = _get_target_callable("text_to_speech_facebook_mms", text_to_speech_facebook_mms)
    fn(
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
    fn = _get_target_callable("text_to_speech_piper_tts", text_to_speech_piper_tts)
    fn(message, output_path, language=language, speed=speed)


def _handle_aws_polly(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    fn = _get_target_callable("aws_polly_text_to_wave", aws_polly_text_to_wave)
    fn(message, output_path)


def _handle_kokoro(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    fn = _get_target_callable("text_to_speech_kokoro_tts", text_to_speech_kokoro_tts)
    fn(message, output_path, language=language, speed=speed)


def _handle_silero(
    message: str,
    output_path: str,
    language: Optional[str] = None,
    speed: float = 1.0,
) -> None:
    fn = _get_target_callable("text_to_speech_silero_tts", text_to_speech_silero_tts)
    fn(message, output_path, language=language, speed=speed)


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
    resolver = _get_target_callable("resolve_engine_for_language", resolve_engine_for_language)
    engine = engine or resolver(language)

    strategy = TTS_DISPATCH_STRATEGIES.get(engine)
    if not strategy:
        raise ValueError(f"Unsupported TTS engine: {engine}")

    strategy(message, output_path, language, speed)
