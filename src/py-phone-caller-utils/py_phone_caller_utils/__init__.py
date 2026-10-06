"""
Shared utilities, database bindings, web tooling, and configuration for py-phone-caller.
"""

from __future__ import annotations

from py_phone_caller_utils.config import settings, CONFIG_DIR
from py_phone_caller_utils.redis_lock import call_mutex, get_redis_client
from py_phone_caller_utils.event_bus import (
    TELEPHONY_STREAM_CHANNEL,
    publish_event,
    subscribe_events,
)
from py_phone_caller_utils.env_validator import (
    validate_environment_consistency,
    check_database_connectivity,
    run_startup_health_banner,
)

__all__ = [
    "CONFIG_DIR",
    "TELEPHONY_STREAM_CHANNEL",
    "call_mutex",
    "check_database_connectivity",
    "get_redis_client",
    "publish_event",
    "run_startup_health_banner",
    "settings",
    "subscribe_events",
    "validate_environment_consistency",
]
