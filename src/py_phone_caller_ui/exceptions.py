"""
Exception hierarchy for the py_phone_caller_ui service.
"""

from __future__ import annotations


class UiError(Exception):
    """Base exception for py_phone_caller_ui errors."""


class UserAuthenticationError(UiError):
    """Raised when authentication verification fails."""


class LocaleResolutionError(UiError):
    """Raised when an invalid or unresolvable locale is handled."""


class AdminBootstrapError(UiError):
    """Raised when initial administrator creation or password setup fails."""
