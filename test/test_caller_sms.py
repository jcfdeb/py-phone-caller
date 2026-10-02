import asyncio
import pytest
from unittest.mock import patch

from src.caller_sms.caller_sms import init_app
from src.caller_sms.constants import CALLER_SMS_APP_ROUTE


@pytest.fixture
async def cli(aiohttp_client):
    with patch("src.caller_sms.caller_sms._ensure_db_pool"):
        app = await init_app()
        return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_send_the_sms_success(cli):
    with (
        patch("src.caller_sms.caller_sms.CALLER_SMS_CARRIER", "twilio"),
        patch(
            "src.caller_sms.caller_sms.twilio_backend.sms_sender_async"
        ) as mock_sms_sender,
        patch(
            "src.caller_sms.caller_sms.insert_sms"
        ) as mock_insert_sms,
    ):
        future = asyncio.Future()
        future.set_result(None)
        mock_sms_sender.return_value = future

        resp = await cli.post(f"/{CALLER_SMS_APP_ROUTE}?message=test&phone=123")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == 200
        mock_sms_sender.assert_called_once()
        mock_insert_sms.assert_awaited_once_with(
            phone="123",
            message="test",
            carrier="twilio",
            status="sent",
            error="",
        )


@pytest.mark.asyncio
async def test_send_the_sms_on_premise_success(cli):
    with (
        patch("src.caller_sms.caller_sms.CALLER_SMS_CARRIER", "on_premise"),
        patch(
            "src.caller_sms.caller_sms.rust_on_premise.sms_sender_async"
        ) as mock_sms_sender,
        patch(
            "src.caller_sms.caller_sms.insert_sms"
        ) as mock_insert_sms,
    ):
        future = asyncio.Future()
        future.set_result(None)
        mock_sms_sender.return_value = future

        resp = await cli.post(f"/{CALLER_SMS_APP_ROUTE}?message=test&phone=123")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == 200
        mock_sms_sender.assert_called_once()
        mock_insert_sms.assert_awaited_once_with(
            phone="123",
            message="test",
            carrier="on_premise",
            status="sent",
            error="",
        )


@pytest.mark.asyncio
async def test_send_the_sms_failure_records_error(cli):
    with (
        patch("src.caller_sms.caller_sms.CALLER_SMS_CARRIER", "twilio"),
        patch(
            "src.caller_sms.caller_sms.twilio_backend.sms_sender_async"
        ) as mock_sms_sender,
        patch(
            "src.caller_sms.caller_sms.insert_sms"
        ) as mock_insert_sms,
    ):
        future = asyncio.Future()
        future.set_exception(RuntimeError("Twilio network error"))
        mock_sms_sender.return_value = future

        resp = await cli.post(f"/{CALLER_SMS_APP_ROUTE}?message=test&phone=123")
        assert resp.status == 500
        data = await resp.json()
        assert data["status"] == 500
        mock_insert_sms.assert_awaited_once_with(
            phone="123",
            message="test",
            carrier="twilio",
            status="failed",
            error="Twilio network error",
        )


@pytest.mark.asyncio
async def test_send_the_sms_unsupported_carrier(cli):
    with (
        patch("src.caller_sms.caller_sms.CALLER_SMS_CARRIER", "unsupported_carrier"),
        patch(
            "src.caller_sms.caller_sms.insert_sms"
        ) as mock_insert_sms,
    ):
        resp = await cli.post(f"/{CALLER_SMS_APP_ROUTE}?message=test&phone=123")
        assert resp.status == 500
        data = await resp.json()
        assert data["status"] == 500
        mock_insert_sms.assert_awaited_once_with(
            phone="123",
            message="test",
            carrier="unsupported_carrier",
            status="failed",
            error="Carrier 'unsupported_carrier' not supported.",
        )


@pytest.mark.asyncio
async def test_get_sms_records_endpoint(cli):
    with patch("src.caller_sms.caller_sms.select_sms") as mock_select_sms:
        import uuid
        test_id = uuid.uuid4()
        from datetime import datetime
        test_time = datetime(2026, 8, 20, 9, 30)
        mock_select_sms.return_value = [
            {
                "id": test_id,
                "phone": "+393349246425",
                "message": "Alert critical",
                "carrier": "on_premise",
                "status": "sent",
                "created_at": test_time,
                "error": "",
            }
        ]

        resp = await cli.get("/get_sms?limit=10&phone=%2B393349246425&status=sent")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == 200
        assert len(data["records"]) == 1
        assert data["records"][0]["phone"] == "+393349246425"
        assert data["records"][0]["id"] == str(test_id)
        assert data["records"][0]["status"] == "sent"
        mock_select_sms.assert_awaited_once_with(limit=10, phone="+393349246425", status="sent")


@pytest.mark.asyncio
async def test_send_the_sms_missing_params(cli):
    resp = await cli.post(f"/{CALLER_SMS_APP_ROUTE}")
    assert resp.status == 400


@pytest.mark.asyncio
async def test_rust_sms_enqueue_and_deduplication(tmp_path):
    try:
        from py_phone_caller_utils.sms import enqueue_sms
    except ImportError:
        pytest.skip("Rust engine not available")

    db_file = tmp_path / "sms_test.db"
    import sqlite3

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE sms_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, phone_number TEXT NOT NULL, message TEXT NOT NULL, status INTEGER DEFAULT 0, retries INTEGER DEFAULT 0, last_attempt_at DATETIME, last_error TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);"
    )
    conn.commit()
    conn.close()

    uri = f"sqlite://{db_file}"

    # 1. Enqueue fresh message
    res1 = await enqueue_sms(uri, "+393349246425", "alert 1")
    assert res1 == "QUEUED"

    # 2. Immediate duplicate while status=0 -> ignored
    res2 = await enqueue_sms(uri, "+393349246425", "alert 1")
    assert res2 == "DUPLICATE_IGNORED"

    # 3. Simulate message failure (status=3, retries=10)
    conn = sqlite3.connect(str(db_file))
    conn.execute("UPDATE sms_queue SET status = 3, retries = 10 WHERE id = 1")
    conn.commit()
    conn.close()

    # 4. Re-enqueueing same message after previous failure MUST queue a new item
    res3 = await enqueue_sms(uri, "+393349246425", "alert 1")
    assert res3 == "QUEUED"

    # 5. Simulate message delivery (status=2)
    conn = sqlite3.connect(str(db_file))
    conn.execute("UPDATE sms_queue SET status = 2 WHERE id = 2")
    conn.commit()
    conn.close()

    # 6. Re-enqueueing same message after delivery MUST queue a new item
    res4 = await enqueue_sms(uri, "+393349246425", "alert 1")
    assert res4 == "QUEUED"


@pytest.mark.asyncio
async def test_rust_sms_priority_over_failed_retry(tmp_path):
    try:
        from py_phone_caller_utils.sms import enqueue_sms
    except ImportError:
        pytest.skip("Rust engine not available")

    db_file = tmp_path / "sms_priority.db"
    import sqlite3

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE sms_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, phone_number TEXT NOT NULL, message TEXT NOT NULL, status INTEGER DEFAULT 0, retries INTEGER DEFAULT 0, last_attempt_at DATETIME, last_error TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);"
    )
    # Old failed message
    conn.execute(
        "INSERT INTO sms_queue (id, phone_number, message, status, retries, last_attempt_at, created_at) "
        "VALUES (1, '+3911111111', 'old failed', 3, 1, datetime('now', '-1 hour'), '2020-01-01 00:00:00');"
    )
    conn.commit()
    conn.close()

    uri = f"sqlite://{db_file}"
    res = await enqueue_sms(uri, "+3922222222", "new urgent message")
    assert res == "QUEUED"

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, phone_number, message FROM sms_queue "
        "WHERE status = 0 "
        "OR ("
        "    id IN ("
        "        SELECT id FROM sms_queue "
        "        WHERE status = 3 AND retries < 10 "
        "        ORDER BY id DESC "
        "        LIMIT 5"
        "    )"
        "    AND (last_attempt_at IS NULL OR last_attempt_at < datetime('now', '-5 minutes'))"
        ") "
        "ORDER BY status ASC, created_at ASC LIMIT 1"
    )
    row = cursor.fetchone()
    conn.close()
    assert row is not None
    assert row[0] == 2, f"Expected row id 2 (new pending) to be picked first, got {row}"


@pytest.mark.asyncio
async def test_db_sms_insert_and_select():
    from unittest.mock import AsyncMock, MagicMock
    from py_phone_caller_utils.py_phone_caller_db.db_sms import (
        insert_sms,
        insert_sms_sync,
        select_sms,
        select_sms_sync,
    )
    from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import (
        Sms,
    )

    with patch.object(Sms, "insert", new_callable=AsyncMock) as mock_insert:
        sms_id = await insert_sms(
            phone="+393349246425",
            message="Test message",
            carrier="on_premise",
            status="sent",
            error="",
        )
        assert sms_id is not None
        mock_insert.assert_awaited_once()

    with patch.object(Sms, "insert") as mock_insert_sync:
        mock_run_sync = MagicMock()
        mock_insert_sync.return_value.run_sync = mock_run_sync
        sms_id = insert_sms_sync(
            phone="+393349246425",
            message="Test message sync",
            carrier="twilio",
            status="queued",
        )
        assert sms_id is not None
        mock_run_sync.assert_called_once()

    class MockSelectQuery:
        def __init__(self, result):
            self._result = result

        def where(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def run_sync(self):
            return self._result

        def __await__(self):
            async def _coro():
                return self._result

            return _coro().__await__()

    with patch.object(Sms, "select") as mock_select:
        mock_select.return_value = MockSelectQuery(
            [{"phone": "+393349246425", "message": "Test"}]
        )

        res = await select_sms(limit=5, phone="+393349246425", status="sent")
        assert res == [{"phone": "+393349246425", "message": "Test"}]

    with patch.object(Sms, "select") as mock_select_sync:
        mock_select_sync.return_value = MockSelectQuery(
            [{"phone": "+393349246425", "message": "Sync test"}]
        )

        res_sync = select_sms_sync(limit=5, phone="+393349246425", status="sent")
        assert res_sync == [{"phone": "+393349246425", "message": "Sync test"}]


@pytest.mark.asyncio
async def test_rust_sms_utf8_message_handling(tmp_path):
    try:
        from py_phone_caller_utils.sms import enqueue_sms
    except ImportError:
        pytest.skip("Rust engine not available")

    db_file = tmp_path / "sms_utf8.db"
    import sqlite3

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        "CREATE TABLE sms_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, phone_number TEXT NOT NULL, message TEXT NOT NULL, status INTEGER DEFAULT 0, retries INTEGER DEFAULT 0, last_attempt_at DATETIME, last_error TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);"
    )
    conn.commit()
    conn.close()

    uri = f"sqlite://{db_file}"
    utf8_text = "Non funziona più il database, controllare il cluster TimescaleDB"
    res = await enqueue_sms(uri, "+393349246425", utf8_text)
    assert res == "QUEUED"

    conn = sqlite3.connect(str(db_file))
    cursor = conn.cursor()
    cursor.execute("SELECT phone_number, message FROM sms_queue WHERE id = 1")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "+393349246425"
    assert row[1] == utf8_text
    assert "più" in row[1]


@pytest.mark.asyncio
async def test_send_sms_on_premise_failure_sovereign_mode_no_fallback(cli):
    """
    Test that when on-premise GSM modem fails and sms_saas_fallback is False (default),
    it fails fast without calling Twilio.
    """
    with (
        patch("src.caller_sms.caller_sms.CALLER_SMS_CARRIER", "on_premise"),
        patch("src.caller_sms.caller_sms.SMS_SAAS_FALLBACK", False),
        patch("src.caller_sms.caller_sms.rust_on_premise.sms_sender_async") as mock_rust_sender,
        patch("src.caller_sms.caller_sms.twilio_backend.sms_sender_async") as mock_twilio_sender,
        patch("src.caller_sms.caller_sms.insert_sms") as mock_insert_sms,
    ):
        future_fail = asyncio.Future()
        future_fail.set_exception(RuntimeError("Modem /dev/ttyUSB2 disconnected"))
        mock_rust_sender.return_value = future_fail

        resp = await cli.post(f"/{CALLER_SMS_APP_ROUTE}?message=Sovereign+Alert&phone=00393349246425")
        assert resp.status == 500
        data = await resp.json()
        assert data["status"] == 500
        assert "disconnected" in data.get("error", "")

        mock_rust_sender.assert_called_once()
        mock_twilio_sender.assert_not_called()
        mock_insert_sms.assert_awaited_once_with(
            phone="00393349246425",
            message="Sovereign Alert",
            carrier="on_premise",
            status="failed",
            error="Modem /dev/ttyUSB2 disconnected",
        )


@pytest.mark.asyncio
async def test_send_sms_on_premise_failure_with_saas_fallback_success(cli):
    """
    Test that when on-premise GSM modem fails and sms_saas_fallback is True with valid Twilio creds,
    it falls back to Twilio successfully.
    """
    with (
        patch("src.caller_sms.caller_sms.CALLER_SMS_CARRIER", "on_premise"),
        patch("src.caller_sms.caller_sms.SMS_SAAS_FALLBACK", True),
        patch("src.caller_sms.caller_sms.TWILIO_ACCOUNT_SID", "ACtest123"),
        patch("src.caller_sms.caller_sms.TWILIO_AUTH_TOKEN", "secret123"),
        patch("src.caller_sms.caller_sms.TWILIO_SMS_FROM", "+1234567890"),
        patch("src.caller_sms.caller_sms.rust_on_premise.sms_sender_async") as mock_rust_sender,
        patch("src.caller_sms.caller_sms.twilio_backend.sms_sender_async") as mock_twilio_sender,
        patch("src.caller_sms.caller_sms.insert_sms") as mock_insert_sms,
    ):
        future_rust_fail = asyncio.Future()
        future_rust_fail.set_exception(RuntimeError("Modem buffer full"))
        mock_rust_sender.return_value = future_rust_fail

        future_twilio_ok = asyncio.Future()
        future_twilio_ok.set_result(None)
        mock_twilio_sender.return_value = future_twilio_ok

        resp = await cli.post(f"/{CALLER_SMS_APP_ROUTE}?message=Fallback+Alert&phone=00393349246425")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == 200

        mock_rust_sender.assert_called_once()
        mock_twilio_sender.assert_called_once_with("Fallback Alert", "00393349246425")
        mock_insert_sms.assert_awaited_once_with(
            phone="00393349246425",
            message="Fallback Alert",
            carrier="twilio_fallback",
            status="sent",
            error="",
        )


@pytest.mark.asyncio
async def test_inbound_sms_acknowledgment(cli):
    """
    Test that POST /sms/inbound with ACK/OK token updates active call record acknowledge_at.
    """
    from py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables import Calls

    fake_active_call = {
        "id": "11111111-2222-3333-4444-555555555555",
        "phone": "00393349246425",
        "asterisk_chan": "chan-test-456",
        "cycle_done": False,
    }

    with (
        patch.object(Calls, "select") as mock_select,
        patch.object(Calls, "update") as mock_update,
        patch("src.caller_sms.caller_sms.insert_sms") as mock_insert_sms,
    ):
        # Mock chaining for select().where().run()
        mock_run = asyncio.Future()
        mock_run.set_result([fake_active_call])
        mock_where = patch.object(mock_select.return_value, "where").start()
        mock_where.return_value.run = lambda: mock_run

        mock_update_run = asyncio.Future()
        mock_update_run.set_result(None)
        mock_update_where = patch.object(mock_update.return_value, "where").start()
        mock_update_where.return_value.run = lambda: mock_update_run

        resp = await cli.post(
            "/sms/inbound",
            json={"From": "+393349246425", "Body": "ACK incident confirmed"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == 200
        assert data["acknowledged"] is True
        assert data["matched_calls"] == 1
        mock_insert_sms.assert_awaited_once()
