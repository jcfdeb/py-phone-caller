import asyncio
import os

from calls import calls_blueprint
from flask import Flask, render_template, url_for
from flask_login import LoginManager
from home import home_blueprint
from login import login_blueprint
from schedule_call import schedule_call_blueprint
from users import users_blueprint
from ws_events import ws_events_blueprint

import py_phone_caller_utils.caller_configuration as conf
from py_phone_caller_utils.login.user import User
from py_phone_caller_utils.py_phone_caller_db.db_user import (
    ensure_admin_user_exists, is_users_table_empty, load_user_by_id,
    reset_admin_password_if_needed)

UI_SESSION_PROTECTION = conf.get_ui_session_protection()
UI_SECRET_KEY = conf.get_ui_secret_key()
UI_LISTEN_ON_HOST = conf.get_ui_listen_on_host()
UI_LISTEN_ON_PORT = conf.get_ui_listen_on_port()
UI_ADMIN_USER = conf.get_ui_admin_user()

login_manager = LoginManager()
login_manager.session_protection = UI_SESSION_PROTECTION

app = Flask(__name__, static_folder="static", static_url_path="/static")

app.config["SECRET_KEY"] = UI_SECRET_KEY
app.config["SESSION_PERMANENT"] = False

login_manager.init_app(app)
login_manager.login_view = "login_blueprint.login"


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


def setup_admin_user():
    """
    Ensures that an admin user exists and resets the admin password if required by environment settings.

    This function checks environment variables and the user table, performing password reset or admin user creation as needed.

    Returns:
        None
    """

    if not os.environ.get("UI_ADMIN_PASSWORD_RESETED"):
        asyncio.run(reset_admin_password_if_needed(UI_ADMIN_USER))

    if is_users_table_empty():
        asyncio.run(ensure_admin_user_exists(UI_ADMIN_USER))


setup_admin_user()

# Prevent password reset twice when UI_ADMIN_PASSWORD_RESETED is set to True
os.environ["UI_ADMIN_PASSWORD_RESETED"] = "True"


if __name__ == "__main__":

    app.run(host=UI_LISTEN_ON_HOST, port=UI_LISTEN_ON_PORT)
