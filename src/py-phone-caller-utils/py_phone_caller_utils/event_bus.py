"""
Redis PubSub real-time telephony and alert event bus.

Provides non-blocking publishing and asynchronous subscription streams
for Server-Sent Events (SSE) and live UI updates.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from py_phone_caller_utils.redis_lock import get_redis_client

logger = logging.getLogger(__name__)

TELEPHONY_STREAM_CHANNEL: str = "py_phone_caller:events:telephony"


async def publish_event(
    event_type: str,
    payload: dict[str, Any],
    channel: str = TELEPHONY_STREAM_CHANNEL,
) -> None:
    """
    Publishes a structured event to a Redis Pub/Sub channel.

    Fail-safe: Redis connectivity errors are caught and logged without raising.

    Args:
        event_type: Type of the event (e.g. 'call_started', 'sms_dispatched').
        payload: Event data dictionary.
        channel: Redis channel name.
    """
    try:
        r = get_redis_client()
        message = {
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": payload,
        }
        await r.publish(channel, json.dumps(message))
    except Exception as err:
        logger.debug(f"Event publish to '{channel}' skipped: {err}")


async def subscribe_events(
    channel: str = TELEPHONY_STREAM_CHANNEL,
    timeout_seconds: float | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Subscribes to a Redis Pub/Sub channel and yields parsed event dictionaries.

    Automatically handles connection setup, message parsing, and teardown.

    Args:
        channel: Redis channel name to subscribe to.
        timeout_seconds: Optional timeout in seconds (reserved for future poll-based backends).

    Yields:
        Parsed JSON message dictionaries.
    """
    r = get_redis_client()
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)
    try:
        async for raw_message in pubsub.listen():
            if raw_message["type"] == "message":
                try:
                    data = json.loads(raw_message["data"])
                    yield data
                except Exception as decode_err:
                    logger.debug(f"Failed to decode message from {channel}: {decode_err}")
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
        except Exception:
            pass


__all__ = [
    "TELEPHONY_STREAM_CHANNEL",
    "publish_event",
    "subscribe_events",
]
