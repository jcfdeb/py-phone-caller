import time
import pytest
from unittest.mock import patch, AsyncMock
from src.caller_prometheus_webhook import (
    AlertNotificationService,
    AsteriskCallClient,
    CallerSmsClient,
    DeduplicationService,
    DispatchItem,
    NotificationMode,
    PrometheusAlert,
    WebhookPayload,
    init_app,
)
from src.caller_prometheus_webhook.caller_prometheus_webhook import (
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
    PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL,
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
async def test_sms_before_call_endpoint(cli):
    payload = {
        "alerts": [{"status": "firing", "annotations": {"description": "SMS Before Call Alert"}}]
    }
    with patch(
        "src.caller_prometheus_webhook.caller_prometheus_webhook.producer"
    ) as mock_producer:
        resp = await cli.post(
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL}", json=payload
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


def test_schemas_dataclasses():
    alert = PrometheusAlert.from_dict({
        "status": "firing",
        "annotations": {"description": "High memory"},
        "labels": {"severity": "critical"},
    })
    assert alert.is_firing is True
    assert alert.description == "High memory"

    payload = WebhookPayload.from_dict({
        "receiver": "webhook_receiver",
        "alerts": [
            {"status": "resolved", "annotations": {"description": "Old issue"}},
            {"status": "firing", "annotations": {"description": "Current issue"}},
        ],
    })
    assert payload.firing_descriptions == ["Current issue"]
    assert payload.receiver == "webhook_receiver"


@pytest.mark.asyncio
async def test_deduplication_service_in_memory():
    dedup = DeduplicationService(ttl_seconds=1, use_redis=False)
    is_dup1 = await dedup.is_duplicate("Message 1")
    assert is_dup1 is False
    is_dup2 = await dedup.is_duplicate("Message 1")
    assert is_dup2 is True

    # After TTL
    time.sleep(1.1)
    is_dup3 = await dedup.is_duplicate("Message 1")
    assert is_dup3 is False


@pytest.mark.asyncio
async def test_alert_notification_service_strategy():
    mock_call = AsyncMock()
    mock_call.place_call.return_value = True
    mock_sms = AsyncMock()
    mock_sms.send_sms.return_value = True

    svc = AlertNotificationService(call_client=mock_call, sms_client=mock_sms)
    await svc.execute_action("123", "msg", NotificationMode.CALL_ONLY.value)
    mock_call.place_call.assert_called_once_with("123", "msg")

    await svc.execute_action("456", "msg2", NotificationMode.SMS_ONLY.value)
    mock_sms.send_sms.assert_called_once_with("456", "msg2")

    await svc.execute_action("789", "msg3", NotificationMode.CALL_AND_SMS.value)
    assert mock_sms.send_sms.call_count == 2
    assert mock_call.place_call.call_count == 2
