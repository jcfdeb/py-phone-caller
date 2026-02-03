from py_phone_caller_utils.config import settings

SECONDS_TO_FORGET = settings.asterisk_call.seconds_to_forget
TIMES_TO_DIAL = settings.asterisk_recaller.times_to_dial
ACKNOWLEDGE_ERROR = settings.logs.acknowledge_error
HEARD_ERROR = settings.logs.heard_error
CALL_REGISTER_APP_ROUTE_REGISTER_CALL = (
    settings.call_register.call_register_app_route_register_call
)
CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE = (
    settings.call_register.call_register_app_route_voice_message
)
CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE = (
    settings.call_register.call_register_scheduled_call_app_route
)
CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE = (
    settings.call_register.call_register_app_route_acknowledge
)
CALL_REGISTER_APP_ROUTE_HEARD = settings.call_register.call_register_app_route_heard
CALL_REGISTER_PORT = int(settings.call_register.call_register_port)
LOCAL_TIMEZONE = settings.scheduled_calls.local_timezone
VOICE_MESSAGE_ERROR = settings.logs.voice_message_error
REGISTER_CALL_ERROR = settings.logs.register_call_error
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
LOST_PARAMETERS_ERROR = settings.logs.get(
    "lost_parameters_error", "Lost parameters 'phone', 'message', or 'scheduled_at'..."
)
