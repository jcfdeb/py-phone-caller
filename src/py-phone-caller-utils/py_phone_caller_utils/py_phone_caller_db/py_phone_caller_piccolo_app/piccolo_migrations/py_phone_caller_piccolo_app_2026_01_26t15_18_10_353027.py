from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import Boolean
from piccolo.columns.column_types import JSONB
from piccolo.columns.column_types import SmallInt
from piccolo.columns.indexes import IndexMethod


ID = "2026-01-26T15:18:10:353027"
VERSION = "1.28.0"
DESCRIPTION = ""


async def forwards():
    manager = MigrationManager(
        migration_id=ID,
        app_name="py_phone_caller_piccolo_app",
        description=DESCRIPTION,
    )

    manager.add_column(
        table_class_name="Calls",
        tablename="calls",
        column_name="call_backup_callee_number_calls",
        db_column_name="call_backup_callee_number_calls",
        column_class_name="SmallInt",
        column_class=SmallInt,
        params={
            "default": 0,
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

    manager.add_column(
        table_class_name="Calls",
        tablename="calls",
        column_name="oncall",
        db_column_name="oncall",
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

    manager.alter_column(
        table_class_name="AddressBook",
        tablename="address_book",
        column_name="on_call_availability",
        db_column_name="on_call_availability",
        params={"default": "{}"},
        old_params={"default": "[]"},
        column_class=JSONB,
        old_column_class=JSONB,
        schema=None,
    )

    return manager
