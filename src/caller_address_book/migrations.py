"""
Database migration management for caller_address_book.

Encapsulates Piccolo ORM migrations and startup initialization.
"""

from __future__ import annotations
import logging

from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.piccolo_app import (
    APP_CONFIG,
)


async def ensure_db_pool() -> None:
    """
    Ensures the Piccolo database connection pool is established.

    Raises:
        RuntimeError: If database connection cannot be started.
    """
    if DB.pool is None:
        await DB.start_connection_pool()
        logging.info("Connected to database for caller_address_book")


async def run_migrations_if_any() -> None:
    """
    Runs pending database migrations for the caller_address_book application.
    """
    try:
        from piccolo.apps.migrations.commands.forwards import forwards

        await forwards(app_name=APP_CONFIG.app_name)
    except Exception as e:
        logging.info(f"Piccolo migrations not executed for caller_address_book: {e}")
