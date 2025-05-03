import logging
from dataclasses import dataclass
from os import environ

import toml

logging.basicConfig(format="%(asctime)s - %(message)s", level=logging.INFO)


def from_file():
    """try to load the configuration from file"""
    try:
        return toml.load(Config.get_path_to_conf())
    except FileNotFoundError:
        logging.info(f"Configuration file '{Config.get_path_to_conf()}' not found.")


def get_asterisk_user():
    """Returns the Asterisk user, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_USER", conf_table="commons", conf_value="asterisk_user"
    )


def get_asterisk_pass():
    """Returns the Asterisk password for the user, can be retrieved
    from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_PASS", conf_table="commons", conf_value="asterisk_pass"
    )


def get_asterisk_host():
    """Returns the Asterisk host/IP, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_HOST", conf_table="commons", conf_value="asterisk_host"
    )


def get_asterisk_web_port():
    """Returns the Asterisk HTTP port (also for WebSocket),
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_WEB_PORT",
        conf_table="commons",
        conf_value="asterisk_web_port",
    )


def get_asterisk_http_scheme():
    """Returns the scheme ('http' or 'https') to compose the URL to reach the
    Asterisk server (is the first part of the URL).,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_HTTP_SCHEME",
        conf_table="commons",
        conf_value="asterisk_http_scheme",
    )


def get_asterisk_url():
    """Composes the URL to reach the Asterisk PBX 'scheme://host:port'"""
    return f"{get_asterisk_http_scheme()}://{get_asterisk_host()}:{get_asterisk_web_port()}"


def get_asterisk_ari_channels():
    """Returns the path, part of the URL ('ari/channels'), to make a POST
    request against the Asterisk ARI in order to start a call. Comes,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_ARI_CHANNELS",
        conf_table="asterisk_call",
        conf_value="asterisk_ari_channels",
    )


def get_asterisk_ari_play():
    """Returns the query string ('play?media=sound') to be used in order
    to play sounds though the 'Stasis' mode, can be retrieved from
    env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_ARI_PLAY",
        conf_table="asterisk_call",
        conf_value="asterisk_ari_play",
    )


def get_asterisk_context():
    """Returns the Asterisk 'context' where the dial plan for 'py-phone-caller'
    is configured, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_CONTEXT",
        conf_table="asterisk_call",
        conf_value="asterisk_context",
    )


def get_asterisk_extension():
    """Returns the Asterisk extension used in the 'context' for 'py-phone-caller'.
    Example: 'exten => 3216,1,Noop()', the extension number is of your choice.py.
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_EXTENSION",
        conf_table="asterisk_call",
        conf_value="asterisk_extension",
    )


def get_asterisk_chan_type():
    """Returns the Asterisk channel where to start the call for the callee,
    possible options:
        'SIP/some-configured-trunk': in order to call through a SIP provider
        'SIP': to call a local SIP extension, consider that the callee number must be a valid extension
        'IAX2/some-configured-trunk': in order to call through a IAX provider or other PBX instance
        'DAHDI': in order to call through a DAHDI channel
    Can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_CHAN_TYPE",
        conf_table="asterisk_call",
        conf_value="asterisk_chan_type",
    )


def get_asterisk_caller_id():
    """Returns the Asterisk Caller ID, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_CALLER_ID",
        conf_table="asterisk_call",
        conf_value="asterisk_caller_id",
    )


def get_call_register_http_scheme():
    """Returns the HTTP scheme to be used within 'call_register',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="CALL_REGISTER_HTTP_SCHEME",
        conf_table="call_register",
        conf_value="call_register_http_scheme",
    )


def get_call_register_host():
    """Returns the host/IP  to be used within the 'call_register',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="CALL_REGISTER_HOST",
        conf_table="call_register",
        conf_value="call_register_host",
    )


def get_call_register_port():
    """Returns the TCP port where the 'call_register' is listening,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="CALL_REGISTER_PORT",
        conf_table="call_register",
        conf_value="call_register_port",
    )


def get_call_register_url():
    """Composes the URL to reach the 'call_register' component, 'scheme://host:port'"""
    return f"{get_call_register_http_scheme()}://{get_call_register_host()}:{get_call_register_port()}"


def get_call_register_app_route_register_call():
    """Returns the path or route where the 'call_register' is waiting for a
    HTTP POST in order for register a call into the DB.
    Example value: 'register_call'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="CALL_REGISTER_APP_ROUTE_REGISTER_CALL",
        conf_table="call_register",
        conf_value="call_register_app_route_register_call",
    )


def get_call_register_app_route_voice_message():
    """Returns the path or route where the 'call_register' is waiting for an
    HTTP POST in order for register the text fo the message into the DB.
    Example value: 'msg'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE",
        conf_table="call_register",
        conf_value="call_register_app_route_voice_message",
    )


def get_call_register_app_route_acknowledge():
    """Returns the path or route where the 'call_register' is waiting for an
    HTTP GET from the Asterisk PBX in order for register, into the DB, if the
    call was acknowledged (Boolean). Example value: 'ack'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE",
        conf_table="call_register",
        conf_value="call_register_app_route_acknowledge",
    )


def get_call_register_app_route_heard():
    """Returns the path or route where the 'call_register' is waiting for an
    HTTP GET from the Asterisk PBX in order to register, into the DB, if the
    audio message was played to the callee (datetime). Example value: 'heard'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="CALL_REGISTER_APP_ROUTE_HEARD",
        conf_table="call_register",
        conf_value="call_register_app_route_heard",
    )


def get_call_register_scheduled_call_app_route():
    """Returns the path or route where the 'call_register' is waiting for an
    HTTP POST from the 'py-phone-caller-ui' in order to register, into the DB, the
    scheduled calls. Example value: 'scheduled_call'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE",
        conf_table="call_register",
        conf_value="call_register_scheduled_call_app_route",
    )


def get_gcloud_tts_language_code():
    """Returns the language code to be used to generate the audio files,
    an example can be: 'it' for Italian, 'en' for English and 'es' for Spanish.
    Please use one at once, no multiple values yet allowed.
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="GCLOUD_TTS_LANGUAGE_CODE",
        conf_table="generate_audio",
        conf_value="gcloud_tts_language_code",
    )


def get_aws_polly_region_name():
    """Returns the AWS Polly region name, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="AWS_POLLY_REGION_NAME",
        conf_table="generate_audio",
        conf_value="aws_polly_region_name",
    )


def get_aws_polly_voice():
    """Returns the AWS Polly voice, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="AWS_POLLY_VOICE",
        conf_table="generate_audio",
        conf_value="aws_polly_voice",
    )


def get_serving_audio_folder():
    """Returns the folder where the audio files are placed in the 'generate_audio',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="SERVING_AUDIO_FOLDER",
        conf_table="generate_audio",
        conf_value="serving_audio_folder",
    )


def get_is_audio_ready_endpoint():
    """Returns the folder where the audio files are placed in the 'generate_audio',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="IS_AUDIO_READY_ENDPOINT",
        conf_table="generate_audio",
        conf_value="is_audio_ready_endpoint",
    )


def get_tts_engine():
    """Returns the pre-trained models folder, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="TTS_ENGINE",
        conf_table="generate_audio",
        conf_value="tts_engine",
    )


def get_pre_trained_models_folder():
    """Returns the pre-trained models folder, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="PRE_TRAINED_MODELS_FOLDER",
        conf_table="generate_audio",
        conf_value="pre_trained_models_folder",
    )


def get_facebook_mms_models_folder():
    """Returns the Facebook MMS models folder, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="FACEBOOK_MMS_MODELS_FOLDER",
        conf_table="generate_audio",
        conf_value="facebook_mms_models_folder",
    )


def get_facebook_mms_language_code():
    """Returns the Facebook MMS language code, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="FACEBOOK_MMS_LANGUAGE_CODE",
        conf_table="generate_audio",
        conf_value="facebook_mms_language_code",
    )


def get_facebook_mms_num2words_language_code():
    """Returns the Facebook MMS language code, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="FACEBOOK_MMS_NUM2WORDS_LANGUAGE_CODE",
        conf_table="generate_audio",
        conf_value="facebook_mms_num2words_language_code",
    )


def get_piper_models_folder():
    """Returns the Piper models folder, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="PIPER_MODELS_FOLDER",
        conf_table="generate_audio",
        conf_value="piper_models_folder",
    )


def get_piper_language_code():
    """Returns the Piper language code, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="PIPER_LANGUAGE_CODE",
        conf_table="generate_audio",
        conf_value="piper_language_code",
    )


def get_piper_python_interpreter():
    """Returns the Piper python interpreter path, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="PIPER_PYTHON_INTERPRETER",
        conf_table="generate_audio",
        conf_value="piper_python_interpreter",
    )


def get_asterisk_call_http_scheme():
    """Returns the HTTP scheme to be used within the 'asterisk_call',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_CALL_HTTP_SCHEME",
        conf_table="asterisk_call",
        conf_value="asterisk_call_http_scheme",
    )


def get_asterisk_call_host():
    """Returns the HOST or the IP address where the 'asterisk_call',
    is listening, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_CALL_HOST",
        conf_table="asterisk_call",
        conf_value="asterisk_call_host",
    )


def get_asterisk_call_port():
    """Returns the TCP port where the 'asterisk_call' is listening,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_CALL_PORT",
        conf_table="asterisk_call",
        conf_value="asterisk_call_port",
    )


def get_asterisk_call_url():
    """Composes the URL to reach the 'asterisk_call' component, 'scheme://host:port'"""
    return f"{get_asterisk_call_http_scheme()}://{get_asterisk_call_host()}:{get_asterisk_call_port()}"


def get_asterisk_call_app_route_place_call():
    """Returns the path or route where the 'asterisk_call' is waiting for a
    HTTP POST in order to start a call against the Asterisk PBX.
    Example value: 'schedule_call'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="ASTERISK_CALL_APP_ROUTE_PLACE_CALL",
        conf_table="asterisk_call",
        conf_value="asterisk_call_app_route_place_call",
    )


def get_asterisk_call_app_route_call_to_queue():
    """Returns the path or route where the 'asterisk_call' is waiting for a
    HTTP POST in order to enqueue a call to be placed through the Asterisk PBX.
    Example value: 'call_to_queue'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE",
        conf_table="asterisk_call",
        conf_value="asterisk_call_app_route_call_to_queue",
    )


def get_asterisk_call_app_route_play():
    """Returns the path or route where the 'asterisk_call' is waiting for a
    HTTP POST in order to make the Asterisk PBX play the audio message in a given channel.
    Example value: 'play'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="ASTERISK_CALL_APP_ROUTE_PLAY",
        conf_table="asterisk_call",
        conf_value="asterisk_call_app_route_play",
    )


def get_seconds_to_forget():
    """Returns the amount of seconds to the retry cycles of every single
    call. This amount of time is divided by the 'times_to_dial',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="SECONDS_TO_FORGET",
        conf_table="asterisk_call",
        conf_value="seconds_to_forget",
    )


def get_generate_audio_http_scheme():
    """Returns the HTTP scheme to be used to reach the 'generate_audio,
    can be retrieved from env var or configuration file.
    Asterisk reads the audio file through HTTP by calling the 'generate_audio' URL"""
    return Config.get_var_value(
        env_var="GENERATE_AUDIO_HTTP_SCHEME",
        conf_table="generate_audio",
        conf_value="generate_audio_http_scheme",
    )


def get_generate_audio_host():
    """Returns the HOST or IP in order to reach the 'generate_audio',
    can be retrieved from env var or configuration file.
    Asterisk reads the audio file through HTTP"""
    return Config.get_var_value(
        env_var="GENERATE_AUDIO_HOST",
        conf_table="generate_audio",
        conf_value="generate_audio_host",
    )


def get_generate_audio_port():
    """Returns the TCP port where the 'generate_audio' is listening,
    can be retrieved from env var or configuration file.
    Asterisk reads the audio file through HTTP"""
    return Config.get_var_value(
        env_var="GENERATE_AUDIO_PORT",
        conf_table="generate_audio",
        conf_value="generate_audio_port",
    )


def get_generate_audio_url():
    """Composes the URL to reach the 'generate_audio' component, 'scheme://host:port'"""
    return f"{get_generate_audio_http_scheme()}://{get_generate_audio_host()}:{get_generate_audio_port()}"


def get_generate_audio_app_route():
    """Returns the path or route where the 'generate_audio' is waiting for a
    HTTP POST in order to create the audio message to be played by Asterisk.
    Example value: 'make_audio'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="GENERATE_AUDIO_APP_ROUTE",
        conf_table="generate_audio",
        conf_value="generate_audio_app_route",
    )


def get_client_timeout_total():
    """Returns the timeout for the 'aiohttp' ClientSession, can be retrieved
    from env var or configuration file."""
    return Config.get_var_value(
        env_var="CLIENT_TIMEOUT_TOTAL",
        conf_table="asterisk_call",
        conf_value="client_timeout_total",
    )


def get_asterisk_stasis_app():
    """
    Returns the name of the Asterisk Stasis application used for ARI integration.

    This function retrieves the value from environment variables or the configuration file.
    See: https://wiki.asterisk.org/wiki/display/AST/Asterisk+16+Application_Stasis

    Returns:
        str: The name of the Asterisk Stasis application.
    """
    return Config.get_var_value(
        env_var="ASTERISK_STASIS_APP",
        conf_table="asterisk_ws_monitor",
        conf_value="asterisk_stasis_app",
    )


def get_times_to_dial():
    """
    Returns the number of times to dial in case of no response for a call attempt.

    This function retrieves the value from environment variables or the configuration file.

    Returns:
        int: The number of dial attempts to make before giving up.
    """
    return Config.get_var_value(
        env_var="TIMES_TO_DIAL",
        conf_table="asterisk_recall",
        conf_value="times_to_dial",
    )


def get_num_of_cpus():
    """
    Returns the number of CPUs to use for launching the ThreadPoolExecutor in audio generation.

    This function retrieves the value from environment variables or the configuration file.

    Returns:
        int: The number of CPUs to use for thread pool execution.
    """
    return Config.get_var_value(
        env_var="NUM_OF_CPUS", conf_table="generate_audio", conf_value="num_of_cpus"
    )


def get_prometheus_webhook_port():
    """Returns the Prometheus Webhook TCP port to listen on,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="PROMETHEUS_WEBHOOK_PORT",
        conf_table="caller_prometheus_webhook",
        conf_value="prometheus_webhook_port",
    )


def get_prometheus_webhook_app_route_call_only():
    """change"""
    return Config.get_var_value(
        env_var="PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY",
        conf_table="caller_prometheus_webhook",
        conf_value="prometheus_webhook_app_route_call_only",
    )


def get_prometheus_webhook_app_route_sms_only():
    """change"""
    return Config.get_var_value(
        env_var="PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY",
        conf_table="caller_prometheus_webhook",
        conf_value="prometheus_webhook_app_route_sms_only",
    )


def get_prometheus_webhook_app_route_sms_before_call():
    """change"""
    return Config.get_var_value(
        env_var="PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL",
        conf_table="caller_prometheus_webhook",
        conf_value="prometheus_webhook_app_route_sms_before_call",
    )


def get_prometheus_webhook_app_route_call_and_sms():
    """change"""
    return Config.get_var_value(
        env_var="PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS",
        conf_table="caller_prometheus_webhook",
        conf_value="prometheus_webhook_app_route_call_and_sms",
    )


def get_prometheus_webhook_receivers():
    """Returns the Prometheus Webhook call and message receives,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="PROMETHEUS_WEBHOOK_RECEIVERS",
        conf_table="caller_prometheus_webhook",
        conf_value="prometheus_webhook_receivers",
    )


def get_caller_sms_http_scheme():
    """Returns the HTTP scheme to be used within the 'caller_sms',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="CALLER_SMS_HTTP_SCHEME",
        conf_table="caller_sms",
        conf_value="caller_sms_http_scheme",
    )


def get_caller_sms_host():
    """Returns the HOST or IP in order to reach the 'caller_sms',
    can be retrieved from env var or configuration file.
    Asterisk reads the audio file through HTTP"""
    return Config.get_var_value(
        env_var="CALLER_SMS_HOST",
        conf_table="caller_sms",
        conf_value="caller_sms_host",
    )


def get_caller_sms_port():
    """Returns the TCP port where the 'caller_sms' is listening,
    can be retrieved from env var or configuration file.
    Asterisk reads the audio file through HTTP"""
    return Config.get_var_value(
        env_var="CALLER_SMS_PORT",
        conf_table="caller_sms",
        conf_value="caller_sms_port",
    )


def get_caller_sms_url():
    """Composes the URL to reach the 'caller_sms' component, 'scheme://host:port'"""
    return f"{get_caller_sms_http_scheme()}://{get_caller_sms_host()}:{get_caller_sms_port()}"


def get_caller_sms_app_route():
    """Returns the path or route where the 'caller_sms' is waiting for a
    HTTP POST in order to send the SMS with the message.
    Example value: 'send_sms'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="CALLER_SMS_APP_ROUTE",
        conf_table="caller_sms",
        conf_value="caller_sms_app_route",
    )


def get_sms_before_call_wait_seconds():
    """Returns the number of seconds to wait after the SMS in order to start the call,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="SMS_BEFORE_CALL_WAIT_SECONDS",
        conf_table="caller_sms",
        conf_value="sms_before_call_wait_seconds",
    )


def get_caller_sms_carrier():
    """Returns the carrier/provider to use when sending SMS (Twilio, Betamax, etc.),
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="CALLER_SMS_CARRIER",
        conf_table="caller_sms",
        conf_value="caller_sms_carrier",
    )


def get_twilio_account_sid():
    """Returns the Twilio account SID, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="TWILIO_ACCOUNT_SID",
        conf_table="caller_sms",
        conf_value="twilio_account_sid",
    )


def get_twilio_auth_token():
    """Returns the Twilio Auth Token, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="TWILIO_AUTH_TOKEN",
        conf_table="caller_sms",
        conf_value="twilio_auth_token",
    )


def get_twilio_sms_from():
    """Returns the Twilio SMS from number, it will not work without this value configured.
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="TWILIO_SMS_FROM",
        conf_table="caller_sms",
        conf_value="twilio_sms_from",
    )


def get_db_host():
    """Returns the HOST or IP of the PostgreSQL instance,
    can be retrieved from env var or configuration file.
    More details at: https://magicstack.github.io/asyncpg/current/api/index.html"""
    return Config.get_var_value(
        env_var="DB_HOST", conf_table="database", conf_value="db_host"
    )


def get_db_port():
    """Returns the port of the PostgreSQL instance,
    can be retrieved from env var or configuration file.
    """
    return Config.get_var_value(
        env_var="DB_PORT", conf_table="database", conf_value="db_port"
    )


def get_db_name():
    """Returns the PostgreSQL database name,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="DB_NAME", conf_table="database", conf_value="db_name"
    )


def get_db_user():
    """Returns the PostgreSQL database user (please don't use the admin 'postgres'),
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="DB_USER", conf_table="database", conf_value="db_user"
    )


def get_db_password():
    """Returns the PostgreSQL password for the user that issues the connection,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="DB_PASSWORD", conf_table="database", conf_value="db_password"
    )


def get_db_dsn():
    """Returns the DB DNS (connection string) in the format
    postgres://user:password@host:port/database
    """
    return f"postgres://{get_db_user()}:{get_db_password()}@{get_db_host()}:{get_db_port()}/{get_db_name()}"


def get_db_max_size():
    """Returns the Max number of connections in the pool,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="DB_MAX_SIZE", conf_table="database", conf_value="db_max_size"
    )


def get_db_max_inactive_connection_lifetime():
    """Returns the Number of seconds after which inactive connections in the
    pool will be closed. Pass 0 to disable this mechanism,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="DB_MAX_INACTIVE_CONNECTION_LIFETIME",
        conf_table="database",
        conf_value="db_max_inactive_connection_lifetime",
    )


def get_scheduled_calls_http_scheme():
    """Returns the HTTP scheme to be used within 'caller_scheduler',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="SCHEDULED_CALLS_HTTP_SCHEME",
        conf_table="scheduled_calls",
        conf_value="scheduled_calls_http_scheme",
    )


def get_scheduled_calls_host():
    """Returns the host/IP  to be used within the 'caller_scheduler',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="SCHEDULED_CALLS_HOST",
        conf_table="scheduled_calls",
        conf_value="scheduled_calls_host",
    )


def get_scheduled_calls_port():
    """Returns the TCP port where the 'caller_scheduler' is listening,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="SCHEDULED_CALLS_PORT",
        conf_table="scheduled_calls",
        conf_value="scheduled_calls_port",
    )


def get_scheduled_call_url():
    """Composes the URL to reach the 'caller_scheduler' component, 'scheme://host:port'"""
    return f"{get_scheduled_calls_http_scheme()}://{get_scheduled_calls_host()}:{get_scheduled_calls_port()}"


def get_scheduled_call_app_route():
    """Returns the path or route where the 'caller_scheduler' is waiting for a
    HTTP POST in order to schedule a call.
    Example value: 'schedule_call'
    Note: use a single string 'correct' and not something this '/not/correct'"""
    return Config.get_var_value(
        env_var="SCHEDULED_CALL_APP_ROUTE",
        conf_table="scheduled_calls",
        conf_value="scheduled_call_app_route",
    )


def get_local_timezone():
    """
    Returns the local timezone to be able to convert to UTC when scheduling calls.
    """
    return Config.get_var_value(
        env_var="LOCAL_TIMEZONE",
        conf_table="scheduled_calls",
        conf_value="local_timezone",
    )


# not tested
def get_log_formatter():
    """Returns the format for the log 'Formatter(fmt=<The value configured in 'caller_config.toml'>)',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="LOG_FORMATTER", conf_table="logger", conf_value="log_formatter"
    )


def get_acknowledge_error():
    """Returns a custom text error for the '/ack' endpoint (call_register),
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ACKNOWLEDGE_ERROR", conf_table="logger", conf_value="acknowledge_error"
    )


def get_heard_error():
    """Returns a custom text error for the '/heard' endpoint (call_register),
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="HEARD_ERROR", conf_table="logger", conf_value="heard_error"
    )


def get_register_call_error():
    """Returns a custom text error for the '/' endpoint of 'call_register',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="REGISTER_CALL_ERROR",
        conf_table="logger",
        conf_value="register_call_error",
    )


def get_voice_message_error():
    """Returns the Asterisk user, can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="VOICE_MESSAGE_ERROR",
        conf_table="logger",
        conf_value="voice_message_error",
    )


def get_asterisk_call_error():
    """Returns a custom text error for the '/asterisk' endpoint of 'asterisk_call',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_CALL_ERROR",
        conf_table="logger",
        conf_value="asterisk_call_error",
    )


def get_asterisk_play_error():
    """Returns a custom text error for the '/play' endpoint of 'asterisk_call',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="ASTERISK_PLAY_ERROR",
        conf_table="logger",
        conf_value="asterisk_play_error",
    )


def get_generate_audio_error():
    """Returns a custom text error for the '/make_audio' endpoint of 'generate_audio',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="GENERATE_AUDIO_ERROR",
        conf_table="logger",
        conf_value="generate_audio_error",
    )


def get_lost_directory_error():
    """Returns a custom text error to be used when there's a problem with
    the 'audio/ folder part of 'generate_audio'. Can be retrieved from env
    var or configuration file."""
    return Config.get_var_value(
        env_var="LOST_DIRECTORY_ERROR",
        conf_table="logger",
        conf_value="lost_directory_error",
    )


def get_caller_sms_error():
    """Returns a custom text error for the '/' endpoint of 'caller_sms',
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="CALLER_SMS_ERROR",
        conf_table="logger",
        conf_value="caller_sms_error",
    )


def get_ws_url():
    """Composes the URL to reach the 'Asterisk' PBX ARI WebSocket interface,
    'scheme://host:port/ari/events?api_key=user:password&app=app_name'"""
    return (
        f"ws://{get_asterisk_host()}:{get_asterisk_web_port()}/ari/events"
        + f"?api_key={get_asterisk_user()}:{get_asterisk_pass()}&app={get_asterisk_stasis_app()}"
    )


def get_queue_scheme():
    """Returns the  scheme to be used within 'queue' backend of celery,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="QUEUE_SCHEME",
        conf_table="queue",
        conf_value="queue_scheme",
    )


def get_queue_host():
    """Returns the host/IP  where the 'queue' service is listening,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="QUEUE_HOST",
        conf_table="queue",
        conf_value="queue_host",
    )


def get_queue_port():
    """Returns the TCP port where the 'queue' service is listening,
    can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="QUEUE_PORT",
        conf_table="queue",
        conf_value="queue_port",
    )


def get_queue_url():
    """Composes the URL to reach the 'queue' service, 'scheme://host:port'"""
    return f"{get_queue_scheme()}://{get_queue_host()}:{get_queue_port()}"


def get_ui_admin_user():
    """Returns the admin user for the UI.
    Can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="UI_ADMIN_USER",
        conf_table="py_phone_caller_ui",
        conf_value="ui_admin_user",
    )


def get_ui_session_protection():
    """Returns the session protection level for the UI.
    Can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="UI_SESSION_PROTECTION",
        conf_table="py_phone_caller_ui",
        conf_value="ui_session_protection",
    )


def get_ui_secret_key():
    """Returns the secret key for the UI.
    Can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="UI_SECRET_KEY",
        conf_table="py_phone_caller_ui",
        conf_value="ui_secret_key",
    )


def get_ui_listen_on_host():
    """Returns the host/IP where the UI is listening.
    Can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="UI_LISTEN_ON_HOST",
        conf_table="py_phone_caller_ui",
        conf_value="ui_listen_on_host",
    )


def get_ui_listen_on_port():
    """Returns the TCP port where the UI is listening.
    Can be retrieved from env var or configuration file."""
    return Config.get_var_value(
        env_var="UI_LISTEN_ON_PORT",
        conf_table="py_phone_caller_ui",
        conf_value="ui_listen_on_port",
    )


@dataclass
class Config:
    """Central configuration management"""

    @staticmethod
    def _error_counter(counter=0):
        """
        Increments and returns an error counter for configuration retrieval attempts.

        This static method is used internally to track the number of failed attempts to retrieve a configuration value.

        Args:
            counter (int, optional): The current error count. Defaults to 0.

        Returns:
            int: The incremented error count.
        """
        counter += 1
        return counter

    @staticmethod
    def get_path_to_conf():
        """
        Returns the path to the configuration file, checking the environment variable first.

        This static method checks for the 'CALLER_CONFIG' environment variable and returns its value,
        or falls back to the default path if not set, logging the decision.

        Returns:
            str: The path to the configuration file.
        """
        try:
            assert environ.get("CALLER_CONFIG")
            return environ.get("CALLER_CONFIG")
        except AssertionError:
            logging.info(
                "No environmental variable 'CALLER_CONFIG' found for the configuration file."
            )
            logging.info("Using the default path 'config/caller_config.toml'")
            return "config/caller_config.toml"

    @staticmethod
    def get_var_value(
        conf_file=from_file,
        env_get=environ.get,
        env_var=None,
        conf_table=None,
        conf_value=None,
    ):
        """
        Retrieves a configuration value from environment variables or a configuration file.

        This static method first checks for the value in environment variables, then falls back to the configuration file.
        If the value is not found in either source, it logs an error and exits the program.

        Args:
            conf_file (callable, optional): Function to load the configuration file. Defaults to from_file.
            env_get (callable, optional): Function to get environment variables. Defaults to environ.get.
            env_var (str, optional): The name of the environment variable to check.
            conf_table (str, optional): The section/table in the configuration file.
            conf_value (str, optional): The key/value name in the configuration file.

        Returns:
            Any: The configuration value from the environment or configuration file.

        Raises:
            SystemExit: If the value cannot be found in either source.
        """

        errors = 0
        try:
            assert env_get(env_var)
            return environ.get(env_var)
        except AssertionError:
            errors += Config._error_counter()
            if environ.get("CALLER_CONFIG_VERBOSE", None):
                logging.info(
                    f"No values found for '{env_var}' in the environmental variables."
                )
        except TypeError:
            logging.info("No values values passed.")
        try:
            return conf_file().get(conf_table).get(conf_value)
        except AttributeError:
            errors += Config._error_counter()
            logging.info(
                f"No values found for 'asterisk_user' in the configuration file '{Config.get_path_to_conf()}'."
            )
        if errors == 2:
            logging.error(f"Unable to get the {conf_value}.")
            exit(1)
