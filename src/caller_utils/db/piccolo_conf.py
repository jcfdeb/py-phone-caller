import logging

from piccolo.engine.postgres import PostgresEngine

import caller_utils.caller_configuration as conf

logging.basicConfig(format=conf.get_log_formatter())

try:
    DB = PostgresEngine(config={"dsn": conf.get_db_dsn()})
except OSError as err:
    logging.exception(f"Unable to connect with the DB -> '{err}'")
