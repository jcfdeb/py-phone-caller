from flask import Blueprint, redirect, render_template, url_for
from flask_login import login_required, logout_user

home_blueprint = Blueprint(
    "home_blueprint",
    __name__,
    template_folder="templates/home",
    static_folder="static",
    static_url_path="/home/static",
)


@home_blueprint.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login_blueprint.login"))


@home_blueprint.route("/")
@login_required
async def home():
    """Returns the home page"""

    return render_template(
        "home.html",
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        logout_url=url_for("home_blueprint.logout"),
    )
