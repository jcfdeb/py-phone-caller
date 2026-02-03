from py_phone_caller_utils.config import settings


CALLER_SMS_PORT = int(settings.caller_sms.caller_sms_port)
CALLER_SMS_APP_ROUTE = settings.caller_sms.caller_sms_app_route
TWILIO_SMS_FROM = settings.caller_sms.twilio_sms_from
NUM_OF_CPUS = settings.generate_audio.num_of_cpus
LOG_FORMATTER = settings.logs.log_formatter
CALLER_SMS_ERROR = settings.logs.caller_sms_error
TWILIO_ACCOUNT_SID = settings.caller_sms.twilio_account_sid
TWILIO_AUTH_TOKEN = settings.caller_sms.twilio_auth_token
CALLER_SMS_CARRIER = settings.caller_sms.caller_sms_carrier
LOG_LEVEL = settings.logs.log_level
