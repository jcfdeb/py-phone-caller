"""
Contact and address book domain models.
"""

from typing import Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
import re


class ContactModel(BaseModel):
    """
    Standardized contact representation.
    """
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=120, description="Full name or team identifier")
    phone: str = Field(..., min_length=4, max_length=30, description="Primary telephone number")
    group: str = Field(default="default", max_length=80, description="On-call escalation group")
    email: Optional[str] = Field(default=None, max_length=120, description="Optional email address")
    description: Optional[str] = Field(default=None, max_length=255, description="Notes / title")
    on_call: bool = Field(default=False, description="Whether contact is currently on duty")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?[0-9]{5,20}$", cleaned):
            raise ValueError(f"Invalid phone number format: '{v}'")
        return cleaned


class ContactCreatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field(..., min_length=4, max_length=30)
    group: str = Field(default="default", max_length=80)
    email: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=255)
    on_call: bool = Field(default=False)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?[0-9]{5,20}$", cleaned):
            raise ValueError(f"Invalid phone number format: '{v}'")
        return cleaned


class ContactUpdatePayload(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=30)
    group: Optional[str] = Field(default=None, max_length=80)
    email: Optional[str] = Field(default=None, max_length=120)
    description: Optional[str] = Field(default=None, max_length=255)
    on_call: Optional[bool] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?[0-9]{5,20}$", cleaned):
            raise ValueError(f"Invalid phone number format: '{v}'")
        return cleaned
