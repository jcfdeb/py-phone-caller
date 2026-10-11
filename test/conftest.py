"""
Centralized Pytest fixtures and testing configuration for py-phone-caller.
Provides isolated mock environments for:
- Database pools (Piccolo ORM Postgres engine)
- Redis broker and Pub/Sub connections
- Deduplication caches
- Web clients and telemetry isolation
"""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    """
    Ensures safe default test environment variables across all test suites.
    """
    monkeypatch.setenv("ENABLE_TELEMETRY", "false")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")


@pytest.fixture
def mock_db_pool(monkeypatch):
    """
    Mocks Piccolo DB engine pool to avoid connecting to external PostgreSQL during unit tests.
    """
    from py_phone_caller_utils.py_phone_caller_db.piccolo_conf import DB

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    monkeypatch.setattr(DB, "pool", mock_pool)
    return mock_pool


@pytest.fixture
def mock_redis():
    """
    Provides a standardized mock Redis client for Celery tasks and event broadcasting.
    """
    mock_r = MagicMock()
    mock_r.set = MagicMock(return_value=True)
    mock_r.get = MagicMock(return_value=None)
    mock_r.publish = AsyncMock(return_value=1)
    mock_r.ping = MagicMock(return_value=True)
    mock_r.aclose = AsyncMock()
    return mock_r


@pytest.fixture
def sample_alert_payload():
    """
    Sample Prometheus Alertmanager webhook payload for testing.
    """
    return {
        "receiver": "webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "HighCpuLoad",
                    "severity": "critical",
                    "instance": "node-01",
                },
                "annotations": {
                    "description": "CPU usage has exceeded 95% on host node-01 for > 5 minutes.",
                    "summary": "High CPU utilization detected.",
                },
                "startsAt": "2026-10-01T12:00:00Z",
            }
        ],
    }


@pytest.fixture
def sample_contact():
    """
    Sample contact record for address book testing.
    """
    return {
        "name": "Jane",
        "surname": "Doe",
        "phone_number": "00393349246425",
        "city": "Rome",
        "country": "Italy",
        "enabled": True,
        "on_call_availability": {"monday": ["09:00", "18:00"]},
    }
