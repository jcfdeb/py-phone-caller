import pytest
from unittest.mock import patch, MagicMock
from aiohttp import web

from src.caller_scheduler.caller_scheduler import schedule_this_call, init_app
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
        assert args[0] == ["00393349246425", "Test alert"]
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
    assert isinstance(app, web.Application)


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
