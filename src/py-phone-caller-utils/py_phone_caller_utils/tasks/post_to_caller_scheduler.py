"""
Helper to post scheduled calls to the Caller Scheduler service.
"""

import requests

from py_phone_caller_utils.tasks.constants import (
    SCHEDULED_CALL_URL,
    SCHEDULED_CALL_APP_ROUTE,
)


URL = f"{SCHEDULED_CALL_URL}/{SCHEDULED_CALL_APP_ROUTE}"


def enqueue_the_call(phone, message, scheduled_at):
    """
    Sends a scheduled call request to the caller scheduler service with the provided details.

    This function posts the phone number, message, and scheduled time to the configured URL and returns the HTTP status code.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message to be delivered during the call.
        scheduled_at (str): The scheduled time for the call in string format.

    Returns:
        int: The HTTP status code returned by the caller scheduler service.
    """
    data = {"phone": phone, "message": message, "scheduled_at": scheduled_at}
    response = requests.post(URL, params=data)
    return response.status_code
