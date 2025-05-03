import logging

from piccolo.conf.apps import AppConfig, AppRegistry, table_finder
from piccolo.engine.postgres import PostgresEngine

import py_phone_caller_utils.caller_configuration as conf

logging.basicConfig(format=conf.get_log_formatter())

try:
    DB = PostgresEngine(config={"dsn": conf.get_db_dsn()})
except OSError as err:
    logging.exception(f"Unable to connect with the DB -> '{err}'")

# A list of paths to piccolo apps
APP_REGISTRY = AppRegistry(
    apps=[
        "py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.piccolo_app"
    ]
)

# AppConfig
APP_CONFIG = AppConfig(
    table_classes=table_finder(
        ["py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables"],
        exclude_imported=True,
    ),
    app_name="py_phone_caller",
    migrations_folder_path="piccolo_migrations",
)
