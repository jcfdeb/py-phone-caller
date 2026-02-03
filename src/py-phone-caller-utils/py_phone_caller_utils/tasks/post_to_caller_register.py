"""
Helper to post scheduled calls directly to the Call Register service.
"""

import requests

from py_phone_caller_utils.tasks.constants import (
    CALL_REGISTER_URL,
    CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE,
)


URL = f"{CALL_REGISTER_URL}/{CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE}"


def insert_the_scheduled_call(phone, message, scheduled_at):
    """
    Sends a scheduled call request to the call register service with the provided details.

    This function posts the phone number, message, and scheduled time to the configured URL and returns the HTTP status code.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message to be delivered during the call.
        scheduled_at (str): The scheduled time for the call in string format.

    Returns:
        int: The HTTP status code returned by the call register service.
    """
    data = {"phone": phone, "message": message, "scheduled_at": scheduled_at}
    response = requests.post(URL, params=data)
    return response.status_code
