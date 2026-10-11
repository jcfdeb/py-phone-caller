"""
Checksum helpers used across services to generate compact, stable identifiers
for calls and messages.
"""

from __future__ import annotations
from hashlib import blake2b
from typing import Any

DIGEST_SIZE: int = 4
ENCODING: str = "utf-8"


async def gen_call_chk_sum(phone: str, message: str) -> str:
    """
    Generates a checksum to uniquely identify a call based on the phone number and message.

    This asynchronous function computes a Blake2b hash using the phone and message as input.

    Args:
        phone: The recipient's phone number.
        message: The message content.

    Returns:
        The hexadecimal string representation of the checksum.
    """
    return blake2b(
        bytes(phone, encoding=ENCODING) + bytes(message, encoding=ENCODING),
        digest_size=DIGEST_SIZE,
    ).hexdigest()


async def gen_msg_chk_sum(message: str) -> str:
    """
    Generates a checksum to uniquely identify a message based on its content.

    This asynchronous function computes a Blake2b hash using the message as input.

    Args:
        message: The message content.

    Returns:
        The hexadecimal string representation of the checksum.
    """
    return blake2b(
        bytes(message, encoding=ENCODING), digest_size=DIGEST_SIZE
    ).hexdigest()


async def gen_unique_chk_sum(phone: str, message: str, first_dial: Any) -> str:
    """
    Generates a unique checksum for a call attempt based on the phone number, message, and first dial timestamp.

    This asynchronous function computes a Blake2b hash using the phone, message, and first dial time as input.

    Args:
        phone: The recipient's phone number.
        message: The message content.
        first_dial: The timestamp of the first dial attempt.

    Returns:
        The hexadecimal string representation of the unique checksum.
    """
    return blake2b(
        bytes(phone, encoding=ENCODING)
        + bytes(message, encoding=ENCODING)
        + bytes(str(first_dial), encoding=ENCODING),
        digest_size=DIGEST_SIZE,
    ).hexdigest()


__all__ = [
    "DIGEST_SIZE",
    "ENCODING",
    "gen_call_chk_sum",
    "gen_msg_chk_sum",
    "gen_unique_chk_sum",
]
