from flask import Blueprint, render_template, request, url_for
from flask_login import login_required

from py_phone_caller_utils.py_phone_caller_db.db_caller_register import \
    select_calls

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
    """
    Displays a paginated, searchable, and sortable list of call records for authenticated users.

    This asynchronous view retrieves call data, applies search and sorting filters, paginates the results,
    and renders the calls.html template with the relevant context for the UI.

    Returns:
        flask.Response: The rendered HTML page displaying the call records.
    """

    search_query = request.args.get("search", "").lower()
    sort_by = request.args.get("sort_by", "element")
    sort_order = request.args.get("sort_order", "asc")

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    all_calls = await select_calls()

    selected_calls = dict(enumerate(all_calls))

    if search_query:
        filtered_calls = {}
        for idx, call_data in selected_calls.items():
            if any(search_query in str(value).lower() for value in call_data.values()):
                filtered_calls[idx] = call_data
        selected_calls = filtered_calls

    paginated_keys = list(selected_calls.keys())

    if sort_by == "element":
        paginated_keys.sort(reverse=(sort_order == "desc"))
    elif sort_by == "times_to_dial":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("times_to_dial", 0),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "dialed_times":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("dialed_times", 0),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "first_dial_time":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("first_dial", ""),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "last_dial_time":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("last_dial", ""),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "heard_at":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("heard_at", ""),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "acknowledge_at":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("acknowledge_at", ""),
            reverse=(sort_order == "desc"),
        )

    total_items = len(paginated_keys)
    total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1

    page = max(1, min(page, total_pages)) if total_pages > 0 else 1

    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_items)
    paginated_keys = paginated_keys[start_idx:end_idx]
    print(selected_calls)
    return render_template(
        "calls.html",
        search_query=search_query,
        table_data=selected_calls,
        paginated_data=paginated_keys,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort_by=sort_by,
        sort_order=sort_order,
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        users_url=url_for("users_blueprint.users"),
        logout_url=url_for("home_blueprint.logout"),
    )
