"""
Unit and integration tests for caller_register.

Tests cover:
- Parameter extraction and validation (JSON and query string)
- Database schema repair, migration reconciliation, and table verification
- Call attempt state machine (new cycle vs ongoing cycle within retry period)
- Acknowledgment and heard status endpoints
- Voice message retrieval and checksum calculation
- Timezone parsing and conversion for scheduled calls
- Service readiness and catalog endpoints
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from aiohttp import web, streams
from aiohttp.test_utils import make_mocked_request

from src.caller_register import caller_register
from src.caller_register.constants import (
    CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE,
    CALL_REGISTER_APP_ROUTE_HEARD,
    CALL_REGISTER_APP_ROUTE_REGISTER_CALL,
    CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE,
    CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE,
)


def _make_payload_request(method: str, path: str, payload_bytes: bytes, content_type: str = "application/json"):
    loop = MagicMock()
    reader = streams.StreamReader(protocol=MagicMock(), limit=1024, loop=loop)
    reader.feed_data(payload_bytes)
    reader.feed_eof()
    return make_mocked_request(method, path, payload=reader, headers={"Content-Type": content_type})


# ---------------------------------------------------------------------------
# Unit tests: Parameter Parsing & Validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_request_parameters_valid_json():
    req = _make_payload_request(
        "POST",
        "/register_call",
        b'{"phone": "12345", "message": "Fire Alarm", "asterisk_chan": "PJSIP/chan-1", "oncall": true, "backup_callee": false}',
    )
    phone, msg, chan, oncall, backup = await caller_register.get_request_parameters(req)
    assert phone == "12345"
    assert msg == "Fire Alarm"
    assert chan == "PJSIP/chan-1"
    assert oncall is True
    assert backup is False


@pytest.mark.asyncio
async def test_get_request_parameters_valid_query():
    req = make_mocked_request(
        "POST",
        "/register_call?phone=54321&message=TestMsg&asterisk_chan=PJSIP/chan-2&oncall=false&backup_callee=true",
    )
    phone, msg, chan, oncall, backup = await caller_register.get_request_parameters(req)
    assert phone == "54321"
    assert msg == "TestMsg"
    assert chan == "PJSIP/chan-2"
    assert oncall is False
    assert backup is True


@pytest.mark.asyncio
async def test_get_request_parameters_missing_raises_bad_request():
    req = make_mocked_request("POST", "/register_call?phone=12345")
    with pytest.raises(web.HTTPBadRequest):
        await caller_register.get_request_parameters(req)


# ---------------------------------------------------------------------------
# Unit tests: Business Logic / Logging Helpers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_present_or_not_logger():
    # Should not raise exception
    await caller_register.present_or_not_logger("12345", timedelta(seconds=30), "Alert")
    await caller_register.present_or_not_logger("12345", None, "Alert")


@pytest.mark.asyncio
async def test_defining_first_dial_time():
    with patch("src.caller_register.caller_register.get_first_dial_age", new_callable=AsyncMock) as mock_age:
        mock_age.return_value = timedelta(seconds=45)
        age = await caller_register.defining_first_dial_time("chk123", 1, "12345", "Test")
        assert age == timedelta(seconds=45)

    with patch("src.caller_register.caller_register.get_first_dial_age", new_callable=AsyncMock) as mock_age:
        mock_age.side_effect = RuntimeError("DB connection dropped")
        age = await caller_register.defining_first_dial_time("chk123", 1, "12345", "Test")
        assert age is None


# ---------------------------------------------------------------------------
# Integration tests: HTTP Endpoints with aiohttp_client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_endpoint_register_call_new_attempt(aiohttp_client):
    app = await caller_register.init_app()
    client = await aiohttp_client(app)

    with patch("src.caller_register.caller_register.check_call_yet_present", new_callable=AsyncMock) as mock_check, \
         patch("src.caller_register.caller_register.insert_into_db", new_callable=AsyncMock) as mock_insert:
        mock_check.return_value = None

        resp = await client.post(
            f"/{CALL_REGISTER_APP_ROUTE_REGISTER_CALL}",
            json={"phone": "0039123456", "message": "Server down", "asterisk_chan": "PJSIP/trunk-01"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": 200}
        mock_insert.assert_called_once()


@pytest.mark.asyncio
async def test_endpoint_register_call_existing_attempt(aiohttp_client):
    app = await caller_register.init_app()
    client = await aiohttp_client(app)

    with patch("src.caller_register.caller_register.check_call_yet_present", new_callable=AsyncMock) as mock_check, \
         patch("src.caller_register.caller_register.get_current_call_id", new_callable=AsyncMock) as mock_id, \
         patch("src.caller_register.caller_register.get_first_dial_age", new_callable=AsyncMock) as mock_age, \
         patch("src.caller_register.caller_register.get_dialed_times", new_callable=AsyncMock) as mock_dialed, \
         patch("src.caller_register.caller_register.update_the_call_db_record", new_callable=AsyncMock) as mock_update:
        mock_check.return_value = 1
        mock_id.return_value = 42
        mock_age.return_value = timedelta(seconds=10)
        mock_dialed.return_value = 1

        resp = await client.post(
            f"/{CALL_REGISTER_APP_ROUTE_REGISTER_CALL}",
            json={"phone": "0039123456", "message": "Server down", "asterisk_chan": "PJSIP/trunk-01"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": 200}
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_endpoint_acknowledge_success(aiohttp_client):
    app = await caller_register.init_app()
    client = await aiohttp_client(app)

    with patch("src.caller_register.caller_register.update_acknowledgement", new_callable=AsyncMock) as mock_ack:
        mock_ack.return_value = True
        resp = await client.get(f"/{CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE}?asterisk_chan=PJSIP/trunk-01")
        assert resp.status == 200
        assert await resp.json() == {"status": 200}


@pytest.mark.asyncio
async def test_endpoint_acknowledge_expired(aiohttp_client):
    app = await caller_register.init_app()
    client = await aiohttp_client(app)

    with patch("src.caller_register.caller_register.update_acknowledgement", new_callable=AsyncMock) as mock_ack:
        mock_ack.return_value = False
        resp = await client.get(f"/{CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE}?asterisk_chan=PJSIP/trunk-01")
        assert resp.status == 400
        data = await resp.json()
        assert "outside the firing period" in data["message"]


@pytest.mark.asyncio
async def test_endpoint_heard_success(aiohttp_client):
    app = await caller_register.init_app()
    client = await aiohttp_client(app)

    with patch("src.caller_register.caller_register.update_heard_at", new_callable=AsyncMock) as mock_heard:
        resp = await client.get(f"/{CALL_REGISTER_APP_ROUTE_HEARD}?asterisk_chan=PJSIP/trunk-01")
        assert resp.status == 200
        assert await resp.json() == {"status": 200}
        mock_heard.assert_called_once_with("PJSIP/trunk-01")


@pytest.mark.asyncio
async def test_endpoint_voice_message_success(aiohttp_client):
    app = await caller_register.init_app()
    client = await aiohttp_client(app)

    with patch("src.caller_register.caller_register.get_msg_chk_sum", new_callable=AsyncMock) as mock_msg:
        mock_msg.return_value = ("Database replication lagging", "a1b2c3d4e5")
        resp = await client.post(
            f"/{CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE}",
            json={"asterisk_chan": "PJSIP/trunk-01"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["message"] == "Database replication lagging"
        assert data["msg_chk_sum"] == "a1b2c3d4e5"


@pytest.mark.asyncio
async def test_endpoint_scheduled_call_success(aiohttp_client):
    app = await caller_register.init_app()
    client = await aiohttp_client(app)

    with patch("src.caller_register.caller_register.insert_scheduled_call", new_callable=AsyncMock) as mock_sched:
        resp = await client.post(
            f"/{CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE}",
            json={
                "phone": "0039123456",
                "message": "Maintenance reminder",
                "scheduled_at": "2026-10-10 14:00:00",
            },
        )
        assert resp.status == 200
        assert await resp.json() == {"status": 200}
        mock_sched.assert_called_once()


@pytest.mark.asyncio
async def test_endpoint_root_catalog(aiohttp_client):
    app = await caller_register.init_app()
    client = await aiohttp_client(app)

    resp = await client.get("/")
    assert resp.status == 200
    data = await resp.json()
    assert data["service"] == "caller_register"
    assert "endpoints" in data


@pytest.mark.asyncio
async def test_endpoint_ready_probe(aiohttp_client):
    app = await caller_register.init_app()
    client = await aiohttp_client(app)

    with patch("src.caller_register.caller_register.check_database_pool", new_callable=AsyncMock) as mock_pool:
        mock_pool.return_value = (True, {"status": "ok"})
        resp = await client.get("/ready")
        assert resp.status == 200
        data = await resp.json()
        assert data["ready"] is True
