import argparse
import logging
import sys
import numpy as np
import soundfile as sf
import scipy.signal
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("kokoro")

try:
    from kokoro import KPipeline
except ImportError:
    logger.error("Error: 'kokoro' package not found. Please install it via pip.")
    sys.exit(1)


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
        "--model", type=str, help="Ignored (handled by KPipeline)", default=None
    )
    parser.add_argument(
        "--voices", type=str, help="Ignored (handled by KPipeline)", default=None
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
    args = parse_arguments()

    logger.info(f"Synthesizing text: '{args.text}'")
    logger.info(f"Language: {args.lang}, Voice: {args.voice_name}")

    try:
        pipeline = KPipeline(lang_code=args.lang)

        generator = pipeline(args.text, voice=args.voice_name, speed=1)

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
