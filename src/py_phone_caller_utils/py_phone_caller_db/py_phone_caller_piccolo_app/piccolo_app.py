"""
Import all the Tables subclasses in your app here and register them with
the APP_CONFIG.
"""

import os

from piccolo.conf.apps import AppConfig

from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
    AsteriskWsEvents, Calls, ScheduledCalls, Users)

CURRENT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))


APP_CONFIG = AppConfig(
    app_name="py_phone_caller_piccolo_app",
    migrations_folder_path=os.path.join(CURRENT_DIRECTORY, "piccolo_migrations"),
    table_classes=[Calls, ScheduledCalls, AsteriskWsEvents, Users],
    migration_dependencies=[],
    commands=[],
)
