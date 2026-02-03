"""
Schedule Call blueprint for the Py Phone Caller UI.

Provides routes for scheduling calls and viewing upcoming schedules.
"""

from flask import Blueprint, render_template, request, url_for, Response
from flask_login import login_required
import csv
import io
import datetime
import pytz
from py_phone_caller_utils.config import settings

LOCAL_TIMEZONE = settings.scheduled_calls.local_timezone
local_tz = pytz.timezone(LOCAL_TIMEZONE)


def localize_datetime(dt):
    """Localizes a naive UTC datetime to the configured local timezone."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(local_tz)


from py_phone_caller_utils.py_phone_caller_db.db_scheduled_calls import (
    select_scheduled_calls,
)
from py_phone_caller_utils.tasks.post_to_caller_register import (
    insert_the_scheduled_call,
)
from py_phone_caller_utils.tasks.post_to_caller_scheduler import enqueue_the_call
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    AddressBook,
)

schedule_call_blueprint = Blueprint(
    "schedule_call_blueprint",
    __name__,
    template_folder="templates/schedule_call",
)


@schedule_call_blueprint.route("/schedule_call/export_csv")
@login_required
async def export_csv():
    """
    Exports scheduled calls for a specific month as a CSV file.

    This asynchronous view retrieves scheduled call data, filters it by the selected month,
    and returns a CSV file for download.

    Returns:
        flask.Response: A CSV file download response.
    """

    export_month = request.args.get("export_month", "")
    if not export_month:
        return "Month parameter is required", 400

    try:
        year, month = map(int, export_month.split("-"))
        start_date = local_tz.localize(datetime.datetime(year, month, 1))
        if month == 12:
            end_date = local_tz.localize(datetime.datetime(year + 1, 1, 1))
        else:
            end_date = local_tz.localize(datetime.datetime(year, month + 1, 1))
    except ValueError:
        return "Invalid month format. Use YYYY-MM", 400

    all_calls = await select_scheduled_calls()

    filtered_calls = []
    for call in all_calls:
        call["inserted_at"] = localize_datetime(call.get("inserted_at"))
        call["scheduled_at"] = localize_datetime(call.get("scheduled_at"))

        scheduled_at = call["scheduled_at"]
        if scheduled_at and start_date <= scheduled_at < end_date:
            filtered_calls.append(call)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["ID", "Phone", "Message", "Inserted At", "Scheduled At"])

    for call in filtered_calls:
        writer.writerow(
            [
                call["id"],
                call["phone"],
                call["message"],
                call["inserted_at"],
                call["scheduled_at"],
            ]
        )

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=scheduled_calls_{export_month}.csv"
        },
    )


@schedule_call_blueprint.route("/schedule_call")
@login_required
async def schedule_call():
    """
    Displays a paginated, searchable, and sortable list of scheduled calls for authenticated users.

    This asynchronous view retrieves scheduled call data, applies search and sorting filters, paginates the results,
    and renders the schedule_call.html template with the relevant context for the UI.

    Returns:
        flask.Response: The rendered HTML page displaying the scheduled calls.
    """

    search_query = request.args.get("search", "").lower()
    sort_by = request.args.get("sort_by", "element")
    sort_order = request.args.get("sort_order", "asc")

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    all_calls = await select_scheduled_calls()

    for call in all_calls:
        if call.get("inserted_at"):
            call["inserted_at"] = localize_datetime(call["inserted_at"])
        if call.get("scheduled_at"):
            call["scheduled_at"] = localize_datetime(call["scheduled_at"])

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
    elif sort_by == "scheduled_time":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("scheduled_at")
            or datetime.datetime.min.replace(tzinfo=pytz.utc),
            reverse=(sort_order == "desc"),
        )

    total_items = len(paginated_keys)
    total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1

    page = max(1, min(page, total_pages)) if total_pages > 0 else 1

    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_items)
    paginated_keys = paginated_keys[start_idx:end_idx]

    contacts = await AddressBook.select()
    try:
        contacts = [c for c in contacts if c.get("enabled")]
    except Exception:
        pass
    try:
        contacts.sort(key=lambda c: f"{c.get('name', '')}{c.get('surname', '')}")
    except Exception:
        pass

    return render_template(
        "schedule_call.html",
        search_query=search_query,
        table_data=selected_calls,
        paginated_data=paginated_keys,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort_by=sort_by,
        sort_order=sort_order,
        form_action=url_for("schedule_call_blueprint.schedule_picker"),
        reload_body=url_for("schedule_call_blueprint.schedule_call"),
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        users_url=url_for("users_blueprint.users"),
        address_book_url=url_for("address_book_blueprint.address_book"),
        logout_url=url_for("home_blueprint.logout"),
        contacts=contacts,
    )


@schedule_call_blueprint.route("/schedule_picker")
@login_required
async def schedule_picker():
    """
    Schedules a new call by enqueuing it for execution and recording it in the database.

    This asynchronous view extracts scheduling parameters from the request, attempts to enqueue the call and insert it into the register,
    and returns a success message or an error status if either operation fails.

    Returns:
        str or dict: "Scheduled OK" on success, or a dictionary with error status and message on failure.
    """
    query_args = request.args.to_dict()

    try:
        status_code_scheduler = enqueue_the_call(
            query_args.get("phone"),
            query_args.get("message"),
            f"{query_args.get('scheduled_date')} {query_args.get('scheduled_time')}",
        )
        if status_code_scheduler != 200:
            return {
                "status": status_code_scheduler,
                "message": f"'caller_scheduler' error (status {status_code_scheduler})",
            }
    except Exception:
        return {
            "status": 500,
            "message": "'caller_scheduler' unreachable, check your settings",
        }

    try:
        status_code_register = insert_the_scheduled_call(
            query_args.get("phone"),
            query_args.get("message"),
            f"{query_args.get('scheduled_date')} {query_args.get('scheduled_time')}",
        )
        if status_code_register != 200:
            return {
                "status": status_code_register,
                "message": f"'caller_register' error (status {status_code_register})",
            }
    except Exception:
        return {
            "status": 500,
            "message": "'caller_register' unreachable, check your settings",
        }

    return "Scheduled OK"
