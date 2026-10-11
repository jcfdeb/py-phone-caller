"""
Caller Register service orchestrator and application entry point.

Provides backward-compatible facades, application bootstrapping, and the
CLI runner, delegating core concerns to migrations, services, and routes.
"""

import asyncio
import logging
import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.dirname(current_dir)

if current_dir in sys.path:
    sys.path.remove(current_dir)

if src_dir not in sys.path:
    sys.path.append(src_dir)

from datetime import UTC, datetime, timedelta
from aiohttp import web

# Re-exported for external tests and mock patches
from py_phone_caller_utils.checksums import (  # noqa: F401
    gen_call_chk_sum,
    gen_msg_chk_sum,
    gen_unique_chk_sum,
)
from py_phone_caller_utils.py_phone_caller_db.db_caller_register import (  # noqa: F401
    check_call_yet_present,
    get_current_call_id,
    get_dialed_times,
    get_first_dial_age,
    get_msg_chk_sum,
    insert_into_db,
    update_acknowledgement,
    update_heard_at,
    update_the_call_db_record,
)
from py_phone_caller_utils.py_phone_caller_db.db_scheduled_calls import (  # noqa: F401
    insert_scheduled_call,
)
from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB  # noqa: F401
from py_phone_caller_utils.telemetry import init_telemetry, instrument_aiohttp_app
from py_phone_caller_utils.web.readiness import check_database_pool  # noqa: F401

from caller_register.constants import (
    CALL_REGISTER_PORT,
    LOG_FORMATTER,
    LOG_LEVEL,
    SECONDS_TO_FORGET,
    TIMES_TO_DIAL,
)
from caller_register.migrations import (
    ensure_database_connection as _ensure_database_connection,  # noqa: F401
    execute_migrations as _execute_migrations,  # noqa: F401
    init_database,
    migration_record_exists as _migration_record_exists,  # noqa: F401
    record_migration_if_missing as _record_migration_if_missing,  # noqa: F401
    reconcile_existing_migration_history as _reconcile_existing_migration_history,  # noqa: F401
    repair_existing_schema as _repair_existing_schema,  # noqa: F401
    run_piccolo_migrations,
    table_exists as _table_exists,  # noqa: F401
    verify_tables as _verify_tables,  # noqa: F401
)
from caller_register.routes import (
    acknowledge,
    extract_registration_payload,
    heard,
    register_call,
    root_catalog,  # noqa: F401
    scheduled_call,
    setup_routes,
    voice_message,
)
from caller_register.schemas import (
    CallChecksums,
    CallRegistrationPayload,
)
from caller_register.services import CallRegistrationService

seconds_to_forget = SECONDS_TO_FORGET
times_to_dial = TIMES_TO_DIAL

logging.basicConfig(format=LOG_FORMATTER, level=LOG_LEVEL, force=True)
init_telemetry("caller_register")

# Shared service instance for legacy module-level helpers
_default_service = CallRegistrationService()


# ---------------------------------------------------------------------------
# Backward-compatible function facades
# ---------------------------------------------------------------------------

async def present_or_not_logger(
    phone: str, first_dial_time: timedelta | None, message: str
) -> None:
    """Logs whether a call is within the retry window."""
    _default_service.log_call_status(phone, first_dial_time, message)


async def get_request_parameters(
    request: web.Request,
) -> tuple[str, str, str, bool, bool]:
    """Extracts phone, message, asterisk_chan, oncall, and backup_callee parameters."""
    payload = await extract_registration_payload(request)
    return (
        payload.phone,
        payload.message,
        payload.asterisk_chan,
        payload.oncall,
        payload.backup_callee,
    )


async def new_call_attempt(
    phone: str,
    message: str,
    asterisk_chan: str,
    msg_chk_sum: str,
    call_chk_sum: str,
    unique_chk_sum: str,
    first_dial: datetime,
    oncall: bool = False,
    backup_callee: bool = False,
) -> None:
    """Inserts a new call attempt record into the database."""
    payload = CallRegistrationPayload(
        phone=phone,
        message=message,
        asterisk_chan=asterisk_chan,
        oncall=oncall,
        backup_callee=backup_callee,
    )
    checksums = CallChecksums(
        call_chk_sum=call_chk_sum,
        msg_chk_sum=msg_chk_sum,
        unique_chk_sum=unique_chk_sum,
        first_dial=first_dial,
    )
    await _default_service.create_new_call_attempt(payload, checksums)


async def defining_first_dial_time(
    call_chk_sum: str, current_call_id: int, phone: str, message: str
) -> timedelta | None:
    """Determines and logs the age of the first dial attempt for a given call."""
    return await _default_service.get_first_dial_age_safe(
        call_chk_sum, current_call_id, phone, message
    )


async def updating_the_call_db_record(
    first_dial_time: timedelta | None,
    call_chk_sum: str,
    current_call_id: int,
    current_dialed_times: int,
    asterisk_chan: str,
    phone: str,
    message: str,
    msg_chk_sum: str,
    unique_chk_sum: str,
    first_dial: datetime,
) -> None:
    """Updates call record or inserts a new cycle record if outside window."""
    payload = CallRegistrationPayload(
        phone=phone,
        message=message,
        asterisk_chan=asterisk_chan,
    )
    checksums = CallChecksums(
        call_chk_sum=call_chk_sum,
        msg_chk_sum=msg_chk_sum,
        unique_chk_sum=unique_chk_sum,
        first_dial=first_dial,
    )
    await _default_service.update_or_recycle_call(
        first_dial_time, current_call_id, payload, checksums
    )


async def init_app() -> web.Application:
    """Creates, instruments, and configures the aiohttp application."""
    app = web.Application()
    instrument_aiohttp_app(app, "caller_register")
    setup_routes(app, _default_service)
    return app


def main() -> None:
    """CLI and process entry point for caller_register."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(init_database())
    except Exception as db_err:
        logging.error(
            f"Database initial connection failed: {db_err}. "
            "Service starting in degraded mode; /ready will report 503 until DB recovers."
        )

    app = loop.run_until_complete(init_app())

    async def cleanup_db(_app: web.Application) -> None:
        if DB.pool is not None:
            await DB.pool.close()
            logging.info("Database connection pool closed")

    app.on_cleanup.append(cleanup_db)
    web.run_app(app, port=int(CALL_REGISTER_PORT), loop=loop)


if __name__ == "__main__":
    main()
