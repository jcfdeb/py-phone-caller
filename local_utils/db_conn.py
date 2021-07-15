import aiologger
import asyncpg
from aiologger.formatters.base import Formatter
from aiologger.levels import LogLevel

import local_utils.caller_configuration as conf

LOG_FORMATTER = conf.get_log_formatter()


LOGGER = aiologger.Logger.with_default_handlers(
    name="db_utils",
    level=LogLevel.INFO,
    formatter=Formatter(fmt=LOG_FORMATTER),
)


async def start_pool(
    db_host,
    db_name,
    db_user,
    db_password,
    db_max_size,
    db_max_inactive_connection_lifetime,
):
    """To start the Connection Pool"""
    try:
        pool = await asyncpg.create_pool(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_password,
            max_size=db_max_size,
            max_inactive_connection_lifetime=db_max_inactive_connection_lifetime,
        )
    except asyncpg.exceptions.ConnectionDoesNotExistError as e:
        await LOGGER.fatal(f"Error during database connection: '{e}'")
        exit(1)
    return pool


async def pool_init(
    db_host,
    db_name,
    db_user,
    db_password,
    db_max_size,
    db_max_inactive_connection_lifetime,
):
    """DB pool initialisation"""
    try:
        pool = await start_pool(
            db_host,
            db_name,
            db_user,
            db_password,
            db_max_size,
            db_max_inactive_connection_lifetime,
        )
    except KeyError:
        LOGGER.error(f"No PostgreSQL Connection 'pool' available.")
    return pool
