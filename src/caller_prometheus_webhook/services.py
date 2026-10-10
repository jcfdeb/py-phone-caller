from __future__ import annotations
"""
Core business logic and services for the caller_prometheus_webhook service.

Encapsulates alert deduplication, asynchronous queue-based consumer/producer
dispatching, and strategy-based notification execution (call only, SMS only,
SMS before call, call and SMS).
"""

import asyncio
import hashlib
import logging
import time
from typing import Any, Awaitable, Callable, Sequence

from py_phone_caller_utils.config import settings

from caller_prometheus_webhook.clients import AsteriskCallClient, CallerSmsClient
from caller_prometheus_webhook.coalescing import AlertCoalescer
from caller_prometheus_webhook.schemas import (
    NotificationMode,
    PrometheusAlert,
    WebhookPayload,
)


class DeduplicationService:
    """
    Sliding-window alert deduplication service.

    Attempts Redis sliding-window check first if enabled; falls back to an in-memory cache.
    """

    def __init__(
        self,
        ttl_seconds: int = 180,
        cache_max_size: int = 500,
        use_redis: bool | None = None,
    ) -> None:
        """
        Initializes the DeduplicationService.

        Args:
            ttl_seconds: Sliding window duration in seconds.
            cache_max_size: Maximum entries in the local cache before pruning.
            use_redis: Whether to attempt Redis-backed deduplication. Defaults to False unless configured.
        """
        self.ttl_seconds = ttl_seconds
        self.cache_max_size = cache_max_size
        if use_redis is None:
            self.use_redis = bool(
                settings.get("caller_prometheus_webhook", {}).get("use_redis_dedup", False)
            )
        else:
            self.use_redis = use_redis
        self._local_cache: dict[str, float] = {}

    def clear(self) -> None:
        """Clears local in-memory cache."""
        self._local_cache.clear()

    async def is_duplicate(self, message: str, ttl_seconds: int | None = None) -> bool:
        """
        Checks whether an alert message has already been processed within the sliding window.

        Args:
            message: Alert description text.
            ttl_seconds: Optional window duration override.

        Returns:
            True if message is a duplicate, False otherwise.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        msg_hash = hashlib.sha256(message.strip().encode("utf-8")).hexdigest()[:16]

        if self.use_redis:
            try:
                import redis.asyncio as aioredis

                queue_cfg = settings.get("QUEUE", {})
                queue_url = queue_cfg.get("queue_url") or queue_cfg.get("QUEUE_URL", "redis://redis.lan:6379/7")
                r = aioredis.from_url(queue_url, socket_connect_timeout=1)
                key = f"alert:dedup:{msg_hash}"
                was_set = await r.set(key, "1", ex=ttl, nx=True)
                await r.aclose()
                if was_set is None:
                    return True
                return False
            except Exception as redis_err:
                logging.debug(f"Redis deduplication unreachable ({redis_err}), using in-memory window")

        now = time.time()
        last_seen = self._local_cache.get(msg_hash)
        if last_seen and (now - last_seen) < ttl:
            return True

        self._local_cache[msg_hash] = now
        if len(self._local_cache) > self.cache_max_size:
            cutoff = now - ttl
            for k in list(self._local_cache.keys()):
                if self._local_cache[k] < cutoff:
                    del self._local_cache[k]

        return False


class AlertNotificationService:
    """
    Service responsible for orchestrating alert notification delivery.

    Dispatches alerts using strategy-based mappings for different notification modes,
    orchestrates background worker queues, and enforces sliding-window deduplication.

    Attributes:
        call_client: Client to place phone calls.
        sms_client: Client to send SMS messages.
        dedup_service: Service to verify and enforce deduplication.
        sms_wait_seconds: Delay before phone call when using SMS-before-call strategy.
        coalescer: Alert storm coalescing engine.
    """

    def __init__(
        self,
        call_client: AsteriskCallClient,
        sms_client: CallerSmsClient,
        dedup_service: DeduplicationService | None = None,
        sms_wait_seconds: float = 30.0,
        coalescer: AlertCoalescer | None = None,
    ) -> None:
        """
        Initializes the notification service and maps notification modes to executable handlers.

        Args:
            call_client: Client to trigger phone calls.
            sms_client: Client to dispatch SMS messages.
            dedup_service: Alert deduplication service.
            sms_wait_seconds: Wait delay before phone call in SMS-before-call mode.
            coalescer: Alert storm coalescing engine.
        """
        self.call_client = call_client
        self.sms_client = sms_client
        self.dedup_service = dedup_service or DeduplicationService()
        self.sms_wait_seconds = sms_wait_seconds
        self.coalescer = coalescer or AlertCoalescer()

        self._action_dispatch: dict[str, Callable[[str, str], Awaitable[None]]] = {
            NotificationMode.CALL_ONLY.value: self.do_call_only,
            NotificationMode.SMS_ONLY.value: self.do_sms_only,
            NotificationMode.SMS_BEFORE_CALL.value: self.do_sms_before_call,
            NotificationMode.CALL_AND_SMS.value: self.do_call_and_sms,
        }

    async def do_call_only(self, receiver: str, message: str) -> None:
        """
        Dispatches a voice phone call.

        Args:
            receiver: Phone destination.
            message: Text-to-speech message content.
        """
        results = await asyncio.gather(
            self.call_client.place_call(receiver, message),
            return_exceptions=True,
        )
        if any(isinstance(r, Exception) or r is False for r in results):
            logging.info(f"Unable to start a call for '{receiver}' with message '{message}'")

    async def do_sms_only(self, receiver: str, message: str) -> None:
        """
        Dispatches an SMS message.

        Args:
            receiver: Phone destination.
            message: SMS body text.
        """
        await self.sms_client.send_sms(receiver, message)

    async def _schedule_sms_before_call(self, receiver: str, message: str) -> None:
        """
        Internal worker that sends SMS, waits for interval, then triggers call.

        Args:
            receiver: Phone destination.
            message: Notification content.
        """
        await self.do_sms_only(receiver, message)
        await asyncio.sleep(self.sms_wait_seconds)
        await self.do_call_only(receiver, message)

    async def do_sms_before_call(self, receiver: str, message: str) -> None:
        """
        Schedules asynchronous background task to send SMS followed by phone call.

        Args:
            receiver: Phone destination.
            message: Notification content.
        """
        asyncio.create_task(self._schedule_sms_before_call(receiver, message))

    async def do_call_and_sms(self, receiver: str, message: str) -> None:
        """
        Dispatches both SMS and phone call.

        Args:
            receiver: Phone destination.
            message: Notification content.
        """
        await self.do_sms_only(receiver, message)
        await self.do_call_only(receiver, message)

    async def execute_action(self, receiver: str, message: str, action_mode: str) -> None:
        """
        Executes the configured notification action using dictionary strategy dispatch.

        Args:
            receiver: Phone number destination.
            message: Alert message.
            action_mode: Mode key ('call_only', 'sms_only', etc.).
        """
        handler = self._action_dispatch.get(action_mode, self.do_call_only)
        await handler(receiver, message)

    async def process_queue(
        self,
        message: str,
        receivers: Sequence[str],
        action_mode: str,
    ) -> None:
        """
        Distributes notifications across multiple receivers using an asyncio.Queue.

        Args:
            message: Voice/SMS alert content.
            receivers: List of destination numbers.
            action_mode: Action mode string.
        """
        queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

        async def _consumer() -> None:
            while True:
                msg, rcv = await queue.get()
                await asyncio.sleep(0.4)
                logging.info(
                    f"Call/Message '{msg}' for '{rcv}' through the endpoint '{action_mode}'"
                )
                await self.execute_action(rcv, msg, action_mode)
                queue.task_done()

        producer_tasks = [
            asyncio.create_task(queue.put((message, rcv))) for rcv in receivers
        ]
        consumer_tasks = [asyncio.create_task(_consumer())]

        await asyncio.gather(*producer_tasks)
        await queue.join()
        for c in consumer_tasks:
            c.cancel()

    async def handle_alert_payload(
        self,
        payload_data: dict[str, Any],
        action_mode: str,
        receivers: Sequence[str],
        dedup_window: int = 180,
    ) -> bool:
        """
        Processes an incoming webhook payload from Alertmanager.

        Filters out inactive or resolved alerts, checks sliding-window deduplication,
        applies alert coalescing when multiple alerts fire simultaneously, and
        dispatches notifications to recipient queues.

        Args:
            payload_data: Raw JSON payload.
            action_mode: Notification action mode.
            receivers: Configured recipient numbers.
            dedup_window: Sliding deduplication window in seconds.

        Returns:
            True if any non-duplicate alerts were queued, False otherwise.
        """
        webhook = WebhookPayload.from_dict(payload_data)
        firing_messages = webhook.firing_descriptions

        if not firing_messages:
            return False

        coalesce_enabled = bool(
            settings.get("caller_prometheus_webhook", {}).get("coalesce_alerts", False)
            or settings.get("caller_prometheus_webhook", {}).get("coalescing_enabled", False)
        )
        firing_messages = (
            webhook.all_firing_descriptions if coalesce_enabled else webhook.firing_descriptions
        )

        unique_firing: list[str] = []
        for msg in firing_messages:
            if await self.dedup_service.is_duplicate(msg, ttl_seconds=dedup_window):
                logging.info(
                    f"Deduplicated repeating alert within {dedup_window}s window. Skipping duplicate calls."
                )
                continue
            unique_firing.append(msg)

        if not unique_firing:
            return False

        dispatched = False
        if coalesce_enabled and len(unique_firing) > 1:
            incident = self.coalescer.coalesce_descriptions(unique_firing)
            msg_to_send = incident.detailed_sms if action_mode == NotificationMode.SMS_ONLY.value else incident.summary_message
            await self.process_queue(msg_to_send, receivers, action_mode)
            dispatched = True
        else:
            for msg in unique_firing:
                await self.process_queue(msg, receivers, action_mode)
                dispatched = True

        return dispatched
