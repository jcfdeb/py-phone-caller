"""
Home blueprint for the Py Phone Caller UI.

Provides the landing page and logout functionality.
"""

from flask import Blueprint, redirect, render_template, url_for
from flask_login import login_required, logout_user

home_blueprint = Blueprint(
    "home_blueprint",
    __name__,
    template_folder="templates/home",
)


@home_blueprint.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login_blueprint.login"))


@home_blueprint.route("/")
@login_required
async def home():
    """
    Renders the home page for authenticated users, providing navigation links to all main sections.

    This asynchronous view returns the rendered home.html template with context URLs for navigation.

    Returns:
        flask.Response: The rendered HTML home page.
    """

    return render_template(
        "home.html",
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        users_url=url_for("users_blueprint.users"),
        address_book_url=url_for("address_book_blueprint.address_book"),
        logout_url=url_for("home_blueprint.logout"),
    )
