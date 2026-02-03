"""
Configuration constants for the Py Phone Caller UI.
"""

from py_phone_caller_utils.config import settings


CALL_REGISTER_URL = f"{settings.call_register.call_register_http_scheme}://{settings.call_register.call_register_host}:{settings.call_register.call_register_port}"
CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE = (
    settings.call_register.call_register_scheduled_call_app_route
)
SCHEDULED_CALL_URL = f"{settings.scheduled_calls.scheduled_calls_http_scheme}://{settings.scheduled_calls.scheduled_calls_host}:{settings.scheduled_calls.scheduled_calls_port}"
SCHEDULED_CALL_APP_ROUTE = settings.scheduled_calls.scheduled_call_app_route
UI_SESSION_PROTECTION = settings.py_phone_caller_ui.ui_session_protection
UI_SECRET_KEY = settings.py_phone_caller_ui.ui_secret_key
UI_LISTEN_ON_HOST = settings.py_phone_caller_ui.ui_listen_on_host
UI_LISTEN_ON_PORT = int(settings.py_phone_caller_ui.ui_listen_on_port)
UI_ADMIN_USER = settings.py_phone_caller_ui.ui_admin_user
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
