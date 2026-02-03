"""
Address Book blueprint for the Py Phone Caller UI.

Provides routes for viewing, searching, and managing contacts, including
calendar views and CSV import/export.
"""

from flask import Blueprint, render_template, request, url_for, jsonify, Response
from flask_login import login_required
import requests
import datetime
from datetime import UTC
import calendar
import json
import io
import csv
import asyncio

from .constants import (
    CALLER_ADDR_BOOK_BASE,
    ROUTE_ADD,
    ROUTE_MODIFY,
    ROUTE_DELETE,
    SERVICE_EXPORT,
    SERVICE_IMPORT,
)
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    AddressBook,
)
from py_phone_caller_utils.py_phone_caller_db.db_address_book import modify_contact


address_book_blueprint = Blueprint(
    "address_book_blueprint",
    __name__,
    template_folder="templates/address_book",
)


async def _select_contacts():
    """
    Retrieves the contacts from the AddressBook, ensuring that the underlying database
    table exists and sorting the retrieved rows by their created time in descending order.
    If the created time is unavailable, rows may remain unsorted. Any exceptions that
    occur during the sort operation are silently ignored.

    :return: A list of dictionaries representing the rows retrieved from the
             AddressBook, potentially sorted by the created time.
    :rtype: list
    """

    rows = await AddressBook.select()
    try:
        rows.sort(key=lambda r: r.get("created_time") or "", reverse=True)
    except Exception:
        pass
    return rows


@address_book_blueprint.route("/address_book")
@login_required
async def address_book():
    """
    Handles the display of the address book page with optional search and sorting
    functionality. Filters contacts according to a case-insensitive search query,
    sorts them based on the specified attribute and order, and renders the result
    using the 'address_book.html' template.

    :param request.args['search']: A case-insensitive string used to filter results
                                   by matching against contact data.
    :param request.args['sort_by']: A string used to determine the attribute for
                                    sorting contacts. Possible values:
                                    'name', 'phone_number', 'enabled',
                                    or 'created_time' (default).
    :param request.args['sort_order']: The sorting order for contacts. Possible
                                       values: 'asc' (ascending) or 'desc' (descending; default).
    :return: A rendered HTML page that includes the filtered and sorted contact list,
             alongside other relevant navigation links.
    :rtype: flask.Response
    """

    search_query = request.args.get("search", "").lower()
    sort_by = request.args.get("sort_by", "created_time")
    sort_order = request.args.get("sort_order", "desc")

    rows = await _select_contacts()

    if search_query:

        def match(row):
            for v in row.values():
                try:
                    if search_query in str(v).lower():
                        return True
                except Exception:
                    continue
            return False

        rows = [r for r in rows if match(r)]

    reverse = sort_order == "desc"
    if sort_by == "name":
        rows.sort(
            key=lambda r: f"{r.get('name', '')}{r.get('surname', '')}", reverse=reverse
        )
    elif sort_by == "phone_number":
        rows.sort(key=lambda r: r.get("phone_number", ""), reverse=reverse)
    elif sort_by == "enabled":
        rows.sort(key=lambda r: 1 if r.get("enabled") else 0, reverse=reverse)
    else:  # created_time
        rows.sort(key=lambda r: r.get("created_time") or "", reverse=reverse)

    return render_template(
        "address_book.html",
        contacts=rows,
        search_query=search_query,
        sort_by=sort_by,
        sort_order=sort_order,
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        users_url=url_for("users_blueprint.users"),
        address_book_url=url_for("address_book_blueprint.address_book"),
        address_book_calendar_url=url_for(
            "address_book_blueprint.address_book_calendar"
        ),
        logout_url=url_for("home_blueprint.logout"),
    )


def _parse_iso_utc(ts: str):
    """
    Parses an ISO 8601 formatted UTC timestamp string and returns a datetime object.

    This function takes an ISO 8601 formatted timestamp string, adjusts it to include
    timezone information if necessary, and returns a timezone-aware `datetime` object
    in UTC. If the string is empty, improperly formatted, or otherwise cannot be parsed,
    the function returns None. It is designed specifically for parsing timestamps
    formatted in UTC.

    :param ts: ISO 8601 formatted timestamp string
    :type ts: str
    :return: A timezone-aware `datetime` object in UTC or None if parsing fails
    :rtype: Optional[datetime.datetime]
    """

    try:
        ts = (ts or "").strip()
        if not ts:
            return None
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _month_bounds(year: int, month: int):
    """
    Determine the first and last datetime of the given year and month.

    The function calculates the bounds for a given month in a specific year
    using the provided `year` and `month`. It returns the first datetime of
    the month and the last datetime of the same month. The timezone is set
    to UTC.

    :param year: The year for which the month's bounds will be determined.
    :type year: int
    :param month: The month (1-12) for which the bounds will be determined.
    :type month: int
    :return: A tuple containing the first datetime of the month and the
             last datetime of the month.
    :rtype: tuple(datetime.datetime, datetime.datetime)
    """

    first = datetime.datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        next_month = datetime.datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime.datetime(year, month + 1, 1, tzinfo=UTC)
    last = next_month - datetime.timedelta(seconds=1)
    return first, last


def _overlaps(a_start, a_end, b_start, b_end):
    """
    Checks whether two intervals overlap.

    This function determines if two intervals, defined by their start and end
    points, overlap. Intervals are inclusive of their bounds. An interval is
    defined with a start and an end value, and the function evaluates whether
    the intervals intersect or not.

    :param a_start: Start value of the first interval.
    :param a_end: End value of the first interval.
    :param b_start: Start value of the second interval.
    :param b_end: End value of the second interval.
    :return: A boolean indicating whether the two intervals overlap.
    """

    return a_start <= b_end and a_end >= b_start


def _extract_windows(contact_row):
    """
    Extracts and formats on-call availability time windows from a contact row. The windows
    are derived from the 'on_call_availability' field in the given contact row and processed
    into tuples containing the start time, end time, and priority level. Invalid or
    malformed windows are ignored.

    :param contact_row: The dictionary containing contact information. Specifically, it
        must include the "on_call_availability" field, which can be a JSON-encoded string
        or a list of dictionaries representing availability windows.
    :type contact_row: dict
    :return: A list of tuples, each containing the start time, end time, and priority level
        (in that order) for valid availability windows. If no valid windows are found, an
        empty list is returned.
    :rtype: list
    """

    windows = []
    raw = contact_row.get("on_call_availability") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = []
    if not isinstance(raw, list):
        raw = []
    for w in raw:
        try:
            s = _parse_iso_utc(str(w.get("start_at")))
            e = _parse_iso_utc(str(w.get("end_at")))
            p = int(w.get("priority"))
            if s and e and s <= e:
                windows.append((s, e, p))
        except Exception:
            continue
    return windows


def _build_calendar(rows, year: int, month: int):
    """
    Constructs a weekly calendar for the given month and filters entries for each day
    based on overlapping time windows within the provided data rows. Each day either
    contains filtered entries or None if it belongs to a different month.

    :param rows: A list of dictionaries representing data rows. Each dictionary should
                 contain details such as enabled status, id, name, surname, and time
                 windows for events.
    :type rows: list[dict]
    :param year: The year for which the calendar is being generated.
    :type year: int
    :param month: The month for which the calendar is being generated.
    :type month: int
    :return: A nested list of dictionaries where the outer list represents weeks
             (one week per sublist), the inner list represents the days in those weeks,
             and each day contains its date and the filtered entries for that date.
             Days belonging to other months within the generated weeks will be None.
    :rtype: list[list[dict]]
    """

    first_day, last_day = _month_bounds(year, month)
    _, num_days = calendar.monthrange(year, month)
    weeks = []
    cal = calendar.Calendar(firstweekday=0)
    for week in cal.monthdatescalendar(year, month):
        week_cells = []
        for d in week:
            if d.month != month:
                week_cells.append(None)
                continue
            day_start = datetime.datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=UTC)
            day_end = datetime.datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)
            entries = []
            for r in rows:
                if not r.get("enabled"):
                    continue
                for s, e, p in _extract_windows(r):
                    if _overlaps(s, e, day_start, day_end):
                        entries.append(
                            {
                                "id": str(r.get("id")),
                                "name": r.get("name"),
                                "surname": r.get("surname"),
                                "priority": p,
                                "start": s,
                                "end": e,
                            }
                        )
                        break
            entries.sort(
                key=lambda x: (x["priority"], (x["name"] or "") + (x["surname"] or ""))
            )
            week_cells.append(
                {
                    "date": d,
                    "entries": entries,
                }
            )
        weeks.append(week_cells)
    return weeks


@address_book_blueprint.route("/address_book/calendar")
@login_required
async def address_book_calendar():
    """
    Handles the route for displaying the address book calendar. This function
    renders a calendar view, showing scheduled contacts for a particular month and
    year. If a month isn't provided in the request, the current month and year
    are used by default.

    The calendar is built based on contact data retrieved asynchronously, and navigation
    facilities are provided to view the previous or next month's calendar.

    :param month_str: The month and year as a string in the format "YYYY-MM". If
        not specified, defaults to the current month.

    :return: A rendered HTML page displaying the monthly calendar with navigation links.
    """

    month_str = request.args.get("month")
    today = datetime.datetime.now(UTC)
    try:
        if month_str:
            year, month = map(int, month_str.split("-"))
        else:
            year, month = today.year, today.month
    except Exception:
        year, month = today.year, today.month

    rows = await _select_contacts()
    weeks = _build_calendar(rows, year, month)

    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    next_year = year if month < 12 else year + 1
    next_month = month + 1 if month < 12 else 1

    return render_template(
        "calendar.html",
        year=year,
        month=month,
        month_str=f"{year:04d}-{month:02d}",
        weeks=weeks,
        prev_month=f"{prev_year:04d}-{prev_month:02d}",
        next_month=f"{next_year:04d}-{next_month:02d}",
        home_url=url_for("home_blueprint.home"),
        calls_url=url_for("calls_blueprint.calls"),
        ws_events_url=url_for("ws_events_blueprint.ws_events"),
        schedule_call_url=url_for("schedule_call_blueprint.schedule_call"),
        users_url=url_for("users_blueprint.users"),
        address_book_url=url_for("address_book_blueprint.address_book"),
        address_book_calendar_url=url_for(
            "address_book_blueprint.address_book_calendar"
        ),
        logout_url=url_for("home_blueprint.logout"),
    )


def _iso_z(dt: datetime.datetime) -> str:
    """
    Converts a datetime object to an ISO 8601 string representation with 'Z'
    notation for UTC timezone. If any exception occurs during the conversion, an
    empty string is returned.

    :param dt: The datetime object to convert.
    :type dt: datetime.datetime
    :return: The ISO 8601 string representation of the datetime object in UTC timezone,
             or an empty string if an error occurs during the conversion.
    :rtype: str
    """

    try:
        return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
    except Exception:
        return ""


@address_book_blueprint.route("/address_book/calendar/export_csv")
@login_required
async def calendar_export_csv():
    """
    Exports a filtered list of calendar events in CSV format for the given month. The
    export includes all contacts with active availability windows overlapping the defined
    month.

    :param month_str: Optional query parameter specifying the month in the format "YYYY-MM".
        If not provided, defaults to the current month.
    :return: A Flask `Response` object containing the CSV data with the corresponding headers.
    """

    month_str = request.args.get("month") or request.args.get("export_month")
    today = datetime.datetime.now(UTC)
    try:
        if month_str:
            year, month = map(int, str(month_str).split("-"))
        else:
            year, month = today.year, today.month
    except Exception:
        year, month = today.year, today.month
    start_month, end_month = _month_bounds(year, month)

    rows = await _select_contacts()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "name", "surname", "start_at", "end_at", "priority"])

    for r in rows:
        if not r.get("enabled"):
            continue
        rid = str(r.get("id"))
        name = r.get("name") or ""
        surname = r.get("surname") or ""
        for s, e, p in _extract_windows(r):
            if _overlaps(s, e, start_month, end_month):
                writer.writerow(
                    [
                        rid,
                        name,
                        surname,
                        _iso_z(s),
                        _iso_z(e),
                        int(p),
                    ]
                )

    output.seek(0)
    filename = f"address_book_availability_{year:04d}-{month:02d}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={filename}"},
    )


@address_book_blueprint.route("/address_book/calendar/import_csv", methods=["POST"])
@login_required
async def calendar_import_csv():
    """
    Handles the import of calendar data from a CSV file. The endpoint processes the CSV file uploaded by the user,
    validates its format, and updates the availability information of the contacts in the address book based
    on the data in the file. The CSV is expected to include specific fields such as "id", "name", "surname",
    "start_at", "end_at", and "priority". Invalid rows or records may result in errors that are reported
    in the response.

    :return: JSON response summarizing the import operation, including the count of processed rows,
             successfully updated records, IDs of updated contacts, IDs of contacts not found, and details
             of the first few encountered errors.
    :rtype: Tuple[flask.Response, int]
    """

    file = request.files.get("file")
    if not file:
        return jsonify(
            {
                "status": 400,
                "message": "No CSV file uploaded (field name should be 'file')",
            }
        ), 400

    try:
        content = file.read().decode("utf-8", errors="replace")
    except Exception:
        return jsonify({"status": 400, "message": "Unable to read CSV file"}), 400

    reader = csv.DictReader(io.StringIO(content))
    expected = ["id", "name", "surname", "start_at", "end_at", "priority"]
    got = [h.strip().lower() for h in (reader.fieldnames or [])]
    if not all(h in got for h in expected):
        return jsonify(
            {
                "status": 400,
                "message": "Malformed CSV header",
                "expected": expected,
                "got": got,
            }
        ), 400

    contact_updates = {}
    errors = []
    total_rows = 0

    for idx, row in enumerate(reader, start=2):
        total_rows += 1
        try:
            cid = (row.get("id") or "").strip()
            s = (row.get("start_at") or "").strip()
            e = (row.get("end_at") or "").strip()
            pr_str = (row.get("priority") or "0").strip()
            if not cid or not s or not e:
                raise ValueError("Missing id/start_at/end_at")
            s_dt = _parse_iso_utc(s)
            e_dt = _parse_iso_utc(e)
            if not s_dt or not e_dt:
                raise ValueError("Invalid timestamp format")
            if s_dt > e_dt:
                raise ValueError("start_at after end_at")
            pr = int(pr_str)

            contact_updates.setdefault(cid, []).append(
                {
                    "start_at": _iso_z(s_dt),
                    "end_at": _iso_z(e_dt),
                    "priority": pr,
                }
            )
        except Exception as ex:
            errors.append({"row": idx, "error": str(ex)})
            continue

    if not contact_updates:
        return jsonify(
            {
                "status": 400,
                "message": "No valid rows found in the CSV",
                "errors_count": len(errors),
                "errors": errors[:10],
            }
        ), 400

    ids_list = list(contact_updates.keys())
    existing_rows = await AddressBook.select(AddressBook.id).where(
        AddressBook.id.is_in(ids_list)
    )
    existing_ids = {str(r.get("id")) for r in existing_rows}
    not_found_ids = sorted({cid for cid in ids_list if cid not in existing_ids})

    avail_rows = await AddressBook.select(
        AddressBook.id, AddressBook.on_call_availability
    ).where(AddressBook.id.is_in(list(existing_ids)))
    avail_map = {str(r.get("id")): r.get("on_call_availability") for r in avail_rows}

    def _normalize_avail(raw):
        """
        Normalizes the input to ensure it is a valid list. If the input is a JSON string, it attempts to
        decode it into a Python list. If the input is invalid or decoding fails, an empty list is returned.

        :param raw: A value to normalize, which may be a list, a JSON-encoded string representing a
            list, or any other value. If it is an invalid or unrecognized format, an empty list will
            be returned.
        :return: A list extracted or normalized from the input value.
        """

        val = raw or []
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                val = []
        if not isinstance(val, list):
            val = []
        return val

    updated_contact_ids = []
    imported_windows = 0

    batch = []
    for cid in existing_ids:
        current = _normalize_avail(avail_map.get(cid))
        to_add = contact_updates.get(cid, [])
        if not to_add:
            continue
        merged = current + to_add
        imported_windows += len(to_add)
        batch.append((cid, merged))
        updated_contact_ids.append(cid)

        if len(batch) >= 10:
            for bcid, merged_av in batch:
                try:
                    await modify_contact(bcid, {"on_call_availability": merged_av})
                except Exception as ex:
                    errors.append({"id": bcid, "error": str(ex)})
            batch.clear()
            await asyncio.sleep(0.05)

    for bcid, merged_av in batch:
        try:
            await modify_contact(bcid, {"on_call_availability": merged_av})
        except Exception as ex:
            errors.append({"id": bcid, "error": str(ex)})

    summary = {
        "status": 200,
        "processed_rows": total_rows,
        "imported_windows": imported_windows,
        "updated_contacts": len(set(updated_contact_ids)),
        "updated_contact_ids": sorted(set(updated_contact_ids)),
        "not_found_ids": not_found_ids,
        "errors_count": len(errors),
        "errors": errors[:10],
    }

    return jsonify(summary), 200


@address_book_blueprint.route("/address_book/export_csv")
@login_required
async def export_contacts_csv():
    """
    Exports contacts in CSV format to the client.

    This asynchronous endpoint fetches contact data from an external address book
    service and prepares it in a downloadable CSV format. If the external request
    is successful, the data is returned with appropriate headers for the
    client to download. In case of any exception or errors during the process,
    the server will respond with an internal server error and the error message.

    :return: A tuple containing a Flask Response object with the exported CSV content or
             an error message, and the corresponding HTTP status code.
    :rtype: tuple[flask.Response, int]
    """

    try:
        resp = requests.get(f"{CALLER_ADDR_BOOK_BASE}/{SERVICE_EXPORT}", timeout=30)
        content = resp.content or b""
        headers = {
            "Content-Disposition": resp.headers.get(
                "Content-Disposition", "attachment; filename=address_book_export.csv"
            )
        }
        return Response(content, mimetype="text/csv", headers=headers), resp.status_code
    except Exception as e:
        return Response(str(e), status=500)


@address_book_blueprint.route("/address_book/import_csv", methods=["POST"])
@login_required
async def import_contacts_csv():
    """
    Handles the import of contacts via CSV into the address book.

    Users must upload a valid CSV file that contains the contact information
    to be imported. This endpoint forwards the uploaded file to an external
    service responsible for processing and importing the file data into the
    address book. The response from the external service is then returned
    to the client.

    :parameters:
        - file: FileStorage
            The CSV file uploaded by the user. This file should be sent in the
            request body under the field name 'file'.

    :return:
        A JSON response containing the status and message of the operation.
        On success, the response from the external service is forwarded to
        the client. On failure, an appropriate error message and corresponding
        status code are returned.

    :raises:
        - 400: If no file is uploaded with the request or the file field is
          improperly named.
        - 500: If an exception occurs during communication with the external
          service or while handling the uploaded file.
    """

    file = request.files.get("file")
    if not file:
        return jsonify(
            {
                "status": 400,
                "message": "No CSV file uploaded (field name should be 'file')",
            }
        ), 400
    try:
        files = {
            "file": (
                getattr(file, "filename", "address_book.csv"),
                file.stream,
                "text/csv",
            )
        }
        resp = requests.post(
            f"{CALLER_ADDR_BOOK_BASE}/{SERVICE_IMPORT}", files=files, timeout=120
        )
        try:
            data = resp.json()
        except Exception:
            data = {"status": resp.status_code, "message": resp.text}
        return jsonify(data), resp.status_code
    except Exception as e:
        return jsonify({"status": 500, "message": str(e)}), 500


@address_book_blueprint.route("/address_book/api/add", methods=["POST"])
@login_required
def api_add_contact():
    """
    Adds a new contact to the address book by forwarding the request and payload
    to an external address book service. The request and response are processed
    to ensure valid JSON data.

    :raises: If the JSON payload is invalid or a network/service error occurs,
             an appropriate response with relevant status code and message
             will be returned.

    :return: A JSON response indicating the status of the operation and the data
             returned by the external address book service. Possible status codes
             include:
             - 400: Invalid JSON payload.
             - 200: Successful addition of contact (status depends on the external service).
             - 500: Internal error occurred (e.g., network issues with external service).
    """

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"status": 400, "message": "Invalid JSON"}), 400

    try:
        resp = requests.post(
            f"{CALLER_ADDR_BOOK_BASE}/{ROUTE_ADD}", json=payload, timeout=5
        )
        data = None
        if resp.content:
            ct = resp.headers.get("Content-Type", "").lower()
            if "application/json" in ct:
                try:
                    data = resp.json()
                except Exception:
                    data = {"message": resp.text}
            else:
                data = {"message": resp.text}
        return jsonify({"status": resp.status_code, "data": data}), resp.status_code
    except Exception as e:
        return jsonify({"status": 500, "message": str(e)}), 500


@address_book_blueprint.route("/address_book/api/modify/<contact_id>", methods=["POST"])
@login_required
def api_modify_contact(contact_id: str):
    """
    Modifies an existing contact in the address book by updating its details with the
    information provided in the request payload. This endpoint interacts with an
    external service to make the modification.

    :param contact_id: The unique identifier of the contact to be modified.
    :type contact_id: str
    :return: A JSON response containing the status code and data returned by the external
        service. In the case of an error, the response includes the error message.
    :rtype: flask.Response
    """

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"status": 400, "message": "Invalid JSON"}), 400

    try:
        resp = requests.put(
            f"{CALLER_ADDR_BOOK_BASE}/{ROUTE_MODIFY}/{contact_id}",
            json=payload,
            timeout=5,
        )
        return jsonify(
            {"status": resp.status_code, "data": resp.json() if resp.content else None}
        ), resp.status_code
    except Exception as e:
        return jsonify({"status": 500, "message": str(e)}), 500


@address_book_blueprint.route("/address_book/api/delete", methods=["POST"])
@login_required
def api_delete_contacts():
    """
    Deletes specified contacts from the address book. The function expects a JSON payload
    containing a list of contact IDs. It validates the JSON payload and sends a DELETE
    request to the address book service to process the deletion. Responds with the
    status and result of the delete operation.

    :param payload: JSON payload containing a list of contact IDs under the key "ids".

    :return: Response with either success or error information.

    :raises:
        - 400: If the JSON payload is invalid or "ids" are not provided.
        - 500: If the delete operation fails due to a server-side or network error.
    """

    try:
        payload = request.get_json(force=True)
        ids = payload.get("ids", []) if isinstance(payload, dict) else []
    except Exception:
        return jsonify({"status": 400, "message": "Invalid JSON"}), 400

    if not ids:
        return jsonify({"status": 400, "message": "Provide ids: [uuid, ...]"}), 400

    try:
        resp = requests.delete(
            f"{CALLER_ADDR_BOOK_BASE}/{ROUTE_DELETE}", json={"ids": ids}, timeout=5
        )
        return jsonify(
            {"status": resp.status_code, "data": resp.json() if resp.content else None}
        ), resp.status_code
    except Exception as e:
        return jsonify({"status": 500, "message": str(e)}), 500
