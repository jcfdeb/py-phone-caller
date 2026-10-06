"""
caller_address_book package.

Manages address book contacts, schedules, CSV bulk import/export, and on-call responder lookups.
"""

from caller_address_book.exceptions import (
    AddressBookDatabaseError,
    CallerAddressBookError,
    ContactNotFoundError,
    ContactValidationError,
)
from caller_address_book.schemas import (
    ContactCSVRow,
    ContactItem,
    ImportSummary,
)
from caller_address_book.migrations import (
    ensure_db_pool,
    run_migrations_if_any,
)
from caller_address_book.services import (
    AddressBookService,
    normalize_string,
    serialize_json_field,
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

__all__ = [
    "AddressBookDatabaseError",
    "AddressBookService",
    "CallerAddressBookError",
    "ContactCSVRow",
    "ContactItem",
    "ContactNotFoundError",
    "ContactValidationError",
    "ImportSummary",
    "delete_contact_delete",
    "ensure_db_pool",
    "get_contact_on_call",
    "get_contacts_export_csv",
    "normalize_string",
    "post_contact_add",
    "post_contacts_import_csv",
    "put_contact_modify",
    "run_migrations_if_any",
    "serialize_json_field",
    "setup_routes",
]
