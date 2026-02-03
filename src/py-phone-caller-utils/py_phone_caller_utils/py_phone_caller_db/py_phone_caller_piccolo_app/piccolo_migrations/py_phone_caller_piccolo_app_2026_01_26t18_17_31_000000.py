from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Boolean
from piccolo.columns.indexes import IndexMethod


ID = "2026-01-26T18:17:31:000000"
VERSION = "1.28.0"
DESCRIPTION = "Add backup_callee column to Calls table"


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="py_phone_caller_piccolo_app",
        description=DESCRIPTION,
    )

    manager.add_column(
        table_class_name="Calls",
        tablename="calls",
        column_name="backup_callee",
        db_column_name="backup_callee",
        column_class_name="Boolean",
        column_class=Boolean,
        params={
            "default": False,
            "null": False,
            "primary_key": False,
            "unique": False,
            "index": False,
            "index_method": IndexMethod.btree,
            "choices": None,
            "db_column_name": None,
            "secret": False,
        },
        schema=None,
    )

    return manager
