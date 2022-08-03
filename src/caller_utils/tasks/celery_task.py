import requests
from celery import Celery

import caller_utils.caller_configuration as conf

BROKER_URL = f"{conf.get_queue_url()}/0"
URL = f"{conf.get_asterisk_call_url()}/{conf.get_asterisk_call_app_route_place_call()}"
app = Celery("tasks", broker=BROKER_URL)


@app.task
def do_this_call(phone, message):
    """Schedules a call in a given future time"""
    data = {"phone": phone, "message": message}
    response = requests.post(URL, params=data)
    return response.status_code
