import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from py_phone_caller_utils.checksums import (
    gen_call_chk_sum,
    gen_msg_chk_sum,
    gen_unique_chk_sum,
)
from py_phone_caller_utils.login.user import User
from py_phone_caller_utils.event_bus import (
    TELEPHONY_STREAM_CHANNEL,
    publish_event,
    subscribe_events,
)
from py_phone_caller_utils.redis_lock import call_mutex, get_redis_client
from py_phone_caller_utils.env_validator import (
    validate_environment_consistency,
    run_startup_health_banner,
)
from py_phone_caller_utils.models import (
    AlertSeverity,
    CallAlertRequest,
    CallDispatchSpec,
    ChannelState,
    ContactCreatePayload,
    ContactModel,
    ContactUpdatePayload,
    DtmfAckPayload,
    PrometheusAlertItem,
    PrometheusWebhookPayload,
    SmsCarrier,
    SmsPayload,
    SmsRecordModel,
    SmsStatus,
)


@pytest.mark.asyncio
async def test_checksums_generation():
    call_chk = await gen_call_chk_sum("0039123456789", "Server alert")
    assert isinstance(call_chk, str)
    assert len(call_chk) == 8  # 4 bytes hex = 8 chars

    msg_chk = await gen_msg_chk_sum("Server alert")
    assert isinstance(msg_chk, str)
    assert len(msg_chk) == 8

    unique_chk = await gen_unique_chk_sum("0039123456789", "Server alert", "2026-10-06 10:00:00")
    assert isinstance(unique_chk, str)
    assert len(unique_chk) == 8

    # Determinism
    call_chk_2 = await gen_call_chk_sum("0039123456789", "Server alert")
    assert call_chk == call_chk_2


def test_user_session_model():
    with patch("py_phone_caller_utils.login.user.select_user_id", return_value="user-uuid-1234"):
        u = User("admin")
        assert u.username == "admin"
        assert u.is_authenticated is True
        assert u.is_active is True
        assert u.is_anonymous is False
        assert u.get_id() == "user-uuid-1234"


@pytest.mark.asyncio
async def test_event_bus_publish_fail_safe():
    with patch("py_phone_caller_utils.event_bus.get_redis_client") as mock_get_client:
        mock_r = MagicMock()
        mock_r.publish = AsyncMock(side_effect=Exception("Redis down"))
        mock_get_client.return_value = mock_r

        # Should not raise exception
        await publish_event("test_event", {"message": "hello"})
        mock_r.publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_event_bus_publish_success():
    with patch("py_phone_caller_utils.event_bus.get_redis_client") as mock_get_client:
        mock_r = MagicMock()
        mock_r.publish = AsyncMock(return_value=1)
        mock_get_client.return_value = mock_r

        await publish_event("telephony_update", {"call_id": 42})
        mock_r.publish.assert_awaited_once()
        args, _ = mock_r.publish.call_args
        assert args[0] == TELEPHONY_STREAM_CHANNEL
        assert "telephony_update" in args[1]


@pytest.mark.asyncio
async def test_redis_call_mutex_fail_open():
    with patch("py_phone_caller_utils.redis_lock.get_redis_client") as mock_get_client:
        mock_r = MagicMock()
        mock_lock = MagicMock()
        mock_lock.acquire = AsyncMock(side_effect=ConnectionError("Unreachable"))
        mock_r.lock.return_value = mock_lock
        mock_get_client.return_value = mock_r

        # Lock fails gracefully in fail-open mode without blocking
        async with call_mutex("call-1234") as acquired:
            assert acquired is False


@pytest.mark.asyncio
async def test_redis_call_mutex_success():
    with patch("py_phone_caller_utils.redis_lock.get_redis_client") as mock_get_client:
        mock_r = MagicMock()
        mock_lock = MagicMock()
        mock_lock.acquire = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock(return_value=None)
        mock_r.lock.return_value = mock_lock
        mock_get_client.return_value = mock_r

        async with call_mutex("call-5678") as acquired:
            assert acquired is True
        mock_lock.release.assert_awaited_once()


def test_env_validator_consistency():
    diag = validate_environment_consistency()
    assert isinstance(diag, dict)
    assert "status" in diag
    assert "config_summary" in diag
    run_startup_health_banner("test_service")


def test_models_domain_validations():
    # Alert model
    alert_item = PrometheusAlertItem(
        status="firing",
        labels={"severity": "critical", "alertname": "HighDiskUsage"},
        annotations={"summary": "Disk 95% full"},
    )
    assert alert_item.severity == AlertSeverity.CRITICAL
    assert alert_item.alert_name == "HighDiskUsage"
    assert alert_item.summary == "Disk 95% full"

    # Contact model phone normalization
    contact = ContactModel(
        name="Sysadmin Oncall",
        phone="+39 (334) 924-6425",
        group="devops",
    )
    assert contact.phone == "+393349246425"

    with pytest.raises(ValueError):
        ContactModel(name="Bad Phone", phone="invalid-num")

    # SMS Payload validation
    sms_payload = SmsPayload(phone="0039 334 1122334", message="Critical Alert")
    assert sms_payload.phone == "00393341122334"

    # Telephony dispatch spec
    spec = CallDispatchSpec(
        endpoint="PJSIP/trunk/0039123",
        phone="0039123",
        audio_file="/tmp/test.wav",
    )
    assert spec.timeout_seconds == 60
    assert spec.context == "from-internal"
