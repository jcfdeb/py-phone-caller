import importlib.util
import logging
import os
import re
from pathlib import Path

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


def resolve_mms_model_path(lang_code: str = None, model_path: str = None) -> str:
    """
    Resolves the filesystem path or Hugging Face Hub model identifier for a Facebook MMS TTS model.

    Checks:
    1. Direct model_path if provided and exists.
    2. Candidate local filesystem paths in generate_audio and project directory structure.
    3. Falls back to canonical Hugging Face Hub model identifier 'facebook/mms-tts-{lang_code}'.
    """
    lang = lang_code or FACEBOOK_MMS_LANGUAGE_CODE or "spa"
    model_folder_name = f"mms-tts-{lang}"

    if model_path and os.path.exists(model_path):
        return os.path.abspath(model_path)

    # Search known candidate locations
    candidates = []

    # 1. Candidate relative to generate_audio package location
    try:
        spec = importlib.util.find_spec("generate_audio")
        if spec and spec.submodule_search_locations:
            for pkg_dir in spec.submodule_search_locations:
                candidates.append(
                    os.path.join(
                        pkg_dir,
                        PRE_TRAINED_MODELS_FOLDER,
                        FACEBOOK_MMS_MODELS_FOLDER,
                        model_folder_name,
                    )
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
            PRE_TRAINED_MODELS_FOLDER,
            FACEBOOK_MMS_MODELS_FOLDER,
            model_folder_name,
        )
    )

    # 3. Candidates relative to current working directory
    candidates.append(
        os.path.join(
            os.getcwd(),
            "src",
            "generate_audio",
            PRE_TRAINED_MODELS_FOLDER,
            FACEBOOK_MMS_MODELS_FOLDER,
            model_folder_name,
        )
    )
    candidates.append(
        os.path.join(
            os.getcwd(),
            PRE_TRAINED_MODELS_FOLDER,
            FACEBOOK_MMS_MODELS_FOLDER,
            model_folder_name,
        )
    )
    candidates.append(
        os.path.join(
            os.getcwd(),
            "pre_trained_models",
            "facebook",
            model_folder_name,
        )
    )

    # 4. Standard container paths
    candidates.append(
        os.path.join(
            "/app",
            "src",
            "generate_audio",
            PRE_TRAINED_MODELS_FOLDER,
            FACEBOOK_MMS_MODELS_FOLDER,
            model_folder_name,
        )
    )
    candidates.append(
        os.path.join(
            "/app",
            PRE_TRAINED_MODELS_FOLDER,
            FACEBOOK_MMS_MODELS_FOLDER,
            model_folder_name,
        )
    )

    for cand in candidates:
        cand_path = os.path.abspath(cand)
        if os.path.isdir(cand_path) and (
            os.path.exists(os.path.join(cand_path, "config.json"))
            or os.path.exists(os.path.join(cand_path, "model.safetensors"))
        ):
            return cand_path

    # Fall back to canonical Hugging Face Hub model ID (e.g. 'facebook/mms-tts-spa')
    return f"facebook/{model_folder_name}"


def convert_numbers_in_string(text, lang="es"):
    """
    Converts numbers found within a string to their word representations
    using the num2words library.

    Args:
        text (str): The input string containing numbers.
        lang (str): The language code for number conversion (example: 'it' for Italian, 'en' for English, etc).

    Returns:
        str: The string with numbers replaced by their word forms.
    """
    lang_map = {
        "spa": "es",
        "ita": "it",
        "eng": "en",
        "fra": "fr",
        "deu": "de",
        "por": "pt",
        "rus": "ru",
    }
    effective_lang = lang_map.get(lang, lang)

    def replace_number(match):
        number_str = match.group(0)
        try:
            number = int(number_str)
            return num2words(number, lang=effective_lang)
        except Exception:
            try:
                number = float(number_str)
                return num2words(number, lang=effective_lang)
            except Exception:
                return number_str

    pattern = r"\b\d+(\.\d+)?\b"
    return re.sub(pattern, replace_number, text)


def text_to_speech_facebook_mms(text, lang_code=None, output_path=None, model_path=None):
    """
    Generates speech audio from text using a Facebook MMS TTS model for the specified language.

    This function loads the appropriate pre-trained MMS model, converts numbers in the text to words,
    generates the audio, and saves it to the specified output path.

    Args:
        text (str): The input text to convert to speech.
        lang_code (str, optional): The language code for the TTS model. Defaults to settings.
        output_path (str, optional): The path where the generated audio file will be saved.
        model_path (str, optional): Explicit path or model ID to use.

    Returns:
        None

    Raises:
        RuntimeError: If audio generation fails.
    """
    effective_lang = lang_code or FACEBOOK_MMS_LANGUAGE_CODE
    num2words_lang = FACEBOOK_MMS_NUM2WORDS_LANGUAGE_CODE or effective_lang

    resolved_path = resolve_mms_model_path(effective_lang, model_path)
    logging.info(f"MMS: loading model for language '{effective_lang}' from {resolved_path}...")

    try:
        numbers_in_text = convert_numbers_in_string(text, num2words_lang)
    except Exception as e:
        logging.warning(
            f"MMS: an error occurred when converting numbers in text: {e}, using raw text"
        )
        numbers_in_text = text

    try:
        create_audio_through_facebook_mms(resolved_path, numbers_in_text, output_path)
    except Exception as e:
        logging.exception(f"MMS: an error occurred: {e}")
        raise RuntimeError(f"MMS audio generation failed: {e}") from e


def create_audio_through_facebook_mms(model_path, text, output_path):
    """Generates speech audio from text using a Facebook MMS model.

    Loads a pre-trained Facebook MMS model, tokenizes the input text,
    generates the corresponding waveform, and saves it as a WAV file
    in 16-bit PCM format at 8000 Hz to be compliant with Asterisk's
    WAV format.

    Args:
        model_path (str): The path or HF model ID to the pre-trained Facebook MMS model.
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
    if os.path.dirname(output_path):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    scipy.io.wavfile.write(output_path, rate=target_sampling_rate, data=waveform_pcm)
    logging.info("MMS: audio generation done.")
