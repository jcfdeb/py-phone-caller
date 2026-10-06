from datetime import datetime, timezone
import pytest
from unittest.mock import patch, MagicMock
from aiohttp import web

from src.caller_scheduler import (
    CallSchedulerService,
    CeleryTaskDispatcher,
    InvalidScheduleTimeError,
    MissingScheduleParameterError,
    PriorityQueue,
    ScheduleCallRequest,
    ScheduleCallResponse,
    TaskEnqueueError,
    TimezoneConverter,
    init_app,
    schedule_this_call,
)
from py_phone_caller_utils.tasks.celery_task import do_this_call
from py_phone_caller_utils.tasks.post_to_caller_register import (
    insert_the_scheduled_call,
)
from py_phone_caller_utils.tasks.post_to_caller_scheduler import (
    enqueue_the_call,
)


@pytest.mark.asyncio
async def test_schedule_this_call_missing_params(aiohttp_client):
    app = web.Application()
    app.router.add_route("POST", "/schedule_call", schedule_this_call)
    client = await aiohttp_client(app)

    # Missing all parameters
    resp = await client.post("/schedule_call")
    assert resp.status == 400

    # Missing scheduled_at
    resp = await client.post("/schedule_call?phone=123&message=test")
    assert resp.status == 400


@pytest.mark.asyncio
async def test_schedule_this_call_invalid_date(aiohttp_client):
    app = web.Application()
    app.router.add_route("POST", "/schedule_call", schedule_this_call)
    client = await aiohttp_client(app)

    resp = await client.post(
        "/schedule_call?phone=123&message=test&scheduled_at=not-a-valid-date"
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == 400
    assert "message" in data


@pytest.mark.asyncio
async def test_schedule_this_call_success(aiohttp_client):
    app = web.Application()
    app.router.add_route("POST", "/schedule_call", schedule_this_call)
    client = await aiohttp_client(app)

    with patch.object(do_this_call, "apply_async") as mock_apply:
        resp = await client.post(
            "/schedule_call?phone=00393349246425&message=Test+alert&scheduled_at=2026-08-25+14:30"
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == 200
        mock_apply.assert_called_once()
        args, kwargs = mock_apply.call_args
        call_args = args[0] if args else kwargs.get("args")
        assert call_args == ["00393349246425", "Test alert"]
        assert kwargs["eta"] is not None


@pytest.mark.asyncio
async def test_schedule_this_call_celery_error(aiohttp_client):
    app = web.Application()
    app.router.add_route("POST", "/schedule_call", schedule_this_call)
    client = await aiohttp_client(app)

    with patch.object(
        do_this_call, "apply_async", side_effect=Exception("Redis connection error")
    ):
        resp = await client.post(
            "/schedule_call?phone=00393349246425&message=Test+alert&scheduled_at=2026-08-25+14:30"
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == 500
        assert "Redis connection error" in data["message"]


@pytest.mark.asyncio
async def test_caller_scheduler_init_app():
    app = await init_app()
    assert app is not None and hasattr(app, 'router')


def test_do_this_call_task():
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        status = do_this_call("00393349246425", "Scheduled emergency alert")
        assert status == 200
        mock_post.assert_called_once()


def test_insert_the_scheduled_call_helper():
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        status = insert_the_scheduled_call(
            "00393349246425", "Scheduled emergency alert", "2026-08-25 14:30"
        )
        assert status == 200
        mock_post.assert_called_once()


def test_enqueue_the_call_helper():
    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        status = enqueue_the_call(
            "00393349246425", "Scheduled emergency alert", "2026-08-25 14:30"
        )
        assert status == 200
        mock_post.assert_called_once()


def test_periodic_recall_task_locking():
    from py_phone_caller_utils.tasks.celery_task import periodic_recall_task
    with patch("redis.from_url") as mock_redis_from_url:
        mock_r = MagicMock()
        mock_redis_from_url.return_value = mock_r
        # Test case 1: Lock already held by another worker
        mock_r.set.return_value = False
        res = periodic_recall_task()
        assert res == "skipped_locked"

        # Test case 2: Lock acquired
        mock_r.set.return_value = True
        with patch("asterisk_recaller.asterisk_recaller.run_single_recall_cycle", return_value=3):
            res2 = periodic_recall_task()
            assert res2 == "processed_3"


def test_record_dead_letter_task():
    from py_phone_caller_utils.tasks.celery_task import record_dead_letter
    with patch("py_phone_caller_utils.py_phone_caller_db.piccolo_conf.DB.pool", new=MagicMock()):
        with patch("py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables.DeadLetterQueue.insert") as mock_insert:
            record_dead_letter(
                task_id="test-task-123",
                task_name="do_this_call",
                queue="telephony.dlq",
                payload={"phone": "0039123456789", "message": "Poison pill"},
                exc_str="HTTP 500 Asterisk Down",
                tb_str="Traceback..."
            )
            mock_insert.assert_called_once()


def test_schemas_schedule_call_request():
    req = ScheduleCallRequest.from_dict({
        "phone": " 0039123456789 ",
        "message": " Hello World ",
        "scheduled_at": " 2026-10-01 10:00:00 ",
        "priority": "9",
        "lang": "en",
    })
    assert req.phone == "0039123456789"
    assert req.message == "Hello World"
    assert req.scheduled_at == "2026-10-01 10:00:00"
    assert req.priority == 9
    assert req.lang == "en"

    with pytest.raises(MissingScheduleParameterError):
        ScheduleCallRequest.from_dict({"phone": "123"})


def test_priority_queue_mapping():
    assert PriorityQueue.from_priority(9) == PriorityQueue.P0
    assert PriorityQueue.from_priority(8) == PriorityQueue.P0
    assert PriorityQueue.from_priority(7) == PriorityQueue.P2
    assert PriorityQueue.from_priority(0) == PriorityQueue.P2


def test_timezone_converter():
    tz_conv = TimezoneConverter("UTC")
    utc_dt = tz_conv.to_utc("2026-10-01 12:00:00")
    assert utc_dt.hour == 12
    assert utc_dt.tzinfo is not None

    with pytest.raises(InvalidScheduleTimeError):
        tz_conv.to_utc("not-a-valid-time-string")


def test_celery_task_dispatcher():
    mock_task = MagicMock()
    dispatcher = CeleryTaskDispatcher(task_target=mock_task)
    eta = datetime.now(timezone.utc)
    dispatcher.dispatch("123", "msg", eta, 5, "telephony.p2", lang="es")
    mock_task.apply_async.assert_called_once_with(
        ["123", "msg"],
        priority=5,
        queue="telephony.p2",
        eta=eta,
        kwargs={"lang": "es"},
    )

    mock_task.apply_async.side_effect = RuntimeError("Broker down")
    with pytest.raises(TaskEnqueueError):
        dispatcher.dispatch("123", "msg", eta, 5, "telephony.p2")


def test_call_scheduler_service():
    mock_disp = MagicMock()
    service = CallSchedulerService(dispatcher=mock_disp, tz_converter=TimezoneConverter("UTC"))
    req = ScheduleCallRequest(
        phone="0039123",
        message="Alert",
        scheduled_at="2026-10-01 15:00:00",
        priority=8,
    )
    res = service.schedule(req)
    assert res.status == 200
    mock_disp.dispatch.assert_called_once()
    assert mock_disp.dispatch.call_args.kwargs["queue"] == "telephony.p0"
