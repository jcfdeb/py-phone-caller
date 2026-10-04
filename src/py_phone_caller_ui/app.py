"""
Py Phone Caller UI application.

Flask-based web UI for managing calls, schedules, users, WS events, address
book, and SMS. Integrates with the backend services and exposes multiple blueprints.
Features full internationalization (i18n) across 10 locales via Flask-Babel
and a real-time NOC Telemetry Dashboard.
"""

import asyncio
import logging
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)


from py_phone_caller_ui.calls import calls_blueprint
from flask import Flask, render_template, url_for, jsonify, Response, request, session, redirect
from flask_babel import Babel, gettext as _
from py_phone_caller_utils.web.swagger import generate_swagger_ui_html, build_openapi_schema
from flask_login import LoginManager
from py_phone_caller_ui.home import home_blueprint
from py_phone_caller_ui.login import login_blueprint
from py_phone_caller_ui.schedule_call import schedule_call_blueprint
from py_phone_caller_ui.users import users_blueprint
from py_phone_caller_ui.ws_events import ws_events_blueprint
from py_phone_caller_ui.address_book import address_book_blueprint
from py_phone_caller_ui.sms import sms_blueprint

from py_phone_caller_utils.env_validator import run_startup_health_banner
run_startup_health_banner('py_phone_caller_ui')
from py_phone_caller_utils.login.user import User
from py_phone_caller_utils.py_phone_caller_db.db_user import (
    ensure_admin_user_exists,
    load_user_by_id,
    reset_admin_password_if_needed,
)
from py_phone_caller_utils.telemetry import init_telemetry, instrument_flask_app
from datetime import datetime, timedelta
import pytz

from py_phone_caller_ui.constants import (
    UI_SESSION_PROTECTION,
    UI_SECRET_KEY,
    UI_LISTEN_ON_HOST,
    UI_LISTEN_ON_PORT,
    UI_ADMIN_USER,
    LOG_FORMATTER,
    LOG_LEVEL,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
logging.info(f"Logging initialized with level {LOG_LEVEL}")

init_telemetry("py_phone_caller_ui")

login_manager = LoginManager()
login_manager.session_protection = UI_SESSION_PROTECTION

app = Flask(
    __name__,
    root_path=current_dir,
    static_folder="static",
    static_url_path="/static",
)

instrument_flask_app(app)

app.config["SECRET_KEY"] = UI_SECRET_KEY
app.config["SESSION_PERMANENT"] = False

# i18n & Locales Configuration
SUPPORTED_LOCALES = {
    "en": {"name": "English", "flag": "🇬🇧", "dir": "ltr"},
    "es": {"name": "Español", "flag": "🇪🇸", "dir": "ltr"},
    "it": {"name": "Italiano", "flag": "🇮🇹", "dir": "ltr"},
    "de": {"name": "Deutsch", "flag": "🇩🇪", "dir": "ltr"},
    "fr": {"name": "Français", "flag": "🇫🇷", "dir": "ltr"},
    "ru": {"name": "Русский", "flag": "🇷🇺", "dir": "ltr"},
    "zh": {"name": "中文 (Chinese)", "flag": "🇨🇳", "dir": "ltr"},
    "hi": {"name": "हिन्दी (Hindi)", "flag": "🇮🇳", "dir": "ltr"},
    "he": {"name": "עברית (Hebrew)", "flag": "🇮🇱", "dir": "rtl"},
    "ar": {"name": "العربية (Arabic)", "flag": "🇸🇦", "dir": "rtl"},
}

LOCALE_ALIASES = {
    "zh_cn": "zh",
    "zh-cn": "zh",
    "zh_hans": "zh",
    "zh-hans": "zh",
    "zh_sg": "zh",
    "zh-sg": "zh",
    "zh_tw": "zh",
    "zh-tw": "zh",
    "hi_in": "hi",
    "hi-in": "hi",
    "es_es": "es",
    "es-es": "es",
    "it_it": "it",
    "it-it": "it",
    "de_de": "de",
    "de-de": "de",
    "fr_fr": "fr",
    "fr-fr": "fr",
    "ru_ru": "ru",
    "ru-ru": "ru",
    "en_us": "en",
    "en-us": "en",
    "en_gb": "en",
    "en-gb": "en",
    "he_il": "he",
    "he-il": "he",
    "ar_sa": "ar",
    "ar-sa": "ar",
    "ar_eg": "ar",
    "ar-eg": "ar",
    "ar_ae": "ar",
    "ar-ae": "ar",
}


def resolve_locale(code: str | None) -> str | None:
    """
    Resolves standard or regional language code to a supported UI locale.
    """
    if not code:
        return None
    normalized = code.strip().lower().replace("-", "_")
    if normalized in SUPPORTED_LOCALES:
        return normalized
    if normalized in LOCALE_ALIASES:
        return LOCALE_ALIASES[normalized]
    prefix = normalized.split("_")[0]
    if prefix in SUPPORTED_LOCALES:
        return prefix
    return None


def get_locale():
    """
    Negotiates locale with persistent priority:
    1. Explicit session preference
    2. Persistent HTTP cookie
    3. Accept-Language header best match
    4. Default fallback: 'en'
    """
    if "locale" in session:
        resolved = resolve_locale(session["locale"])
        if resolved:
            return resolved
    cookie_loc = request.cookies.get("locale")
    if cookie_loc:
        resolved = resolve_locale(cookie_loc)
        if resolved:
            return resolved
    candidates = list(SUPPORTED_LOCALES.keys()) + list(LOCALE_ALIASES.keys())
    best = request.accept_languages.best_match(candidates)
    if best:
        resolved = resolve_locale(best)
        if resolved:
            return resolved
    return "en"


app.config["BABEL_DEFAULT_LOCALE"] = "en"
app.config["BABEL_TRANSLATION_DIRECTORIES"] = os.path.join(current_dir, "translations")

babel = Babel(app, locale_selector=get_locale)

logging.info(f"Flask app initialized with static_folder: {app.static_folder}")
logging.info(f"Flask app initialized with static_url_path: {app.static_url_path}")

login_manager.init_app(app)
login_manager.login_view = "login_blueprint.login"


@app.context_processor
def inject_now():
    return {"now": datetime.now(pytz.utc), "timedelta": timedelta}


@app.context_processor
def inject_locale_info():
    curr = get_locale()
    return {
        "current_locale": curr,
        "current_locale_meta": SUPPORTED_LOCALES.get(curr, SUPPORTED_LOCALES["en"]),
        "supported_locales": SUPPORTED_LOCALES,
        "_": _,
    }


@app.route("/set_locale/<lang_code>")
def set_locale(lang_code):
    """
    Switches the UI language, persisting choice in session and long-lived cookie.
    """
    resolved = resolve_locale(lang_code)
    lang = resolved if resolved else "en"
    session["locale"] = lang
    target = request.referrer or url_for("home_blueprint.home")
    resp = redirect(target)
    resp.set_cookie("locale", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@login_manager.unauthorized_handler
def unauthorized():
    """
    Handles unauthorized access attempts by rendering the unauthorized page.

    This function returns the unauthorized.html template with a link to the login page.

    Returns:
        flask.Response: The rendered HTML unauthorized page.

    https://flask-login.readthedocs.io/en/latest/#customizing-the-login-process
    """

    return render_template(
        "unauthorized.html", login_url=url_for("login_blueprint.login")
    )


@login_manager.user_loader
def load_user(user_id):
    """
    Loads a user for Flask-Login based on the provided user ID.

    This function retrieves the user record from the database and returns a User object if found, or None otherwise.

    Args:
        user_id (str): The unique identifier of the user.

    Returns:
        User or None: The User object if found, or None if the user does not exist.
    """
    loaded_user = load_user_by_id(user_id)
    if loaded_user is None:
        return None
    return User(username=loaded_user.get("email"))


app.register_blueprint(login_blueprint)
app.register_blueprint(home_blueprint)
app.register_blueprint(calls_blueprint)
app.register_blueprint(schedule_call_blueprint)
app.register_blueprint(users_blueprint)
app.register_blueprint(ws_events_blueprint)
app.register_blueprint(address_book_blueprint)
app.register_blueprint(sms_blueprint)


# OpenAPI 3.0 /docs Swagger UI specification for the Web Dashboard
@app.route("/docs")
def ui_swagger_docs():
    return Response(
        generate_swagger_ui_html(
            title="py-phone-caller Web UI API",
            openapi_url="/docs/swagger.json",
        ),
        mimetype="text/html",
    )


@app.route("/docs/swagger.json")
def ui_swagger_json():
    schema = build_openapi_schema(
        title="py-phone-caller Web UI",
        description="Web dashboard, metrics visualization, and administrative REST endpoints",
        version="1.0.0",
        paths={
            "/": {
                "get": {
                    "summary": "Home dashboard with real-time KPI metrics and call resolution statistics"
                }
            },
            "/api/dashboard_metrics": {
                "get": {
                    "summary": "Real-time NOC Telemetry metrics JSON for dashboard widgets"
                }
            },
            "/set_locale/{lang_code}": {
                "get": {
                    "summary": "Set current session & cookie UI language"
                }
            },
            "/calls/": {"get": {"summary": "Call registry log view"}},
            "/address_book/": {"get": {"summary": "Address book contact manager"}},
            "/sms/": {"get": {"summary": "SMS delivery history and message logs"}},
            "/schedule_call/": {"get": {"summary": "Call scheduling interface"}},
            "/users/": {"get": {"summary": "User management"}},
            "/ws_events/": {
                "get": {"summary": "Live WebSocket Stasis call events view"}
            },
            "/health": {"get": {"summary": "Application health check"}},
            "/metrics": {"get": {"summary": "Prometheus metrics endpoint"}},
        },
    )
    return jsonify(schema)


async def _setup_admin_user_async():
    """Internal async function to handle admin user setup."""
    created_admin_password = await ensure_admin_user_exists(UI_ADMIN_USER)
    if created_admin_password is None:
        await reset_admin_password_if_needed(UI_ADMIN_USER)


def setup_admin_user():
    """
    Ensures that an admin user exists and resets the admin password if required by environment settings.

    This function checks environment variables and the user table, performing password reset or admin user creation as needed.

    Returns:
        None
    """
    is_reseted = os.environ.get("UI_ADMIN_PASSWORD_RESETED")
    logging.debug(f"Checking admin user setup. UI_ADMIN_PASSWORD_RESETED: {is_reseted}")

    if not is_reseted:
        logging.debug("Performing admin user setup...")
        try:
            asyncio.run(_setup_admin_user_async())
            os.environ["UI_ADMIN_PASSWORD_RESETED"] = "True"
            logging.debug("Admin user setup completed successfully.")
        except Exception as e:
            logging.error(f"Failed to setup admin user: {e}", exc_info=True)


setup_admin_user()

if __name__ == "__main__":
    app.run(host=UI_LISTEN_ON_HOST, port=UI_LISTEN_ON_PORT)
