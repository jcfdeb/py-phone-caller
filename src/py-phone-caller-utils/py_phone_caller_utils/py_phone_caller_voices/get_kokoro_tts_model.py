#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
from pathlib import Path
from huggingface_hub import hf_hub_download
from py_phone_caller_utils.config import settings

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)

logger = logging.getLogger(__name__)

REPO_ID = getattr(settings.generate_audio, "kokoro_repo_id", "hexgrad/Kokoro-82M")
MODEL_FILENAME = getattr(
    settings.generate_audio, "kokoro_model_filename", "kokoro-v1_0.pth"
)
KOKORO_MODELS_BASE_DIR = getattr(
    settings.generate_audio, "pre_trained_models_folder", "pre_trained_models"
)
KOKORO_MODELS_FOLDER = getattr(
    settings.generate_audio, "kokoro_models_folder", "kokoro_tts"
)

# Default voice file for each language code
DEFAULT_VOICES = {
    "a": "af_heart",  # American English (female)
    "b": "bf_emma",  # British English (female)
    "e": "ef_dora",  # Spanish (female)
    "f": "ff_siwis",  # French (female)
    "h": "hf_alpha",  # Hindi (female)
    "i": "if_sara",  # Italian (female)
    "j": "jf_alpha",  # Japanese (female)
    "p": "pf_dora",  # Brazilian Portuguese (female)
    "z": "zf_xiaobei",  # Mandarin Chinese (female)
}


async def download_kokoro_model_async(
    base_dir=None,
    voice_names=None,
    download_all_voices=False,
    repo_id=None,
    model_filename=None,
):
    """
    Download Kokoro TTS model (config, weights, voices) using huggingface_hub into the target directory.
    """
    repo_id = repo_id or REPO_ID
    model_filename = model_filename or MODEL_FILENAME

    if base_dir:
        base_dir_path = Path(base_dir)
        if base_dir_path.name == KOKORO_MODELS_FOLDER:
            dest_dir = base_dir_path
        else:
            dest_dir = base_dir_path / KOKORO_MODELS_FOLDER
    else:
        dest_dir = Path(KOKORO_MODELS_BASE_DIR) / KOKORO_MODELS_FOLDER

    dest_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()

    try:
        logger.info(
            f"Checking/Downloading config.json and {model_filename} from {repo_id} to {dest_dir}..."
        )

        # 1. Download config.json
        await loop.run_in_executor(
            None,
            lambda: hf_hub_download(
                repo_id=repo_id,
                filename="config.json",
                local_dir=str(dest_dir),
            ),
        )

        # 2. Download model weights
        model_path = await loop.run_in_executor(
            None,
            lambda: hf_hub_download(
                repo_id=repo_id,
                filename=model_filename,
                local_dir=str(dest_dir),
            ),
        )

        # 3. Voices to download
        voices_dir = dest_dir / "voices"
        voices_dir.mkdir(parents=True, exist_ok=True)

        voices_to_download = set()
        if download_all_voices:
            for voice in DEFAULT_VOICES.values():
                voices_to_download.add(voice)
        elif voice_names:
            if isinstance(voice_names, str):
                voices_to_download.add(voice_names)
            else:
                for v in voice_names:
                    voices_to_download.add(v)
        else:
            for voice in DEFAULT_VOICES.values():
                voices_to_download.add(voice)

        for voice in voices_to_download:
            voice_clean = voice.replace(".pt", "")
            voice_filename = f"voices/{voice_clean}.pt"
            logger.info(f"Checking/Downloading voice '{voice_clean}' from {repo_id}...")
            await loop.run_in_executor(
                None,
                lambda vf=voice_filename: hf_hub_download(
                    repo_id=repo_id,
                    filename=vf,
                    local_dir=str(dest_dir),
                ),
            )

        logger.info(f"Kokoro model and voices saved successfully to: {dest_dir}")
        return str(dest_dir)
    except Exception as e:
        logger.error(f"Failed to download Kokoro model: {e}")
        raise


async def main_async():
    parser = argparse.ArgumentParser(
        description="Download Kokoro TTS model and voices for offline use"
    )
    parser.add_argument(
        "--base-dir",
        "-d",
        type=str,
        default=KOKORO_MODELS_BASE_DIR,
        help="Base directory where the model will be saved",
    )
    parser.add_argument(
        "--repo-id",
        type=str,
        default=REPO_ID,
        help="Hugging Face repository ID",
    )
    parser.add_argument(
        "--model-filename",
        type=str,
        default=MODEL_FILENAME,
        help="Model filename on Hugging Face Hub (e.g., kokoro-v1_0.pth)",
    )
    parser.add_argument(
        "--voice",
        "-v",
        type=str,
        help="Specific voice name to download (e.g., af_heart, ef_dora)",
    )
    parser.add_argument(
        "--all-voices",
        "-a",
        action="store_true",
        help="Download all default voices for all supported languages",
    )

    args = parser.parse_args()

    voice_names = [args.voice] if args.voice else None
    await download_kokoro_model_async(
        base_dir=args.base_dir,
        voice_names=voice_names,
        download_all_voices=args.all_voices,
        repo_id=args.repo_id,
        model_filename=args.model_filename,
    )


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
