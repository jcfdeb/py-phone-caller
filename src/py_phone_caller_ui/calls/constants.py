from py_phone_caller_utils.config import settings


CALL_REGISTER_HTTP_SCHEME = settings.call_register.call_register_http_scheme
CALL_REGISTER_HOST = settings.call_register.call_register_host
CALL_REGISTER_PORT = int(settings.call_register.call_register_port)
CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE = (
    settings.call_register.call_register_app_route_acknowledge
)
CALL_REGISTER_ENDPOINT = f"{CALL_REGISTER_HTTP_SCHEME}://{CALL_REGISTER_HOST}:{CALL_REGISTER_PORT}/{CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE}"
