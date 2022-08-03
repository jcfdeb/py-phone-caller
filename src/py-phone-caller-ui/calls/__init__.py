from flask import Blueprint, render_template, url_for
from flask_login import login_required

from caller_utils.db.db_caller_register import select_calls

calls_blueprint = Blueprint(
    "calls_blueprint",
    __name__,
    template_folder="templates/calls",
    static_folder="static",
    static_url_path="/calls/static",
)


@calls_blueprint.route("/calls")
@login_required
async def calls():
    """Returns the list of received calls"""
    selected_calls = dict(enumerate(await select_calls()))
    return render_template(
        "calls.html",
        table_data=selected_calls,
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        logout_url=url_for("home_blueprint.logout"),
    )
