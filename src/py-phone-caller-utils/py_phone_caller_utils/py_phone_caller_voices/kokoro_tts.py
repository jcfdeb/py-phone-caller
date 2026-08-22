import argparse
import importlib.util
import logging
import os
import sys
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
            os.getcwd(), "src", "generate_audio", "pre_trained_models", "kokoro_tts"
        )
    )
    candidates.append(
        os.path.join(os.getcwd(), "pre_trained_models", "kokoro_tts")
    )

    # 4. Standard container paths
    candidates.append("/app/src/generate_audio/pre_trained_models/kokoro_tts")
    candidates.append("/app/pre_trained_models/kokoro_tts")

    for cand in candidates:
        cand_path = os.path.abspath(cand)
        if os.path.isdir(cand_path) and (
            os.path.exists(os.path.join(cand_path, "config.json"))
            or os.path.exists(os.path.join(cand_path, "kokoro-v1_0.pth"))
        ):
            return cand_path

    return None


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
        "--output", type=Path, required=True, help="Output WAV file path"
    )
    parser.add_argument(
        "--model", type=str, help="Path to local Kokoro model directory", default=None
    )
    parser.add_argument(
        "--voices", type=str, help="Path to local voices directory or .pt file", default=None
    )

    return parser.parse_args()


def resample_for_asterisk(audio_data, original_rate, target_rate=8000):
    """
    Resamples audio data to the target sample rate using scipy.
    """
    if original_rate == target_rate:
        return audio_data

    samples = len(audio_data)
    new_samples = int(samples * target_rate / original_rate)
    return scipy.signal.resample(audio_data, new_samples)


def main():
    """
    Main entry point for the Kokoro TTS script.
    """
    if KPipeline is None:
        logger.error("Error: 'kokoro' package not found. Please install it via pip or uv.")
        sys.exit(1)

    args = parse_arguments()

    logger.info(f"Synthesizing text: '{args.text}'")
    logger.info(f"Language: {args.lang}, Voice: {args.voice_name}")

    try:
        local_model_dir = resolve_kokoro_model_dir(args.model)
        if local_model_dir:
            logger.info(f"Using local Kokoro model directory: {local_model_dir}")
            config_path = os.path.join(local_model_dir, "config.json")
            model_path = os.path.join(local_model_dir, "kokoro-v1_0.pth")

            if not os.path.exists(config_path):
                config_path = None
            if not os.path.exists(model_path):
                model_path = None

            if config_path and model_path and KModel is not None:
                kmodel = KModel(
                    repo_id="hexgrad/Kokoro-82M",
                    config=config_path,
                    model=model_path,
                ).eval()
                pipeline = KPipeline(lang_code=args.lang, model=kmodel)
            else:
                pipeline = KPipeline(lang_code=args.lang)

            # Check for local voice file
            if args.voice_name.endswith(".pt") and os.path.exists(args.voice_name):
                voice_to_use = args.voice_name
            elif os.path.exists(
                os.path.join(local_model_dir, "voices", f"{args.voice_name}.pt")
            ):
                voice_to_use = os.path.join(
                    local_model_dir, "voices", f"{args.voice_name}.pt"
                )
                logger.info(f"Using local voice file: {voice_to_use}")
            elif args.voices and os.path.exists(
                os.path.join(args.voices, f"{args.voice_name}.pt")
            ):
                voice_to_use = os.path.join(args.voices, f"{args.voice_name}.pt")
                logger.info(f"Using local voice file from args.voices: {voice_to_use}")
            else:
                voice_to_use = args.voice_name
        else:
            pipeline = KPipeline(lang_code=args.lang)
            voice_to_use = args.voice_name

        generator = pipeline(args.text, voice=voice_to_use, speed=1)

        full_audio = []
        for _, _, audio in generator:
            full_audio.append(audio)

        if not full_audio:
            logger.error("No audio generated")
            sys.exit(1)

        audio_concat = np.concatenate(full_audio)

        native_rate = 24000
        target_rate = 8000

        logger.info(f"Resampling from {native_rate}Hz to {target_rate}Hz...")
        audio_8k = resample_for_asterisk(audio_concat, native_rate, target_rate)

        args.output.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Saving to {args.output}")
        sf.write(str(args.output), audio_8k, target_rate, subtype="PCM_16")

        logger.info("Audio saved successfully.")

    except Exception as e:
        logger.critical(f"Error generating audio: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
