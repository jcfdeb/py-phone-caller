from flask import Blueprint, render_template, url_for
from flask_login import login_required

from caller_utils.db.db_asterisk_ws_monitor import select_ws_events

ws_events_blueprint = Blueprint(
    "ws_events_blueprint",
    __name__,
    template_folder="templates/ws_events",
    static_folder="static",
    static_url_path="/ws_events/static",
)


@ws_events_blueprint.route("/ws_events")
@login_required
async def ws_events():
    """Returns the Asterisk WebSocket Events"""
    db_ws_events = dict(enumerate(await select_ws_events()))
    return render_template(
        "ws_events.html",
        table_data=db_ws_events,
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        logout_url=url_for("home_blueprint.logout"),
    )
