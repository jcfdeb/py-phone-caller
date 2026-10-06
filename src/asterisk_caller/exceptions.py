"""
Domain exceptions for the asterisk_caller service.

Provides strongly-typed domain exception hierarchies to avoid generic
exception catching and clearly distinguish telecom PBX, address book,
and parameter validation errors.
"""


class AsteriskCallerError(Exception):
    """Base exception for all asterisk_caller domain failures."""


class OnCallPhoneUnavailable(RuntimeError, AsteriskCallerError):
    """Raised when the special 'oncall' phone alias cannot be resolved."""


class MissingParameterError(AsteriskCallerError):
    """Raised when an incoming HTTP request lacks required fields."""

    def __init__(self, message: str, missing_fields: list[str]) -> None:
        super().__init__(message)
        self.missing_fields = missing_fields


class AriConnectionError(AsteriskCallerError):
    """Raised when a connection to the Asterisk ARI interface fails."""


class CircuitBreakerOpenError(AsteriskCallerError):
    """Raised when the Asterisk ARI circuit breaker is open due to repeated failures."""
