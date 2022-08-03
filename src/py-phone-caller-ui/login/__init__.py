import logging

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import LoginManager, login_user
from werkzeug.security import check_password_hash

from caller_utils.db.db_user import select_user
from caller_utils.login.user import User

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
    """Display the login form for py-phone-caller"""
    return render_template("login.html", home_url=url_for("home_blueprint.home"))


@login_blueprint.route("/enter", methods=["POST"])
async def enter():
    """Managing the logins for py-phone-caller"""

    form_email = request.form.get("email")
    form_password = request.form.get("password")

    user_from_db = await select_user(form_email)

    try:
        current_user = User(username=user_from_db.get("email"))
        current_user.password = user_from_db.get("password")
    except AttributeError:
        redirect(url_for("login_blueprint.login"))

    try:

        if check_password_hash(current_user.password, form_password):
            login_user(current_user)
            return redirect(url_for("home_blueprint.home"))
        else:
            logging.info(f"Invalid Username or password for '{form_email}'...")
    except UnboundLocalError:
        logging.info(f"Invalid Username or password for '{form_email}'...")

    # In case of wrong user & pass
    return render_template("login.html", home_url=url_for("home_blueprint.home"))
