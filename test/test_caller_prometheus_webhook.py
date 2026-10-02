import time
import pytest
from unittest.mock import patch, AsyncMock
from src.caller_prometheus_webhook.caller_prometheus_webhook import (
    init_app,
    the_alert_description,
    start_the_asterisk_call,
    send_message_to_caller_sms,
)

@pytest.fixture(autouse=True)
def reset_dedup(monkeypatch):
    from src.caller_prometheus_webhook import caller_prometheus_webhook
    caller_prometheus_webhook._LOCAL_DEDUP_CACHE.clear()
    # Mock redis check in unit tests to use fresh memory
    async def mock_is_duplicate_alert(message: str, ttl_seconds: int = 180) -> bool:
        msg_hash = caller_prometheus_webhook.hashlib.sha256(message.strip().encode("utf-8")).hexdigest()[:16]
        now = time.time()
        last_seen = caller_prometheus_webhook._LOCAL_DEDUP_CACHE.get(msg_hash)
        if last_seen and (now - last_seen) < ttl_seconds:
            return True
        caller_prometheus_webhook._LOCAL_DEDUP_CACHE[msg_hash] = now
        return False
    monkeypatch.setattr(caller_prometheus_webhook, "is_duplicate_alert", mock_is_duplicate_alert)

from src.caller_prometheus_webhook.constants import (
    PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY,
    PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY,
    PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS,
)


@pytest.fixture
async def cli(aiohttp_client):
    app = await init_app()
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_call_only_endpoint(cli):
    payload = {
        "alerts": [{"status": "firing", "annotations": {"description": "Test Alert Description"}}]
    }
    with patch(
        "src.caller_prometheus_webhook.caller_prometheus_webhook.producer"
    ) as mock_producer:
        resp = await cli.post(
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}", json=payload
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "200"
        mock_producer.assert_called_once()


@pytest.mark.asyncio
async def test_sms_only_endpoint(cli):
    payload = {
        "alerts": [{"status": "firing", "annotations": {"description": "SMS Critical Alert"}}]
    }
    with patch(
        "src.caller_prometheus_webhook.caller_prometheus_webhook.producer"
    ) as mock_producer:
        resp = await cli.post(
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY}", json=payload
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "200"
        mock_producer.assert_called_once()


@pytest.mark.asyncio
async def test_call_and_sms_endpoint(cli):
    payload = {
        "alerts": [{"status": "firing", "annotations": {"description": "Combined Alert"}}]
    }
    with patch(
        "src.caller_prometheus_webhook.caller_prometheus_webhook.producer"
    ) as mock_producer:
        resp = await cli.post(
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS}", json=payload
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "200"
        mock_producer.assert_called_once()


@pytest.mark.asyncio
async def test_the_alert_description_empty():
    desc = await the_alert_description({"alerts": []})
    assert desc == []

    desc_resolved = await the_alert_description(
        {"alerts": [{"status": "resolved", "annotations": {"description": "Resolved Alert"}}]}
    )
    assert desc_resolved == []


@pytest.mark.asyncio
async def test_start_the_asterisk_call_and_sms_network():
    with patch("aiohttp.ClientSession.post") as mock_post:
        await start_the_asterisk_call("+393340000000", "Test Call")
        assert mock_post.called

    with patch("aiohttp.ClientSession.post") as mock_post:
        await send_message_to_caller_sms("+393340000000", "Test SMS")
        assert mock_post.called


@pytest.mark.asyncio
async def test_alert_deduplication(cli):
    payload = {
        "alerts": [{"status": "firing", "annotations": {"description": "Deduplication Test Alert"}}]
    }
    with patch(
        "src.caller_prometheus_webhook.caller_prometheus_webhook.producer"
    ) as mock_producer:
        # First post should trigger producer
        resp1 = await cli.post(
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}", json=payload
        )
        assert resp1.status == 200
        assert mock_producer.call_count == 1

        # Second post within sliding window should be suppressed by deduplicator
        resp2 = await cli.post(
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}", json=payload
        )
        assert resp2.status == 200
        # Call count remains 1 because duplicate alert was discarded
        assert mock_producer.call_count == 1
