from py_phone_caller_utils.config import settings

EVENT_TYPE = "StasisStart"
CHANNEL_STATE = "Up"
IS_AUDIO_READY_ENDPOINT = settings.generate_audio.is_audio_ready_endpoint
CALL_REGISTER_HTTP_SCHEME = settings.call_register.call_register_http_scheme
CALL_REGISTER_HOST = settings.call_register.call_register_host
CALL_REGISTER_PORT = int(settings.call_register.call_register_port)
CALL_REGISTER_URL = (
    f"{CALL_REGISTER_HTTP_SCHEME}://{CALL_REGISTER_HOST}:{CALL_REGISTER_PORT}"
)
CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE = (
    settings.call_register.call_register_app_route_voice_message
)
GENERATE_AUDIO_HTTP_SCHEME = settings.generate_audio.generate_audio_http_scheme
GENERATE_AUDIO_HOST = settings.generate_audio.generate_audio_host
GENERATE_AUDIO_PORT = int(settings.generate_audio.generate_audio_port)
GENERATE_AUDIO_URL = (
    f"{GENERATE_AUDIO_HTTP_SCHEME}://{GENERATE_AUDIO_HOST}:{GENERATE_AUDIO_PORT}"
)
GENERATE_AUDIO_APP_ROUTE = settings.generate_audio.generate_audio_app_route
ASTERISK_CALL_URL = f"{settings.asterisk_call.asterisk_call_http_scheme}://{settings.asterisk_call.asterisk_call_host}:{settings.asterisk_call.asterisk_call_port}"
ASTERISK_CALL_APP_ROUTE_PLAY = settings.asterisk_call.asterisk_call_app_route_play
ASTERISK_HOST = settings.commons.asterisk_host
ASTERISK_WEB_PORT = int(settings.commons.asterisk_web_port)
ASTERISK_USER = settings.commons.asterisk_user
ASTERISK_PASS = settings.commons.asterisk_pass
ASTERISK_STASIS_APP = settings.asterisk_ws_monitor.asterisk_stasis_app
WS_URL = (
    f"ws://{ASTERISK_HOST}:{ASTERISK_WEB_PORT}/ari/events"
    + f"?api_key={ASTERISK_USER}:{ASTERISK_PASS}&app={ASTERISK_STASIS_APP}"
)
LOG_FORMATTER = settings.logs.log_formatter
LOG_LEVEL = settings.logs.log_level
