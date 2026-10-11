"""
asterisk_recaller package.

Provides automated retry dialing and escalation services for unacknowledged calls.
"""

from asterisk_recaller.client import AsteriskCallClient
from asterisk_recaller.exceptions import (
    AsteriskRecallerError,
    NoOnCallContactsError,
    RecallerConnectionError,
)
from asterisk_recaller.schemas import (
    BackupCallItem,
    OnCallContact,
    RecallCycleResult,
    RecallItem,
)
from asterisk_recaller.services import RecallerService
from asterisk_recaller.asterisk_recaller import (
    asterisk_recaller,
    recall_post,
    run_single_recall_cycle,
)

__all__ = [
    "AsteriskCallClient",
    "AsteriskRecallerError",
    "BackupCallItem",
    "NoOnCallContactsError",
    "OnCallContact",
    "RecallCycleResult",
    "RecallItem",
    "RecallerConnectionError",
    "RecallerService",
    "asterisk_recaller",
    "recall_post",
    "run_single_recall_cycle",
]
