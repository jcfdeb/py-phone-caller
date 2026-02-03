#!/usr/bin/env python3
import asyncio
import logging
from huggingface_hub import hf_hub_download
from py_phone_caller_utils.config import settings

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)

logger = logging.getLogger(__name__)

REPO_ID = settings.generate_audio.kokoro_repo_id
MODEL_FILENAME = settings.generate_audio.kokoro_model_filename


async def download_kokoro_model_async(base_dir=None):
    """
    Download Kokoro TTS model (v1.0) using huggingface_hub.
    This ensures the model is present in the HuggingFace cache.
    """
    loop = asyncio.get_running_loop()
    try:
        logger.info(f"Checking/Downloading {MODEL_FILENAME} from {REPO_ID}...")
        # Run synchronous hf_hub_download in executor
        model_path = await loop.run_in_executor(
            None, lambda: hf_hub_download(repo_id=REPO_ID, filename=MODEL_FILENAME)
        )
        logger.info(f"Kokoro model found/downloaded at: {model_path}")
        return model_path
    except Exception as e:
        logger.error(f"Failed to download Kokoro model: {e}")
        raise


async def main_async():
    await download_kokoro_model_async()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
