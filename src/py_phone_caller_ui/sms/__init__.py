"""
SMS blueprint for the Py Phone Caller UI.

Provides routes for viewing, searching, sorting, and exporting SMS message records.
"""

import csv
import datetime
import io
import logging
from typing import Any, Dict, List, Optional

from flask import Blueprint, Response, render_template, request
from flask_login import login_required
import pytz

from py_phone_caller_utils.config import settings
from py_phone_caller_utils.py_phone_caller_db.db_sms import select_sms

try:
    LOCAL_TIMEZONE = settings.scheduled_calls.local_timezone
    local_tz = pytz.timezone(LOCAL_TIMEZONE)
except Exception:
    local_tz = pytz.utc


def localize_datetime(dt: Optional[datetime.datetime]) -> Optional[datetime.datetime]:
    """Localizes a naive UTC datetime to the configured local timezone."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(local_tz)


sms_blueprint = Blueprint(
    "sms_blueprint",
    __name__,
    template_folder="templates/sms",
)


@sms_blueprint.route("/sms/export_csv")
@login_required
async def export_csv():
    """
    Exports SMS records for a specific month as a CSV file.

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

    all_sms = await select_sms()

    filtered_sms: List[Dict[str, Any]] = []
    for item in all_sms:
        item_copy = dict(item)
        if item_copy.get("created_at"):
            item_copy["created_at"] = localize_datetime(item_copy["created_at"])

        created_at = item_copy.get("created_at")
        if created_at and start_date <= created_at < end_date:
            filtered_sms.append(item_copy)

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(
        [
            "ID",
            "Phone",
            "Message",
            "Carrier",
            "Status",
            "Created At",
            "Error",
        ]
    )

    for item in filtered_sms:
        writer.writerow(
            [
                item.get("id", ""),
                item.get("phone", ""),
                item.get("message", ""),
                item.get("carrier", ""),
                item.get("status", ""),
                item.get("created_at", ""),
                item.get("error", ""),
            ]
        )

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment;filename=sms_{export_month}.csv"
        },
    )


@sms_blueprint.route("/sms")
@login_required
async def sms():
    """
    Displays a paginated, searchable, and sortable list of SMS records.

    Returns:
        flask.Response: The rendered HTML page displaying the SMS records.
    """
    search_query = request.args.get("search", "").lower()
    sort_by = request.args.get("sort_by", "created_at")
    sort_order = request.args.get("sort_order", "desc")

    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)

    all_sms = await select_sms()

    processed_sms = []
    for item in all_sms:
        item_dict = dict(item)
        if item_dict.get("created_at"):
            item_dict["created_at"] = localize_datetime(item_dict["created_at"])
        processed_sms.append(item_dict)

    selected_sms = dict(enumerate(processed_sms))

    if search_query:
        filtered_sms = {}
        for idx, sms_data in selected_sms.items():
            if any(search_query in str(value).lower() for value in sms_data.values()):
                filtered_sms[idx] = sms_data
        selected_sms = filtered_sms

    paginated_keys = list(selected_sms.keys())

    if sort_by == "element":
        paginated_keys.sort(reverse=(sort_order == "desc"))
    elif sort_by == "phone":
        paginated_keys.sort(
            key=lambda k: str(selected_sms[k].get("phone", "")).lower(),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "carrier":
        paginated_keys.sort(
            key=lambda k: str(selected_sms[k].get("carrier", "")).lower(),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "status":
        paginated_keys.sort(
            key=lambda k: str(selected_sms[k].get("status", "")).lower(),
            reverse=(sort_order == "desc"),
        )
    elif sort_by == "created_at":
        paginated_keys.sort(
            key=lambda k: selected_sms[k].get("created_at")
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
        "sms.html",
        search_query=search_query,
        table_data=selected_sms,
        paginated_data=paginated_keys,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort_by=sort_by,
        sort_order=sort_order,
        total_items=total_items,
    )
