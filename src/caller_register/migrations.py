"""
Database schema migrations, schema repair, and table verification routines.

Handles idempotent schema adjustments, Piccolo migration forwards, and
table consistency checks during service bootstrapping.
"""

import logging
import traceback
from piccolo.apps.migrations.tables import Migration
from piccolo.querystring import QueryString

from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB
from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.piccolo_app import (
    APP_CONFIG,
)
from caller_register.exceptions import DatabaseConnectionError, SchemaMigrationError


async def ensure_database_connection() -> bool:
    """Ensures that a connection pool to the database is active.

    Returns:
        bool: True if connection is available or established, False otherwise.

    Raises:
        DatabaseConnectionError: If starting the pool encounters an unrecoverable error.
    """
    if DB.pool is not None:
        return True

    try:
        await DB.start_connection_pool()
        logging.info("Connected to database connection pool")
        return True
    except Exception as err:
        logging.error(f"Error establishing database connection pool: {err}")
        return False


async def table_exists(table_name: str) -> bool:
    """Checks whether a given table exists in the current PostgreSQL schema.

    Args:
        table_name: Name of the relational table.

    Returns:
        bool: True if table exists in information_schema, False otherwise.
    """
    result = await DB.run_querystring(
        QueryString(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = {}
            ) AS exists;
            """,
            table_name,
        )
    )
    return bool(result and result[0]["exists"])


async def migration_record_exists(migration_name: str) -> bool:
    """Checks if a Piccolo migration record has already been registered.

    Args:
        migration_name: The migration identifier string.

    Returns:
        bool: True if recorded, False otherwise.
    """
    result = await Migration.select(Migration.name).where(
        (Migration.app_name == APP_CONFIG.app_name) & (Migration.name == migration_name)
    )
    return bool(result)


async def record_migration_if_missing(migration_name: str) -> bool:
    """Inserts a migration record into the Piccolo tracking table if not present.

    Args:
        migration_name: The migration identifier string.

    Returns:
        bool: True if newly recorded, False if already present.
    """
    if await migration_record_exists(migration_name):
        return False

    await Migration.insert(
        Migration(name=migration_name, app_name=APP_CONFIG.app_name)
    )
    return True


async def reconcile_existing_migration_history() -> None:
    """Marks baseline Piccolo migrations as applied when their tables already exist.

    Handles legacy databases created before migration tracking was reliable,
    avoiding duplicate creation errors while allowing fresh installs to run normally.
    """
    await Migration.create_table(if_not_exists=True)

    legacy_baselines = (
        ("2024-04-14T21:26:37:661173", ("calls",)),
        ("2024-04-14T21:50:55:271426", ("users", "asterisk_ws_events", "scheduled_calls")),
        ("2025-10-15T10:42:38:439829", ("address_book",)),
    )

    reconciled: list[str] = []
    for migration_name, required_tables in legacy_baselines:
        tables_exist = [await table_exists(table) for table in required_tables]
        if all(tables_exist) and await record_migration_if_missing(migration_name):
            reconciled.append(migration_name)

    if reconciled:
        logging.info("Marked existing legacy migration(s) as applied: %s", ", ".join(reconciled))


async def execute_migrations() -> bool:
    """Executes forward Piccolo migrations after enabling necessary PostgreSQL extensions.

    Returns:
        bool: True if forward migrations executed successfully, False otherwise.
    """
    try:
        await DB.run_ddl('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        logging.info("Ensured uuid-ossp extension is enabled")

        await reconcile_existing_migration_history()

        from piccolo.apps.migrations.commands.forwards import forwards

        await forwards(app_name=APP_CONFIG.app_name)
        logging.info("Successfully applied migrations")
        return True
    except Exception as err:
        logging.error(f"Error running forward migrations: {err}")
        return False


async def repair_existing_schema() -> bool:
    """Applies idempotent DDL updates for tables created in earlier versions.

    Returns:
        bool: True if all schema repairs succeeded, False otherwise.
    """
    try:
        await DB.run_ddl(
            """
            ALTER TABLE calls
                ADD COLUMN IF NOT EXISTS call_backup_callee_number_calls smallint DEFAULT 0 NOT NULL,
                ADD COLUMN IF NOT EXISTS oncall boolean DEFAULT false NOT NULL,
                ADD COLUMN IF NOT EXISTS backup_callee boolean DEFAULT false NOT NULL,
                ADD COLUMN IF NOT EXISTS lang varchar(32) DEFAULT '' NOT NULL;
            """
        )
        logging.info("Ensured legacy Calls table contains backup, oncall, and lang columns")

        await DB.run_ddl(
            """
            ALTER TABLE scheduled_calls
                ADD COLUMN IF NOT EXISTS lang varchar(32) DEFAULT '' NOT NULL;
            """
        )
        logging.info("Ensured ScheduledCalls table contains lang column")

        await DB.run_ddl(
            """
            ALTER TABLE users
                ADD COLUMN IF NOT EXISTS annotations varchar(2048) DEFAULT '' NOT NULL;
            """
        )
        logging.info("Ensured legacy Users table contains annotations column")

        await DB.run_ddl(
            """
            CREATE TABLE IF NOT EXISTS sms (
                id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
                phone varchar(64) DEFAULT '' NOT NULL,
                message varchar(1024) DEFAULT '' NOT NULL,
                carrier varchar(64) DEFAULT '' NOT NULL,
                status varchar(64) DEFAULT '' NOT NULL,
                created_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL,
                error varchar(1024) DEFAULT '' NOT NULL
            );
            """
        )
        logging.info("Ensured SMS table exists")

        await DB.run_ddl(
            """
            CREATE TABLE IF NOT EXISTS dead_letter_queue (
                id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
                task_id varchar(128) DEFAULT '' NOT NULL,
                task_name varchar(128) DEFAULT '' NOT NULL,
                queue varchar(64) DEFAULT 'telephony.dlq' NOT NULL,
                payload jsonb DEFAULT '{}'::jsonb NOT NULL,
                exception varchar(2048) DEFAULT '' NOT NULL,
                traceback varchar(4096) DEFAULT '' NOT NULL,
                created_at timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL
            );
            """
        )
        logging.info("Ensured DeadLetterQueue table exists")
        return True
    except Exception as err:
        logging.error(f"Error repairing existing database schema: {err}")
        logging.error(traceback.format_exc())
        return False


async def verify_tables() -> None:
    """Queries and verifies record counts across all declared tables in APP_CONFIG."""
    tables = APP_CONFIG.table_classes
    if not tables:
        return

    logging.info(f"Verifying {len(tables)} tables...")
    for table_class in tables:
        try:
            count = await table_class.count()
            logging.info(f"{table_class.__name__}: exists (contains {count} records)")
        except Exception as err:
            logging.error(f"{table_class.__name__}: error querying table - {err}")


async def run_piccolo_migrations() -> bool:
    """Executes migrations, verifies schema integrity, and logs execution outcome.

    Returns:
        bool: True if migrations and verification succeeded, False otherwise.
    """
    logging.info("Running Piccolo migrations...")

    if not await ensure_database_connection():
        return False

    try:
        logging.info(f"Found app config for {APP_CONFIG.app_name}")
        success = await execute_migrations()
        if success:
            await verify_tables()
        return success
    except Exception as err:
        logging.error(f"Error during migration execution: {err}")
        logging.error(traceback.format_exc())
        return False
    finally:
        logging.info("Piccolo migration process completed")


async def init_database() -> None:
    """Bootstraps the database with fallback table creation and schema repairs."""
    logging.info("Initializing the database...")

    migration_success = await run_piccolo_migrations()
    if not migration_success:
        logging.warning("Migrations failed, falling back to direct table creation")
        for table_class in APP_CONFIG.table_classes:
            try:
                logging.info(f"Creating table: {table_class.__name__}")
                await table_class.create_table(if_not_exists=True)
                logging.info(f"Table {table_class.__name__} created successfully")
            except Exception as err:
                logging.error(f"Error creating table {table_class.__name__}: {err}")

    repair_ok = await repair_existing_schema()
    if repair_ok:
        await verify_tables()
    else:
        logging.error("Database initialization completed with schema repair errors")

    logging.info("Database initialization completed")
