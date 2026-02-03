"""
Celery task to invoke the Asterisk Caller HTTP endpoint at the scheduled time.
"""

import requests
import logging
from celery import Celery

from py_phone_caller_utils.tasks.constants import (
    BROKER_URL,
    URL,
    LOG_FORMATTER,
    LOG_LEVEL,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
app = Celery("tasks", broker=BROKER_URL)

app.conf.enable_utc = True
app.conf.timezone = "UTC"


@app.task
def do_this_call(phone, message):
    """
    Executes a call task by sending a POST request to the Asterisk call endpoint with the provided phone and message.

    This Celery task posts the call data to the configured URL and returns the HTTP status code of the response.

    Args:
        phone (str): The recipient's phone number.
        message (str): The message to be delivered during the call.

    Returns:
        int: The HTTP status code returned by the Asterisk call endpoint.
    """
    data = {"phone": phone, "message": message}
    response = requests.post(URL, params=data)
    return response.status_code
