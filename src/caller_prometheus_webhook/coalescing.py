"""
Alert Storm Coalescing and Incident Batching Engine for caller_prometheus_webhook.

Provides intelligent aggregation of cascading Prometheus alerts during major
infrastructure incidents to prevent telephony trunk saturation and responder alert fatigue.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Sequence

from py_phone_caller_utils.config import settings
from caller_prometheus_webhook.schemas import PrometheusAlert

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class CoalescedIncident:
    """
    Consolidated incident representation representing one or more alerts.

    Attributes:
        alert_count: Total number of firing alerts aggregated.
        summary_message: Concise voice message for Text-to-Speech synthesis.
        detailed_sms: Extended text message suitable for SMS delivery.
        sample_descriptions: First few sample alert descriptions.
    """

    alert_count: int
    summary_message: str
    detailed_sms: str
    sample_descriptions: tuple[str, ...] = field(default_factory=tuple)


class AlertCoalescer:
    """
    Coalesces multiple raw alert descriptions or PrometheusAlert items into
    a synthesized, voice-friendly summary message.
    """

    def __init__(self, max_samples_in_tts: int = 3) -> None:
        self.max_samples_in_tts = max_samples_in_tts

    def coalesce_descriptions(self, descriptions: Sequence[str]) -> CoalescedIncident:
        """
        Synthesizes a list of alert descriptions into a unified CoalescedIncident.

        Handles edge cases for empty lists and single-alert payloads, and aggregates
        multiple alerts during incident storms by generating prioritized speech summaries
        and structured multi-line SMS notifications.

        Args:
            descriptions: Sequence of string alert descriptions.

        Returns:
            CoalescedIncident with TTS prompt and SMS body.
        """
        cleaned = [d.strip() for d in descriptions if d and d.strip()]
        count = len(cleaned)

        if count == 0:
            return CoalescedIncident(
                alert_count=0,
                summary_message="No active alert data.",
                detailed_sms="No active alert data.",
            )

        if count == 1:
            desc = cleaned[0]
            return CoalescedIncident(
                alert_count=1,
                summary_message=desc,
                detailed_sms=desc,
                sample_descriptions=(desc,),
            )

        samples = tuple(cleaned[: self.max_samples_in_tts])
        sample_text = ". ".join(samples)
        remainder = count - len(samples)

        if remainder > 0:
            tts_prompt = (
                f"Alert Storm: {count} firing alerts detected. "
                f"Top alerts: {sample_text}. And {remainder} additional alerts."
            )
        else:
            tts_prompt = f"Alert Storm: {count} firing alerts detected: {sample_text}."

        sms_body = (
            f"[ALERT STORM - {count} ALERTS]\n"
            + "\n".join(f"- {d}" for d in cleaned[:5])
        )
        if count > 5:
            sms_body += f"\n...and {count - 5} more."

        return CoalescedIncident(
            alert_count=count,
            summary_message=tts_prompt,
            detailed_sms=sms_body,
            sample_descriptions=samples,
        )

    def coalesce_alerts(self, alerts: Sequence[PrometheusAlert]) -> CoalescedIncident:
        """Synthesizes a list of PrometheusAlert objects."""
        firing_descs = [a.description for a in alerts if a.is_firing]
        return self.coalesce_descriptions(firing_descs)


class CoalescingBuffer:
    """
    Sliding window buffer for collecting incoming alerts across multiple HTTP
    webhook requests before dispatching a single consolidated incident.
    """

    def __init__(
        self,
        flush_callback: Callable[[CoalescedIncident, Sequence[str], str], Coroutine[Any, Any, None]],
        window_seconds: float = 10.0,
        max_batch_size: int = 50,
    ) -> None:
        self.flush_callback = flush_callback
        self.window_seconds = window_seconds
        self.max_batch_size = max_batch_size
        self._buffered_messages: list[str] = []
        self._receivers: set[str] = set()
        self._action_mode: str = "call_only"
        self._timer_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.coalescer = AlertCoalescer()

    @property
    def is_active(self) -> bool:
        """Returns True if a batch is currently accumulating."""
        return len(self._buffered_messages) > 0

    async def add_alerts(
        self,
        messages: Sequence[str],
        receivers: Sequence[str],
        action_mode: str,
    ) -> None:
        """Adds alerts to the buffer, starting or resetting the window."""
        async with self._lock:
            self._buffered_messages.extend(messages)
            self._receivers.update(receivers)
            self._action_mode = action_mode

            if len(self._buffered_messages) >= self.max_batch_size:
                logger.info(f"Coalescing buffer reached max batch size ({self.max_batch_size}). Flushing immediately.")
                await self._flush_unlocked()
                return

            if self._timer_task is None or self._timer_task.done():
                self._timer_task = asyncio.create_task(self._wait_and_flush())

    async def _wait_and_flush(self) -> None:
        await asyncio.sleep(self.window_seconds)
        async with self._lock:
            await self._flush_unlocked()

    async def _flush_unlocked(self) -> None:
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = None

        if not self._buffered_messages:
            return

        messages_to_flush = list(self._buffered_messages)
        receivers_to_flush = list(self._receivers)
        mode = self._action_mode

        self._buffered_messages.clear()
        self._receivers.clear()

        incident = self.coalescer.coalesce_descriptions(messages_to_flush)
        logger.info(
            f"Flushed coalesced incident: {incident.alert_count} alerts "
            f"to {len(receivers_to_flush)} receivers via mode '{mode}'"
        )
        try:
            await self.flush_callback(incident, receivers_to_flush, mode)
        except Exception as err:
            logger.error(f"Error in coalescing buffer flush callback: {err}", exc_info=True)
