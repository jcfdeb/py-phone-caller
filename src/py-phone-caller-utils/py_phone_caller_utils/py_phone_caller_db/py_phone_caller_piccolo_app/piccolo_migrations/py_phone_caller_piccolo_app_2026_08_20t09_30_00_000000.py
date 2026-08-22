from piccolo.apps.migrations.auto.migration_manager import MigrationManager
from piccolo.columns.column_types import UUID, Timestamp, Varchar
from piccolo.columns.defaults.timestamp import TimestampNow
from piccolo.columns.defaults.uuid import UUID4
from piccolo.columns.indexes import IndexMethod

ID = "2026-08-20T09:30:00:000000"
VERSION = "1.28.0"
DESCRIPTION = "Add Sms table for tracking SMS messages"


async def forwards():
    manager = MigrationManager(
        migration_id=ID, app_name="py_phone_caller_piccolo_app", description=DESCRIPTION
    )

    manager.add_table(
        class_name="Sms", tablename="sms", schema=None, columns=None
    )

    manager.add_column(
        table_class_name="Sms",
        tablename="sms",
        column_name="id",
        db_column_name="id",
        column_class_name="UUID",
        column_class=UUID,
        params={
            "default": UUID4(),
            "null": False,
            "primary_key": True,
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
        table_class_name="Sms",
        tablename="sms",
        column_name="phone",
        db_column_name="phone",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 64,
            "default": "",
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
        table_class_name="Sms",
        tablename="sms",
        column_name="message",
        db_column_name="message",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 1024,
            "default": "",
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
        table_class_name="Sms",
        tablename="sms",
        column_name="carrier",
        db_column_name="carrier",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 64,
            "default": "",
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
        table_class_name="Sms",
        tablename="sms",
        column_name="status",
        db_column_name="status",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 64,
            "default": "",
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
        table_class_name="Sms",
        tablename="sms",
        column_name="created_at",
        db_column_name="created_at",
        column_class_name="Timestamp",
        column_class=Timestamp,
        params={
            "default": TimestampNow(),
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
        table_class_name="Sms",
        tablename="sms",
        column_name="error",
        db_column_name="error",
        column_class_name="Varchar",
        column_class=Varchar,
        params={
            "length": 1024,
            "default": "",
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
