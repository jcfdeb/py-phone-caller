"""
Readiness probe and dependency health check utilities.
Provides structured HTTP 503 diagnostics when backing services (PostgreSQL, Redis,
Asterisk ARI/PBX, TTS engine) are unreachable or initializing, while keeping
liveness endpoints (/live, /healthz) healthy to prevent orchestrator crash-loops.
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple, Union
from aiohttp import web

logger = logging.getLogger(__name__)

# Registered dependency check callback signature: async def check() -> Tuple[bool, str]
CheckFunc = Callable[[], Coroutine[Any, Any, Tuple[bool, str]]]


class ReadinessRegistry:
    """
    Registry for service dependency checks.
    """

    def __init__(self, service_name: str):
        self.service_name = service_name
        self.checks: Dict[str, CheckFunc] = {}

    def register(self, name: str, check_func: CheckFunc):
        """Register an async check function returning (is_ready: bool, message: str)."""
        self.checks[name] = check_func

    async def evaluate(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Executes all registered dependency checks concurrently.
        Returns (is_ready, details_dict).
        """
        if not self.checks:
            return True, {"status": "ready", "service": self.service_name, "checks": {}}

        results = {}
        all_ready = True

        for name, check_func in self.checks.items():
            try:
                # Wrap with a 3-second timeout per individual check to prevent hangs
                ready, msg = await asyncio.wait_for(check_func(), timeout=3.0)
                results[name] = {"ready": ready, "message": msg}
                if not ready:
                    all_ready = False
            except asyncio.TimeoutError:
                results[name] = {"ready": False, "message": "Timed out after 3.0s"}
                all_ready = False
            except Exception as e:
                results[name] = {"ready": False, "message": f"Exception: {str(e)}"}
                all_ready = False

        status = "ready" if all_ready else "degraded"
        details = {
            "status": status,
            "service": self.service_name,
            "ready": all_ready,
            "checks": results,
        }
        return all_ready, details


# Built-in Dependency Checkers

async def check_database_pool() -> Tuple[bool, str]:
    """
    Checks if Piccolo DB connection pool is initialized and can execute a simple query.
    """
    try:
        from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB

        if DB.pool is None:
            # Attempt to start connection pool if not already running
            try:
                await DB.start_connection_pool()
            except Exception as pool_err:
                return False, f"Database connection pool not established: {pool_err}"

        # Test simple query
        await DB.run_querystring("SELECT 1;")
        return True, "Database pool connected and responsive"
    except Exception as e:
        return False, f"Database check failed: {str(e)}"


async def check_redis_broker(redis_url: Optional[str] = None) -> Tuple[bool, str]:
    """
    Checks if Redis / Valkey broker is responsive.
    """
    try:
        import redis.asyncio as aioredis
        from py_phone_caller_utils.config import settings

        url = redis_url or settings.get("CELERY_BROKER_URL") or "redis://127.0.0.1:6379/0"
        r = aioredis.from_url(url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        return True, "Redis broker reachable and responsive"
    except Exception as e:
        return False, f"Redis broker unreachable: {str(e)}"


async def check_asterisk_ari(ari_url: str, username: str, secret: str) -> Tuple[bool, str]:
    """
    Checks if Asterisk ARI interface is responsive.
    """
    from aiohttp import ClientSession, BasicAuth, ClientTimeout

    try:
        url = f"{ari_url.rstrip('/')}/asterisk/info"
        auth = BasicAuth(username, secret) if username and secret else None
        async with ClientSession(timeout=ClientTimeout(total=2.0)) as session:
            async with session.get(url, auth=auth) as resp:
                if resp.status in (200, 204):
                    return True, "Asterisk ARI connected"
                return False, f"Asterisk ARI returned HTTP {resp.status}"
    except Exception as e:
        return False, f"Asterisk ARI unreachable: {str(e)}"


def setup_readiness_probe(
    app: web.Application,
    service_name: str,
    registry: Optional[ReadinessRegistry] = None,
) -> ReadinessRegistry:
    """
    Mounts /ready endpoint onto an aiohttp web application.
    If dependencies are unhealthy, returns HTTP 503 with structured JSON diagnostics.
    """
    reg = registry or ReadinessRegistry(service_name)

    async def ready_handler(request: web.Request) -> web.Response:
        all_ready, details = await reg.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    app.router.add_get("/ready", ready_handler)
    return reg
