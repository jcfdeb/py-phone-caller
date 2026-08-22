#!/usr/bin/env python3
"""
Unattended PostgreSQL Database & Role Provisioner for py-phone-caller.

This utility connects to PostgreSQL using administrative credentials (e.g., 'postgres')
and idempotently performs the full unattended initialization required for py-phone-caller:
  1. Creates or updates the application user/role with LOGIN and password.
  2. Creates the application database (if not existing) owned by the application user.
  3. Grants all database and public schema privileges to the application user.
  4. Enables required extensions ('uuid-ossp', 'pgcrypto').
  5. Verifies end-to-end connectivity using the newly provisioned application credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any, Dict, Optional

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("init_postgres_db")


def quote_ident(ident: str) -> str:
    """Safely quote a SQL identifier (table, user, db name)."""
    return '"' + ident.replace('"', '""') + '"'


def quote_literal(val: str) -> str:
    """Safely quote a SQL string literal."""
    return "'" + val.replace("'", "''") + "'"


def load_dynaconf_db_defaults(config_dir: Optional[str] = None) -> Dict[str, Any]:
    """Attempt to load database settings from Dynaconf if available."""
    defaults: Dict[str, Any] = {
        "db_host": "127.0.0.1",
        "db_port": 5432,
        "db_name": "py_phone_caller",
        "db_user": "py_phone_caller",
        "db_password": "py_phone_caller_password",
    }
    try:
        if config_dir:
            os.environ["CALLER_CONFIG_DIR"] = config_dir
        from dynaconf import Dynaconf  # type: ignore[import-not-found]

        cfg_dir = config_dir or os.getenv("CALLER_CONFIG_DIR", "src/config")
        settings_file = os.path.join(cfg_dir, "settings.toml")
        secrets_file = os.path.join(cfg_dir, ".secrets.toml")
        settings = Dynaconf(
            settings_files=[settings_file, secrets_file],
            environments=False,
            load_dotenv=False,
        )
        if hasattr(settings, "database"):
            db = settings.database
            if hasattr(db, "db_host"):
                defaults["db_host"] = str(db.db_host)
            if hasattr(db, "db_port"):
                defaults["db_port"] = int(db.db_port)
            if hasattr(db, "db_name"):
                defaults["db_name"] = str(db.db_name)
            if hasattr(db, "db_user"):
                defaults["db_user"] = str(db.db_user)
            if hasattr(db, "db_password"):
                defaults["db_password"] = str(db.db_password)
    except Exception as exc:
        logger.debug("Could not load Dynaconf settings: %s", exc)

    return defaults


async def provision_postgres_database(
    admin_host: str,
    admin_port: int,
    admin_user: str,
    admin_password: Optional[str],
    admin_db: str,
    app_db_name: str,
    app_db_user: str,
    app_db_password: str,
    ssl: Optional[str] = None,
    dry_run: bool = False,
    skip_extensions: bool = False,
) -> bool:
    """
    Perform unattended database, user, permissions, and extensions provisioning.
    """
    if asyncpg is None:
        raise RuntimeError("asyncpg is required to run init_postgres_db. Please install asyncpg or run via uv.")

    logger.info(
        "Connecting to PostgreSQL as admin user '%s' at %s:%d/%s...",
        admin_user,
        admin_host,
        admin_port,
        admin_db,
    )

    if dry_run:
        logger.info("[DRY RUN] Would check/create role '%s'", app_db_user)
        logger.info("[DRY RUN] Would check/create database '%s' owned by '%s'", app_db_name, app_db_user)
        logger.info("[DRY RUN] Would grant privileges on '%s' to '%s'", app_db_name, app_db_user)
        if not skip_extensions:
            logger.info("[DRY RUN] Would create extensions 'uuid-ossp' and 'pgcrypto' in '%s'", app_db_name)
        return True

    # 1. Connect to admin/maintenance database
    admin_conn = await asyncpg.connect(
        host=admin_host,
        port=admin_port,
        user=admin_user,
        password=admin_password,
        database=admin_db,
        ssl=ssl,
    )

    try:
        # Check if role exists
        role_exists = await admin_conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = $1",
            app_db_user,
        )

        quoted_user = quote_ident(app_db_user)
        quoted_pass = quote_literal(app_db_password)

        if not role_exists:
            logger.info("Creating application role '%s' with LOGIN...", app_db_user)
            await admin_conn.execute(
                f"CREATE ROLE {quoted_user} WITH LOGIN ENCRYPTED PASSWORD {quoted_pass};"
            )
            logger.info("Application role '%s' created successfully.", app_db_user)
        else:
            logger.info("Role '%s' already exists; updating password and ensuring LOGIN...", app_db_user)
            await admin_conn.execute(
                f"ALTER ROLE {quoted_user} WITH LOGIN ENCRYPTED PASSWORD {quoted_pass};"
            )
            logger.info("Application role '%s' updated successfully.", app_db_user)

        # Check if database exists
        db_exists = await admin_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            app_db_name,
        )

        quoted_db = quote_ident(app_db_name)

        if not db_exists:
            logger.info("Creating application database '%s' owned by '%s'...", app_db_name, app_db_user)
            await admin_conn.execute(
                f"CREATE DATABASE {quoted_db} OWNER {quoted_user} ENCODING 'UTF8';"
            )
            logger.info("Application database '%s' created successfully.", app_db_name)
        else:
            logger.info("Database '%s' already exists; ensuring ownership by '%s'...", app_db_name, app_db_user)
            await admin_conn.execute(
                f"ALTER DATABASE {quoted_db} OWNER TO {quoted_user};"
            )

        # Grant database-level privileges
        logger.info("Granting all privileges on database '%s' to '%s'...", app_db_name, app_db_user)
        await admin_conn.execute(
            f"GRANT ALL PRIVILEGES ON DATABASE {quoted_db} TO {quoted_user};"
        )
    finally:
        await admin_conn.close()

    # 2. Connect as admin to target application database to configure schema & extensions
    logger.info("Connecting to target database '%s' as admin to configure schema and extensions...", app_db_name)
    app_admin_conn = await asyncpg.connect(
        host=admin_host,
        port=admin_port,
        user=admin_user,
        password=admin_password,
        database=app_db_name,
        ssl=ssl,
    )

    try:
        # Schema privileges
        logger.info("Granting all schema public privileges to '%s'...", app_db_user)
        await app_admin_conn.execute(
            f"GRANT ALL ON SCHEMA public TO {quoted_user};"
        )
        await app_admin_conn.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {quoted_user};"
        )
        await app_admin_conn.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {quoted_user};"
        )

        # Extensions
        if not skip_extensions:
            logger.info("Ensuring 'uuid-ossp' extension is installed...")
            await app_admin_conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
            logger.info("Ensuring 'pgcrypto' extension is installed...")
            await app_admin_conn.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')
            logger.info("Database extensions verified successfully.")
    finally:
        await app_admin_conn.close()

    # 3. Verify connection as the newly configured application user
    logger.info(
        "Verifying application user connectivity as '%s' on %s:%d/%s...",
        app_db_user,
        admin_host,
        admin_port,
        app_db_name,
    )
    user_conn = await asyncpg.connect(
        host=admin_host,
        port=admin_port,
        user=app_db_user,
        password=app_db_password,
        database=app_db_name,
        ssl=ssl,
    )
    try:
        row = await user_conn.fetchrow("SELECT current_user, current_database(), version();")
        if row:
            logger.info(
                "Verification SUCCESS: Connected as user '%s' to database '%s' (%s)",
                row["current_user"],
                row["current_database"],
                row["version"].split(",")[0],
            )
    finally:
        await user_conn.close()

    logger.info("Unattended PostgreSQL provisioning completed successfully.")
    return True


def build_parser() -> argparse.ArgumentParser:
    defaults = load_dynaconf_db_defaults()

    parser = argparse.ArgumentParser(
        description="Unattended PostgreSQL Database & Role Provisioner for py-phone-caller."
    )
    parser.add_argument(
        "--admin-host",
        dest="admin_host",
        default=os.getenv("PGHOST", defaults.get("db_host", "127.0.0.1")),
        help="PostgreSQL admin host (default: PGHOST or from settings.toml or 127.0.0.1)",
    )
    parser.add_argument(
        "--admin-port",
        dest="admin_port",
        type=int,
        default=int(os.getenv("PGPORT", defaults.get("db_port", 5432))),
        help="PostgreSQL admin port (default: PGPORT or from settings.toml or 5432)",
    )
    parser.add_argument(
        "--admin-user",
        dest="admin_user",
        default=os.getenv("PGUSER", os.getenv("PY_PHONE_CALLER_DB_ADMIN_USER", "postgres")),
        help="PostgreSQL admin username (default: PGUSER or postgres)",
    )
    parser.add_argument(
        "--admin-password",
        dest="admin_password",
        default=os.getenv("PGPASSWORD", os.getenv("PY_PHONE_CALLER_DB_ADMIN_PASSWORD", "")),
        help="PostgreSQL admin password (default: PGPASSWORD or PY_PHONE_CALLER_DB_ADMIN_PASSWORD)",
    )
    parser.add_argument(
        "--admin-db",
        dest="admin_db",
        default=os.getenv("PGDATABASE", "postgres"),
        help="Maintenance database to connect for admin tasks (default: postgres)",
    )
    parser.add_argument(
        "--app-db-name",
        dest="app_db_name",
        default=os.getenv("APP_DB_NAME", defaults.get("db_name", "py_phone_caller")),
        help="Application database name to create (default: py_phone_caller)",
    )
    parser.add_argument(
        "--app-db-user",
        dest="app_db_user",
        default=os.getenv("APP_DB_USER", defaults.get("db_user", "py_phone_caller")),
        help="Application database user/role to create (default: py_phone_caller)",
    )
    parser.add_argument(
        "--app-db-password",
        dest="app_db_password",
        default=os.getenv("APP_DB_PASSWORD", defaults.get("db_password", "py_phone_caller_password")),
        help="Application database user password to set (default: py_phone_caller_password)",
    )
    parser.add_argument(
        "--config-dir",
        dest="config_dir",
        default=os.getenv("CALLER_CONFIG_DIR", None),
        help="Optional path to py-phone-caller config directory containing settings.toml",
    )
    parser.add_argument(
        "--ssl",
        dest="ssl",
        default=None,
        help="SSL mode for database connection (e.g., 'require', 'prefer', 'disable')",
    )
    parser.add_argument(
        "--skip-extensions",
        dest="skip_extensions",
        action="store_true",
        help="Skip creation of uuid-ossp and pgcrypto extensions",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print actions without modifying PostgreSQL",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Re-evaluate config defaults if config-dir was explicitly given
    if args.config_dir:
        loaded = load_dynaconf_db_defaults(args.config_dir)
        if args.app_db_name == "py_phone_caller" and "db_name" in loaded:
            args.app_db_name = loaded["db_name"]
        if args.app_db_user == "py_phone_caller" and "db_user" in loaded:
            args.app_db_user = loaded["db_user"]
        if args.app_db_password == "py_phone_caller_password" and "db_password" in loaded:
            args.app_db_password = loaded["db_password"]

    admin_password = args.admin_password if args.admin_password else None

    try:
        asyncio.run(
            provision_postgres_database(
                admin_host=args.admin_host,
                admin_port=args.admin_port,
                admin_user=args.admin_user,
                admin_password=admin_password,
                admin_db=args.admin_db,
                app_db_name=args.app_db_name,
                app_db_user=args.app_db_user,
                app_db_password=args.app_db_password,
                ssl=args.ssl,
                dry_run=args.dry_run,
                skip_extensions=args.skip_extensions,
            )
        )
        return 0
    except Exception as exc:
        logger.error("Failed to provision PostgreSQL database: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
