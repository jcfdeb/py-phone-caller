#!/usr/bin/env python3
import argparse
import importlib.util
import logging
import os
import sys
from pathlib import Path
import numpy as np
import soundfile as sf
import torch

try:
    import scipy.signal
except ImportError:
    scipy = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("silero_tts")

DEFAULT_SPEAKERS = {
    "en": "en_0",
    "ru": "kseniya",
    "de": "thorsten",
    "es": "es_0",
    "fr": "fr_0",
    "indic": "hindi_female",
}

MODEL_FILENAMES = {
    "en": "v3_en.pt",
    "ru": "v4_ru.pt",
    "de": "v3_de.pt",
    "es": "v3_es.pt",
    "fr": "v3_fr.pt",
    "indic": "v3_indic.pt",
}

_MODEL_CACHE = {}


def resolve_device(requested_device: str = "auto") -> str:
    """
    Resolves compute device ('cuda' or 'cpu').
    If 'auto', uses 'cuda' when available, else 'cpu'.
    """
    req = (requested_device or "auto").lower().strip()
    if req == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    if req == "cuda" and not torch.cuda.is_available():
        logger.warning("CUDA requested but not available. Falling back to CPU.")
        return "cpu"
    return req


def resolve_silero_model_path(lang: str = "en", model_path: str = None) -> str:
    """
    Resolves the filesystem path to the Silero TTS checkpoint for the given language.
    """
    clean_lang = lang.lower().strip()
    expected_filename = MODEL_FILENAMES.get(clean_lang, f"v3_{clean_lang}.pt")

    if model_path:
        p = os.path.abspath(model_path)
        if os.path.isfile(p):
            return p
        if os.path.isdir(p):
            # 1. Look in subfolder <p>/<clean_lang>/<expected_filename>
            sub_file = os.path.join(p, clean_lang, expected_filename)
            if os.path.isfile(sub_file):
                return sub_file
            # 2. Look in <p>/<expected_filename>
            direct_file = os.path.join(p, expected_filename)
            if os.path.isfile(direct_file):
                return direct_file
            # 3. Look in <p>/<clean_lang>.pt
            lang_pt = os.path.join(p, f"{clean_lang}.pt")
            if os.path.isfile(lang_pt):
                return lang_pt
            # 4. Any .pt file inside directory
            for f in os.listdir(p):
                if f.endswith(".pt"):
                    return os.path.join(p, f)

    candidates = []

    # 1. Candidate relative to generate_audio package location
    try:
        spec = importlib.util.find_spec("generate_audio")
        if spec and spec.submodule_search_locations:
            for pkg_dir in spec.submodule_search_locations:
                candidates.append(
                    os.path.join(pkg_dir, "pre_trained_models", "silero_tts", clean_lang, expected_filename)
                )
                candidates.append(
                    os.path.join(pkg_dir, "pre_trained_models", "silero_tts", expected_filename)
                )
    except Exception:
        pass

    # 2. Candidate relative to this file's repository location
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    repo_models_dir = os.path.join(
        current_file_dir,
        "..",
        "..",
        "..",
        "generate_audio",
        "pre_trained_models",
        "silero_tts",
    )
    candidates.append(os.path.join(repo_models_dir, clean_lang, expected_filename))
    candidates.append(os.path.join(repo_models_dir, expected_filename))

    # 3. Candidates relative to current working directory
    cwd = os.getcwd()
    candidates.append(os.path.join(cwd, "src", "generate_audio", "pre_trained_models", "silero_tts", clean_lang, expected_filename))
    candidates.append(os.path.join(cwd, "src", "generate_audio", "pre_trained_models", "silero_tts", expected_filename))
    candidates.append(os.path.join(cwd, "pre_trained_models", "silero_tts", clean_lang, expected_filename))
    candidates.append(os.path.join(cwd, "pre_trained_models", "silero_tts", expected_filename))

    # 4. Standard container paths
    candidates.append(f"/app/src/generate_audio/pre_trained_models/silero_tts/{clean_lang}/{expected_filename}")
    candidates.append(f"/app/src/generate_audio/pre_trained_models/silero_tts/{expected_filename}")
    candidates.append(f"/app/pre_trained_models/silero_tts/{clean_lang}/{expected_filename}")
    candidates.append(f"/app/pre_trained_models/silero_tts/{expected_filename}")

    for cand in candidates:
        cand_path = os.path.abspath(cand)
        if os.path.isfile(cand_path) and os.path.getsize(cand_path) > 0:
            return cand_path

    return None


def load_silero_model(model_path: str, device: str = "auto"):
    """
    Loads Silero TTS model from a local .pt checkpoint using torch.package or torch.jit.
    Cached in memory for zero cold-start latency.
    """
    actual_device = resolve_device(device)
    cache_key = f"{model_path}:{actual_device}"
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    logger.info(f"Loading Silero model from {model_path} onto {actual_device}...")
    torch_device = torch.device(actual_device)

    try:
        importer = torch.package.PackageImporter(model_path)
        model = importer.load_pickle("tts_models", "model")
    except Exception as pkg_err:
        logger.debug(f"PackageImporter failed ({pkg_err}), attempting torch.jit.load...")
        model = torch.jit.load(model_path, map_location=torch_device)

    if hasattr(model, "to"):
        model.to(torch_device)

    _MODEL_CACHE[cache_key] = model
    logger.info(f"Silero model loaded successfully on {actual_device}.")
    return model


def resample_audio(audio_data: np.ndarray, original_rate: int, target_rate: int = 8000) -> np.ndarray:
    """
    Resamples audio to target sample rate using scipy if available, or linear interpolation.
    """
    if original_rate == target_rate:
        return audio_data

    samples = len(audio_data)
    new_samples = int(samples * target_rate / original_rate)
    if scipy is not None:
        return scipy.signal.resample(audio_data, new_samples)
    else:
        orig_indices = np.linspace(0, samples - 1, samples)
        new_indices = np.linspace(0, samples - 1, new_samples)
        return np.interp(new_indices, orig_indices, audio_data)


def text_to_speech_silero(
    message: str,
    output_path: str,
    lang: str = "en",
    speaker: str = None,
    sample_rate: int = 8000,
    speed: float = 1.0,
    model_path: str = None,
    device: str = "auto",
) -> None:
    """
    Synthesize audio using Silero TTS and write 16-bit mono PCM WAV for Asterisk.
    """
    if not message or not message.strip():
        raise ValueError("Cannot synthesize empty message")

    clean_lang = lang.lower().strip()
    target_speaker = speaker or DEFAULT_SPEAKERS.get(clean_lang, "en_0")

    resolved_path = resolve_silero_model_path(clean_lang, model_path)
    if not resolved_path or not os.path.exists(resolved_path):
        raise FileNotFoundError(
            f"Silero model for '{clean_lang}' not found. Searched in: {model_path or 'default paths'}"
        )

    actual_device = resolve_device(device)
    model = load_silero_model(resolved_path, device=actual_device)

    # Silero native sample rates are 8000, 24000, 48000.
    native_sr = sample_rate if sample_rate in (8000, 24000, 48000) else 8000

    logger.info(
        f"Synthesizing Silero speech: lang={clean_lang}, speaker={target_speaker}, "
        f"native_sr={native_sr}, target_sr={sample_rate}, speed={speed}, device={actual_device}"
    )

    try:
        audio = model.apply_tts(
            text=message,
            speaker=target_speaker,
            sample_rate=native_sr,
        )
    except Exception as e:
        logger.error(f"Silero apply_tts failed: {e}")
        raise RuntimeError(f"Silero TTS synthesis failed: {e}") from e

    if isinstance(audio, torch.Tensor):
        audio_np = audio.detach().cpu().numpy()
    else:
        audio_np = np.asarray(audio)

    audio_np = np.squeeze(audio_np)

    # Resample if target sample rate differs from synthesis sample rate
    if native_sr != sample_rate:
        logger.info(f"Resampling audio from {native_sr}Hz to {sample_rate}Hz...")
        audio_np = resample_audio(audio_np, native_sr, sample_rate)

    # Adjust speed if requested and scipy is available
    if speed is not None and abs(speed - 1.0) > 0.01 and speed > 0:
        new_length = int(len(audio_np) / speed)
        if scipy is not None:
            audio_np = scipy.signal.resample(audio_np, new_length)

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Write 16-bit mono PCM WAV for Asterisk ARI compatibility
    sf.write(str(out_file), audio_np, sample_rate, subtype="PCM_16")
    logger.info(f"Audio saved successfully to {out_file} ({sample_rate}Hz, 16-bit PCM)")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Text-to-Speech synthesis using Silero Models (PyTorch)"
    )
    parser.add_argument("text", nargs="?", type=str, help="Text to synthesize")
    parser.add_argument(
        "--message",
        "-m",
        type=str,
        help="Text to synthesize (alias for positional text)",
    )
    parser.add_argument(
        "--lang",
        "-l",
        type=str,
        default="en",
        help="Language code (en, ru, de, es, fr, indic)",
    )
    parser.add_argument(
        "--speaker",
        "-s",
        type=str,
        default=None,
        help="Speaker name (e.g., en_0, kseniya, thorsten, es_0)",
    )
    parser.add_argument(
        "--sample-rate",
        "-r",
        type=int,
        default=8000,
        help="Output sample rate in Hz (8000 or 16000 for Asterisk)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed multiplier (default 1.0)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Output WAV file path",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path to local Silero model checkpoint (.pt) or models directory",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="auto",
        help="Inference device ('auto', 'cpu', or 'cuda')",
    )

    return parser.parse_args()


def main():
    args = parse_arguments()
    text = args.text or args.message
    if not text:
        logger.error("Error: No message text provided. Specify positional text or --message.")
        sys.exit(1)

    try:
        text_to_speech_silero(
            message=text,
            output_path=str(args.output),
            lang=args.lang,
            speaker=args.speaker,
            sample_rate=args.sample_rate,
            speed=args.speed,
            model_path=args.model,
            device=args.device,
        )
    except Exception as e:
        logger.critical(f"Error generating Silero audio: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
