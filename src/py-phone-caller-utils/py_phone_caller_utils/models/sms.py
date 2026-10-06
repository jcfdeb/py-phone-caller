"""
SMS messaging domain models and status schemas.
"""

from enum import Enum
from typing import Optional
from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ConfigDict, field_validator
import re


class SmsStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    DUPLICATE_IGNORED = "duplicate_ignored"
    UNKNOWN = "unknown"


class SmsCarrier(str, Enum):
    ON_PREMISE = "on_premise"
    TWILIO = "twilio"
    DEFAULT = "default"


class SmsPayload(BaseModel):
    """
    Inbound request schema to enqueue or send an SMS.
    """
    model_config = ConfigDict(str_strip_whitespace=True)

    phone: str = Field(..., min_length=4, max_length=30, description="Destination phone number")
    message: str = Field(..., min_length=1, max_length=1600, description="SMS text content")
    carrier: Optional[str] = Field(default="default", description="Preferred carrier/gateway")
    group: Optional[str] = Field(default=None, description="Target contact group if phone is omitted")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        # Normalize spaces and dashes
        cleaned = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?[0-9]{5,20}$", cleaned):
            raise ValueError(f"Invalid phone number format: '{v}'")
        return cleaned


class SmsRecordModel(BaseModel):
    """
    Persisted SMS entity representation.
    """
    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4)
    phone: str
    message: str
    carrier: str = "default"
    status: SmsStatus = SmsStatus.QUEUED
    created_at: Optional[datetime] = None
    error: Optional[str] = None
