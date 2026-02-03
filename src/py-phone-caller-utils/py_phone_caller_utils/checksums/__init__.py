"""
Checksum helpers used across services to generate compact, stable identifiers
for calls and messages.
"""

from hashlib import blake2b

DIGEST_SIZE = 4
ENCODING = "utf-8"


# Checksum functions
async def gen_call_chk_sum(phone, message):
    """
    Generates a checksum to uniquely identify a call based on the phone number and message.

    This asynchronous function computes a Blake2b hash using the phone and message as input.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message content.

    Returns:
        str: The hexadecimal string representation of the checksum.
    """
    return blake2b(
        bytes(phone, encoding=ENCODING) + bytes(message, encoding=ENCODING),
        digest_size=DIGEST_SIZE,
    ).hexdigest()


async def gen_msg_chk_sum(message):
    """
    Generates a checksum to uniquely identify a message based on its content.

    This asynchronous function computes a Blake2b hash using the message as input.

    Args:
        message (str): The message content.

    Returns:
        str: The hexadecimal string representation of the checksum.
    """
    return blake2b(
        bytes(message, encoding=ENCODING), digest_size=DIGEST_SIZE
    ).hexdigest()


async def gen_unique_chk_sum(phone, message, first_dial):
    """
    Generates a unique checksum for a call attempt based on the phone number, message, and first dial timestamp.

    This asynchronous function computes a Blake2b hash using the phone, message, and first dial time as input.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message content.
        first_dial (Any): The timestamp of the first dial attempt.

    Returns:
        str: The hexadecimal string representation of the unique checksum.
    """
    return blake2b(
        bytes(phone, encoding=ENCODING)
        + bytes(message, encoding=ENCODING)
        + bytes(str(first_dial), encoding=ENCODING),
        digest_size=DIGEST_SIZE,
    ).hexdigest()
