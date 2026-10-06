"""
TTS Engine enumerations and configuration resolution.
"""

from enum import Enum
import logging
from typing import Dict

try:
    from .constants import (
        CONFIG_TTS_ENGINE,
        FACEBOOK_MMS_LANGUAGE_CODE,
        KOKORO_LANG,
        PIPER_LANGUAGE_CODE,
        SILERO_LANG,
    )
except ImportError:
    from constants import (
        CONFIG_TTS_ENGINE,
        FACEBOOK_MMS_LANGUAGE_CODE,
        KOKORO_LANG,
        PIPER_LANGUAGE_CODE,
        SILERO_LANG,
    )


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


_DEFAULT_LANG_MAP: Dict[TTSEngine, str] = {
    TTSEngine.FACEBOOK_MMS: FACEBOOK_MMS_LANGUAGE_CODE,
    TTSEngine.PIPER: PIPER_LANGUAGE_CODE,
    TTSEngine.KOKORO: KOKORO_LANG,
    TTSEngine.SILERO: SILERO_LANG,
    TTSEngine.GOOGLE_GTTS: "en",
    TTSEngine.AWS_POLLY: "en-US",
}
