"""
Core business logic and orchestration services for the asterisk_recaller service.

Encapsulates recall cycle evaluation, primary retry dispatching, and escalation
to backup on-call contacts using linear workflows and early guard clauses.
"""

from __future__ import annotations
import asyncio
import datetime
import logging
from typing import Any, Awaitable, Callable, Sequence

from asterisk_recaller.client import AsteriskCallClient
from asterisk_recaller.schemas import BackupCallItem, OnCallContact, RecallItem


class RecallerService:
    """
    Orchestration service for managing call retries and backup escalations.

    Attributes:
        call_client_fn: Async callable or client to dispatch outbound calls.
        select_to_recall_fn: Async callable to fetch candidate calls for retry.
        select_backup_calls_fn: Async callable to fetch unacknowledged calls needing backup.
        get_on_call_contacts_fn: Async callable to retrieve list of on-call personnel.
        increment_backup_call_count_fn: Async callable to increment backup counter on DB.
        times_to_dial: Maximum retry attempts for primary calls.
        seconds_to_forget: Window before calls are deemed expired.
        sleep_and_retry: Pause duration between successive dial actions.
        call_backup_callee_max_times: Maximum allowed backup escalation attempts.
    """

    def __init__(
        self,
        call_client_fn: Callable[..., Awaitable[Any]],
        select_to_recall_fn: Callable[..., Awaitable[Sequence[dict[str, Any]] | None]],
        select_backup_calls_fn: Callable[..., Awaitable[Sequence[dict[str, Any]] | None]],
        get_on_call_contacts_fn: Callable[..., Awaitable[Sequence[dict[str, Any]] | None]],
        increment_backup_call_count_fn: Callable[[Any], Awaitable[Any]],
        times_to_dial: int = 3,
        seconds_to_forget: float = 300.0,
        sleep_and_retry: float = 60.0,
        call_backup_callee_max_times: int = 3,
    ) -> None:
        """
        Initializes the RecallerService with required dependencies and policies.

        Args:
            call_client_fn: Function or client place-call dispatcher.
            select_to_recall_fn: Hook to query retry candidates.
            select_backup_calls_fn: Hook to query backup escalation candidates.
            get_on_call_contacts_fn: Hook to query on-call staff directory.
            increment_backup_call_count_fn: Hook to record dispatched backup attempt.
            times_to_dial: Maximum number of dialing attempts.
            seconds_to_forget: Duration in seconds before giving up on a call.
            sleep_and_retry: Sleep interval between retry calls.
            call_backup_callee_max_times: Threshold for backup escalation.
        """
        self.call_client_fn = call_client_fn
        self.select_to_recall_fn = select_to_recall_fn
        self.select_backup_calls_fn = select_backup_calls_fn
        self.get_on_call_contacts_fn = get_on_call_contacts_fn
        self.increment_backup_call_count_fn = increment_backup_call_count_fn
        self.times_to_dial = times_to_dial
        self.seconds_to_forget = seconds_to_forget
        self.sleep_and_retry = sleep_and_retry
        self.call_backup_callee_max_times = call_backup_callee_max_times

    async def process_primary_recalls(
        self, now_utc: datetime.datetime | None = None
    ) -> int:
        """
        Scans for and executes retries for unacknowledged primary calls.

        Uses guard clauses to exit early if no eligible records exist.

        Args:
            now_utc: Optional evaluation timestamp (defaults to current UTC time).

        Returns:
            Count of primary recall actions dispatched.
        """
        current_time = now_utc or datetime.datetime.now(datetime.timezone.utc)
        lesser_seconds_to_forget = current_time - datetime.timedelta(
            seconds=self.seconds_to_forget
        )
        greater_sleep_and_retry = current_time - datetime.timedelta(
            seconds=self.sleep_and_retry
        )

        records = await self.select_to_recall_fn(
            self.times_to_dial,
            lesser_seconds_to_forget.replace(tzinfo=None),
            greater_sleep_and_retry.replace(tzinfo=None),
        )

        # Early return guard clause
        if not records:
            return 0

        action_count = 0
        for raw_item in records:
            item = RecallItem.from_dict(raw_item)
            logging.info(
                f"Retry to call phone number: '{item.phone}' to play the message: "
                f"'{item.message}' - Total retry period: '{item.seconds_to_forget}' seconds"
            )

            await self.call_client_fn(item.phone, item.message)
            action_count += 1
            await asyncio.sleep(self.sleep_and_retry)

        return action_count

    async def process_backup_calls(self) -> int:
        """
        Scans for and initiates backup escalation calls to on-call contacts.

        Uses early returns when no backup candidates or active on-call contacts exist.

        Returns:
            Count of backup calls dispatched.
        """
        backup_calls = await self.select_backup_calls_fn(
            self.call_backup_callee_max_times
        )

        # Early return guard clause
        if not backup_calls:
            return 0

        on_call_contacts = await self.get_on_call_contacts_fn()

        # Guard clause: verify active on-call staff
        if not on_call_contacts:
            logging.warning("No on-call contacts found for backup calls.")
            return 0

        action_count = 0
        num_contacts = len(on_call_contacts)

        for raw_call in backup_calls:
            call = BackupCallItem.from_dict(raw_call)
            backup_idx = (call.backup_count + 1) % num_contacts
            contact_data = on_call_contacts[backup_idx]
            contact = OnCallContact.from_dict(contact_data)
            backup_phone = contact.phone_number

            logging.info(
                f"Call not acknowledged for '{call.phone}'. "
                f"Backup attempt {call.backup_count + 1}. "
                f"Initiating backup call to '{backup_phone}'."
            )

            await self.call_client_fn(
                backup_phone,
                call.message,
                backup_callee="true",
            )
            await self.increment_backup_call_count_fn(call.call_id)
            action_count += 1
            await asyncio.sleep(self.sleep_and_retry)

        return action_count

    async def run_single_cycle(
        self, now_utc: datetime.datetime | None = None
    ) -> int:
        """
        Executes a single end-to-end recall evaluation cycle.

        Args:
            now_utc: Optional evaluation timestamp override.

        Returns:
            Total combined count of primary and backup recall actions executed.
        """
        primary_actions = await self.process_primary_recalls(now_utc=now_utc)
        backup_actions = await self.process_backup_calls()
        return primary_actions + backup_actions
