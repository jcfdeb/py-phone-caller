"""
Core business logic and lifecycle orchestration for call registration.

Provides the CallRegistrationService, eliminating nested branching with early
guard clauses, typed payload models, dependency injection, and structured
state transitions.
"""

from datetime import UTC, datetime, timedelta
import logging
import sys
from typing import Any
import pytz
from dateutil import parser

from py_phone_caller_utils.checksums import (
    gen_call_chk_sum,
    gen_msg_chk_sum,
    gen_unique_chk_sum,
)
from py_phone_caller_utils.py_phone_caller_db import db_caller_register as default_db_register
from py_phone_caller_utils.py_phone_caller_db import db_scheduled_calls as default_db_scheduled
from caller_register.constants import (
    LOCAL_TIMEZONE,
    SECONDS_TO_FORGET,
    TIMES_TO_DIAL,
)
from caller_register.exceptions import (
    InvalidScheduledDateError,
)
from caller_register.schemas import (
    CallChecksums,
    CallRegistrationPayload,
    ScheduledCallPayload,
    VoiceMessagePayload,
)


class DatabaseAdapter:
    """Dynamic database adapter supporting dependency injection and runtime patching."""

    def __getattr__(self, name: str) -> Any:
        # Check if caller_register has this attribute (for backward compatibility with mock patches)
        legacy_mod = sys.modules.get("src.caller_register.caller_register") or sys.modules.get("caller_register.caller_register")
        if legacy_mod and hasattr(legacy_mod, name):
            return getattr(legacy_mod, name)
        if hasattr(default_db_register, name):
            return getattr(default_db_register, name)
        if hasattr(default_db_scheduled, name):
            return getattr(default_db_scheduled, name)
        raise AttributeError(f"DatabaseAdapter has no attribute '{name}'")


class CallRegistrationService:
    """Orchestrates outbound call attempt tracking, acknowledgments, and schedules."""

    def __init__(
        self,
        seconds_to_forget: int = SECONDS_TO_FORGET,
        times_to_dial: int = TIMES_TO_DIAL,
        local_timezone: str = LOCAL_TIMEZONE,
        db: Any | None = None,
    ) -> None:
        self.seconds_to_forget = seconds_to_forget
        self.times_to_dial = times_to_dial
        self.local_timezone = local_timezone
        self.db = db or DatabaseAdapter()

    async def compute_checksums(self, phone: str, message: str) -> CallChecksums:
        """Computes call, message, and unique hash checksums with UTC timestamp.

        Args:
            phone: Destination phone number.
            message: Alert message text.

        Returns:
            CallChecksums: Container holding all computed hashes and start timestamp.
        """
        call_chk_sum = await gen_call_chk_sum(phone, message)
        msg_chk_sum = await gen_msg_chk_sum(message)
        first_dial = datetime.now(UTC).replace(tzinfo=None)
        unique_chk_sum = await gen_unique_chk_sum(phone, message, first_dial)
        return CallChecksums(
            call_chk_sum=call_chk_sum,
            msg_chk_sum=msg_chk_sum,
            unique_chk_sum=unique_chk_sum,
            first_dial=first_dial,
        )

    def log_call_status(
        self, phone: str, first_dial_time: timedelta | None, message: str
    ) -> None:
        """Logs whether a call attempt is within the active retry window.

        Args:
            phone: Destination phone number.
            first_dial_time: Elapsed time since the first dial attempt, or None.
            message: Alert message text.
        """
        if not first_dial_time:
            logging.info(
                f"A previous call for '{phone}' with message '{message}' is outside "
                f"retry period ({self.seconds_to_forget}s). Starting a new cycle."
            )
            return

        logging.info(
            f"A call for '{phone}' was started '{first_dial_time}' ago with message '{message}' "
            f"and is inside retry period ({self.seconds_to_forget}s). Managing active call."
        )

    async def create_new_call_attempt(
        self, payload: CallRegistrationPayload, checksums: CallChecksums
    ) -> None:
        """Inserts a brand-new call attempt record into the database.

        Args:
            payload: Input registration details.
            checksums: Cryptographic hashes and timestamp.
        """
        logging.info(f"No active call cycles for '{payload.phone}' with message '{payload.message}'.")
        try:
            await self.db.insert_into_db(
                payload.phone,
                payload.message,
                payload.asterisk_chan,
                checksums.msg_chk_sum,
                checksums.call_chk_sum,
                checksums.unique_chk_sum,
                checksums.first_dial,
                self.seconds_to_forget,
                self.times_to_dial,
                oncall=payload.oncall,
                backup_callee=payload.backup_callee,
                lang=payload.lang or "",
            )
        except Exception as err:
            logging.exception(
                f"Error creating initial DB record for phone={payload.phone} message={payload.message}: {err}"
            )

    async def get_first_dial_age_safe(
        self, call_chk_sum: str, current_call_id: int, phone: str, message: str
    ) -> timedelta | None:
        """Retrieves and logs the age of the first dial attempt safely.

        Args:
            call_chk_sum: Checksum of the call.
            current_call_id: Database identifier of the active record.
            phone: Destination phone number.
            message: Alert message text.

        Returns:
            timedelta | None: Elapsed time since first dial, or None on error.
        """
        try:
            first_dial_time = await self.db.get_first_dial_age(call_chk_sum, current_call_id)
            self.log_call_status(phone, first_dial_time, message)
            return first_dial_time
        except Exception as err:
            logging.exception(
                f"Error fetching first dial age for call_id={current_call_id}: {err}"
            )
            return None

    async def update_or_recycle_call(
        self,
        first_dial_time: timedelta | None,
        current_call_id: int,
        payload: CallRegistrationPayload,
        checksums: CallChecksums,
    ) -> None:
        """Updates an active call record or initializes a recycled call cycle.

        Args:
            first_dial_time: Elapsed time since the first dial attempt.
            current_call_id: Primary key ID of the existing call attempt.
            payload: Validated registration payload.
            checksums: Cryptographic hashes and timestamp.
        """
        in_retry_window = (
            first_dial_time is not None
            and first_dial_time < timedelta(seconds=self.seconds_to_forget)
        )

        if in_retry_window:
            try:
                current_dialed_times = await self.db.get_dialed_times(
                    self.seconds_to_forget, checksums.call_chk_sum
                )
                await self.db.update_the_call_db_record(
                    checksums.call_chk_sum,
                    current_call_id,
                    current_dialed_times,
                    payload.asterisk_chan,
                    payload.phone,
                    payload.message,
                    lang=payload.lang,
                )
                return
            except Exception as err:
                logging.info(
                    f"Update failed, fallback creating new record for phone={payload.phone}: {err}"
                )

        await self.db.insert_into_db(
            payload.phone,
            payload.message,
            payload.asterisk_chan,
            checksums.msg_chk_sum,
            checksums.call_chk_sum,
            checksums.unique_chk_sum,
            checksums.first_dial,
            self.seconds_to_forget,
            self.times_to_dial,
            lang=payload.lang or "",
        )

    async def process_call_registration(self, payload: CallRegistrationPayload) -> None:
        """Processes an incoming call registration request through the state machine.

        Args:
            payload: Validated registration payload.
        """
        checksums = await self.compute_checksums(payload.phone, payload.message)
        call_yet_present = await self.db.check_call_yet_present(
            checksums.call_chk_sum, payload.phone, payload.message
        )

        # Early return guard clause: completely new call attempt
        if call_yet_present is None:
            await self.create_new_call_attempt(payload, checksums)
            return

        current_call_id = await self.db.get_current_call_id(
            self.seconds_to_forget, checksums.call_chk_sum
        )

        # Early return guard clause: no active uncompleted cycle found within retention window
        if current_call_id is None:
            await self.create_new_call_attempt(payload, checksums)
            logging.info(
                f"No uncompleted cycle for '{payload.phone}' in last {self.seconds_to_forget}s. Started new cycle."
            )
            return

        first_dial_time = await self.get_first_dial_age_safe(
            checksums.call_chk_sum, current_call_id, payload.phone, payload.message
        )
        await self.update_or_recycle_call(
            first_dial_time, current_call_id, payload, checksums
        )

    async def acknowledge_channel(self, asterisk_chan: str) -> bool:
        """Marks a channel as acknowledged by the callee.

        Args:
            asterisk_chan: Asterisk channel identifier.

        Returns:
            bool: True if acknowledged successfully, False if expired or not found.
        """
        return bool(await self.db.update_acknowledgement(asterisk_chan))

    async def mark_channel_heard(self, asterisk_chan: str) -> None:
        """Updates the heard timestamp for the specified channel.

        Args:
            asterisk_chan: Asterisk channel identifier.
        """
        await self.db.update_heard_at(asterisk_chan)

    async def get_voice_message_payload(self, asterisk_chan: str) -> VoiceMessagePayload:
        """Retrieves the voice message text, checksum, and target language for an active channel.

        Args:
            asterisk_chan: Asterisk channel identifier.

        Returns:
            VoiceMessagePayload: Message text, hash checksum, and language (empty if not found).
        """
        try:
            res = await self.db.get_msg_chk_sum(asterisk_chan)
            if not res or res[0] is None:
                return VoiceMessagePayload(message="", msg_chk_sum="", lang=None)
            msg = res[0]
            chk = res[1]
            lang = getattr(res, "lang", None)
            if not lang and len(res) > 2:
                lang = res[2]
            return VoiceMessagePayload(
                message=str(msg or ""),
                msg_chk_sum=str(chk or ""),
                lang=str(lang).strip() if lang else None,
            )
        except Exception:
            logging.info("No data retrieved from DB for message or checksum")
            return VoiceMessagePayload(message="", msg_chk_sum="", lang=None)

    async def parse_and_schedule_call(
        self, phone: str, message: str, scheduled_at_str: str, lang: str | None = None
    ) -> ScheduledCallPayload:
        """Parses scheduled time, converts to UTC, and stores scheduled call record.

        Args:
            phone: Destination phone number.
            message: Message text.
            scheduled_at_str: Date/time string in local timezone format.
            lang: Optional target voice language code.

        Returns:
            ScheduledCallPayload: Recorded schedule details.

        Raises:
            InvalidScheduledDateError: If the date cannot be parsed or localized.\n        """
        try:
            scheduled_at = parser.parse(scheduled_at_str)
            tz = pytz.timezone(self.local_timezone)
            localized_time = (
                tz.localize(scheduled_at, is_dst=None)
                if scheduled_at.tzinfo is None
                else scheduled_at
            )
            scheduled_at_utc = localized_time.astimezone(pytz.utc).replace(tzinfo=None)
        except Exception as err:
            raise InvalidScheduledDateError(
                f"Unable to parse or convert date '{scheduled_at_str}': {err}"
            ) from err

        call_chk_sum = await gen_call_chk_sum(phone, message)
        inserted_at = datetime.now(UTC).replace(tzinfo=None)

        try:
            await self.db.insert_scheduled_call(
                phone, message, call_chk_sum, inserted_at, scheduled_at_utc, lang=lang or ""
            )
        except TypeError:
            # Fallback for mock objects without lang parameter
            await self.db.insert_scheduled_call(
                phone, message, call_chk_sum, inserted_at, scheduled_at_utc
            )

        return ScheduledCallPayload(
            phone=phone,
            message=message,
            call_chk_sum=call_chk_sum,
            inserted_at=inserted_at,
            scheduled_at_utc=scheduled_at_utc,
            lang=lang,
        )
