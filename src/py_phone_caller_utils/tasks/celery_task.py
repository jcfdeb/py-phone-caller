import requests
from celery import Celery

import py_phone_caller_utils.caller_configuration as conf

BROKER_URL = f"{conf.get_queue_url()}/0"
URL = f"{conf.get_asterisk_call_url()}/{conf.get_asterisk_call_app_route_place_call()}"
app = Celery("tasks", broker=BROKER_URL)


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
