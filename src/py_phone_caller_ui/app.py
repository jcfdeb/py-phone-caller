"""
Py Phone Caller UI application.

Flask-based web UI for managing calls, schedules, users, WS events, and address
book. Integrates with the backend services and exposes multiple blueprints.
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
from flask import Flask, render_template, url_for
from flask_login import LoginManager
from py_phone_caller_ui.home import home_blueprint
from py_phone_caller_ui.login import login_blueprint
from py_phone_caller_ui.schedule_call import schedule_call_blueprint
from py_phone_caller_ui.users import users_blueprint
from py_phone_caller_ui.ws_events import ws_events_blueprint
from py_phone_caller_ui.address_book import address_book_blueprint

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

logging.info(f"Flask app initialized with static_folder: {app.static_folder}")
logging.info(f"Flask app initialized with static_url_path: {app.static_url_path}")

login_manager.init_app(app)
login_manager.login_view = "login_blueprint.login"


@app.context_processor
def inject_now():
    return {"now": datetime.now(pytz.utc), "timedelta": timedelta}


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


async def _setup_admin_user_async():
    """Internal async function to handle admin user setup."""
    await ensure_admin_user_exists(UI_ADMIN_USER)
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
