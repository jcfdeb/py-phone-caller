"""
Data schemas and contracts for the caller_address_book service.

Adheres to Python 3.14 standards using modern Pydantic models for validation
and immutable slotted dataclasses for lightweight data transfer.
"""

from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any, List, Optional
from pydantic import BaseModel, Field, field_validator


class ContactCSVRow(BaseModel):
    """
    Pydantic schema validator for CSV contact imports.
    Guarantees strict data integrity, non-blank names, and dialable/E.164 phone formats.
    """

    id: Optional[str] = None
    name: str = Field(..., min_length=1)
    surname: Optional[str] = ""
    address: Optional[str] = ""
    zip_code: Optional[str] = ""
    city: Optional[str] = ""
    state: Optional[str] = ""
    country: Optional[str] = ""
    phone_number: str = Field(...)
    enabled: Optional[bool] = None
    annotations: Optional[str] = ""
    on_call_availability: Optional[List[Any]] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("Contact 'name' cannot be blank.")
        return s

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        s = (v or "").strip()
        clean = re.sub(r"[\s\-\(\)\.]", "", s)
        if not re.match(r"^(\+|00)?[0-9]{5,18}$", clean):
            raise ValueError(
                f"Invalid phone number format '{s}'. Must be a dialable / E.164 number with 5-18 digits."
            )
        return clean


@dataclass(slots=True, frozen=True)
class ContactItem:
    """
    Immutable representation of an address book contact.

    Attributes:
        name: First/Given name.
        phone_number: Normalized phone number.
        id: Optional persistent UUID.
        surname: Optional family name.
        enabled: Whether contact is active.
    """

    name: str
    phone_number: str
    id: str | None = None
    surname: str = ""
    enabled: bool = True


@dataclass(slots=True, frozen=True)
class ImportSummary:
    """
    Summary outcome of a CSV import operation.

    Attributes:
        processed_rows: Total rows encountered in the CSV.
        created: Count of new contacts inserted.
        updated: Count of existing contacts updated.
        errors_count: Total count of validation or insertion errors.
        errors: Sample list of error details.
    """

    processed_rows: int
    created: int
    updated: int
    errors_count: int
    errors: list[dict[str, Any]]
