"""
Py Phone Caller UI application.

Flask-based web UI for managing calls, schedules, users, WS events, address
book, and SMS. Integrates with backend services and exposes multiple blueprints.
Features full internationalization (i18n) across 10 locales via Flask-Babel
and a real-time NOC Telemetry Dashboard.
"""

from __future__ import annotations
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

import pytz
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import Babel, gettext as _
from flask_login import LoginManager

from py_phone_caller_utils.env_validator import run_startup_health_banner
run_startup_health_banner("py_phone_caller_ui")

from py_phone_caller_utils.login.user import User
from py_phone_caller_utils.py_phone_caller_db.db_user import (
    ensure_admin_user_exists,
    load_user_by_id,
    reset_admin_password_if_needed,
)
from py_phone_caller_utils.telemetry import init_telemetry, instrument_flask_app
from py_phone_caller_utils.web.swagger import build_openapi_schema, generate_swagger_ui_html

from py_phone_caller_ui.address_book import address_book_blueprint
from py_phone_caller_ui.calls import calls_blueprint
from py_phone_caller_ui.constants import (
    LOG_FORMATTER,
    LOG_LEVEL,
    UI_ADMIN_USER,
    UI_LISTEN_ON_HOST,
    UI_LISTEN_ON_PORT,
    UI_SECRET_KEY,
    UI_SESSION_PROTECTION,
)
from py_phone_caller_ui.exceptions import (
    AdminBootstrapError,
    LocaleResolutionError,
    UiError,
    UserAuthenticationError,
)
from py_phone_caller_ui.home import home_blueprint
from py_phone_caller_ui.login import login_blueprint
from py_phone_caller_ui.schedule_call import schedule_call_blueprint
from py_phone_caller_ui.schemas import (
    AdminBootstrapResult,
    LocaleMeta,
    ServiceEndpointSummary,
    TextDirection,
)
from py_phone_caller_ui.services import (
    LOCALE_ALIASES,
    SUPPORTED_LOCALES,
    AdminBootstrapService,
    LocaleService,
    UserAuthenticationService,
)
from py_phone_caller_ui.sms import sms_blueprint
from py_phone_caller_ui.users import users_blueprint
from py_phone_caller_ui.ws_events import ws_events_blueprint

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
logging.info(f"Logging initialized with level {LOG_LEVEL}")

init_telemetry("py_phone_caller_ui")

# Core domain services
_locale_service = LocaleService(
    supported_locales=SUPPORTED_LOCALES,
    aliases=LOCALE_ALIASES,
    default_locale="en",
)
_auth_service = UserAuthenticationService(loader_fn=load_user_by_id)
_admin_service = AdminBootstrapService(admin_user=UI_ADMIN_USER)

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


def resolve_locale(code: str | None) -> str | None:
    """Resolves standard or regional language code to a supported UI locale."""
    return _locale_service.resolve_locale(code)


def get_locale() -> str:
    """Negotiates locale with persistent priority cascade."""
    session_loc = session.get("locale")
    cookie_loc = request.cookies.get("locale")
    return _locale_service.negotiate_locale(
        session_locale=session_loc,
        cookie_locale=cookie_loc,
        header_matcher=request.accept_languages.best_match,
    )


app.config["BABEL_DEFAULT_LOCALE"] = "en"
app.config["BABEL_TRANSLATION_DIRECTORIES"] = os.path.join(current_dir, "translations")

babel = Babel(app, locale_selector=get_locale)

logging.info(f"Flask app initialized with static_folder: {app.static_folder}")
logging.info(f"Flask app initialized with static_url_path: {app.static_url_path}")

login_manager.init_app(app)
login_manager.login_view = "login_blueprint.login"


@app.context_processor
def inject_now() -> dict[str, Any]:
    return {"now": datetime.now(pytz.utc), "timedelta": timedelta}


@app.context_processor
def inject_locale_info() -> dict[str, Any]:
    curr = get_locale()
    return {
        "current_locale": curr,
        "current_locale_meta": SUPPORTED_LOCALES.get(curr, SUPPORTED_LOCALES["en"]),
        "supported_locales": SUPPORTED_LOCALES,
        "_": _,
    }


@app.route("/set_locale/<lang_code>")
def set_locale(lang_code: str) -> Response:
    """Switches the UI language, persisting choice in session and long-lived cookie."""
    resolved = _locale_service.resolve_locale(lang_code)
    lang = resolved if resolved else "en"
    session["locale"] = lang
    target = request.referrer or url_for("home_blueprint.home")
    resp = redirect(target)
    resp.set_cookie("locale", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return resp


@login_manager.unauthorized_handler
def unauthorized() -> str:
    """Handles unauthorized access attempts by rendering the unauthorized page."""
    return render_template(
        "unauthorized.html", login_url=url_for("login_blueprint.login")
    )


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    """Loads a user for Flask-Login based on the provided user ID."""
    return _auth_service.load_user(user_id)


# Register modular blueprints
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
def ui_swagger_docs() -> Response:
    return Response(
        generate_swagger_ui_html(
            title="py-phone-caller Web UI API",
            openapi_url="/docs/swagger.json",
        ),
        mimetype="text/html",
    )


@app.route("/docs/swagger.json")
def ui_swagger_json() -> Response:
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


async def _setup_admin_user_async() -> None:
    """Internal async function to handle admin user setup."""
    created_admin_password = await ensure_admin_user_exists(UI_ADMIN_USER)
    if created_admin_password is None:
        await reset_admin_password_if_needed(UI_ADMIN_USER)


def setup_admin_user() -> None:
    """
    Ensures that an admin user exists and resets the admin password if required.
    """
    _admin_service.bootstrap()


setup_admin_user()

if __name__ == "__main__":
    app.run(host=UI_LISTEN_ON_HOST, port=UI_LISTEN_ON_PORT)
