"""
Constants for Celery tasks and HTTP endpoints used by the scheduler helpers.
"""

from py_phone_caller_utils.config import settings

BROKER_URL = f"{settings.queue.queue_url}"
ASTERISK_CALL_URL = f"{settings.asterisk_call.asterisk_call_http_scheme}://{settings.asterisk_call.asterisk_call_host}:{settings.asterisk_call.asterisk_call_port}"
URL = f"{ASTERISK_CALL_URL}/{settings.asterisk_call.asterisk_call_app_route_place_call}"
CALL_REGISTER_HTTP_SCHEME = settings.call_register.call_register_http_scheme
CALL_REGISTER_HOST = settings.call_register.call_register_host
CALL_REGISTER_PORT = int(settings.call_register.call_register_port)
CALL_REGISTER_URL = (
    f"{CALL_REGISTER_HTTP_SCHEME}://{CALL_REGISTER_HOST}:{CALL_REGISTER_PORT}"
)
CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE = (
    settings.call_register.call_register_scheduled_call_app_route
)
SCHEDULED_CALLS_HTTP_SCHEME = settings.scheduled_calls.scheduled_calls_http_scheme
SCHEDULED_CALLS_HOST = settings.scheduled_calls.scheduled_calls_host
SCHEDULED_CALLS_PORT = int(settings.scheduled_calls.scheduled_calls_port)
SCHEDULED_CALL_URL = (
    f"{SCHEDULED_CALLS_HTTP_SCHEME}://{SCHEDULED_CALLS_HOST}:{SCHEDULED_CALLS_PORT}"
)
SCHEDULED_CALL_APP_ROUTE = settings.scheduled_calls.scheduled_call_app_route
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
