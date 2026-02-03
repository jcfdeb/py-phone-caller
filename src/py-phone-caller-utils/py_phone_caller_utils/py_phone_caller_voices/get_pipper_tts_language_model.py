#!/usr/bin/env python3
import argparse
import asyncio
import logging
from pathlib import Path

import httpx

from py_phone_caller_utils.config import settings

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)

PIPER_VOICES_URL = settings.generate_audio.piper_voices_url
PIPER_BASE_URL = PIPER_VOICES_URL.replace("tree/main", "resolve/main")
PIPER_VOICES_JSON_URL = f"{PIPER_BASE_URL}/voices.json"
PIPER_MODELS_BASE_DIR = settings.generate_audio.pre_trained_models_folder
PIPER_MODELS_SUBDIR = settings.generate_audio.piper_models_folder

logger = logging.getLogger(__name__)


async def download_file(client, url, dest_path):
    """
    Asynchronously download a file from a URL to a destination path.
    """
    logger.info(f"Downloading {url} to {dest_path}...")
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    async with client.stream("GET", url, follow_redirects=True) as response:
        if response.status_code != 200:
            logger.error(f"Failed to download {url}: Status {response.status_code}")
            return False

        with open(dest_path, "wb") as f:
            async for chunk in response.aiter_bytes():
                f.write(chunk)
    return True


async def download_piper_model_async(language_code, base_dir):
    """
    Download Piper TTS model for the specified language and save it locally with normalized names.
    """
    async with httpx.AsyncClient() as client:
        logger.info(f"Fetching voices.json from {PIPER_VOICES_JSON_URL}")
        response = await client.get(PIPER_VOICES_JSON_URL, follow_redirects=True)
        if response.status_code != 200:
            logger.error(f"Failed to fetch voices.json: Status {response.status_code}")
            return

        voices_data = response.json()

        voice_id = None
        voice_info = None
        for vid, info in voices_data.items():
            if info.get("language", {}).get("code") == language_code:
                voice_id = vid
                voice_info = info
                break

        if not voice_id:
            logger.error(f"No Piper voice found for language code: {language_code}")
            return

        logger.info(f"Found voice: {voice_id}")

        files = voice_info.get("files", {})
        onnx_remote_path = None
        json_remote_path = None
        model_card_remote_path = None

        for f_path in files.keys():
            if f_path.endswith(".onnx"):
                onnx_remote_path = f_path
            elif f_path.endswith(".onnx.json"):
                json_remote_path = f_path
            elif f_path.endswith("MODEL_CARD"):
                model_card_remote_path = f_path

        if not onnx_remote_path:
            logger.error(f"No .onnx file found for voice: {voice_id}")
            return

        dest_dir = Path(base_dir) / PIPER_MODELS_SUBDIR / language_code
        dest_dir.mkdir(parents=True, exist_ok=True)

        files_to_download = [
            (onnx_remote_path, dest_dir / f"{language_code}.onnx"),
        ]

        if json_remote_path:
            files_to_download.append(
                (json_remote_path, dest_dir / f"{language_code}.onnx.json")
            )

        if model_card_remote_path:
            files_to_download.append((model_card_remote_path, dest_dir / "MODEL_CARD"))
        else:
            lang_short = language_code.split("_")[0]
            voice_name = voice_info.get("name")
            quality = voice_info.get("quality")
            hf_voice_path = f"{lang_short}/{language_code}/{voice_name}/{quality}"
            files_to_download.append(
                (f"{hf_voice_path}/MODEL_CARD", dest_dir / "MODEL_CARD")
            )

        for hf_path, dest_path in files_to_download:
            url = f"{PIPER_BASE_URL}/{hf_path}"
            success = await download_file(client, url, dest_path)
            if not success and "MODEL_CARD" in hf_path:
                logger.warning("Could not download MODEL_CARD, continuing...")

        logger.info(
            f"Piper model for '{language_code}' saved successfully to {dest_dir}"
        )


async def main_async():
    parser = argparse.ArgumentParser(
        description="Download Piper TTS models for offline use"
    )
    parser.add_argument(
        "--language",
        "-l",
        type=str,
        default=settings.generate_audio.piper_language_code,
        help="Language code for the Piper model (e.g., 'it_IT', 'en_US', 'es_ES')",
    )
    parser.add_argument(
        "--base-dir",
        "-d",
        type=str,
        default=PIPER_MODELS_BASE_DIR,
        help="Base directory where the model will be saved",
    )
    parser.add_argument(
        "--multiple",
        "-m",
        nargs="+",
        help="Download multiple languages at once (e.g., -m it_IT en_US es_ES)",
    )

    args = parser.parse_args()

    try:
        if args.multiple:
            for lang in args.multiple:
                await download_piper_model_async(lang, args.base_dir)
        else:
            await download_piper_model_async(args.language, args.base_dir)

    except Exception as e:
        logger.error(f"An error occurred when downloading Piper TTS model: {e}")
        raise


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
