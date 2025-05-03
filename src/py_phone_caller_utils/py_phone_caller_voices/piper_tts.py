import argparse
import logging
import wave
from pathlib import Path

import librosa
import numpy as np
from piper.voice import PiperVoice

"""
Warning: 
    This script will be executed using a different Python environment,
    using Python 3.11.x due 'piper-tts' is not yet compatible with Python 3.12.x'
    
    
    # python3.11 piper_tts.py "Your text to speak" --model ./custom/model.onnx --config ./custom/config.onnx.json --output ./custom_output.wav
"""

logging.basicConfig()
logger = logging.getLogger("piper")
logger.setLevel(logging.INFO)


def resample_audio(audio_bytes, orig_sr, target_sr=8000):
    """
    Resamples raw audio bytes from the original sample rate to the target sample rate.

    This function converts the audio bytes to float, resamples using librosa, and returns the result as int16 bytes.

    Args:
        audio_bytes (bytes): The raw audio data in int16 format.
        orig_sr (int): The original sample rate of the audio.
        target_sr (int, optional): The target sample rate. Defaults to 8000.

    Returns:
        bytes: The resampled audio data in int16 format.
    """
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
    audio_float = audio_np.astype(np.float32) / 32768.0
    audio_resampled = librosa.resample(
        audio_float, orig_sr=orig_sr, target_sr=target_sr
    )
    audio_int16 = (audio_resampled * 32768.0).astype(np.int16)
    return audio_int16.tobytes()


MODEL_PATH = None
CONFIG_PATH = None
OUTPUT_WAV_PATH = None


def parse_arguments():
    """
    Parses command-line arguments for the Piper TTS script.

    This function sets up the argument parser for text input, model path, config path, and output WAV file path.

    Returns:
        argparse.Namespace: The parsed command-line arguments.
    """
    parser = argparse.ArgumentParser(description="Text-to-Speech using Piper TTS")
    parser.add_argument("text", type=str, help="Text to synthesize")
    parser.add_argument(
        "--model", type=Path, default=MODEL_PATH, help="Path to the .onnx model file"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to the .onnx.json config file",
    )
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_WAV_PATH, help="Output WAV file path"
    )
    return parser.parse_args()


def main() -> None:
    """
    Main entry point for the Piper TTS script.

    This function parses command-line arguments, loads the TTS model and config, synthesizes speech from text,
    resamples the audio to 8000 Hz, and saves it as a WAV file. It logs each step and handles errors gracefully.

    Returns:
        None
    """
    args = parse_arguments()

    if not args.model.exists():
        logger.critical(f"Model file not found at: {args.model}")
        return
    if not args.config.exists():
        logger.critical(f"Config file not found at: {args.config}")
        return

    logger.info(f"Loading voice from: {args.model}")

    try:
        voice = PiperVoice.load(args.model, config_path=args.config)
        logger.info("Voice loaded successfully.")
    except Exception as e:
        logger.critical(f"Error loading voice: {e}")
        return

    logger.info(f"Synthesizing text: '{args.text}'")
    audio_bytes = b"".join(iter(voice.synthesize_stream_raw(args.text)))

    logger.info(f"Synthesized {len(audio_bytes)} bytes of audio.")

    sample_rate = voice.config.sample_rate
    sample_width = 2
    channels = 1

    logger.info(f"Saving audio to: {args.output}")
    logger.info(
        f"Audio Parameters: Rate={sample_rate}, Width={sample_width}, Channels={channels}"
    )

    target_sample_rate = 8000
    audio_resampled = resample_audio(
        audio_bytes, voice.config.sample_rate, target_sample_rate
    )

    with wave.open(str(args.output), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(target_sample_rate)
        wav_file.writeframes(audio_resampled)

    logger.info("Audio saved successfully.")


if __name__ == "__main__":
    main()
