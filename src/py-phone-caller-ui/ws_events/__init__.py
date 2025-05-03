from flask import Blueprint, render_template, request, url_for
from flask_login import login_required

from py_phone_caller_utils.py_phone_caller_db.db_asterisk_ws_monitor import \
    select_ws_events

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
    """
    Displays a paginated and searchable list of Asterisk WebSocket events for authenticated users.

    This asynchronous view retrieves event data, applies search filters, paginates the results,
    and renders the ws_events.html template with the relevant context for the UI.

    Returns:
        flask.Response: The rendered HTML page displaying the WebSocket events.
    """

    search_query = request.args.get("search", "").lower()

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    all_events = await select_ws_events()

    db_ws_events = dict(enumerate(all_events))

    if search_query:
        filtered_events = {
            idx: event_data
            for idx, event_data in db_ws_events.items()
            if any(search_query in str(value).lower() for value in event_data.values())
        }
        db_ws_events = filtered_events

    total_items = len(db_ws_events)
    total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1

    page = max(1, min(page, total_pages)) if total_pages > 0 else 1

    paginated_keys = list(db_ws_events.keys())
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_items)
    paginated_keys = paginated_keys[start_idx:end_idx]

    return render_template(
        "ws_events.html",
        search_query=search_query,
        table_data=db_ws_events,
        paginated_data=paginated_keys,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        users_url=url_for("users_blueprint.users"),
        logout_url=url_for("home_blueprint.logout"),
    )
