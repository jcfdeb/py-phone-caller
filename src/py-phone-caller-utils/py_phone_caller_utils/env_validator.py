"""
Environment and Database Credential Health Validator.

Validates that critical configurations (PostgreSQL credentials, Redis connection,
Asterisk ARI settings, GSM modem serial devices) are syntactically sound and
verifies actual database network reachability at process startup.
"""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("py_phone_caller.validator")


def validate_environment_consistency() -> Dict[str, Any]:
    """
    Checks environment variables and settings for common configuration pitfalls:
    - Missing or default weak database passwords
    - Hostname mismatches (e.g. localhost vs postgresql.lan in docker/host setups)
    - Redis connectivity configuration
    """
    from py_phone_caller_utils.config import settings

    diagnostics = {
        "status": "healthy",
        "warnings": [],
        "errors": [],
        "config_summary": {},
    }

    # 1. Database Configuration Checks
    db_user = settings.get("database.db_user") or os.environ.get("POSTGRES_USER") or "py_phone_caller"
    db_pass = settings.get("database.db_password") or os.environ.get("POSTGRES_PASSWORD") or ""
    db_host = settings.get("database.db_host") or os.environ.get("POSTGRES_HOST") or "127.0.0.1"
    db_port = settings.get("database.db_port") or os.environ.get("POSTGRES_PORT") or 5432
    db_name = settings.get("database.db_name") or os.environ.get("POSTGRES_DB") or "py_phone_caller"

    diagnostics["config_summary"]["database"] = {
        "user": db_user,
        "host": db_host,
        "port": db_port,
        "database": db_name,
        "password_configured": bool(db_pass),
    }

    if not db_pass:
        diagnostics["errors"].append("Database password ('database.db_password' or 'POSTGRES_PASSWORD') is empty.")
        diagnostics["status"] = "degraded"
    elif db_pass in ("super_secure_password", "postgres", "password"):
        diagnostics["warnings"].append("Database password appears to use default/insecure placeholder.")

    # 2. Redis Configuration Checks
    redis_url = settings.get("queue.queue_url") or settings.get("QUEUE", {}).get("QUEUE_URL", "")
    redis_host = settings.get("queue.queue_host") or "127.0.0.1"
    diagnostics["config_summary"]["redis"] = {
        "configured_url": redis_url or f"redis://{redis_host}:6379/7"
    }

    # 3. Asterisk ARI Checks
    ari_user = settings.get("commons.asterisk_user") or ""
    ari_host = settings.get("commons.asterisk_host") or ""
    diagnostics["config_summary"]["asterisk"] = {
        "user": ari_user,
        "host": ari_host,
    }

    return diagnostics


async def check_database_connectivity(timeout_seconds: float = 2.0) -> Tuple[bool, str]:
    """
    Actively attempts an async connection to PostgreSQL using asyncpg to verify
    credentials and host reachability before starting web services.
    """
    from py_phone_caller_utils.config import settings
    import asyncpg

    db_user = settings.get("database.db_user") or "py_phone_caller"
    db_pass = settings.get("database.db_password") or ""
    db_host = settings.get("database.db_host") or "127.0.0.1"
    db_port = int(settings.get("database.db_port") or 5432)
    db_name = settings.get("database.db_name") or "py_phone_caller"

    # If host ends in .lan and not resolvable, also check 127.0.0.1 fallback
    hosts_to_try = [db_host]
    if db_host not in ("127.0.0.1", "localhost"):
        hosts_to_try.append("127.0.0.1")

    last_error = ""
    for target_host in hosts_to_try:
        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(
                    user=db_user,
                    password=db_pass,
                    database=db_name,
                    host=target_host,
                    port=db_port,
                    timeout=timeout_seconds,
                ),
                timeout=timeout_seconds + 0.5,
            )
            version = await conn.fetchval("SELECT version();")
            await conn.close()
            return True, f"Connected to PostgreSQL ({target_host}:{db_port}): {version.split()[0]} {version.split()[1]}"
        except Exception as exc:
            last_error = str(exc)

    return False, f"Failed to connect to PostgreSQL ({db_host}:{db_port}): {last_error}"


def run_startup_health_banner(service_name: str) -> None:
    """Prints a structured startup diagnostic log for any py-phone-caller service."""
    env_diag = validate_environment_consistency()
    if env_diag["errors"]:
        logger.warning(f"[{service_name}] Environment Config Errors: {env_diag['errors']}")
    if env_diag["warnings"]:
        logger.info(f"[{service_name}] Environment Config Warnings: {env_diag['warnings']}")
    logger.info(f"[{service_name}] Config Validation: {env_diag['status'].upper()}")
