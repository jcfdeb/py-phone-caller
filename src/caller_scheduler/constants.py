from py_phone_caller_utils.config import settings

SCHEDULED_CALL_APP_ROUTE = settings.scheduled_calls.scheduled_call_app_route
SCHEDULED_CALLS_PORT = int(settings.scheduled_calls.scheduled_calls_port)
LOCAL_TIMEZONE = settings.scheduled_calls.local_timezone
SCHEDULED_CALL_ERROR = settings.logs.scheduled_call_error
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
