"""
Domain exceptions for the caller_address_book service.

Provides strongly-typed domain exception hierarchies to avoid generic
exception handling and clearly separate contact validation, database,
and CSV parsing issues.
"""


class CallerAddressBookError(Exception):
    """Base exception for all caller_address_book domain failures."""


class ContactValidationError(CallerAddressBookError):
    """Raised when contact payload or row data fails validation constraints."""


class ContactNotFoundError(CallerAddressBookError):
    """Raised when a requested contact cannot be located."""


class AddressBookDatabaseError(CallerAddressBookError):
    """Raised when database operations fail."""
