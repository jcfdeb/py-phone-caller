from py_phone_caller_utils.config import settings
from multiprocessing import Queue

ASTERISK_URL = f"{settings.commons.asterisk_http_scheme}://{settings.commons.asterisk_host}:{settings.commons.asterisk_web_port}"
ASTERISK_EXTENSION = settings.asterisk_call.asterisk_extension
ASTERISK_CONTEXT = settings.asterisk_call.asterisk_context
ASTERISK_CALLER_ID = settings.asterisk_call.asterisk_caller_id
CALL_REGISTER_URL = f"{settings.call_register.call_register_http_scheme}://{settings.call_register.call_register_host}:{settings.call_register.call_register_port}"
CALL_REGISTER_APP_ROUTE_REGISTER_CALL = (
    settings.call_register.call_register_app_route_register_call
)
ASTERISK_CHAN_TYPE = settings.asterisk_call.asterisk_chan_type
ASTERISK_USER = settings.commons.asterisk_user
ASTERISK_PASS = settings.commons.asterisk_pass
CALLER_ADDRESS_BOOK_URL = f"{settings.caller_address_book.caller_address_book_http_scheme}://{settings.caller_address_book.caller_address_book_host}:{settings.caller_address_book.caller_address_book_port}"
CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT = (
    settings.caller_address_book.caller_address_book_route_on_call_contact
)
ASTERISK_ARI_CHANNELS = settings.asterisk_call.asterisk_ari_channels
ASTERISK_PLAY_ERROR = settings.logs.asterisk_play_error
GENERATE_AUDIO_URL = f"{settings.generate_audio.generate_audio_http_scheme}://{settings.generate_audio.generate_audio_host}:{settings.generate_audio.generate_audio_port}"
SERVING_AUDIO_FOLDER = settings.generate_audio.serving_audio_folder
ASTERISK_ARI_PLAY = settings.asterisk_call.asterisk_ari_play
ASTERISK_CALL_APP_ROUTE_PLACE_CALL = (
    settings.asterisk_call.asterisk_call_app_route_place_call
)
ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE = (
    settings.asterisk_call.asterisk_call_app_route_call_to_queue
)
ASTERISK_CALL_APP_ROUTE_PLAY = settings.asterisk_call.asterisk_call_app_route_play
ASTERISK_CALL_PORT = int(settings.asterisk_call.asterisk_call_port)
WAIT_FOR_CALL_CYCLE = settings.asterisk_call.seconds_to_forget
CLIENT_TIMEOUT_TOTAL = settings.asterisk_call.client_timeout_total
CALL_QUEUE = Queue()
ASTERISK_CALL_ERROR = settings.logs.asterisk_call_error
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
