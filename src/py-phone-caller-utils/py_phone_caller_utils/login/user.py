"""
User session and identity model for py_phone_caller_ui authentication.
"""

from __future__ import annotations
from typing import Any
from py_phone_caller_utils.py_phone_caller_db.db_user import select_user_id


class User:
    """User representation compatible with Flask-Login."""

    __slots__ = ("username",)

    def __init__(self, username: str) -> None:
        """
        Initializes a User instance with the provided username.

        Args:
            username: The unique username of the user.
        """
        self.username = username

    @property
    def is_authenticated(self) -> bool:
        """Indicates whether the user is authenticated."""
        return True

    @property
    def is_active(self) -> bool:
        """Indicates whether the user account is active."""
        return True

    @property
    def is_anonymous(self) -> bool:
        """Indicates whether the user is anonymous."""
        return False

    def get_id(self) -> str:
        """
        Retrieves the unique identifier for the user from the database.

        Returns:
            The unique identifier of the user as string.
        """
        return str(select_user_id(self.username))


__all__ = ["User"]
