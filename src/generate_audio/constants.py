import sys
from py_phone_caller_utils.config import settings


SERVING_AUDIO_FOLDER = settings.generate_audio.serving_audio_folder
IS_AUDIO_READY_ENDPOINT = settings.generate_audio.is_audio_ready_endpoint
NUM_OF_CPUS = settings.generate_audio.num_of_cpus
PRE_TRAINED_MODELS_FOLDER = settings.generate_audio.pre_trained_models_folder
FACEBOOK_MMS_MODELS_FOLDER = settings.generate_audio.facebook_mms_models_folder
FACEBOOK_MMS_LANGUAGE_CODE = settings.generate_audio.facebook_mms_language_code
PIPER_MODELS_FOLDER = settings.generate_audio.piper_models_folder
PIPER_LANGUAGE_CODE = settings.generate_audio.piper_language_code
CONFIG_TTS_ENGINE = settings.generate_audio.tts_engine
PIPER_PYTHON_INTERPRETER = settings.generate_audio.piper_python_interpreter

if PIPER_PYTHON_INTERPRETER in ["python", "python3"]:
    PIPER_PYTHON_INTERPRETER = sys.executable

KOKORO_MODELS_FOLDER = settings.generate_audio.kokoro_models_folder
KOKORO_LANG = settings.generate_audio.kokoro_lang
KOKORO_PYTHON_INTERPRETER = settings.generate_audio.kokoro_python_interpreter
KOKORO_MODEL_URL = settings.generate_audio.kokoro_model_url
KOKORO_VOICES_BASE_URL = settings.generate_audio.kokoro_voices_base_url

if KOKORO_PYTHON_INTERPRETER in ["python", "python3"]:
    KOKORO_PYTHON_INTERPRETER = sys.executable

GENERATE_AUDIO_APP_ROUTE = settings.generate_audio.generate_audio_app_route
GENERATE_AUDIO_PORT = int(settings.generate_audio.generate_audio_port)
GENERATE_AUDIO_ERROR = settings.logs.generate_audio_error
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
