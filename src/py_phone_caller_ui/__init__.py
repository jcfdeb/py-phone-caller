"""
py_phone_caller_ui package.

Modular Flask web interface for py-phone-caller.
Exposes schemas, services, application instance, and blueprint components.
"""

from __future__ import annotations

from py_phone_caller_ui.exceptions import (
    AdminBootstrapError,
    LocaleResolutionError,
    UiError,
    UserAuthenticationError,
)
from py_phone_caller_ui.schemas import (
    AdminBootstrapResult,
    LocaleMeta,
    ServiceEndpointSummary,
    TextDirection,
)
from py_phone_caller_ui.services import (
    LOCALE_ALIASES,
    SUPPORTED_LOCALES,
    AdminBootstrapService,
    LocaleService,
    UserAuthenticationService,
)
from py_phone_caller_ui.app import app

__all__ = [
    "AdminBootstrapError",
    "AdminBootstrapResult",
    "AdminBootstrapService",
    "LOCALE_ALIASES",
    "LocaleMeta",
    "LocaleResolutionError",
    "LocaleService",
    "SUPPORTED_LOCALES",
    "ServiceEndpointSummary",
    "TextDirection",
    "UiError",
    "UserAuthenticationError",
    "UserAuthenticationService",
    "app",
]
