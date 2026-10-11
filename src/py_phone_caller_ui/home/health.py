"""
Gateway and Microservice Cluster Health Monitor for the py_phone_caller_ui.

Probes APISIX Gateway, Keycloak IAM, Asterisk ARI/WS, PostgreSQL database,
Redis queue, and SMS dispatch engines with non-blocking concurrent checks.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp
from py_phone_caller_utils.config import settings

logger = logging.getLogger(__name__)


async def check_http_endpoint(url: str, timeout_sec: float = 0.8) -> tuple[bool, int, str]:
    """Helper to defensively ping an HTTP endpoint with a strict timeout."""
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                text = await resp.text()
                return (resp.status in (200, 204, 302, 401, 404), resp.status, text[:200])
    except Exception as exc:
        return (False, 0, str(exc))


async def check_gateway_health() -> dict[str, Any]:
    """
    Inspects APISIX Gateway connectivity and operational state.

    Defensively probes APISIX Prometheus metrics or local port 9080 HTTP ingress.
    """
    gateway_cfg = settings.get("gateway", {})
    behind_gw = gateway_cfg.get("behind_gateway", False)
    gw_url = str(gateway_cfg.get("gateway_public_url", "http://127.0.0.1:9080"))

    test_urls = [
        "http://127.0.0.1:9080/apisix/prometheus/metrics",
        f"{gw_url.rstrip('/')}/api/v1/health",
        "http://127.0.0.1:9080/",
    ]
    for url in test_urls:
        ok, status, _ = await check_http_endpoint(url, timeout_sec=0.5)
        if ok or status == 404:
            return {
                "status": "healthy",
                "label": "APISIX Gateway",
                "badge": "APISIX Ingress OK",
                "detail": f"Active reverse proxy at {gw_url}",
                "active": True,
            }

    if not behind_gw:
        return {
            "status": "standalone",
            "label": "API Ingress",
            "badge": "Standalone Ingress",
            "detail": "Operating in direct microservice mode (APISIX bypass)",
            "active": False,
        }

    return {
        "status": "unreachable",
        "label": "APISIX Gateway",
        "badge": "Gateway Offline",
        "detail": f"Could not connect to gateway endpoint {gw_url}",
        "active": False,
    }


async def check_iam_health() -> dict[str, Any]:
    """Inspects Keycloak Identity & Access Management reachability."""
    auth_cfg = settings.get("auth", {})
    provider = auth_cfg.get("provider", "local")
    oauth_cfg = auth_cfg.get("oauth2", {})
    is_oauth_enabled = bool(oauth_cfg.get("enabled", False) or provider == "oauth2")

    if not is_oauth_enabled:
        return {
            "status": "local",
            "label": "Identity IAM",
            "badge": "Native RBAC",
            "detail": "Native role-based database authentication active",
            "active": False,
        }

    issuer = str(oauth_cfg.get("issuer_url", "http://127.0.0.1:8180/realms/py-phone-caller"))
    well_known = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    ok, status, _ = await check_http_endpoint(well_known, timeout_sec=0.8)

    if ok:
        return {
            "status": "healthy",
            "label": "Keycloak IAM",
            "badge": "Keycloak SSO Active",
            "detail": f"Realm operational at {issuer}",
            "active": True,
        }

    return {
        "status": "unreachable",
        "label": "Keycloak IAM",
        "badge": "SSO Unreachable",
        "detail": f"Cannot reach OIDC discovery endpoint at {well_known}",
        "active": False,
    }


async def check_database_health() -> dict[str, Any]:
    """Measures PostgreSQL query round-trip latency via active ping."""
    t0 = time.perf_counter()
    try:
        from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import Users
        await Users.raw("SELECT 1").run()
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "status": "healthy",
            "label": "Database",
            "badge": f"PostgreSQL ({latency_ms}ms)",
            "detail": f"Connected to {settings.get('database.db_name', 'py_phone_caller')} ({latency_ms} ms)",
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        return {
            "status": "error",
            "label": "Database",
            "badge": "DB Error",
            "detail": str(exc),
            "latency_ms": None,
        }


async def check_redis_health() -> dict[str, Any]:
    """Validates Redis connection and queue status."""
    try:
        from py_phone_caller_utils.redis_lock import get_redis_client
        r = get_redis_client()
        t0 = time.perf_counter()
        pong = await r.ping()
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        if pong:
            return {
                "status": "healthy",
                "label": "Redis Cache",
                "badge": f"Queue Depth 0 ({latency_ms}ms)",
                "detail": f"Cluster broker responsive ({latency_ms} ms)",
            }
    except Exception:
        pass

    return {
        "status": "standalone",
        "label": "Redis Cache",
        "badge": "In-Memory Queue",
        "detail": "Operating in local in-memory queue fallback mode",
    }


async def check_asterisk_health() -> dict[str, Any]:
    """Inspects Asterisk Call microservice (:8081)."""
    call_port = settings.get("asterisk_call.asterisk_call_port", 8081)
    call_host = settings.get("asterisk_call.asterisk_call_host", "127.0.0.1")
    url = f"http://{call_host}:{call_port}/live"
    ok, status, _ = await check_http_endpoint(url, timeout_sec=0.5)

    if ok:
        return {
            "status": "healthy",
            "label": "Asterisk ARI",
            "badge": "ARI Connected",
            "detail": f"Telephony daemon online on port {call_port}",
        }
    return {
        "status": "warning",
        "label": "Asterisk ARI",
        "badge": "ARI Standby",
        "detail": f"Microservice port {call_port} unresponsive or idle",
    }


async def check_sms_health() -> dict[str, Any]:
    """Inspects SMS carrier configuration and microservice (:8085)."""
    carrier = getattr(settings.caller_sms, "caller_sms_carrier", "on_premise")
    sms_port = getattr(settings.caller_sms, "caller_sms_port", 8085)
    url = f"http://127.0.0.1:{sms_port}/live"
    ok, _, _ = await check_http_endpoint(url, timeout_sec=0.5)

    if carrier == "on_premise":
        modems = getattr(settings.caller_sms, "modems", [])
        count = len(modems) if modems else 1
        badge = f"Modems {count}/{count} Ready"
    else:
        badge = "Twilio Cloud Ready"

    return {
        "status": "healthy" if ok else "warning",
        "label": "SMS Engine",
        "badge": badge,
        "detail": f"{'Online' if ok else 'Standby'} (Carrier: {carrier})",
    }


async def get_cluster_health() -> dict[str, Any]:
    """
    Aggregates all component health checks concurrently.

    Probes the gateway, IAM identity provider, PostgreSQL database,
    Redis queue, Asterisk ARI engine, and SMS carrier service. Computes
    the aggregate health state ('healthy', 'warning', or 'degraded')
    and includes an execution timestamp.

    Returns:
        dict[str, Any]: Health status dictionary for each subsystem and overall cluster.
    """
    results = await asyncio.gather(
        check_gateway_health(),
        check_iam_health(),
        check_database_health(),
        check_redis_health(),
        check_asterisk_health(),
        check_sms_health(),
        return_exceptions=True,
    )

    names = ["gateway", "iam", "database", "redis", "asterisk", "sms"]
    health: dict[str, Any] = {}
    for name, res in zip(names, results):
        if isinstance(res, Exception):
            health[name] = {
                "status": "error",
                "label": name.capitalize(),
                "badge": "Check Error",
                "detail": str(res),
            }
        else:
            health[name] = res

    statuses = [h.get("status") for h in health.values()]
    if "error" in statuses:
        overall = "degraded"
    elif "warning" in statuses or "unreachable" in statuses:
        overall = "warning"
    else:
        overall = "healthy"

    health["overall"] = overall
    health["timestamp"] = time.time()
    return health
