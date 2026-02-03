"""
Caller Address Book service.

Provides endpoints to manage contacts (add, modify, delete), query on-call
contacts, and import/export the address book in CSV format.
"""

import asyncio
import logging
import io
import csv
import json
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)


from aiohttp import web

from py_phone_caller_utils.py_phone_caller_db.db_address_book import (
    add_contact,
    delete_contacts,
    get_on_call_contact,
    modify_contact,
)
from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.piccolo_app import (
    APP_CONFIG,
)
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    AddressBook,
)
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app

from caller_address_book.constants import (
    CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_MODIFY_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_DELETE_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT,
    CALLER_ADDRESS_BOOK_PORT,
    LOG_FORMATTER,
    LOG_LEVEL,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)

init_telemetry("caller_address_book")


async def _ensure_db_pool():
    """
    Ensures the database connection pool is established.

    This function checks if the database connection pool is initialized. If not,
    it initiates the connection pool and logs the success of the connection to
    the database.

    :raises RuntimeError: If the database connection pool cannot be started.

    :return: None
    """

    if DB.pool is None:
        await DB.start_connection_pool()
        logging.info("Connected to database for caller_address_book")


async def _run_migrations_if_any():
    """
    Run pending database migrations if any are defined for the application.

    This function attempts to execute database migrations specified under the
    application's migration configuration using the Piccolo ORM. It handles
    any exceptions raised during the migration process and logs relevant
    information.

    :raises Exception: In case the migrations cannot be executed due to an
        error or a problem with the migration configuration.

    :return: None
    """

    try:
        from piccolo.apps.migrations.commands.forwards import forwards

        await forwards(app_name=APP_CONFIG.app_name)
    except Exception as e:
        logging.info(f"Piccolo migrations not executed for caller_address_book: {e}")


async def post_contact_add(request: web.Request) -> web.Response:
    """
    Handles the addition of a new contact by processing an incoming HTTP POST request.

    This asynchronous function processes a POST request containing a JSON body with the
    required contact information. It validates the JSON payload, calls the `add_contact`
    function to persist the new contact, and responds with the newly created contact's ID.
    If errors occur, it returns the appropriate HTTP error responses.

    :param request: The HTTP request object.
    :type request: web.Request
    :return: HTTP response containing the ID of the newly added contact or an error message.
    :rtype: web.Response
    :raises web.HTTPBadRequest: If the JSON body is invalid or required fields are missing.
    :raises web.HTTPInternalServerError: If an unexpected server error occurs during the contact creation process.
    """

    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    try:
        contact_id = await add_contact(payload)
        return web.json_response({"id": contact_id}, status=201)
    except ValueError as ve:
        raise web.HTTPBadRequest(text=str(ve))
    except Exception as e:
        logging.exception("Error adding contact")
        raise web.HTTPInternalServerError(text=str(e))


async def put_contact_modify(request: web.Request) -> web.Response:
    """
    Handles the modification of an existing contact. This asynchronous function
    takes the `request` containing the contact data, processes the JSON payload,
    and attempts to update the specified contact's details in the database based
    on the contact ID found in the request path.

    If the request does not contain a valid JSON body or is missing the contact ID,
    an appropriate HTTP error will be raised.

    :param request: HTTP request object of type ``web.Request`` containing the
        JSON payload to modify the contact and the contact ID in the path.
    :return: A ``web.Response`` object with the JSON response indicating whether the
        contact was successfully updated. The response includes a field "updated"
        which is 1 if the contact is updated, 0 otherwise.
    :raises web.HTTPBadRequest: If the JSON payload is invalid or the contact ID
        is missing from the request.
    :raises web.HTTPInternalServerError: In case of any internal error during the
        update operation, with the exception details provided in the response text.
    """

    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    contact_id = request.match_info.get("id")
    if not contact_id:
        raise web.HTTPBadRequest(text="Missing contact id in path")

    changes = {k: v for k, v in payload.items() if k != "id"}
    try:
        updated = await modify_contact(contact_id, changes)
        return web.json_response({"updated": int(updated)})
    except Exception as e:
        logging.exception("Error modifying contact")
        raise web.HTTPInternalServerError(text=str(e))


async def delete_contact_delete(request: web.Request) -> web.Response:
    """
    Deletes contacts based on the provided list of UUIDs in the request JSON body.

    This asynchronous function processes a DELETE HTTP request. It extracts a list of IDs from
    the JSON payload and attempts to delete the corresponding contacts. If successful, it returns
    a JSON response with the count of deleted contacts. The request must contain a valid JSON body
    with an "ids" array of UUIDs.

    :param request: The HTTP request object containing the JSON body.
    :type request: web.Request
    :return: A JSON response with the number of successfully deleted contacts.
    :rtype: web.Response
    :raises web.HTTPBadRequest: If the request body is not a valid JSON or does
        not contain a properly formatted "ids" array.
    :raises web.HTTPInternalServerError: If an error occurs while deleting the contacts,
        such as a database or server exception.
    """

    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    ids = []
    if isinstance(payload, dict) and isinstance(payload.get("ids"), list):
        ids = [str(x) for x in payload.get("ids")]

    if not ids:
        raise web.HTTPBadRequest(text="Provide JSON body with 'ids': [uuid, ...]")

    try:
        deleted = await delete_contacts(ids)
        return web.json_response({"deleted": int(deleted)})
    except Exception as e:
        logging.exception("Error deleting contacts")
        raise web.HTTPInternalServerError(text=str(e))


async def get_contact_on_call(request: web.Request) -> web.Response:
    """
    Fetches the current on-call contact information asynchronously.

    This function attempts to retrieve the on-call contact details, including the phone number,
    from the appropriate data source. If no contact is found, a 404 error response is returned.
    In case of any exceptions during the process, the error is logged and a 500 error response
    is returned.

    :param request: An instance of the `web.Request` object representing the HTTP request.
    :type request: web.Request
    :return: A JSON response containing the phone number of the on-call contact or an error
             message. Response status is 200 if successful, 404 if no contact found, or 500
             in case of an error.
    :rtype: web.Response
    """

    try:
        contact = await get_on_call_contact()
        if not contact:
            return web.json_response({"error": "No on-call contact found"}, status=404)
        return web.json_response({"phone_number": contact.get("phone_number")})
    except Exception as e:
        logging.exception("Error getting on-call contact")
        return web.json_response({"error": str(e)}, status=500)


async def get_contacts_export_csv(request: web.Request) -> web.StreamResponse:
    """
    Fetches and exports the contacts data from the AddressBook as a CSV file.

    This asynchronous function retrieves all the rows from the AddressBook, formats the
    data into a CSV file, and returns it as a downloadable HTTP response. The CSV file
    contains headers and rows of contact details.

    :param request: The HTTP request object.
    :type request: web.Request
    :return: A StreamResponse containing the exported CSV file or an error response
        in case of failure.
    :rtype: web.StreamResponse
    """

    try:
        rows = await AddressBook.select()
        output = io.StringIO()
        writer = csv.writer(output)
        headers = [
            "id",
            "name",
            "surname",
            "address",
            "zip_code",
            "city",
            "state",
            "country",
            "phone_number",
            "enabled",
            "created_time",
            "annotations",
            "on_call_availability",
        ]
        writer.writerow(headers)
        for r in rows:

            def jdump(val):
                try:
                    obj = val
                    if isinstance(obj, str):
                        try:
                            obj = json.loads(obj)
                        except Exception:
                            obj = []
                    if obj is None:
                        obj = []
                    return json.dumps(obj, separators=(",", ":"))
                except Exception:
                    return "[]"

            writer.writerow(
                [
                    str(r.get("id")),
                    r.get("name") or "",
                    r.get("surname") or "",
                    r.get("address") or "",
                    r.get("zip_code") or "",
                    r.get("city") or "",
                    r.get("state") or "",
                    r.get("country") or "",
                    r.get("phone_number") or "",
                    "true" if r.get("enabled") else "false",
                    r.get("created_time") or "",
                    r.get("annotations") or "",
                    jdump(r.get("on_call_availability") or []),
                ]
            )
        output.seek(0)
        resp = web.Response(text=output.getvalue())
        resp.content_type = "text/csv"
        resp.headers["Content-Disposition"] = (
            "attachment; filename=address_book_export.csv"
        )
        return resp
    except Exception as e:
        logging.exception("Error exporting contacts CSV")
        return web.json_response({"error": str(e)}, status=500)


async def post_contacts_import_csv(request: web.Request) -> web.Response:
    """
    Handles the import of contacts from a CSV file provided through a multipart/form-data request or
    as raw text. Validates the CSV content, processes rows to update or create contact entries, and
    returns a summary of results.

    :param request: The HTTP request containing the CSV data. It is either a multipart request with
        a file field or plain text in the body.
    :return: A JSON response with the number of rows processed, created, updated, and any errors
        encountered.
    """

    try:
        content = None
        if request.content_type and request.content_type.startswith("multipart/"):
            data = await request.post()
            file_field = data.get("file")
            if file_field is None:
                return web.json_response(
                    {"status": 400, "message": "No file field provided"}, status=400
                )
            content = file_field.file.read().decode("utf-8", errors="replace")
        else:
            content = await request.text()
        reader = csv.DictReader(io.StringIO(content))
        required = {"name", "phone_number"}
        processed = 0
        created = 0
        updated = 0
        errors = []
        batch_new = []
        batch_updates = []

        existing_rows = await AddressBook.select(
            AddressBook.id,
            AddressBook.name,
            AddressBook.surname,
            AddressBook.phone_number,
        )
        existing_ids = {str(r.get("id")) for r in existing_rows}

        def _norm(s: str) -> str:
            """
            Normalizes the input string by stripping leading and trailing whitespace
            and converting it to lowercase.

            :param s: The input string to normalize.
            :type s: str
            :return: A normalized string that is stripped of leading/trailing whitespace
                and converted to lowercase.
            :rtype: str
            """
            return (s or "").strip().lower()

        by_pns = {
            (
                _norm(r.get("phone_number")),
                _norm(r.get("name")),
                _norm(r.get("surname")),
            ): str(r.get("id"))
            for r in existing_rows
        }

        for idx, row in enumerate(reader, start=2):
            try:
                processed += 1
                r = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
                cid = r.get("id") or ""
                enabled_str = r.get("enabled", "").lower()
                enabled = (
                    True
                    if enabled_str in ("true", "1", "yes", "y")
                    else False
                    if enabled_str in ("false", "0", "no", "n")
                    else None
                )
                avail_raw = r.get("on_call_availability") or "[]"
                try:
                    s = (avail_raw or "").strip()
                    val = json.loads(s) if s else []
                    if isinstance(val, str):
                        try:
                            val2 = json.loads(val)
                            val = val2
                        except Exception:
                            pass
                    on_call_availability = val if isinstance(val, list) else []
                except Exception:
                    on_call_availability = []
                changes = {
                    "name": r.get("name", ""),
                    "surname": r.get("surname", ""),
                    "address": r.get("address", ""),
                    "zip_code": r.get("zip_code", ""),
                    "city": r.get("city", ""),
                    "state": r.get("state", ""),
                    "country": r.get("country", ""),
                    "phone_number": r.get("phone_number", ""),
                    "annotations": r.get("annotations", ""),
                    "on_call_availability": on_call_availability,
                }
                if enabled is not None:
                    changes["enabled"] = enabled
                if not changes.get("name") or not changes.get("phone_number"):
                    raise ValueError("Missing required name or phone_number")

                target_id = None
                if cid and cid in existing_ids:
                    target_id = cid
                else:
                    key = (
                        _norm(changes.get("phone_number")),
                        _norm(changes.get("name")),
                        _norm(changes.get("surname")),
                    )
                    target_id = by_pns.get(key)

                if target_id:
                    batch_updates.append((target_id, changes))
                else:
                    payload = changes.copy()
                    if "enabled" not in payload:
                        payload["enabled"] = False
                    batch_new.append(payload)
            except Exception as ex:
                errors.append({"row": idx, "error": str(ex)})

        async def _process_updates(items):
            """
            Processes updates for a given list of items in asynchronous chunks.

            This function processes a list of updates in chunks of size 10. For each chunk,
            it attempts to modify a contact using the provided `modify_contact` function.
            If an error occurs during this process, it captures the contact ID and the
            error details for further handling. The function ensures that the process
            is cooperative with other asynchronous tasks.

            :param items: List of items to be processed. Each item in the list should be a
                tuple containing a contact ID and the associated contact object.
            :type items: list[tuple]

            :return: This function does not return any specific value or output. Results of
                processed updates (e.g., errors or success counts) should be managed via
                the shared state within the surrounding context.
            :rtype: None
            """

            nonlocal updated
            for i in range(0, len(items), 10):
                chunk = items[i : i + 10]
                for cid, ch in chunk:
                    try:
                        await modify_contact(cid, ch)
                        updated += 1
                    except Exception as ex:
                        errors.append({"id": cid, "error": str(ex)})
                await asyncio.sleep(0)

        async def _process_creates(items):
            """
            Processes a list of items by creating contacts in chunks. Handles errors on a
            per-item basis by collecting error details for failed operations. This is
            an asynchronous function aimed at processing items in batches for efficiency.

            :param items: A list of dictionaries containing payloads to be processed
                          where each payload represents an item to be added as a contact.
            :type items: list[dict]
            :return: None. The function modifies the `created` counter (number of
                     successfully processed items) and appends to the `errors` list for
                     failed cases.
            """

            nonlocal created
            for i in range(0, len(items), 10):
                chunk = items[i : i + 10]
                for payload in chunk:
                    try:
                        await add_contact(payload)
                        created += 1
                    except Exception as ex:
                        errors.append({"name": payload.get("name"), "error": str(ex)})
                await asyncio.sleep(0)

        await _process_updates(batch_updates)
        await _process_creates(batch_new)

        return web.json_response(
            {
                "status": 200,
                "processed_rows": processed,
                "updated": updated,
                "created": created,
                "errors_count": len(errors),
                "errors": errors[:10],
            }
        )
    except Exception as e:
        logging.exception("Error importing contacts CSV")
        return web.json_response({"error": str(e)}, status=500)


async def init_app():
    """
    Initializes the application environment, including database pool setup
    and route definitions.

    This function prepares the web application by ensuring required resources
    are initialized and then defining the available HTTP routes for handling
    various contact-related operations.
    """

    await _ensure_db_pool()

    app = web.Application()

    instrument_aiohttp_app(app)

    app.router.add_route(
        "POST", f"/{CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT}", post_contact_add
    )
    app.router.add_route(
        "PUT",
        f"/{CALLER_ADDRESS_BOOK_ROUTE_MODIFY_CONTACT}" + "/{id}",
        put_contact_modify,
    )
    app.router.add_route(
        "DELETE",
        f"/{CALLER_ADDRESS_BOOK_ROUTE_DELETE_CONTACT}",
        delete_contact_delete,
    )
    app.router.add_route(
        "GET",
        f"/{CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT}",
        get_contact_on_call,
    )
    app.router.add_route("GET", "/contacts_export_csv", get_contacts_export_csv)
    app.router.add_route("POST", "/contacts_import_csv", post_contacts_import_csv)
    return app


if __name__ == "__main__":
    web.run_app(init_app(), port=int(CALLER_ADDRESS_BOOK_PORT))
