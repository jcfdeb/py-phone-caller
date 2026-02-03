"""
Calls blueprint for the Py Phone Caller UI.

Provides routes for viewing, searching, and exporting call records.
"""

from flask import Blueprint, render_template, request, url_for, Response, jsonify
from flask_login import login_required
import csv
import io
import datetime
import pytz
import requests
from datetime import timedelta, UTC
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


from py_phone_caller_utils.py_phone_caller_db.db_caller_register import select_calls

from .constants import CALL_REGISTER_ENDPOINT


calls_blueprint = Blueprint(
    "calls_blueprint",
    __name__,
    template_folder="templates/calls",
)


@calls_blueprint.route("/calls/export_csv")
@login_required
async def export_csv():
    """
    Exports call records for a specific month as a CSV file.

    This asynchronous view retrieves call data, filters it by the selected month,
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

    all_calls = await select_calls()

    filtered_calls = []
    for call in all_calls:
        for key in ["first_dial", "last_dial", "heard_at", "acknowledge_at"]:
            if call.get(key):
                call[key] = localize_datetime(call[key])

        first_dial = call["first_dial"]
        if first_dial and start_date <= first_dial < end_date:
            filtered_calls.append(call)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "ID",
            "Phone",
            "Message",
            "Asterisk Channel",
            "Message Checksum",
            "Call Checksum",
            "Unique Checksum",
            "Times To Dial",
            "Dialed Times",
            "Seconds To Forget",
            "First Dial",
            "Last Dial",
            "Heard At",
            "Acknowledge At",
            "Cycle Done",
            "On Call",
            "Backup Callee",
        ]
    )

    for call in filtered_calls:
        writer.writerow(
            [
                call["id"],
                call["phone"],
                call["message"],
                call["asterisk_chan"],
                call["msg_chk_sum"],
                call["call_chk_sum"],
                call["unique_chk_sum"],
                call["times_to_dial"],
                call["dialed_times"],
                call["seconds_to_forget"],
                call["first_dial"],
                call["last_dial"],
                call["heard_at"],
                call["acknowledge_at"],
                call["cycle_done"],
                call.get("oncall", False),
                call.get("backup_callee", False),
            ]
        )

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=calls_{export_month}.csv"
        },
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
    sort_by = request.args.get("sort_by", "first_dial_time")
    sort_order = request.args.get("sort_order", "desc")

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    all_calls = await select_calls()

    for call in all_calls:
        for key in ["first_dial", "last_dial", "heard_at", "acknowledge_at"]:
            if call.get(key):
                call[key] = localize_datetime(call[key])

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
            key=lambda k: selected_calls[k].get("first_dial")
            or datetime.datetime.min.replace(tzinfo=pytz.utc),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "last_dial_time":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("last_dial")
            or datetime.datetime.min.replace(tzinfo=pytz.utc),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "heard_at":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("heard_at")
            or datetime.datetime.min.replace(tzinfo=pytz.utc),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "acknowledge_at":
        paginated_keys.sort(
            key=lambda k: selected_calls[k].get("acknowledge_at")
            or datetime.datetime.min.replace(tzinfo=pytz.utc),
            reverse=(sort_order == "desc"),
        )

    total_items = len(paginated_keys)
    total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1

    page = max(1, min(page, total_pages)) if total_pages > 0 else 1

    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_items)
    paginated_keys = paginated_keys[start_idx:end_idx]
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
        address_book_url=url_for("address_book_blueprint.address_book"),
        logout_url=url_for("home_blueprint.logout"),
        now=datetime.datetime.now(pytz.utc),
        timedelta=timedelta,
        call_register_endpoint=url_for("calls_blueprint.proxy_acknowledge"),
    )


@calls_blueprint.route("/calls/proxy_acknowledge")
@login_required
async def proxy_acknowledge():
    """
    Proxies the acknowledge request to the call register endpoint.

    This route acts as a proxy between the web UI and the backend service,
    allowing the UI to be exposed to the internet while keeping the backend
    service within the LAN.

    Returns:
        flask.Response: A JSON response from the call register endpoint.
    """

    asterisk_chan = request.args.get("asterisk_chan")
    if not asterisk_chan:
        return jsonify(
            {"status": 400, "message": "Missing asterisk_chan parameter"}
        ), 400

    try:
        response = requests.get(
            f"{CALL_REGISTER_ENDPOINT}?asterisk_chan={asterisk_chan}"
        )
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify(
            {
                "status": 500,
                "message": f"Error communicating with backend service: {str(e)}",
            }
        ), 500
