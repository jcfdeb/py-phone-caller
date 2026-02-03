import logging
import os
import wave

import boto3
import numpy as np
from scipy.signal import resample

from py_phone_caller_utils.config import settings

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)

SERVING_AUDIO_FOLDER = settings.generate_audio.serving_audio_folder
AWS_POLLY_REGION_NAME = settings.generate_audio.aws_polly_region_name
AWS_POLLY_VOICE = settings.generate_audio.aws_polly_voice

polly_client = boto3.client("polly", region_name=AWS_POLLY_REGION_NAME)


def text_to_pcm(message, voice_id="Salli", output_format="pcm", sample_rate="16000"):
    """
    Synthesizes speech from the given text using AWS Polly and returns the PCM audio stream.

    Args:
    message (str): The text to synthesize.
    voice_id (str): The ID of the voice to use (e.g., 'Salli', 'Matthew').
    output_format (str): The desired output format ('pcm' or 'mp3', etc.).
    sample_rate (str): The desired sample rate for the PCM output (e.g., '8000', '16000', '22050').

    Returns:
    bytes: The raw PCM audio data as bytes, or None if an error occurs.
    """
    try:
        response = polly_client.synthesize_speech(
            VoiceId=voice_id,
            OutputFormat=output_format,
            SampleRate=sample_rate,
            Text=message,
        )
        if "AudioStream" in response:
            return response["AudioStream"].read()
        logging.error("Error: Could not retrieve audio stream from Polly response.")
        return None
    except Exception as e:
        logging.exception(f"Error during Polly synthesis: {e}")
        return None


def normalize_pcm_sample_rate(
    pcm_data, original_rate, target_rate, sample_width=2, num_channels=1
):
    """
    Normalizes the sample rate of PCM data using resampling.

    Args:
    pcm_data (bytes): The raw PCM audio data.
    original_rate (int): The original sample rate of the PCM data.
    target_rate (int): The desired target sample rate (e.g., 8000).
    sample_width (int): The sample width in bytes.
    num_channels (int): The number of audio channels.

    Returns:
    bytes: The PCM data resampled to the target rate.
    """
    if sample_width == 2:
        dtype = np.int16
    elif sample_width == 1:
        dtype = np.uint8
    else:
        raise ValueError("Unsupported sample width")

    samples = np.frombuffer(pcm_data, dtype=dtype)
    if num_channels > 1:
        samples = samples.reshape(-1, num_channels)

    num_original_samples = len(samples)
    num_target_samples = int(num_original_samples * (target_rate / original_rate))

    resampled_audio = resample(samples, num_target_samples)
    resampled_audio = resampled_audio.astype(dtype)

    if num_channels > 1:
        resampled_audio = resampled_audio.flatten()

    return resampled_audio.tobytes()


def create_wave_file_from_pcm(
    pcm_data, output_filename, sample_rate, num_channels, sample_width
):
    """
    Creates a WAV file from raw PCM data.

    Args:
    pcm_data (bytes): The raw PCM audio data.
    output_filename (str): The name of the output WAV file.
    sample_rate (int): The sample rate of the audio data.
    num_channels (int): The number of audio channels.
    sample_width (int): The sample width in bytes.
    """
    os.makedirs(os.path.dirname(output_filename), exist_ok=True)
    with wave.open(output_filename, "w") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)


def aws_polly_text_to_wave(
    message,
    output_filename=f"{SERVING_AUDIO_FOLDER}/asterisk_audio.wav",
    target_sample_rate=8000,
    voice_id=AWS_POLLY_VOICE,
):
    """
    Generates a mono WAV file at the specified sample rate (default 8000 Hz) from text using AWS Polly.

    Args:
    message (str): The text to synthesize.
    output_filename (str): The name of the output WAV file.
    target_sample_rate (int): The desired sample rate for the final WAV file (default 8000 Hz).
    voice_id (str): The ID of the voice to use in Polly.
    """

    original_pcm_data = text_to_pcm(
        message, voice_id=voice_id, output_format="pcm", sample_rate="16000"
    )
    if original_pcm_data is None:
        return

    original_sample_rate = 16000
    num_channels = 1
    sample_width = 2

    if original_sample_rate != target_sample_rate:
        logging.info(
            f"Resampling from {original_sample_rate} Hz to {target_sample_rate} Hz."
        )
        normalized_pcm_data = normalize_pcm_sample_rate(
            original_pcm_data,
            original_sample_rate,
            target_sample_rate,
            sample_width,
            num_channels,
        )
    else:
        normalized_pcm_data = original_pcm_data

    create_wave_file_from_pcm(
        normalized_pcm_data,
        output_filename,
        target_sample_rate,
        num_channels,
        sample_width,
    )
    logging.info(
        f"Successfully created '{output_filename}' with a sample rate of {target_sample_rate} Hz."
    )
