import asyncio
import logging
from concurrent.futures.thread import ThreadPoolExecutor

from py_phone_caller_utils.sms.twilio_sms import sms_twilio
from caller_sms.constants import (
    TWILIO_SMS_FROM,
    NUM_OF_CPUS,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
)


async def sms_sender_async(message, phone_number):
    """
    Sends an SMS message asynchronously using a thread pool executor.

    This asynchronous function delegates the SMS sending task to a thread pool, allowing non-blocking execution.

    Args:
        message (str): The SMS message content to be sent.
        phone_number (str): The recipient's phone number.

    Returns:
        concurrent.futures.Future: A future representing the execution of the SMS sending task.
    """
    inner_loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=NUM_OF_CPUS)
    logging.info(f"Sending the SMS message '{message}' to '{phone_number}'")
    return inner_loop.run_in_executor(
        executor,
        sms_twilio,
        message,
        phone_number,
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN,
        TWILIO_SMS_FROM,
    )
