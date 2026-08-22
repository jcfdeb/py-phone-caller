from piccolo.apps.migrations.auto.migration_manager import MigrationManager

from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB


ID = "2026-08-16T15:45:00:000000"
VERSION = "1.28.0"
DESCRIPTION = "Repair missing legacy schema columns"


async def add_missing_legacy_schema_columns():
    await DB.run_ddl(
        """
        ALTER TABLE calls
        ADD COLUMN IF NOT EXISTS call_backup_callee_number_calls SMALLINT NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS oncall BOOLEAN NOT NULL DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS backup_callee BOOLEAN NOT NULL DEFAULT FALSE
        """
    )

    await DB.run_ddl(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS annotations VARCHAR(2048) NOT NULL DEFAULT ''
        """
    )


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="py_phone_caller_piccolo_app",
        description=DESCRIPTION,
    )

    manager.raw.append(add_missing_legacy_schema_columns)

    return manager
