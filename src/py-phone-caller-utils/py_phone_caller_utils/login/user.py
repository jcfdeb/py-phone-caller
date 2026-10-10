"""
User session and identity model for py_phone_caller_ui authentication.
"""

from __future__ import annotations
from typing import Any
from py_phone_caller_utils.config import settings
from py_phone_caller_utils.py_phone_caller_db.db_user import select_user_id


class User:
    """User representation compatible with Flask-Login and RBAC."""

    __slots__ = ("username", "roles", "email", "_id")

    def __init__(
        self,
        username: str,
        roles: list[str] | None = None,
        email: str | None = None,
        id: str | None = None,
    ) -> None:
        """
        Initializes a User instance with identity and RBAC roles.

        Args:
            username: The unique username of the user.
            roles: Optional list of realm/client roles (e.g. ['alert-admin']).
            email: Optional email address of the user.
            id: Optional database primary key identifier.
        """
        self.username = username
        self.roles = list(roles) if roles else []
        self.email = email or username
        self._id = id

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
        if self._id is not None:
            return str(self._id)
        return str(select_user_id(self.username))

    def has_role(self, role: str) -> bool:
        """Checks if user possesses a given RBAC role."""
        return role in self.roles

    @property
    def is_admin(self) -> bool:
        """Checks if the user has administrative privileges."""
        if "alert-admin" in self.roles:
            return True
        admin_user = getattr(getattr(settings, "ui", None), "ui_admin_user", "admin")
        return bool(self.username and self.username.lower() == str(admin_user).lower())

    @property
    def is_operator(self) -> bool:
        """Checks if the user has operator or admin privileges."""
        return self.is_admin or "alert-operator" in self.roles

    @property
    def is_viewer(self) -> bool:
        """Checks if the user has viewer, operator, or admin privileges."""
        return self.is_operator or "alert-viewer" in self.roles


__all__ = ["User"]
