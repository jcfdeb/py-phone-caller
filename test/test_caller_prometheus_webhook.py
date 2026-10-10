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

@pytest.mark.asyncio
async def test_webhook_with_valid_bearer_token(cli):
    import base64, json
    payload = {
        "alerts": [{"status": "firing", "annotations": {"description": "M2M Authenticated Alert"}}]
    }
    jwt_claims = {
        "sub": "service-account-m2m",
        "azp": "py-phone-caller-m2m",
        "iss": "https://py-phone-caller.link/realms/py-phone-caller",
        "exp": 9999999999,
        "realm_access": {"roles": ["alert-operator"]},
    }
    b64_payload = base64.urlsafe_b64encode(json.dumps(jwt_claims).encode()).decode().rstrip("=")
    token = f"header.{b64_payload}.signature"
    headers = {"Authorization": f"Bearer {token}"}

    with patch(
        "src.caller_prometheus_webhook.caller_prometheus_webhook.producer"
    ) as mock_producer:
        resp = await cli.post(
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}", json=payload, headers=headers
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "200"
        mock_producer.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_required_auth_behavior(cli, monkeypatch):
    import base64, json
    from py_phone_caller_utils.config import settings

    # Simulate require_auth = True
    monkeypatch.setattr(settings, "caller_prometheus_webhook", {
        **settings.get("caller_prometheus_webhook", {}),
        "require_auth": True,
    })

    payload = {
        "alerts": [{"status": "firing", "annotations": {"description": "Auth Enforced Alert"}}]
    }

    # 1. Missing Authorization header -> 401 Unauthorized
    resp_no_auth = await cli.post(f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}", json=payload)
    assert resp_no_auth.status == 401

    # 2. Expired token -> 401 Unauthorized
    expired_claims = {
        "sub": "service-account-m2m",
        "azp": "py-phone-caller-m2m",
        "exp": 1000,
        "realm_access": {"roles": ["alert-operator"]},
    }
    b64_expired = base64.urlsafe_b64encode(json.dumps(expired_claims).encode()).decode().rstrip("=")
    expired_token = f"h.{b64_expired}.s"
    resp_expired = await cli.post(
        f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}",
        json=payload,
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp_expired.status == 401

    # 3. Valid token with alert-operator role -> 200 OK
    valid_claims = {
        "sub": "service-account-m2m",
        "azp": "py-phone-caller-m2m",
        "exp": 9999999999,
        "realm_access": {"roles": ["alert-operator"]},
    }
    b64_valid = base64.urlsafe_b64encode(json.dumps(valid_claims).encode()).decode().rstrip("=")
    valid_token = f"h.{b64_valid}.s"
    with patch(
        "src.caller_prometheus_webhook.caller_prometheus_webhook.producer"
    ) as mock_producer:
        resp_valid = await cli.post(
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}",
            json=payload,
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp_valid.status == 200
        mock_producer.assert_called_once()

@pytest.mark.asyncio
async def test_alert_coalescer_single_and_multi():
    from src.caller_prometheus_webhook.coalescing import AlertCoalescer

    coalescer = AlertCoalescer(max_samples_in_tts=2)

    # Empty
    empty_inc = coalescer.coalesce_descriptions([])
    assert empty_inc.alert_count == 0

    # Single
    single_inc = coalescer.coalesce_descriptions(["Host down"])
    assert single_inc.alert_count == 1
    assert single_inc.summary_message == "Host down"

    # Multiple (Alert Storm)
    multi_inc = coalescer.coalesce_descriptions(["Host down", "Disk full", "High memory", "DB connection lost"])
    assert multi_inc.alert_count == 4
    assert "Alert Storm: 4 firing alerts detected." in multi_inc.summary_message
    assert "Host down. Disk full." in multi_inc.summary_message
    assert "And 2 additional alerts." in multi_inc.summary_message
    assert "[ALERT STORM - 4 ALERTS]" in multi_inc.detailed_sms


@pytest.mark.asyncio
async def test_coalescing_buffer_flushing():
    import asyncio
    from src.caller_prometheus_webhook.coalescing import CoalescingBuffer

    flushed_incidents = []

    async def mock_callback(incident, receivers, mode):
        flushed_incidents.append((incident, receivers, mode))

    buffer = CoalescingBuffer(flush_callback=mock_callback, window_seconds=0.1, max_batch_size=3)
    assert not buffer.is_active

    await buffer.add_alerts(["Alert 1", "Alert 2"], ["+1234"], "call_only")
    assert buffer.is_active

    # Wait for timer to flush
    await asyncio.sleep(0.15)
    assert not buffer.is_active
    assert len(flushed_incidents) == 1
    inc, rcvs, mode = flushed_incidents[0]
    assert inc.alert_count == 2
    assert "+1234" in rcvs


@pytest.mark.asyncio
async def test_handle_alert_payload_with_coalescing_enabled(monkeypatch):
    from py_phone_caller_utils.config import settings
    from src.caller_prometheus_webhook.services import AlertNotificationService

    monkeypatch.setattr(settings, "caller_prometheus_webhook", {
        **settings.get("caller_prometheus_webhook", {}),
        "coalescing_enabled": True,
    })

    mock_call = AsyncMock()
    mock_call.place_call.return_value = True
    mock_sms = AsyncMock()
    mock_sms.send_sms.return_value = True

    svc = AlertNotificationService(call_client=mock_call, sms_client=mock_sms)

    payload = {
        "alerts": [
            {"status": "firing", "annotations": {"description": "CPU Spike"}},
            {"status": "firing", "annotations": {"description": "RAM Full"}},
            {"status": "firing", "annotations": {"description": "Disk Full"}},
        ]
    }

    with patch.object(svc, "process_queue", new_callable=AsyncMock) as mock_queue:
        dispatched = await svc.handle_alert_payload(payload, "call_only", ["+1234"])
        assert dispatched is True
        mock_queue.assert_called_once()
        queued_msg = mock_queue.call_args[0][0]
        assert "Alert Storm: 3 firing alerts detected" in queued_msg

