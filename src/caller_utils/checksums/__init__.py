from hashlib import blake2b

DIGEST_SIZE = 4
ENCODING = "utf-8"


# Checksum functions
async def gen_call_chk_sum(phone, message):
    """Generates a call checksum in order correlate a phone number and a message"""
    return blake2b(
        bytes(phone, encoding=ENCODING) + bytes(message, encoding=ENCODING),
        digest_size=DIGEST_SIZE,
    ).hexdigest()


async def gen_msg_chk_sum(message):
    """Generates a checksum in order to identify the message"""
    return blake2b(
        bytes(message, encoding=ENCODING), digest_size=DIGEST_SIZE
    ).hexdigest()


async def gen_unique_chk_sum(phone, message, first_dial):
    """Generates a checksum in order to identify every single call"""
    return blake2b(
        bytes(phone, encoding=ENCODING)
        + bytes(message, encoding=ENCODING)
        + bytes(str(first_dial), encoding=ENCODING),
        digest_size=DIGEST_SIZE,
    ).hexdigest()
