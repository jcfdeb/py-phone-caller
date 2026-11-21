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
SMS_SAAS_FALLBACK = bool(getattr(settings.caller_sms, "sms_saas_fallback", False))
SMS_SIP_MESSAGE_ENABLED = bool(
    getattr(settings.caller_sms, "sms_sip_message_enabled", True)
)

ASTERISK_URL = f"{settings.commons.asterisk_http_scheme}://{settings.commons.asterisk_host}:{settings.commons.asterisk_web_port}"
ASTERISK_USER = settings.commons.asterisk_user
ASTERISK_PASS = settings.commons.asterisk_pass
ASTERISK_CHAN_TYPE = settings.asterisk_call.asterisk_chan_type
ASTERISK_CALLER_ID = settings.asterisk_call.asterisk_caller_id

CALLER_ADDRESS_BOOK_URL = (
    f"{settings.caller_address_book.caller_address_book_http_scheme}://"
    f"{settings.caller_address_book.caller_address_book_host}:"
    f"{settings.caller_address_book.caller_address_book_port}"
)
CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT = (
    settings.caller_address_book.caller_address_book_route_on_call_contact
)
