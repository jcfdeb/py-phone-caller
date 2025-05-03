import logging

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import LoginManager, login_user
from werkzeug.security import check_password_hash

from py_phone_caller_utils.login.user import User
from py_phone_caller_utils.py_phone_caller_db.db_user import select_user

HOME_TEMPLATE = "home_blueprint.home"
LOGIN_TEMPLATE = "login.html"

login_manager = LoginManager()
login_manager.session_protection = "strong"


login_blueprint = Blueprint(
    "login_blueprint",
    __name__,
    template_folder="templates/login",
    static_folder="static",
    static_url_path="/login/static",
)


@login_blueprint.route("/login", methods=["GET"])
async def login():
    """
    Renders the login page for the application.

    This asynchronous view returns the rendered login.html template with the home URL context.

    Returns:
        flask.Response: The rendered HTML login page.
    """
    return render_template(LOGIN_TEMPLATE, home_url=url_for(HOME_TEMPLATE))


@login_blueprint.route("/enter", methods=["POST"])
async def enter():
    """
    Processes the login form submission and authenticates the user.

    This asynchronous view checks the provided credentials, logs the user in if valid, and redirects to the home page or returns an error.

    Returns:
        flask.Response: A redirect to the home page on success, or the login page with an error message on failure.
    """

    form_email = request.form.get("email")
    form_password = request.form.get("password")

    user_from_db = await select_user(form_email)

    if not user_from_db:
        logging.info(f"Login attempt failed: User '{form_email}' not found.")
        return redirect(url_for("login_blueprint.login"))

    current_user = User(username=user_from_db.get("email"))
    stored_password_hash = user_from_db.get("password")

    if check_password_hash(stored_password_hash, form_password):
        login_user(current_user)
        return redirect(url_for("home_blueprint.home"))
    else:
        logging.info(f"Invalid password attempt for user '{form_email}'.")
        return render_template(
            LOGIN_TEMPLATE,
            home_url=url_for(HOME_TEMPLATE),
            error="Invalid username or password",
        )
