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


@pytest.mark.asyncio
async def test_db_caller_register_parameterizes_sql_and_handles_results():
    from piccolo.query.methods.raw import Raw
    from py_phone_caller_utils.py_phone_caller_db.db_caller_register import (
        Calls,
        get_current_call_id,
        get_dialed_times,
    )

    sqli_payload = "deadbeef' OR '1'='1"
    captured_queries = []

    original_raw = Calls.raw

    def spy_raw(sql, *args):
        raw_obj = original_raw(sql, *args)
        captured_queries.append(raw_obj.querystring.compile_string())
        return raw_obj

    with (
        patch.object(Calls, "raw", side_effect=spy_raw),
        patch.object(Raw, "run", new_callable=AsyncMock) as mock_run,
    ):
        mock_run.return_value = [{"id": "call-uuid-999"}]
        call_id = await get_current_call_id("60", sqli_payload)
        assert call_id == "call-uuid-999"

        compiled_sql, bound_args = captured_queries[-1]
        assert sqli_payload not in compiled_sql
        assert "$1" in compiled_sql and "$2" in compiled_sql
        assert bound_args == [60, sqli_payload]

        # Empty result returns None
        mock_run.return_value = []
        assert await get_current_call_id(60, "abcd1234") is None

        # Dialed times happy path + parameterization check
        mock_run.return_value = [{"dialed_times": 3}]
        dialed = await get_dialed_times(120, sqli_payload)
        assert dialed == 3
        compiled_sql_2, bound_args_2 = captured_queries[-1]
        assert sqli_payload not in compiled_sql_2
        assert "$1" in compiled_sql_2 and "$2" in compiled_sql_2
        assert bound_args_2 == [120, sqli_payload]

        # Empty result returns None
        mock_run.return_value = []
        assert await get_dialed_times(120, "abcd1234") is None

        # Event loop RuntimeError propagates
        mock_run.side_effect = RuntimeError("RUNTIME_LOOP_IN_ERROR: closed")
        with pytest.raises(RuntimeError):
            await get_current_call_id(60, "abcd1234")
        with pytest.raises(RuntimeError):
            await get_dialed_times(60, "abcd1234")

        # Generic DB exception fails closed to None
        mock_run.side_effect = ValueError("transient db error")
        assert await get_current_call_id(60, "abcd1234") is None
        assert await get_dialed_times(60, "abcd1234") is None


@pytest.mark.asyncio
async def test_db_asterisk_recaller_select_backup_calls_parameterized():
    from piccolo.query.methods.raw import Raw
    from py_phone_caller_utils.py_phone_caller_db.db_asterisk_recaller import (
        Calls,
        select_backup_calls,
    )

    captured_queries = []
    original_raw = Calls.raw

    def spy_raw(sql, *args):
        raw_obj = original_raw(sql, *args)
        captured_queries.append(raw_obj.querystring.compile_string())
        return raw_obj

    sample_rows = [
        {
            "id": "uuid-1",
            "phone": "+393341234567",
            "message": "Node down",
            "call_backup_callee_number_calls": 1,
            "seconds_to_forget": 300,
        }
    ]
    with (
        patch.object(Calls, "raw", side_effect=spy_raw),
        patch.object(Raw, "run", new_callable=AsyncMock, return_value=sample_rows),
    ):
        rows = await select_backup_calls("3")
        assert rows == sample_rows
        compiled_sql, bound_args = captured_queries[-1]
        assert "$1" in compiled_sql
        assert bound_args == [3]

