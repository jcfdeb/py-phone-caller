"""
Distributed Async Locking Utility using Redis.

Provides a non-blocking / timed context manager for synchronizing critical
sections across multiple workers or service instances (e.g. call-level state
transitions in Piccolo ORM).
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
import redis.asyncio as aioredis
from py_phone_caller_utils.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional[aioredis.Redis] = None


def get_redis_client() -> aioredis.Redis:
    """
    Returns a shared or singleton async Redis client instance configured
    from settings.queue.queue_url.
    """
    global _redis_client
    if _redis_client is None:
        queue_url = getattr(settings.queue, "queue_url", "redis://127.0.0.1:6379/7")
        _redis_client = aioredis.from_url(
            queue_url,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
    return _redis_client


@asynccontextmanager
async def call_mutex(
    resource_id: str,
    timeout: float = 10.0,
    blocking_timeout: float = 5.0,
) -> AsyncIterator[bool]:
    """
    Distributed async lock for call-level state mutations (e.g., heard_at, acknowledge_at).

    If Redis is unreachable or raises a connection error, gracefully logs a warning
    and yields control without blocking execution, ensuring high availability even in
    standalone/offline test environments.

    Args:
        resource_id (str): Identifier for the resource to lock (e.g., call_id or asterisk_chan).
        timeout (float): Max lock validity lifetime in seconds (default 10.0s).
        blocking_timeout (float): Max time to wait acquiring the lock in seconds (default 5.0s).

    Yields:
        bool: True if lock acquired, False if fallback/unacquired.
    """
    lock_key = f"lock:call:{resource_id}"
    lock = None
    acquired = False

    try:
        r = get_redis_client()
        lock = r.lock(name=lock_key, timeout=timeout, blocking_timeout=blocking_timeout)
        acquired = await lock.acquire()
        if not acquired:
            logger.warning(f"Could not acquire distributed lock for resource: {lock_key}")
    except Exception as err:
        logger.warning(
            f"Redis lock acquisition skipped or failed ({err}). Proceeding in fail-open mode for {lock_key}."
        )
        lock = None
        acquired = False

    try:
        yield acquired
    finally:
        if lock and acquired:
            try:
                await lock.release()
            except Exception as release_err:
                logger.debug(f"Failed to release distributed lock for {lock_key}: {release_err}")
