"""
Model discovery and language capability scanner across TTS engines.
"""

import os
import sys
from typing import Any, Callable, Dict, List, Optional, Set

try:
    from .constants import (
        FACEBOOK_MMS_MODELS_FOLDER,
        KOKORO_LANG,
        KOKORO_MODEL_FILENAME,
        KOKORO_MODELS_FOLDER,
        PIPER_MODELS_FOLDER,
        PRE_TRAINED_MODELS_FOLDER,
        SILERO_MODELS_FOLDER,
    )
    from .enums import TTSEngine, TTS_ENGINE, _DEFAULT_LANG_MAP
    from .languages import (
        LANGUAGE_ALIASES,
        LANGUAGE_FLAGS,
        LANGUAGE_NAMES,
        _kokoro_voice_to_lang,
    )
except ImportError:
    from constants import (
        FACEBOOK_MMS_MODELS_FOLDER,
        KOKORO_LANG,
        KOKORO_MODEL_FILENAME,
        KOKORO_MODELS_FOLDER,
        PIPER_MODELS_FOLDER,
        PRE_TRAINED_MODELS_FOLDER,
        SILERO_MODELS_FOLDER,
    )
    from enums import TTSEngine, TTS_ENGINE, _DEFAULT_LANG_MAP
    from languages import (
        LANGUAGE_ALIASES,
        LANGUAGE_FLAGS,
        LANGUAGE_NAMES,
        _kokoro_voice_to_lang,
    )


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


def scan_installed_languages(base_models_dir: str = None) -> Dict[str, Any]:
    """
    Scans the pre-trained models directory for installed weights and configs
    across all supported engines, returning active language options and the
    complete multi-engine language inventory.
    """
    current_engine = _get_current_tts_engine()

    if base_models_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_models_dir = os.path.join(script_dir, PRE_TRAINED_MODELS_FOLDER)

    installed: Dict[str, Any] = {
        "facebook_mms": _scan_facebook_mms(base_models_dir),
        "piper_tts": _scan_piper(base_models_dir),
        "kokoro_tts": _scan_kokoro(base_models_dir),
        "silero_tts": _scan_silero(base_models_dir),
    }

    default_lang = _DEFAULT_LANG_MAP.get(current_engine, "")
    builder = _ACTIVE_LANG_BUILDERS.get(current_engine, _build_google_active_langs)
    active_langs = builder(installed, default_lang)

    for item in active_langs:
        item["engine"] = current_engine.value
        item["is_default"] = (item["code"] == default_lang)
        item["flag"] = LANGUAGE_FLAGS.get(item["code"], "")

    all_languages: List[Dict[str, Any]] = list(active_langs)
    seen_normalized = {
        LANGUAGE_ALIASES.get(item["code"].lower(), item["code"].lower())
        for item in active_langs
    }
    seen_codes = {item["code"] for item in active_langs}

    offline_engines = [
        (TTSEngine.SILERO, "silero_tts"),
        (TTSEngine.PIPER, "piper_tts"),
        (TTSEngine.FACEBOOK_MMS, "facebook_mms"),
    ]
    for eng_enum, eng_key in offline_engines:
        if current_engine == eng_enum:
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

    if current_engine != TTSEngine.KOKORO and installed["kokoro_tts"]["ready"]:
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
        "active_engine": current_engine.value,
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
    current_engine = _get_current_tts_engine()

    clean_lang = str(language).strip() if language else ""
    if not clean_lang or current_engine in (TTSEngine.GOOGLE_GTTS, TTSEngine.AWS_POLLY):
        return current_engine

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
                "z": "zf_xiaobei", "zh": "zf_xiaobei",
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
    if _supports(current_engine):
        return current_engine

    # 2. Check offline fallback candidates in priority order
    for candidate in (TTSEngine.SILERO, TTSEngine.PIPER, TTSEngine.FACEBOOK_MMS, TTSEngine.KOKORO):
        if _supports(candidate):
            return candidate

    return current_engine
