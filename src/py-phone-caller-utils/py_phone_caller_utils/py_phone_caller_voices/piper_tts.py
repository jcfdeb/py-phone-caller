import argparse
import logging
import os
import threading
import wave
from pathlib import Path

import numpy as np
from scipy import signal
from piper.voice import PiperVoice

"""
Warning:
    This script generates audio using the Piper TTS engine.

    Example usage:
    # python3 piper_tts.py "Your text to speak" --model ./it_IT.onnx --config ./it_IT.onnx.json --output ./output.wav
"""

logging.basicConfig()
logger = logging.getLogger("piper")
logger.setLevel(logging.INFO)

_VOICE_CACHE: dict[tuple[str, str], PiperVoice] = {}
_VOICE_CACHE_LOCK = threading.Lock()


def load_piper_voice(model_path: str | Path, config_path: str | Path) -> PiperVoice:
    """Load and cache a PiperVoice instance in memory for low-latency reuse."""
    key = (os.path.abspath(str(model_path)), os.path.abspath(str(config_path)))
    with _VOICE_CACHE_LOCK:
        voice = _VOICE_CACHE.get(key)
        if voice is None:
            logger.info(f"Loading Piper voice from: {key[0]}")
            voice = PiperVoice.load(key[0], config_path=key[1])
            _VOICE_CACHE[key] = voice
            logger.info("Piper voice loaded and cached in memory.")
        return voice


def resample_audio(audio_bytes, orig_sr, target_sr=8000):
    """
    Resamples raw audio bytes from the original sample rate to the target sample rate.

    This function converts the audio bytes to float, resamples using scipy.signal, and returns the result as int16 bytes.

    Args:
        audio_bytes (bytes): The raw audio data in int16 format.
        orig_sr (int): The original sample rate of the audio.
        target_sr (int, optional): The target sample rate. Defaults to 8000.

    Returns:
        bytes: The resampled audio data in int16 format.
    """
    if orig_sr == target_sr:
        return audio_bytes

    audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
    audio_float = audio_np.astype(np.float32) / 32768.0

    number_of_samples = round(len(audio_float) * target_sr / orig_sr)
    audio_resampled = signal.resample(audio_float, number_of_samples)

    audio_int16 = np.clip(audio_resampled * 32768.0, -32768, 32767).astype(np.int16)
    return audio_int16.tobytes()


def text_to_speech_piper(
    text: str,
    model_path: str | Path,
    config_path: str | Path,
    output_path: str | Path,
    speed: float = 1.0,
    target_sample_rate: int = 8000,
) -> None:
    """Synthesize speech in-process using a cached PiperVoice and write an atomic 8 kHz PCM WAV."""
    model_p = Path(model_path)
    config_p = Path(config_path)
    out_p = Path(output_path)

    if not model_p.exists():
        raise FileNotFoundError(f"Model file not found at: {model_p}")
    if not config_p.exists():
        raise FileNotFoundError(f"Config file not found at: {config_p}")

    voice = load_piper_voice(model_p, config_p)

    logger.info(f"Synthesizing text: '{text}'")
    # length_scale is inverse of speed: lower length_scale -> faster speech, higher -> slower
    length_scale = 1.0 / max(0.2, min(5.0, speed)) if speed > 0 else 1.0
    from piper.config import SynthesisConfig

    syn_config = SynthesisConfig(length_scale=length_scale)
    audio_bytes = b"".join(
        chunk.audio_int16_bytes for chunk in voice.synthesize(text, syn_config=syn_config)
    )

    logger.info(f"Synthesized {len(audio_bytes)} bytes of audio.")

    sample_rate = voice.config.sample_rate
    sample_width = 2
    channels = 1

    audio_resampled = resample_audio(audio_bytes, sample_rate, target_sample_rate)

    out_p.parent.mkdir(parents=True, exist_ok=True)
    tmp_p = out_p.with_name(f".{out_p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with wave.open(str(tmp_p), "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(target_sample_rate)
            wav_file.writeframes(audio_resampled)
        os.replace(tmp_p, out_p)
    except Exception:
        if tmp_p.exists():
            tmp_p.unlink(missing_ok=True)
        raise

    logger.info(f"Audio saved successfully to: {out_p}")


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
        "--speed",
        type=float,
        default=1.0,
        help="Speech speed multiplier (1.0 = normal, 0.85 = slower/clearer)",
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

    try:
        text_to_speech_piper(
            text=args.text,
            model_path=args.model,
            config_path=args.config,
            output_path=args.output,
            speed=args.speed,
        )
    except Exception as e:
        logger.critical(f"Error generating Piper audio: {e}")


if __name__ == "__main__":
    main()
