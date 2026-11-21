"""
Runners for offline TTS engines (Piper, Kokoro, Silero).

Executes synthesis in-process by default so ONNX/PyTorch models stay warm in RAM
across requests, while preserving transparent subprocess fallback when a distinct
Python interpreter is configured or ``PPC_TTS_SUBPROCESS=1`` is set.
"""

import importlib.util
import logging
import os
import site
import subprocess
import sys

try:
    from .constants import (
        KOKORO_LANG,
        KOKORO_MODELS_FOLDER,
        KOKORO_PYTHON_INTERPRETER,
        NUM_OF_CPUS,
        PIPER_LANGUAGE_CODE,
        PIPER_MODELS_FOLDER,
        PIPER_PYTHON_INTERPRETER,
        PRE_TRAINED_MODELS_FOLDER,
        SILERO_LANG,
        SILERO_MODELS_FOLDER,
        SILERO_PYTHON_INTERPRETER,
        SILERO_SAMPLE_RATE,
        SILERO_SPEAKER,
    )
except ImportError:
    from constants import (
        KOKORO_LANG,
        KOKORO_MODELS_FOLDER,
        KOKORO_PYTHON_INTERPRETER,
        NUM_OF_CPUS,
        PIPER_LANGUAGE_CODE,
        PIPER_MODELS_FOLDER,
        PIPER_PYTHON_INTERPRETER,
        PRE_TRAINED_MODELS_FOLDER,
        SILERO_LANG,
        SILERO_MODELS_FOLDER,
        SILERO_PYTHON_INTERPRETER,
        SILERO_SAMPLE_RATE,
        SILERO_SPEAKER,
    )

_TORCH_THREADS_CONFIGURED = False

_SILERO_DEFAULT_SPEAKERS = {
    "en": "en_0",
    "ru": "kseniya",
    "de": "eva_k",
    "es": "es_0",
    "fr": "fr_0",
    "indic": "hindi_female",
}


def _configure_torch_threads() -> None:
    """Applies configured NUM_OF_CPUS to PyTorch intra-op thread pool once per process."""
    global _TORCH_THREADS_CONFIGURED
    if _TORCH_THREADS_CONFIGURED:
        return
    try:
        num_cpus = int(NUM_OF_CPUS)
        if num_cpus > 0:
            import torch

            torch.set_num_threads(num_cpus)
            logging.info(f"Configured PyTorch intra-op threads to {num_cpus}")
    except Exception as exc:
        logging.debug(f"Skipping PyTorch thread tuning: {exc}")
    finally:
        _TORCH_THREADS_CONFIGURED = True


def _use_in_process(interpreter: str) -> bool:
    """Returns True when the engine can run in-process with cached weights."""
    if os.environ.get("PPC_TTS_SUBPROCESS", "").strip().lower() in ("1", "true", "yes"):
        return False
    if not interpreter:
        return True
    try:
        return os.path.realpath(interpreter) == os.path.realpath(sys.executable)
    except OSError:
        return interpreter == sys.executable


def file_not_found_error(error_text: str, file_location: str) -> None:
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


def text_to_speech_piper_tts(
    message: str, output_path: str, language: str = None, speed: float = 1.0
):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    target_lang = language or PIPER_LANGUAGE_CODE
    piper_alias = {
        "it": "it_IT",
        "en": "en_US",
        "es": "es_ES",
        "fr": "fr_FR",
        "de": "de_DE",
        "nl": "nl_NL",
    }
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

    if _use_in_process(PIPER_PYTHON_INTERPRETER):
        try:
            from py_phone_caller_utils.py_phone_caller_voices.piper_tts import (
                text_to_speech_piper,
            )

            logging.info(f"Running Piper TTS in-process for lang={target_lang} -> {output_path}")
            text_to_speech_piper(
                text=message,
                model_path=model_path,
                config_path=config_path,
                output_path=output_path,
                speed=speed,
            )
            logging.info(f"Piper TTS completed successfully for output: {output_path}")
            return
        except Exception as e:
            error_msg = f"Error running Piper TTS in-process: {str(e)}"
            logging.error(error_msg)
            raise RuntimeError(error_msg) from e

    piper_script = _find_voice_script("piper_tts.py")
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
    current_file_dir = os.path.dirname(os.path.abspath(__file__))

    voice_name_map = {
        "a": "af_heart", "b": "bf_emma", "e": "ef_dora", "f": "ff_siwis",
        "h": "hf_alpha", "i": "if_sara", "j": "jf_alpha", "p": "pf_dora", "z": "zf_xiaobei",
        "en": "af_heart", "es": "ef_dora", "fr": "ff_siwis", "hi": "hf_alpha",
        "it": "if_sara", "ja": "jf_alpha", "pt": "pf_dora", "zh": "zf_xiaobei",
        "spa": "ef_dora", "eng": "af_heart", "fra": "ff_siwis", "ita": "if_sara",
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

    kokoro_lang_reverse = {
        "en": "a", "es": "e", "fr": "f", "hi": "h", "it": "i", "ja": "j", "pt": "p", "zh": "z",
        "eng": "a", "spa": "e", "fra": "f", "ita": "i",
    }
    kokoro_cli_lang = kokoro_lang_reverse.get(target_lang, target_lang)

    if _use_in_process(KOKORO_PYTHON_INTERPRETER):
        try:
            _configure_torch_threads()
            from py_phone_caller_utils.py_phone_caller_voices.kokoro_tts import (
                text_to_speech_kokoro,
            )

            logging.info(
                f"Running Kokoro TTS in-process for lang={kokoro_cli_lang}, voice={voice_name} -> {output_path}"
            )
            text_to_speech_kokoro(
                text=message,
                output_path=output_path,
                voice_name=voice_name,
                lang=kokoro_cli_lang,
                speed=speed,
                model_path=local_model_dir if os.path.exists(local_model_dir) else None,
            )
            logging.info(f"Kokoro TTS completed successfully for output: {output_path}")
            return
        except Exception as e:
            error_msg = f"Error running Kokoro TTS in-process: {str(e)}"
            logging.error(error_msg)
            raise RuntimeError(error_msg) from e

    kokoro_script = _find_voice_script("kokoro_tts.py")
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
        speaker = _SILERO_DEFAULT_SPEAKERS.get(target_lang, f"{target_lang}_0")

    if _use_in_process(SILERO_PYTHON_INTERPRETER):
        try:
            _configure_torch_threads()
            from py_phone_caller_utils.py_phone_caller_voices.silero_tts import (
                text_to_speech_silero,
            )

            logging.info(
                f"Running Silero TTS in-process for lang={target_lang}, speaker={speaker} -> {output_path}"
            )
            text_to_speech_silero(
                message=message,
                output_path=output_path,
                lang=target_lang,
                speaker=speaker,
                sample_rate=SILERO_SAMPLE_RATE,
                speed=speed,
                model_path=local_models_base if os.path.exists(local_models_base) else None,
            )
            logging.info(f"Silero TTS completed successfully for output: {output_path}")
            return
        except Exception as e:
            error_msg = f"Error running Silero TTS in-process: {str(e)}"
            logging.error(error_msg)
            raise RuntimeError(error_msg) from e

    silero_script = _find_voice_script("silero_tts.py")
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
