from py_phone_caller_utils.config import settings

ASTERISK_CALL_URL = f"{settings.asterisk_call.asterisk_call_http_scheme}://{settings.asterisk_call.asterisk_call_host}:{settings.asterisk_call.asterisk_call_port}"
ASTERISK_CALL_APP_ROUTE_PLACE_CALL = (
    settings.asterisk_call.asterisk_call_app_route_place_call
)
SMS_BEFORE_CALL_WAIT_SECONDS = settings.caller_sms.sms_before_call_wait_seconds
CALLER_SMS_URL = f"{settings.caller_sms.caller_sms_http_scheme}://{settings.caller_sms.caller_sms_host}:{settings.caller_sms.caller_sms_port}"
CALLER_SMS_APP_ROUTE = settings.caller_sms.caller_sms_app_route
CLIENT_TIMEOUT_TOTAL = settings.asterisk_call.client_timeout_total
PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY = (
    settings.caller_prometheus_webhook.prometheus_webhook_app_route_call_only
)
PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY = (
    settings.caller_prometheus_webhook.prometheus_webhook_app_route_sms_only
)
PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL = (
    settings.caller_prometheus_webhook.prometheus_webhook_app_route_sms_before_call
)
PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS = (
    settings.caller_prometheus_webhook.prometheus_webhook_app_route_call_and_sms
)
PROMETHEUS_WEBHOOK_PORT = int(settings.caller_prometheus_webhook.prometheus_webhook_port)
PROMETHEUS_WEBHOOK_RECEIVERS = (
    settings.caller_prometheus_webhook.prometheus_webhook_receivers
)
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
