import argparse
import importlib.util
import logging
import os
import sys
import threading
import numpy as np
import soundfile as sf
import scipy.signal
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kokoro")

try:
    from kokoro import KPipeline, KModel
except ImportError:
    KPipeline = None
    KModel = None

_KOKORO_CACHE_LOCK = threading.Lock()
_KOKORO_MODEL_CACHE: dict[tuple[str, str], object] = {}
_KOKORO_PIPELINE_CACHE: dict[tuple[str, str], object] = {}


def resolve_kokoro_model_dir(model_path: str = None) -> str:
    """
    Resolves the filesystem directory containing Kokoro TTS model files (config.json, weights, voices).
    """
    if model_path:
        p = os.path.abspath(model_path)
        if os.path.isdir(p) and (
            os.path.exists(os.path.join(p, "config.json"))
            or os.path.exists(os.path.join(p, "kokoro-v1_0.pth"))
        ):
            return p
        if os.path.isfile(p):
            return os.path.dirname(p)

    candidates = []

    # 1. Candidate relative to generate_audio package location
    try:
        spec = importlib.util.find_spec("generate_audio")
        if spec and spec.submodule_search_locations:
            for pkg_dir in spec.submodule_search_locations:
                candidates.append(
                    os.path.join(pkg_dir, "pre_trained_models", "kokoro_tts")
                )
    except Exception:
        pass

    # 2. Candidate relative to this file's repository location
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(
        os.path.join(
            current_file_dir,
            "..",
            "..",
            "..",
            "generate_audio",
            "pre_trained_models",
            "kokoro_tts",
        )
    )

    # 3. Candidates relative to current working directory
    candidates.append(
        os.path.join(
            os.getcwd(), "py-phone-caller", "generate_audio", "pre_trained_models", "kokoro_tts"
        )
    )
    candidates.append(
        os.path.join(
            os.getcwd(), "src", "generate_audio", "pre_trained_models", "kokoro_tts"
        )
    )
    candidates.append(
        os.path.join(os.getcwd(), "pre_trained_models", "kokoro_tts")
    )

    # 4. Standard container paths
    candidates.append("/app/py-phone-caller/generate_audio/pre_trained_models/kokoro_tts")
    candidates.append("/app/pre_trained_models/kokoro_tts")

    for cand in candidates:
        cand_path = os.path.abspath(cand)
        if os.path.isdir(cand_path) and (
            os.path.exists(os.path.join(cand_path, "config.json"))
            or os.path.exists(os.path.join(cand_path, "kokoro-v1_0.pth"))
        ):
            return cand_path

    return None


def _get_kokoro_pipeline(lang: str, local_model_dir: str | None):
    """Load and cache Kokoro KModel (shared across all languages) and KPipeline per language."""
    dir_key = os.path.abspath(local_model_dir) if local_model_dir else ""
    pipe_key = (dir_key, lang)
    with _KOKORO_CACHE_LOCK:
        pipeline = _KOKORO_PIPELINE_CACHE.get(pipe_key)
        if pipeline is not None:
            return pipeline

        kmodel = None
        if local_model_dir and KModel is not None:
            config_path = os.path.join(local_model_dir, "config.json")
            model_path = os.path.join(local_model_dir, "kokoro-v1_0.pth")
            if os.path.exists(config_path) and os.path.exists(model_path):
                model_key = (config_path, model_path)
                kmodel = _KOKORO_MODEL_CACHE.get(model_key)
                if kmodel is None:
                    logger.info(f"Loading Kokoro model into memory from: {local_model_dir}")
                    kmodel = KModel(
                        repo_id="hexgrad/Kokoro-82M",
                        config=config_path,
                        model=model_path,
                    ).eval()
                    _KOKORO_MODEL_CACHE[model_key] = kmodel

        if kmodel is not None:
            pipeline = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", model=kmodel)
        else:
            pipeline = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M")

        _KOKORO_PIPELINE_CACHE[pipe_key] = pipeline
        return pipeline


def resample_for_asterisk(audio_data, original_rate, target_rate=8000):
    """
    Resamples audio data to the target sample rate using scipy.
    """
    if original_rate == target_rate:
        return audio_data

    samples = len(audio_data)
    new_samples = int(samples * target_rate / original_rate)
    return scipy.signal.resample(audio_data, new_samples)


def text_to_speech_kokoro(
    text: str,
    output_path: str | Path,
    voice_name: str = "af_heart",
    lang: str = "a",
    speed: float = 1.0,
    model_path: str | None = None,
    voices_path: str | None = None,
) -> None:
    """Synthesize speech in-process using cached Kokoro KModel + KPipeline and write an atomic 8 kHz WAV."""
    if KPipeline is None:
        raise ImportError("'kokoro' package not found. Please install it via pip or uv.")

    logger.info(f"Synthesizing Kokoro text (lang={lang}, voice={voice_name})")

    local_model_dir = resolve_kokoro_model_dir(model_path)
    if local_model_dir:
        logger.info(f"Using local Kokoro model directory: {local_model_dir}")
        pipeline = _get_kokoro_pipeline(lang, local_model_dir)

        if voice_name.endswith(".pt") and os.path.exists(voice_name):
            voice_to_use = voice_name
        elif os.path.exists(
            os.path.join(local_model_dir, "voices", f"{voice_name}.pt")
        ):
            voice_to_use = os.path.join(
                local_model_dir, "voices", f"{voice_name}.pt"
            )
            logger.info(f"Using local voice file: {voice_to_use}")
        elif voices_path and os.path.exists(
            os.path.join(voices_path, f"{voice_name}.pt")
        ):
            voice_to_use = os.path.join(voices_path, f"{voice_name}.pt")
            logger.info(f"Using local voice file from voices_path: {voice_to_use}")
        else:
            voice_to_use = voice_name
    else:
        pipeline = _get_kokoro_pipeline(lang, None)
        voice_to_use = voice_name

    generator = pipeline(text, voice=voice_to_use, speed=speed)

    full_audio = []
    for _, _, audio in generator:
        full_audio.append(audio)

    if not full_audio:
        raise RuntimeError("No audio generated by Kokoro TTS")

    audio_concat = np.concatenate(full_audio)

    native_rate = 24000
    target_rate = 8000

    audio_8k = resample_for_asterisk(audio_concat, native_rate, target_rate)

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    tmp_p = out_p.with_name(f".{out_p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        sf.write(str(tmp_p), audio_8k, target_rate, subtype="PCM_16", format="WAV")
        os.replace(tmp_p, out_p)
    except Exception:
        if tmp_p.exists():
            tmp_p.unlink(missing_ok=True)
        raise

    logger.info(f"Kokoro audio saved successfully to {out_p}")


def parse_arguments():
    """
    Parses command-line arguments for the Kokoro TTS script.
    """
    parser = argparse.ArgumentParser(
        description="Text-to-Speech using Kokoro TTS (PyTorch)"
    )
    parser.add_argument("text", type=str, help="Text to synthesize")
    parser.add_argument(
        "--voice-name",
        type=str,
        default="af_heart",
        help="Voice name to use (e.g., if_sara, af_heart, bf_emma)",
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="a",
        help="Language code: a=American English, b=British English, e=Spanish, f=French, h=Hindi, i=Italian, j=Japanese, p=Portuguese, z=Chinese",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed rate multiplier (default 1.0, e.g. 0.85 for high clarity)",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Output WAV file path"
    )
    parser.add_argument(
        "--model", type=str, help="Path to local Kokoro model directory", default=None
    )
    parser.add_argument(
        "--voices", type=str, help="Path to local voices directory or .pt file", default=None
    )

    return parser.parse_args()


def main():
    """
    Main entry point for the Kokoro TTS script.
    """
    if KPipeline is None:
        logger.error("Error: 'kokoro' package not found. Please install it via pip or uv.")
        sys.exit(1)

    args = parse_arguments()

    try:
        text_to_speech_kokoro(
            text=args.text,
            output_path=args.output,
            voice_name=args.voice_name,
            lang=args.lang,
            speed=args.speed,
            model_path=args.model,
            voices_path=args.voices,
        )
    except Exception as e:
        logger.critical(f"Error generating audio: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
