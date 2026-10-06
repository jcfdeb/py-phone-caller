"""
Data contracts and schema definitions for the asterisk_recaller service.

Adheres to Python 3.14 standards using immutable, slotted dataclasses
for high performance and strict type checking.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(slots=True, frozen=True)
class RecallItem:
    """
    Represents an unacknowledged primary call candidate eligible for retry.

    Attributes:
        phone: Recipient phone number.
        message: Message to be delivered.
        seconds_to_forget: Configured expiration duration in seconds.
    """

    phone: str
    message: str
    seconds_to_forget: int | float = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RecallItem:
        """
        Creates a RecallItem from a dictionary.

        Args:
            data: Key-value mapping containing item fields.

        Returns:
            A validated immutable RecallItem instance.
        """
        return cls(
            phone=str(data.get("phone") or ""),
            message=str(data.get("message") or ""),
            seconds_to_forget=data.get("seconds_to_forget") or 0,
        )


@dataclass(slots=True, frozen=True)
class BackupCallItem:
    """
    Represents a persistently unacknowledged call requiring escalation to on-call contacts.

    Attributes:
        call_id: Unique database identifier of the original call.
        phone: Original target phone number.
        message: Alert message to deliver.
        backup_count: Number of previous backup attempts dispatched.
    """

    call_id: str | int
    phone: str
    message: str
    backup_count: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BackupCallItem:
        """
        Creates a BackupCallItem from a dictionary.

        Args:
            data: Key-value mapping containing backup call fields.

        Returns:
            A validated immutable BackupCallItem instance.
        """
        return cls(
            call_id=data.get("id") or "",
            phone=str(data.get("phone") or ""),
            message=str(data.get("message") or ""),
            backup_count=int(data.get("call_backup_callee_number_calls") or 0),
        )


@dataclass(slots=True, frozen=True)
class OnCallContact:
    """
    Represents an on-call personnel contact entry for escalation calls.

    Attributes:
        phone_number: Contact telephone number.
    """

    phone_number: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> OnCallContact:
        """
        Creates an OnCallContact from a dictionary.

        Args:
            data: Key-value mapping containing contact fields.

        Returns:
            A validated immutable OnCallContact instance.
        """
        return cls(phone_number=str(data.get("phone_number") or ""))


@dataclass(slots=True, frozen=True)
class RecallCycleResult:
    """
    Summary outcome of a single recall evaluation cycle.

    Attributes:
        primary_actions: Count of primary recall attempts dispatched.
        backup_actions: Count of backup escalation calls dispatched.
    """

    primary_actions: int = 0
    backup_actions: int = 0

    @property
    def total_actions(self) -> int:
        """Returns the sum of all recall actions performed."""
        return self.primary_actions + self.backup_actions
