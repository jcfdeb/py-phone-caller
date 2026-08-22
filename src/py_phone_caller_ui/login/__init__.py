"""
Login blueprint for the Py Phone Caller UI.

Handles user authentication.
"""

import logging
from datetime import UTC, datetime

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import login_user

from py_phone_caller_utils.login.user import User
from py_phone_caller_utils.py_phone_caller_db.db_user import (
    check_user_password,
    is_legacy_password_hash,
    select_user,
    update_password,
)
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    Users,
)

HOME_TEMPLATE = "home_blueprint.home"
LOGIN_TEMPLATE = "login.html"


login_blueprint = Blueprint(
    "login_blueprint",
    __name__,
    template_folder="templates/login",
)


@login_blueprint.route("/login", methods=["GET", "POST"])
async def login():
    """
    Handles the login process, including rendering the login page and processing credentials.

    This asynchronous view supports both GET (rendering the form) and POST (processing the login).
    It checks the provided credentials, logs the user in if valid, and redirects to the home page or returns an error.

    Returns:
        flask.Response: The rendered HTML login page or a redirect to the home page.
    """

    if request.method == "POST":
        form_email = request.form.get("email") or ""
        form_password = request.form.get("password") or ""

        if not form_email or not form_password:
            logging.info("Login attempt failed: Missing email or password.")
            return render_template(
                LOGIN_TEMPLATE,
                home_url=url_for(HOME_TEMPLATE),
                error="Invalid username or password",
            )

        user_from_db = await select_user(form_email)

        if not user_from_db:
            logging.info(f"Login attempt failed: User '{form_email}' not found.")
            return render_template(
                LOGIN_TEMPLATE,
                home_url=url_for(HOME_TEMPLATE),
                error="Invalid username or password",
            )

        if not user_from_db.get("is_active", True):
            logging.info(f"Login attempt blocked: User '{form_email}' is disabled.")
            return render_template(
                LOGIN_TEMPLATE,
                home_url=url_for(HOME_TEMPLATE),
                error="Account is disabled. Please contact an administrator.",
            )

        current_user = User(username=user_from_db.get("email"))
        stored_password_hash = user_from_db.get("password")

        if check_user_password(stored_password_hash, form_password):
            if is_legacy_password_hash(stored_password_hash):
                await update_password(form_email, form_password)
            login_user(current_user)
            await Users.update(
                {Users.last_login: datetime.now(UTC).replace(tzinfo=None)}
            ).where(Users.email == form_email)
            return redirect(url_for("home_blueprint.home"))
        else:
            logging.info(f"Invalid password attempt for user '{form_email}'.")
            return render_template(
                LOGIN_TEMPLATE,
                home_url=url_for(HOME_TEMPLATE),
                error="Invalid username or password",
            )

    return render_template(LOGIN_TEMPLATE, home_url=url_for(HOME_TEMPLATE))
