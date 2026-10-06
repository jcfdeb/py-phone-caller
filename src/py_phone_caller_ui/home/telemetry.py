"""
Telemetry and metrics calculation module for the Py Phone Caller NOC Dashboard.

Computes real-time call lifecycle statistics, DTMF acknowledgment rates,
escalation numbers, and hardware gateway routing indicators with fast Redis TTL caching.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from py_phone_caller_utils.config import settings
from py_phone_caller_utils.redis_lock import get_redis_client
from py_phone_caller_utils.py_phone_caller_db.db_caller_register import select_calls
from py_phone_caller_utils.py_phone_caller_db.db_sms import select_sms

logger = logging.getLogger(__name__)


async def get_noc_dashboard_metrics() -> Dict[str, Any]:
    """
    Computes real-time NOC Telemetry metrics with 5-second Redis caching.
    Ensures sub-5ms UI dashboard loads with zero DB query contention.
    """
    cache_key = "py_phone_caller:ui:noc_metrics"
    try:
        r = get_redis_client()
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.debug(f"Redis cache check failed: {e}")

    try:
        all_calls = await select_calls()
    except Exception as e:
        logger.error(f"Error fetching calls for metrics: {e}")
        all_calls = []

    try:
        all_sms = await select_sms()
    except Exception as e:
        logger.error(f"Error fetching sms for metrics: {e}")
        all_sms = []

    total_calls = len(all_calls)
    ack_count = 0
    heard_count = 0
    escalated_count = 0
    in_flight_count = 0

    for c in all_calls:
        ack_dt = c.get("acknowledge_at")
        is_ack = bool(ack_dt and getattr(ack_dt, "year", 0) > 2000)

        heard_dt = c.get("heard_at")
        is_heard = bool(heard_dt and getattr(heard_dt, "year", 0) > 2000 and not is_ack)

        is_escalated = bool(c.get("backup_callee"))
        is_in_flight = not c.get("cycle_done", False) and not is_ack

        if is_ack:
            ack_count += 1
        elif is_heard:
            heard_count += 1
        elif is_escalated:
            escalated_count += 1
        elif is_in_flight:
            in_flight_count += 1

    ack_rate = round((ack_count / total_calls * 100), 1) if total_calls > 0 else 100.0

    total_sms = len(all_sms)
    sms_delivered = sum(
        1 for s in all_sms if s.get("status") in ("sent", "delivered", "received_ack")
    )
    sms_failed = sum(1 for s in all_sms if s.get("status") == "failed")
    sms_rate = round((sms_delivered / total_sms * 100), 1) if total_sms > 0 else 100.0

    # Hardware & Gateway indicators
    carrier = getattr(settings.caller_sms, "caller_sms_carrier", "on_premise")
    is_gsm = carrier == "on_premise"

    metrics = {
        "total_calls": total_calls,
        "ack_count": ack_count,
        "ack_rate": ack_rate,
        "heard_count": heard_count,
        "escalated_count": escalated_count,
        "in_flight_count": in_flight_count,
        "total_sms": total_sms,
        "sms_delivered": sms_delivered,
        "sms_failed": sms_failed,
        "sms_rate": sms_rate,
        "is_gsm": is_gsm,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        r = get_redis_client()
        await r.setex(cache_key, 5, json.dumps(metrics))
    except Exception as e:
        logger.debug(f"Failed to set Redis cache: {e}")

    return metrics
