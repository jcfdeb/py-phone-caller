"""
Domain schemas and data contracts for the py_phone_caller_ui service.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TextDirection(StrEnum):
    """HTML layout direction."""

    LTR = "ltr"
    RTL = "rtl"


@dataclass(slots=True, frozen=True)
class LocaleMeta:
    """
    Metadata representation for a supported UI locale.

    Attributes:
        code: ISO-639-1 language code (e.g. 'en', 'es', 'it').
        name: Native display name of the language.
        flag: Flag emoji symbol.
        direction: Layout direction ('ltr' or 'rtl').
    """

    code: str
    name: str
    flag: str
    direction: TextDirection = TextDirection.LTR

    def to_dict(self) -> dict[str, str]:
        """Converts to dictionary representation for template injection."""
        return {
            "name": self.name,
            "flag": self.flag,
            "dir": self.direction.value,
        }


@dataclass(slots=True, frozen=True)
class ServiceEndpointSummary:
    """
    Metadata describing an exposed HTTP route in OpenAPI / Swagger UI.

    Attributes:
        path: URI endpoint path.
        method: HTTP method in lowercase ('get', 'post').
        summary: Human-readable route purpose.
    """

    path: str
    method: str
    summary: str


@dataclass(slots=True, frozen=True)
class AdminBootstrapResult:
    """
    Result contract for admin user verification on service startup.

    Attributes:
        admin_user: Configured administrator username.
        already_initialized: Whether initialization had previously run.
        created: Whether a fresh admin user was created in the database.
        error: Optional error detail if execution failed.
    """

    admin_user: str
    already_initialized: bool
    created: bool = False
    error: str | None = None
