"""
HTTP request handlers and routing for caller_address_book.

Defines REST endpoints for contact CRUD, on-call lookup, and CSV import/export.
"""

from __future__ import annotations
import logging
import sys
from aiohttp import web

from py_phone_caller_utils.web import create_service_catalog, setup_swagger_routes
from py_phone_caller_utils.web.readiness import ReadinessRegistry, check_database_pool

from caller_address_book.constants import (
    CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_DELETE_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_MODIFY_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT,
)
from caller_address_book.exceptions import ContactValidationError
from caller_address_book.services import AddressBookService


def _resolve_service(request: web.Request, explicit_service: AddressBookService | None) -> AddressBookService:
    """Dynamically resolves service instance supporting runtime mock overrides."""
    if explicit_service is not None:
        return explicit_service

    getter = request.app.get("address_book_service_factory")
    if getter:
        return getter()

    mod = sys.modules.get("src.caller_address_book.caller_address_book") or sys.modules.get(
        "caller_address_book.caller_address_book"
    )
    if mod and hasattr(mod, "_get_active_service"):
        return mod._get_active_service()

    return request.app.get("address_book_service") or AddressBookService()


async def post_contact_add(
    request: web.Request, service: AddressBookService | None = None
) -> web.Response:
    """
    Handles addition of a new contact via HTTP POST.

    Args:
        request: The aiohttp web request.
        service: Optional AddressBookService instance.

    Returns:
        JSON response with the new contact ID and HTTP 201 status.

    Raises:
        web.HTTPBadRequest: If JSON payload is invalid or fields missing.
        web.HTTPInternalServerError: For unexpected database errors.
    """
    svc = _resolve_service(request, service)
    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    try:
        contact_id = await svc.add_new_contact(payload)
        return web.json_response({"id": contact_id}, status=201)
    except (ValueError, ContactValidationError) as ve:
        raise web.HTTPBadRequest(text=str(ve))
    except Exception as e:
        logging.exception("Error adding contact")
        raise web.HTTPInternalServerError(text=str(e))


async def put_contact_modify(
    request: web.Request, service: AddressBookService | None = None
) -> web.Response:
    """
    Handles modification of an existing contact via HTTP PUT.

    Args:
        request: The aiohttp web request.
        service: Optional AddressBookService instance.

    Returns:
        JSON response indicating whether update succeeded.

    Raises:
        web.HTTPBadRequest: If JSON payload is invalid or contact ID is missing.
        web.HTTPInternalServerError: For unexpected database errors.
    """
    svc = _resolve_service(request, service)
    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    contact_id = request.match_info.get("id")
    if not contact_id:
        raise web.HTTPBadRequest(text="Missing contact id in path")

    try:
        updated = await svc.update_contact(contact_id, payload)
        return web.json_response({"updated": int(updated)})
    except Exception as e:
        logging.exception("Error modifying contact")
        raise web.HTTPInternalServerError(text=str(e))


async def delete_contact_delete(
    request: web.Request, service: AddressBookService | None = None
) -> web.Response:
    """
    Handles deletion of contacts via HTTP DELETE.

    Args:
        request: The aiohttp web request.
        service: Optional AddressBookService instance.

    Returns:
        JSON response indicating count of deleted contacts.

    Raises:
        web.HTTPBadRequest: If JSON body does not contain an 'ids' array.
        web.HTTPInternalServerError: For unexpected database errors.
    """
    svc = _resolve_service(request, service)
    try:
        payload = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    ids: list[str] = []
    if isinstance(payload, dict) and isinstance(payload.get("ids"), list):
        ids = [str(x) for x in payload.get("ids")]

    if not ids:
        raise web.HTTPBadRequest(text="Provide JSON body with 'ids': [uuid, ...]")

    try:
        deleted = await svc.remove_contacts(ids)
        return web.json_response({"deleted": int(deleted)})
    except Exception as e:
        logging.exception("Error deleting contacts")
        raise web.HTTPInternalServerError(text=str(e))


async def get_contact_on_call(
    request: web.Request, service: AddressBookService | None = None
) -> web.Response:
    """
    Fetches the current on-call contact phone number via HTTP GET.

    Args:
        request: The aiohttp web request.
        service: Optional AddressBookService instance.

    Returns:
        JSON response with the on-call phone number or 404 error.
    """
    svc = _resolve_service(request, service)
    try:
        contact = await svc.resolve_on_call_contact()
        if not contact:
            return web.json_response({"error": "No on-call contact found"}, status=404)
        return web.json_response({"phone_number": contact.get("phone_number")})
    except Exception as e:
        logging.exception("Error getting on-call contact")
        return web.json_response({"error": str(e)}, status=500)


async def get_contacts_export_csv(
    request: web.Request, service: AddressBookService | None = None
) -> web.Response:
    """
    Exports all contacts as a downloadable CSV stream via HTTP GET.

    Args:
        request: The aiohttp web request.
        service: Optional AddressBookService instance.

    Returns:
        HTTP response containing the CSV attachment.
    """
    svc = _resolve_service(request, service)
    try:
        csv_text = await svc.export_csv()
        resp = web.Response(text=csv_text)
        resp.content_type = "text/csv"
        resp.headers["Content-Disposition"] = "attachment; filename=address_book_export.csv"
        return resp
    except Exception as e:
        logging.exception("Error exporting contacts CSV")
        return web.json_response({"error": str(e)}, status=500)


async def post_contacts_import_csv(
    request: web.Request, service: AddressBookService | None = None
) -> web.Response:
    """
    Imports contacts from a CSV upload or payload via HTTP POST.

    Args:
        request: The aiohttp web request.
        service: Optional AddressBookService instance.

    Returns:
        JSON response summarizing imported rows and error counts.
    """
    svc = _resolve_service(request, service)
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

        summary = await svc.import_csv(content)
        return web.json_response(
            {
                "status": 200,
                "processed_rows": summary.processed_rows,
                "updated": summary.updated,
                "created": summary.created,
                "errors_count": summary.errors_count,
                "errors": summary.errors,
            }
        )
    except Exception as e:
        logging.exception("Error importing contacts CSV")
        return web.json_response({"error": str(e)}, status=500)


def setup_routes(app: web.Application) -> None:
    """
    Registers all routes and documentation onto the aiohttp application.

    Args:
        app: The aiohttp web Application.
    """
    registry = ReadinessRegistry("caller_address_book")
    registry.register("postgres_pool", check_database_pool)

    async def address_book_ready(request: web.Request) -> web.Response:
        all_ready, details = await registry.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    app.router.add_route("GET", "/ready", address_book_ready)

    async def root_catalog(request: web.Request) -> web.Response:
        catalog = create_service_catalog(
            service_name="caller_address_book",
            description="Address book and on-call contact management service for py-phone-caller",
            version="1.0.0",
            docs_url="/docs",
            openapi_spec="/docs/swagger.json",
            endpoints={
                f"POST /{CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT}": "Adds new contact (JSON body)",
                f"PUT /{CALLER_ADDRESS_BOOK_ROUTE_MODIFY_CONTACT}/{{id}}": "Modifies contact by ID (JSON body)",
                f"DELETE /{CALLER_ADDRESS_BOOK_ROUTE_DELETE_CONTACT}": "Deletes contacts (JSON body: ids list)",
                f"GET /{CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT}": "Retrieves current on-call contact phone",
                "GET /contacts_export_csv": "Exports address book as CSV stream",
                "POST /contacts_import_csv": "Imports contacts from CSV file or body",
                "GET /live": "Liveness health check",
                "GET /ready": "Readiness probe",
                "GET /metrics": "Prometheus telemetry metrics",
            },
        )
        return web.json_response(catalog)

    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route(
        "POST", f"/{CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT}", post_contact_add
    )
    app.router.add_route(
        "PUT",
        f"/{CALLER_ADDRESS_BOOK_ROUTE_MODIFY_CONTACT}/{{id}}",
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

    setup_swagger_routes(
        app=app,
        service_name="caller_address_book",
        description="Address Book and On-Call Responder Directory Management Service",
        paths={
            f"/{CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT}": {
                "post": {
                    "summary": "Create new contact",
                    "description": "Adds contact to Piccolo address book with on-call availability schedule.",
                    "responses": {"200": {"description": "Contact created"}},
                }
            },
            f"/{CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT}": {
                "get": {
                    "summary": "Resolve current on-call phone number",
                    "responses": {"200": {"description": "Current on-call contact number"}},
                }
            },
            "/contacts_export_csv": {
                "get": {
                    "summary": "Export contacts to CSV file",
                    "responses": {"200": {"description": "CSV stream attachment"}},
                }
            },
        },
    )
