import logging
import os.path

from gtts import gTTS
from pydub import AudioSegment

import local_utils.caller_configuration as conf

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(thread)s %(funcName)s %(message)s"
)

# Define a folder to store the audio files
SERVING_AUDIO_FOLDER = conf.get_serving_audio_folder()
GCLOUD_TTS_LANGUAGE_CODE = conf.get_gcloud_tts_language_code()


def mp3_to_wave(an_audio_file):
    sound = AudioSegment.from_mp3(f"{an_audio_file}.mp3")
    sound.export(
        f"{an_audio_file}.wav", format="wav", parameters=["-ar", "8000", "-ac", "1"]
    )


def create_audio_file(message_text, file_name):
    """This function creates the audio file to be server through HTTP"""

    if not os.path.exists(f"{SERVING_AUDIO_FOLDER}/{file_name}.wav"):
        name_of_file = f"{SERVING_AUDIO_FOLDER}/{file_name}"

        def audio_creation():
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
    create_audio_file(
        "Audio di Test", "pino"
    )  # TODO Doesn't work without paramenters...
