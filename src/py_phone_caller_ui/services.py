"""
Business logic and services for the py_phone_caller_ui service.

Encapsulates locale resolution and negotiation, admin user bootstrap lifecycle,
and user authentication loaders.
"""

from __future__ import annotations
import asyncio
import logging
import os
from typing import Any, Callable, Sequence

from py_phone_caller_utils.login.user import User
from py_phone_caller_utils.py_phone_caller_db.db_user import (
    ensure_admin_user_exists,
    load_user_by_id,
    reset_admin_password_if_needed,
)

from py_phone_caller_ui.constants import UI_ADMIN_USER
from py_phone_caller_ui.exceptions import AdminBootstrapError
from py_phone_caller_ui.schemas import (
    AdminBootstrapResult,
    LocaleMeta,
    TextDirection,
)

logger = logging.getLogger(__name__)

SUPPORTED_LOCALES: dict[str, dict[str, str]] = {
    "en": {"name": "English", "flag": "🇬🇧", "dir": "ltr"},
    "es": {"name": "Español", "flag": "🇪🇸", "dir": "ltr"},
    "it": {"name": "Italiano", "flag": "🇮🇹", "dir": "ltr"},
    "de": {"name": "Deutsch", "flag": "🇩🇪", "dir": "ltr"},
    "fr": {"name": "Français", "flag": "🇫🇷", "dir": "ltr"},
    "ru": {"name": "Русский", "flag": "🇷🇺", "dir": "ltr"},
    "zh": {"name": "中文 (Chinese)", "flag": "🇨🇳", "dir": "ltr"},
    "hi": {"name": "हिन्दी (Hindi)", "flag": "🇮🇳", "dir": "ltr"},
    "he": {"name": "עברית (Hebrew)", "flag": "🇮🇱", "dir": "rtl"},
    "ar": {"name": "العربية (Arabic)", "flag": "🇸🇦", "dir": "rtl"},
}

LOCALE_ALIASES: dict[str, str] = {
    "zh_cn": "zh",
    "zh-cn": "zh",
    "zh_hans": "zh",
    "zh-hans": "zh",
    "zh_sg": "zh",
    "zh-sg": "zh",
    "zh_tw": "zh",
    "zh-tw": "zh",
    "hi_in": "hi",
    "hi-in": "hi",
    "es_es": "es",
    "es-es": "es",
    "it_it": "it",
    "it-it": "it",
    "de_de": "de",
    "de-de": "de",
    "fr_fr": "fr",
    "fr-fr": "fr",
    "ru_ru": "ru",
    "ru-ru": "ru",
    "en_us": "en",
    "en-us": "en",
    "en_gb": "en",
    "en-gb": "en",
    "he_il": "he",
    "he-il": "he",
    "ar_sa": "ar",
    "ar-sa": "ar",
    "ar_eg": "ar",
    "ar-eg": "ar",
    "ar_ae": "ar",
    "ar-ae": "ar",
}


class LocaleService:
    """Service responsible for resolving and negotiating i18n locales."""

    def __init__(
        self,
        supported_locales: dict[str, dict[str, str]] | None = None,
        aliases: dict[str, str] | None = None,
        default_locale: str = "en",
    ) -> None:
        """
        Initializes the LocaleService.

        Args:
            supported_locales: Mapping of locale codes to display dictionaries.
            aliases: Mapping of regional codes to canonical locale codes.
            default_locale: Fallback locale when no match is found.
        """
        self.supported_locales = supported_locales or SUPPORTED_LOCALES
        self.aliases = aliases or LOCALE_ALIASES
        self.default_locale = default_locale

    def resolve_locale(self, code: str | None) -> str | None:
        """
        Resolves a standard or regional language code to a supported UI locale.

        Args:
            code: Candidate language string (e.g. 'en-US', 'es_ES', 'it').

        Returns:
            Canonical locale code if supported, else None.
        """
        if not code:
            return None

        normalized = code.strip().lower().replace("-", "_")

        if normalized in self.supported_locales:
            return normalized

        if normalized in self.aliases:
            return self.aliases[normalized]

        prefix = normalized.split("_")[0]
        if prefix in self.supported_locales:
            return prefix

        return None

    def negotiate_locale(
        self,
        session_locale: str | None,
        cookie_locale: str | None,
        header_matcher: Callable[[Sequence[str]], str | None] | None = None,
    ) -> str:
        """
        Negotiates active UI locale using persistent priority cascade:
        1. Session preference
        2. Cookie preference
        3. Browser Accept-Language header best match
        4. Default fallback ('en')

        Args:
            session_locale: Value stored in Flask session, if any.
            cookie_locale: Value stored in HTTP cookie, if any.
            header_matcher: Callable taking candidate list and returning best match.

        Returns:
            The negotiated locale string.
        """
        if session_locale:
            resolved = self.resolve_locale(session_locale)
            if resolved:
                return resolved

        if cookie_locale:
            resolved = self.resolve_locale(cookie_locale)
            if resolved:
                return resolved

        if header_matcher:
            candidates = list(self.supported_locales.keys()) + list(self.aliases.keys())
            best = header_matcher(candidates)
            if best:
                resolved = self.resolve_locale(best)
                if resolved:
                    return resolved

        return self.default_locale


class AdminBootstrapService:
    """Handles startup verification, creation, and password reset of the admin user."""

    def __init__(self, admin_user: str = UI_ADMIN_USER) -> None:
        self.admin_user = admin_user

    async def _setup_admin_async(self) -> bool:
        """Executes database async creation or password reset."""
        created_admin_password = await ensure_admin_user_exists(self.admin_user)
        if created_admin_password is None:
            await reset_admin_password_if_needed(self.admin_user)
            return False
        return True

    def bootstrap(self) -> AdminBootstrapResult:
        """
        Executes admin user initialization if not already executed in this process.

        Returns:
            AdminBootstrapResult indicating state.
        """
        is_reseted = os.environ.get("UI_ADMIN_PASSWORD_RESETED")
        logger.debug(f"Checking admin user setup. UI_ADMIN_PASSWORD_RESETED: {is_reseted}")

        if is_reseted:
            return AdminBootstrapResult(
                admin_user=self.admin_user,
                already_initialized=True,
                created=False,
            )

        try:
            logger.debug("Performing admin user setup...")
            created = asyncio.run(self._setup_admin_async())
            os.environ["UI_ADMIN_PASSWORD_RESETED"] = "True"
            logger.debug("Admin user setup completed successfully.")
            return AdminBootstrapResult(
                admin_user=self.admin_user,
                already_initialized=False,
                created=created,
            )
        except Exception as err:
            logger.error(f"Failed to setup admin user: {err}", exc_info=True)
            return AdminBootstrapResult(
                admin_user=self.admin_user,
                already_initialized=False,
                created=False,
                error=str(err),
            )


class UserAuthenticationService:
    """User loading service for Flask-Login."""

    def __init__(self, loader_fn: Callable[[str], dict[str, Any] | None] | None = None) -> None:
        self.loader_fn = loader_fn or load_user_by_id

    def load_user(self, user_id: str) -> User | None:
        """
        Loads a User domain instance by ID from the database.

        Args:
            user_id: Unique string identifier of the user.

        Returns:
            User instance if found and valid, otherwise None.
        """
        loaded_user = self.loader_fn(user_id)
        if loaded_user is None:
            return None
        return User(username=loaded_user.get("email"))
