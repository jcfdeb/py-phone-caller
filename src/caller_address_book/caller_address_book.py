"""
Caller Address Book service orchestrator and application entry point.

Provides backward-compatible facades delegating to modular schemas,
migrations, services, and routes.
"""

from __future__ import annotations
import logging
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

from aiohttp import web
from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB
from py_phone_caller_utils.py_phone_caller_db.db_address_book import (
    add_contact,
    delete_contacts,
    get_on_call_contact,
    modify_contact,
)
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    AddressBook,
)
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app

from caller_address_book.constants import (
    CALLER_ADDRESS_BOOK_PORT,
    CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_DELETE_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_MODIFY_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT,
    LOG_FORMATTER,
    LOG_LEVEL,
)
from caller_address_book.exceptions import (
    AddressBookDatabaseError,
    CallerAddressBookError,
    ContactNotFoundError,
    ContactValidationError,
)
from caller_address_book.migrations import (
    ensure_db_pool as _ensure_db_pool,
    run_migrations_if_any as _run_migrations_if_any,
)
from caller_address_book.routes import (
    delete_contact_delete,
    get_contact_on_call,
    get_contacts_export_csv,
    post_contact_add,
    post_contacts_import_csv,
    put_contact_modify,
    setup_routes,
)
from caller_address_book.schemas import (
    ContactCSVRow,
    ContactItem,
    ImportSummary,
)
from caller_address_book.services import (
    AddressBookService,
    normalize_string,
    serialize_json_field,
)

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
init_telemetry("caller_address_book")


def _get_active_service() -> AddressBookService:
    """Builds an AddressBookService referencing module-level callable overrides."""
    return AddressBookService(
        add_contact_fn=globals().get("add_contact", add_contact),
        modify_contact_fn=globals().get("modify_contact", modify_contact),
        delete_contacts_fn=globals().get("delete_contacts", delete_contacts),
        get_on_call_contact_fn=globals().get("get_on_call_contact", get_on_call_contact),
        address_book_table=globals().get("AddressBook", AddressBook),
    )


async def init_app() -> web.Application:
    """
    Initializes the caller_address_book aiohttp application.

    Ensures the database connection pool is active and registers routes.

    Returns:
        Configured aiohttp Application instance.
    """
    try:
        ensure_pool_fn = globals().get("_ensure_db_pool", _ensure_db_pool)
        await ensure_pool_fn()
    except Exception as db_err:
        logging.error(
            f"Database initial pool setup failed: {db_err}. Service starting degraded; /ready will indicate 503."
        )

    app = web.Application()
    instrument_aiohttp_app(app, "caller_address_book")
    app["address_book_service_factory"] = _get_active_service

    async def cleanup_db(application: web.Application) -> None:
        if DB.pool is not None:
            await DB.pool.close()
            logging.info("Database connection pool closed for caller_address_book")

    app.on_cleanup.append(cleanup_db)
    setup_routes(app)
    return app


if __name__ == "__main__":
    web.run_app(init_app(), port=int(CALLER_ADDRESS_BOOK_PORT))
