#!/usr/bin/env python3
import argparse
import asyncio
import functools
import logging
from concurrent.futures import ThreadPoolExecutor

from transformers import AutoTokenizer, VitsModel

import py_phone_caller_utils.caller_configuration as conf

logging.basicConfig(format=conf.get_log_formatter())

FACEBOOK_MMS_LANGUAGE_CODE = conf.get_facebook_mms_language_code()
MMS_MODEL_INSTALL_DIR = "pre_trained_models/facebook"

logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor()


async def run_in_executor(func, *args, **kwargs):
    """
    Runs a synchronous function in a thread pool executor asynchronously.

    This asynchronous utility function allows blocking or CPU-bound functions to be executed without blocking the event loop.

    Args:
        func (callable): The function to execute.
        *args: Positional arguments to pass to the function.
        **kwargs: Keyword arguments to pass to the function.

    Returns:
        Any: The result returned by the executed function.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        executor, functools.partial(func, *args, **kwargs)
    )


async def download_mms_model_async(language, model_dir):
    """
    Asynchronously download an MMS TTS model for the specified language and save it locally.

    Args:
        language (str): Language code for the MMS model (e.g., 'eng', 'fra', 'spa')
        model_dir (str): Directory where the model will be saved
    """
    model_name = f"mms-tts-{language}"
    model_id = f"facebook/{model_name}"

    logger.info(f"Downloading model {model_id}...")

    model = await run_in_executor(VitsModel.from_pretrained, model_id)
    tokenizer = await run_in_executor(AutoTokenizer.from_pretrained, model_id)

    save_path = f"./{model_dir}/{model_name}"
    logger.info(f"Saving model to {save_path}...")

    await asyncio.gather(
        run_in_executor(model.save_pretrained, save_path),
        run_in_executor(tokenizer.save_pretrained, save_path),
    )

    logger.info(f"Model '{model_id}' saved successfully!")


async def main_async():
    """
    Parses command-line arguments and downloads one or more Facebook MMS TTS models asynchronously.

    This asynchronous function handles argument parsing, initiates model downloads for specified languages,
    and logs the progress and any errors encountered during the process.

    Returns:
        None
    """

    parser = argparse.ArgumentParser(
        description="Download MMS TTS models for offline use"
    )

    parser.add_argument(
        "--language",
        "-l",
        type=str,
        default=FACEBOOK_MMS_LANGUAGE_CODE,
        help="Language code for the MMS model (e.g., 'eng', 'fra', 'spa', 'deu')",
    )

    parser.add_argument(
        "--model-dir",
        "-d",
        type=str,
        default=MMS_MODEL_INSTALL_DIR,
        help="Directory where the model will be saved",
    )

    parser.add_argument(
        "--multiple",
        "-m",
        nargs="+",
        help="Download multiple languages at once (e.g., -m eng fra spa) "
        + "More info regardin the supported languages: "
        + "https://dl.fbaipublicfiles.com/mms/misc/language_coverage_mms.html",
    )

    args = parser.parse_args()

    try:
        if args.multiple:
            languages = args.multiple
            logger.info(
                f"Starting download process for languages: {', '.join(languages)}"
            )

            tasks = []
            for lang in languages:
                tasks.append(download_mms_model_async(lang, args.model_dir))

            await asyncio.gather(*tasks)
            logger.info("All models downloaded successfully!")
        else:
            logger.info(
                f"Starting download process for language '{args.language}' to directory '{args.model_dir}'"
            )
            await download_mms_model_async(args.language, args.model_dir)

    except Exception as e:
        logger.error(
            f"An error occurred when downloading the Facebook MMS (TTS) model: {e}"
        )
        raise


def main():
    """
    Main entry point for the Facebook MMS language model downloader script.

    This function runs the asynchronous main_async function to handle argument parsing and model downloads.

    Example usage:
        #: python get_fb_mms_language_model.py --multiple spa eng rus fra vie deu

    Returns:
        None
    """
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
