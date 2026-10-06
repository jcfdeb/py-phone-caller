"""
caller_register package.

Provides call registration, lifecycle management, and DTMF acknowledgment
tracking for py-phone-caller.
"""

from caller_register.exceptions import (
    CallNotFoundError,
    CallerRegisterError,
    DatabaseConnectionError,
    InvalidScheduledDateError,
    MissingParameterError,
    SchemaMigrationError,
)
from caller_register.migrations import (
    init_database,
    run_piccolo_migrations,
)
from caller_register.schemas import (
    CallChecksums,
    CallRegistrationPayload,
    ScheduledCallPayload,
    VoiceMessagePayload,
)
from caller_register.services import CallRegistrationService

__all__ = [
    "CallChecksums",
    "CallNotFoundError",
    "CallRegistrationPayload",
    "CallRegistrationService",
    "CallerRegisterError",
    "DatabaseConnectionError",
    "InvalidScheduledDateError",
    "MissingParameterError",
    "ScheduledCallPayload",
    "SchemaMigrationError",
    "VoiceMessagePayload",
    "init_database",
    "run_piccolo_migrations",
]
