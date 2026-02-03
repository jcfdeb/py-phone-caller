from py_phone_caller_utils.config import settings

ASTERISK_CALL_URL = f"{settings.asterisk_call.asterisk_call_http_scheme}://{settings.asterisk_call.asterisk_call_host}:{settings.asterisk_call.asterisk_call_port}"
ASTERISK_CALL_APP_ROUTE_PLACE_CALL = (
    settings.asterisk_call.asterisk_call_app_route_place_call
)
SLEEP_BEFORE_QUERYING = 10
TIMES_TO_DIAL = settings.asterisk_recaller.times_to_dial
CALL_BACKUP_CALLEE_MAX_TIMES = settings.asterisk_recaller.call_backup_callee_max_times
SECONDS_TO_FORGET = settings.asterisk_call.seconds_to_forget
SLEEP_AND_RETRY = SECONDS_TO_FORGET / (TIMES_TO_DIAL + 1)
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
