from flask import Blueprint, render_template, request, url_for
from flask_login import login_required

from caller_utils.db.db_scheduled_calls import select_scheduled_calls
from caller_utils.tasks.post_to_caller_register import insert_the_scheduled_call
from caller_utils.tasks.post_to_caller_scheduler import enqueue_the_call

schedule_call_blueprint = Blueprint(
    "schedule_call_blueprint",
    __name__,
    template_folder="templates/schedule_call",
    static_folder="static",
    static_url_path="/static",
)


@schedule_call_blueprint.route("/schedule_call")
@login_required
async def schedule_call():
    """Returns the list of received calls"""
    selected_calls = dict(enumerate(await select_scheduled_calls()))
    return render_template(
        "schedule_call.html",
        table_data=selected_calls,
        form_action=url_for("schedule_call_blueprint.schedule_picker"),
        reload_body=url_for("schedule_call_blueprint.schedule_call"),
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        logout_url=url_for("home_blueprint.logout"),
    )


@schedule_call_blueprint.route("/schedule_picker")
@login_required
async def schedule_picker():
    """Dummy route used to submit the form and redirect to '/schedule_call"""
    query_args = request.args.to_dict()

    try:
        enqueue_the_call(
            query_args.get("phone"),
            query_args.get("message"),
            f'{query_args.get("scheduled_date")} {query_args.get("scheduled_time")}',
        )
    except Exception:
        return {
            "status": 500,
            "message": "'caller_scheduler' unreachable, check your settings",
        }

    try:
        insert_the_scheduled_call(
            query_args.get("phone"),
            query_args.get("message"),
            f'{query_args.get("scheduled_date")} {query_args.get("scheduled_time")}',
        )
    except Exception:
        return {
            "status": 500,
            "message": "'caller_register' unreachable, check your settings",
        }

    return "Scheduled OK"
