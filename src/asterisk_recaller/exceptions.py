"""
Domain exceptions for the asterisk_recaller service.

Provides strongly-typed domain exception hierarchies to avoid generic
exception catching and clearly distinguish telecom connection issues,
database access problems, and on-call contact resolution errors.
"""


class AsteriskRecallerError(Exception):
    """Base exception for all asterisk_recaller domain failures."""


class RecallerConnectionError(AsteriskRecallerError):
    """Raised when connection to the Asterisk call service fails."""


class NoOnCallContactsError(AsteriskRecallerError):
    """Raised when no active on-call contacts are available for backup dialing."""
