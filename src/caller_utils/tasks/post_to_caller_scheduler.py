import requests

import caller_utils.caller_configuration as conf

URL = f"{conf.get_scheduled_call_url()}/{conf.get_scheduled_call_app_route()}"


def enqueue_the_call(phone, message, scheduled_at):
    """
    Tries to enqueue a call through the 'caller_scheduler'
    :param phone: Phone number
    :param message: Message (str)
    :param scheduled_at: Time and date where the call should be answered
    """
    data = {"phone": phone, "message": message, "scheduled_at": scheduled_at}
    response = requests.post(URL, params=data)
    return response.status_code
