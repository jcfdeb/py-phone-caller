from piccolo.apps.migrations.auto.migration_manager import MigrationManager

from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB


ID = "2026-11-21T11:30:00:000000"
VERSION = "1.28.0"
DESCRIPTION = "Add optional sms_phone_number column to address_book"


async def add_sms_phone_number_column():
    await DB.run_ddl(
        """
        ALTER TABLE address_book
        ADD COLUMN IF NOT EXISTS sms_phone_number VARCHAR(64) NOT NULL DEFAULT ''
        """
    )


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="py_phone_caller_piccolo_app",
        description=DESCRIPTION,
    )

    manager.raw.append(add_sms_phone_number_column)

    return manager
