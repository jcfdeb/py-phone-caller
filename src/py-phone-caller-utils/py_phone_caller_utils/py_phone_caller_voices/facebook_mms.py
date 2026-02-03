import logging
import os
import re

import numpy as np
import scipy.io.wavfile
import torch
from num2words import num2words
from scipy import signal
from transformers import AutoTokenizer, VitsModel

from py_phone_caller_utils.config import settings

SERVING_AUDIO_FOLDER = settings.generate_audio.serving_audio_folder
PRE_TRAINED_MODELS_FOLDER = settings.generate_audio.pre_trained_models_folder
FACEBOOK_MMS_MODELS_FOLDER = settings.generate_audio.facebook_mms_models_folder
FACEBOOK_MMS_LANGUAGE_CODE = settings.generate_audio.facebook_mms_language_code
FACEBOOK_MMS_NUM2WORDS_LANGUAGE_CODE = (
    settings.generate_audio.facebook_mms_num2words_language_code
)

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)


def convert_numbers_in_string(text, lang):
    """
    Converts numbers found within a string to their word representations
    using the num2words library.

    Args:
        text (str): The input string containing numbers.
        lang (str): The language code for number conversion (example: 'it' for Italian, 'en' for English, etc).

    Returns:
        str: The string with numbers replaced by their word forms.
    """

    def replace_number(match):
        number_str = match.group(0)
        try:
            number = int(number_str)
            return num2words(number, lang=lang)
        except ValueError:
            try:
                number = float(number_str)
                return num2words(number, lang=lang)
            except ValueError:
                return number_str

    pattern = r"\b\d+(\.\d+)?\b"
    return re.sub(pattern, replace_number, text)


def text_to_speech_facebook_mms(text, lang_code, output_path):
    """
    Generates speech audio from text using a Facebook MMS TTS model for the specified language.

    This function loads the appropriate pre-trained MMS model, converts numbers in the text to words,
    generates the audio, and saves it to the specified output path. It logs errors if the language is not supported or if audio generation fails.

    Args:
        text (str): The input text to convert to speech.
        lang_code (str): The language code for the TTS model.
        output_path (str): The path where the generated audio file will be saved.

    Returns:
        None
    """

    model_paths = {
        f"{FACEBOOK_MMS_LANGUAGE_CODE}": f"{PRE_TRAINED_MODELS_FOLDER}/{FACEBOOK_MMS_MODELS_FOLDER}/mms-tts-{FACEBOOK_MMS_LANGUAGE_CODE}",
    }

    if lang_code not in model_paths:
        logging.error(
            f"MMS: error: Language code '{lang_code}' not supported or model not downloaded."
        )
        return

    model_path = model_paths[lang_code]
    logging.info(f"MMS: loading model for language '{lang_code}' from {model_path}...")

    try:
        numbers_in_text = convert_numbers_in_string(
            text, FACEBOOK_MMS_NUM2WORDS_LANGUAGE_CODE
        )
    except Exception as e:
        logging.exception(
            f"MMS: an error occurred when converting numbers in text: {e}"
        )

    try:
        create_audio_through_facebook_mms(model_path, numbers_in_text, output_path)
    except Exception as e:
        logging.exception(f"MMS: an error occurred: {e}")


def create_audio_through_facebook_mms(model_path, text, output_path):
    """Generates speech audio from text using a Facebook MMS model.

    Loads a pre-trained Facebook MMS model, tokenizes the input text,
    generates the corresponding waveform, and saves it as a WAV file
    in 16-bit PCM format at 8000 Hz to be compliant with Asterisk's
    WAV format.

    Args:
        model_path (str): The path to the pre-trained Facebook MMS model.
        text (str): The input text to convert to speech.
        output_path (str): The path where the generated audio file will be saved.

    Returns:
        None
    """
    model = VitsModel.from_pretrained(model_path, low_cpu_mem_usage=False)
    tokenizer = AutoTokenizer.from_pretrained(model_path)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    logging.info("MMS: tokenizing input...")
    inputs = tokenizer(text, return_tensors="pt").to(device)

    logging.info("MMS: generating speech...")
    with torch.no_grad():
        output_waveform = model(**inputs).waveform

    waveform_np = output_waveform.squeeze().cpu().numpy()

    original_sampling_rate = model.config.sampling_rate
    target_sampling_rate = 8000

    logging.info(
        f"MMS: Resampling from {original_sampling_rate}Hz to {target_sampling_rate}Hz..."
    )
    number_of_samples = round(
        len(waveform_np) * target_sampling_rate / original_sampling_rate
    )
    waveform_resampled = signal.resample(waveform_np, number_of_samples)

    waveform_normalized = np.clip(waveform_resampled, -1, 1)
    waveform_pcm = (waveform_normalized * 32767).astype(np.int16)

    logging.info(
        f"MMS: Saving audio to {output_path} as 16-bit PCM at {target_sampling_rate}Hz..."
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    scipy.io.wavfile.write(output_path, rate=target_sampling_rate, data=waveform_pcm)
    logging.info("MMS: audio generation done.")
