import logging
import os.path

from gtts import gTTS
from pydub import AudioSegment

import py_phone_caller_utils.caller_configuration as conf

logging.basicConfig(format=conf.get_log_formatter())

# Define a folder to store the audio files
SERVING_AUDIO_FOLDER = conf.get_serving_audio_folder()
GCLOUD_TTS_LANGUAGE_CODE = conf.get_gcloud_tts_language_code()


def mp3_to_wave(an_audio_file):
    """
    Converts an MP3 audio file to a WAV file with 8000 Hz sample rate and mono channel.

    This function loads the specified MP3 file, exports it as a WAV file, and applies the required audio parameters.

    Args:
        an_audio_file (str): The base filename (without extension) of the audio file to convert.

    Returns:
        None
    """
    sound = AudioSegment.from_mp3(f"{an_audio_file}.mp3")
    sound.export(
        f"{an_audio_file}.wav", format="wav", parameters=["-ar", "8000", "-ac", "1"]
    )


def create_audio_file(message_text, file_name):
    """
    Creates an audio file from the provided text using Google Text-to-Speech (gTTS).

    This function generates an MP3 file from the text, converts it to a WAV file with the required parameters,
    and saves it to the serving audio folder if it does not already exist.

    Args:
        message_text (str): The text to convert to speech.
        file_name (str): The base filename (without extension) for the audio file.

    Returns:
        None
    """

    if not os.path.exists(f"{SERVING_AUDIO_FOLDER}/{file_name}.wav"):
        name_of_file = f"{SERVING_AUDIO_FOLDER}/{file_name}"

        def audio_creation():
            """
            Generates an MP3 file from the provided text using Google Text-to-Speech and converts it to WAV format.

            This function saves the MP3 file, converts it to a WAV file with the required parameters, and logs the operation.

            Returns:
                None
            """
            tts = gTTS(message_text, lang=GCLOUD_TTS_LANGUAGE_CODE)
            tts.save(f"{name_of_file}.mp3")
            mp3_to_wave(f"{name_of_file}")
            logging.info(f'Audio content written to file "{file_name}.wav"')

        try:
            audio_creation()
        except Exception as e:
            print(f"Unable to create the audio file {e}")

    else:
        logging.info(f'Audio file "{file_name}.wav" already exist...')


if __name__ == "__main__":
    # TODO make it usable from the command line...
    create_audio_file("Audio di Test", "pino")
