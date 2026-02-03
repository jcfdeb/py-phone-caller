import logging

from piccolo.conf.apps import AppConfig, AppRegistry, table_finder
from piccolo.engine.postgres import PostgresEngine
from py_phone_caller_utils.config import settings


DB_USER = settings.database.db_user
DB_PASSWORD = settings.database.db_password
DB_HOST = settings.database.db_host
DB_PORT = settings.database.db_port
DB_NAME = settings.database.db_name
DB_DSN = f"postgres://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

logging.basicConfig(
    format=settings.logs.log_formatter, level=settings.logs.log_level, force=True
)

# The PostgresEngine will try to connect to the database to check the version
# during initialization. If the database is not ready yet, it will fail.
# We let it fail so the service can be restarted by the orchestrator (e.g. Docker/Podman)
# and eventually succeed when the database is ready.
DB = PostgresEngine(config={"dsn": DB_DSN})

APP_REGISTRY = AppRegistry(
    apps=[
        "py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.piccolo_app"
    ]
)

APP_CONFIG = AppConfig(
    table_classes=table_finder(
        ["py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables"],
        exclude_imported=True,
    ),
    app_name="py_phone_caller_piccolo_app",
    migrations_folder_path="piccolo_migrations",
)
