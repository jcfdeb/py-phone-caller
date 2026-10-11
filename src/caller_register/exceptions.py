"""
Domain exceptions for the caller_register service.

Provides strongly-typed, domain-specific exception hierarchies to eliminate
generic exception catching and distinguish between validation, database, and
lifecycle state failures.
"""


class CallerRegisterError(Exception):
    """Base exception for all caller_register domain failures."""


class MissingParameterError(CallerRegisterError):
    """Raised when an incoming HTTP request lacks required fields."""

    def __init__(self, message: str, missing_fields: list[str]) -> None:
        super().__init__(message)
        self.missing_fields = missing_fields


class DatabaseConnectionError(CallerRegisterError):
    """Raised when the database connection pool fails or times out."""


class SchemaMigrationError(CallerRegisterError):
    """Raised when database schema migrations or schema repair operations fail."""


class CallNotFoundError(CallerRegisterError):
    """Raised when an operation references a call that does not exist or has expired."""


class InvalidScheduledDateError(CallerRegisterError):
    """Raised when a scheduled call timestamp cannot be parsed or converted."""
