"""
WebSocket Events blueprint for the Py Phone Caller UI.

Provides routes for viewing and searching Asterisk WebSocket events.
"""

import logging
import json
import re

from flask import Blueprint, render_template, request, url_for, Response
from flask_login import login_required
import csv
import io
import datetime
import time

from py_phone_caller_utils.py_phone_caller_db.db_asterisk_ws_monitor import (
    select_ws_events_sync,
)

ws_events_blueprint = Blueprint(
    "ws_events_blueprint",
    __name__,
    template_folder="templates/ws_events",
)


@ws_events_blueprint.route("/ws_events/export_csv")
@login_required
def export_csv():
    """
    Exports WebSocket events for a specific month as a CSV file.

    This asynchronous view retrieves event data, filters it by the selected month,
    and returns a CSV file for download.

    Returns:
        flask.Response: A CSV file download response.
    """

    export_month = request.args.get("export_month", "")
    if not export_month:
        return "Month parameter is required", 400

    try:
        year, month = map(int, export_month.split("-"))
        start_date = datetime.datetime(year, month, 1)
        if month == 12:
            end_date = datetime.datetime(year + 1, 1, 1)
        else:
            end_date = datetime.datetime(year, month + 1, 1)
    except ValueError:
        return "Invalid month format. Use YYYY-MM", 400

    start_timestamp = int(start_date.timestamp())
    end_timestamp = int(end_date.timestamp())

    all_events = select_ws_events_sync()

    logging.info(f"Retrieved {len(all_events)} events from the database")

    filtered_events = []
    for event in all_events:
        event_dict = {
            "id": str(event["id"]),
            "asterisk_chan": event["asterisk_chan"],
            "event_type": event["event_type"],
            "json_data": str(event["json_data"]),
        }

        event_added = False

        try:
            chan_parts = event["asterisk_chan"].split("-")
            for part in chan_parts:
                if part.isdigit() and len(part) >= 10:
                    timestamp = int(part)
                    if start_timestamp <= timestamp < end_timestamp:
                        filtered_events.append(event)
                        event_added = True
                        break

            if not event_added and event["json_data"]:
                json_str = str(event["json_data"])
                import re

                unix_timestamps = re.findall(r"\b\d{10,}\b", json_str)
                for ts_str in unix_timestamps:
                    timestamp = int(ts_str)
                    if start_timestamp <= timestamp < end_timestamp:
                        filtered_events.append(event)
                        event_added = True
                        break
        except (ValueError, AttributeError):
            pass

        if not event_added:
            month_year_str = f"{year}-{month:02d}"
            if any(month_year_str in str(value) for value in event_dict.values()):
                filtered_events.append(event)

    logging.info(
        f"Filtered to {len(filtered_events)} events for month {year}-{month:02d}"
    )

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["ID", "Asterisk Channel", "Event Type", "JSON Data"])

    if filtered_events:
        for event in filtered_events:
            writer.writerow(
                [
                    str(event["id"]),
                    event["asterisk_chan"],
                    event["event_type"],
                    str(event["json_data"]),
                ]
            )
    else:
        writer.writerow(["No events found for the selected month", "", "", ""])

    output.seek(0)
    csv_content = output.getvalue()
    logging.info(f"CSV content length: {len(csv_content)} bytes")

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=ws_events_{export_month}.csv"
        },
    )


@ws_events_blueprint.route("/ws_events")
@login_required
def ws_events():
    """
    Displays a paginated, searchable, and sortable list of Asterisk WebSocket events for authenticated users.

    This asynchronous view retrieves event data, applies search and sorting filters, paginates the results,
    and renders the ws_events.html template with the relevant context for the UI.

    Returns:
        flask.Response: The rendered HTML page displaying the WebSocket events.
    """

    search_query = request.args.get("search", "").lower()
    sort_by = request.args.get("sort_by", "timestamp")
    sort_order = request.args.get("sort_order", "desc")

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    all_events = select_ws_events_sync()

    processed_events = []
    for idx, event in enumerate(all_events):
        event_time = None

        json_data = event["json_data"]
        if isinstance(json_data, str):
            try:
                json_data = json.loads(json_data)
            except:
                pass

        if isinstance(json_data, dict) and "timestamp" in json_data:
            ts_str = json_data["timestamp"]
            try:
                if "+" in ts_str and ":" not in ts_str.split("+")[1]:
                    offset = ts_str.split("+")[1]
                    ts_str = ts_str.split("+")[0] + "+" + offset[:2] + ":" + offset[2:]
                elif (
                    "-" in ts_str and "T" in ts_str and ":" not in ts_str.split("-")[-1]
                ):
                    # Be careful not to split the date dashes
                    parts = ts_str.rsplit("-", 1)
                    if len(parts) == 2 and len(parts[1]) == 4:
                        ts_str = parts[0] + "-" + parts[1][:2] + ":" + parts[1][2:]

                event_time = datetime.datetime.fromisoformat(ts_str)
            except:
                pass

        if not event_time:
            match = re.search(r"(\d{10})", event["asterisk_chan"])
            if match:
                try:
                    event_time = datetime.datetime.fromtimestamp(int(match.group(1)))
                except:
                    pass

        if not event_time:
            event_time = datetime.datetime.fromtimestamp(0)

        try:
            if isinstance(event["json_data"], str):
                pretty_json = json.dumps(json.loads(event["json_data"]), indent=2)
            else:
                pretty_json = json.dumps(event["json_data"], indent=2)
        except:
            pretty_json = str(event["json_data"])

        e_type = event["event_type"].lower()
        if any(x in e_type for x in ["new", "start", "varset"]):
            event_color = "success"
        elif any(x in e_type for x in ["hangup", "end", "destroyed"]):
            event_color = "danger"
        elif any(x in e_type for x in ["dial", "bridge", "state"]):
            event_color = "primary"
        elif any(x in e_type for x in ["playback"]):
            event_color = "info"
        else:
            event_color = "secondary"

        processed_events.append(
            {
                "element": idx,
                "id": str(event["id"]),
                "asterisk_chan": event["asterisk_chan"],
                "event_type": event["event_type"],
                "event_color": event_color,
                "json_data": pretty_json,
                "timestamp": event_time,
                "formatted_time": (
                    event_time.strftime("%d/%m/%Y %H:%M:%S")
                    if event_time.year > 1970
                    else "N/A"
                ),
            }
        )

    if search_query:
        processed_events = [
            e
            for e in processed_events
            if any(search_query in str(v).lower() for v in e.values())
        ]

    if sort_by == "timestamp":
        processed_events.sort(
            key=lambda x: x["timestamp"], reverse=(sort_order == "desc")
        )
    elif sort_by == "event_type":
        processed_events.sort(
            key=lambda x: x["event_type"], reverse=(sort_order == "desc")
        )
    elif sort_by == "asterisk_chan":
        processed_events.sort(
            key=lambda x: x["asterisk_chan"], reverse=(sort_order == "desc")
        )
    elif sort_by == "element":
        processed_events.sort(
            key=lambda x: x["element"], reverse=(sort_order == "desc")
        )

    total_items = len(processed_events)
    total_pages = (total_items + per_page - 1) // per_page if total_items > 0 else 1

    page = max(1, min(page, total_pages)) if total_pages > 0 else 1

    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_items)
    paginated_data = processed_events[start_idx:end_idx]

    return render_template(
        "ws_events.html",
        search_query=search_query,
        paginated_data=paginated_data,
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
    )
