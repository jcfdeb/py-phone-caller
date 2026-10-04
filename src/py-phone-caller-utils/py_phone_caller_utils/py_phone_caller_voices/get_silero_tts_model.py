#!/usr/bin/env python3
import argparse
import asyncio
import logging
import os
from pathlib import Path
import httpx
from py_phone_caller_utils.config import settings

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)

logger = logging.getLogger(__name__)

SILERO_MODELS_BASE_DIR = getattr(
    settings.generate_audio, "pre_trained_models_folder", "pre_trained_models"
)
SILERO_MODELS_FOLDER = getattr(
    settings.generate_audio, "silero_models_folder", "silero_tts"
)
SILERO_DEFAULT_LANG = getattr(settings.generate_audio, "silero_lang", "en")

SILERO_MODELS = {
    "en": {
        "url": "https://models.silero.ai/models/tts/en/v3_en.pt",
        "filename": "v3_en.pt",
        "default_speaker": "en_0",
    },
    "ru": {
        "url": "https://models.silero.ai/models/tts/ru/v4_ru.pt",
        "filename": "v4_ru.pt",
        "default_speaker": "kseniya",
    },
    "de": {
        "url": "https://models.silero.ai/models/tts/de/v3_de.pt",
        "filename": "v3_de.pt",
        "default_speaker": "thorsten",
    },
    "es": {
        "url": "https://models.silero.ai/models/tts/es/v3_es.pt",
        "filename": "v3_es.pt",
        "default_speaker": "es_0",
    },
    "fr": {
        "url": "https://models.silero.ai/models/tts/fr/v3_fr.pt",
        "filename": "v3_fr.pt",
        "default_speaker": "fr_0",
    },
    "indic": {
        "url": "https://models.silero.ai/models/tts/indic/v3_indic.pt",
        "filename": "v3_indic.pt",
        "default_speaker": "hindi_female",
    },
}


async def download_file(client: httpx.AsyncClient, url: str, dest_path: Path) -> bool:
    """
    Asynchronously download a file from a URL to a destination path.
    """
    logger.info(f"Downloading {url} to {dest_path}...")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")

    try:
        async with client.stream("GET", url, follow_redirects=True) as response:
            if response.status_code != 200:
                logger.error(f"Failed to download {url}: HTTP status {response.status_code}")
                return False

            with open(tmp_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    f.write(chunk)

        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            if os.path.exists(dest_path):
                os.remove(dest_path)
            tmp_path.rename(dest_path)
            logger.info(f"Model saved successfully to {dest_path} ({os.path.getsize(dest_path)} bytes)")
            return True
        else:
            logger.error(f"Downloaded file {tmp_path} is empty")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return False
    except Exception as e:
        logger.error(f"Error while downloading {url}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


async def download_silero_model_async(language_code: str, base_dir: str = None) -> str:
    """
    Download Silero TTS model for the specified language into the target directory.
    Returns path to downloaded model file.
    """
    lang = language_code.lower().strip()
    if lang not in SILERO_MODELS:
        raise ValueError(
            f"Unsupported Silero language code: '{language_code}'. "
            f"Supported languages: {list(SILERO_MODELS.keys())}"
        )

    model_info = SILERO_MODELS[lang]
    url = model_info["url"]
    filename = model_info["filename"]

    if base_dir:
        base_dir_path = Path(base_dir)
        if base_dir_path.name == SILERO_MODELS_FOLDER:
            dest_dir = base_dir_path / lang
        elif (base_dir_path / SILERO_MODELS_FOLDER).exists() or base_dir_path.name == "pre_trained_models":
            dest_dir = base_dir_path / SILERO_MODELS_FOLDER / lang
        else:
            dest_dir = base_dir_path / SILERO_MODELS_FOLDER / lang
    else:
        dest_dir = Path(SILERO_MODELS_BASE_DIR) / SILERO_MODELS_FOLDER / lang

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    if dest_path.exists() and dest_path.stat().st_size > 1024 * 1024:
        logger.info(f"Silero model for '{lang}' is already present at {dest_path}")
        return str(dest_path)

    async with httpx.AsyncClient(timeout=120.0) as client:
        success = await download_file(client, url, dest_path)
        if not success:
            raise RuntimeError(f"Failed to download Silero model for '{lang}' from {url}")

    return str(dest_path)


async def main_async():
    parser = argparse.ArgumentParser(
        description="Download Silero TTS model checkpoints for offline telephony use"
    )
    parser.add_argument(
        "--language",
        "-l",
        type=str,
        default=SILERO_DEFAULT_LANG,
        help="Language code for the Silero model (e.g., 'en', 'ru', 'de', 'es', 'fr', 'indic')",
    )
    parser.add_argument(
        "--base-dir",
        "-d",
        type=str,
        default=SILERO_MODELS_BASE_DIR,
        help="Base directory where models will be saved",
    )
    parser.add_argument(
        "--multiple",
        "-m",
        nargs="+",
        help="Download multiple languages at once (e.g., -m en ru de)",
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Download all supported Silero TTS models",
    )

    args = parser.parse_args()

    targets = []
    if args.all:
        targets = list(SILERO_MODELS.keys())
    elif args.multiple:
        targets = args.multiple
    else:
        targets = [args.language]

    for lang in targets:
        await download_silero_model_async(lang, args.base_dir)


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
