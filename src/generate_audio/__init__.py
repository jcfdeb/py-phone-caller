"""
Generate Audio service package.
"""

from .constants import *
from .enums import TTSEngine, TTS_ENGINE
from .languages import LANGUAGE_NAMES, LANGUAGE_FLAGS, LANGUAGE_ALIASES
from .runners import (
    text_to_speech_piper_tts,
    text_to_speech_kokoro_tts,
    text_to_speech_silero_tts,
)
from .discovery import scan_installed_languages, resolve_engine_for_language
from .strategies import generate_tts_audio, TTS_DISPATCH_STRATEGIES
from .generate_audio import init_app, resolve_audio_filename, wave_file_exists

__all__ = [
    "TTSEngine",
    "TTS_ENGINE",
    "LANGUAGE_NAMES",
    "LANGUAGE_FLAGS",
    "LANGUAGE_ALIASES",
    "text_to_speech_piper_tts",
    "text_to_speech_kokoro_tts",
    "text_to_speech_silero_tts",
    "scan_installed_languages",
    "resolve_engine_for_language",
    "generate_tts_audio",
    "TTS_DISPATCH_STRATEGIES",
    "init_app",
    "resolve_audio_filename",
    "wave_file_exists",
]
