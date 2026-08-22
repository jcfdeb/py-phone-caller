import pytest
from unittest.mock import patch, AsyncMock
from base64 import b64encode
from aiohttp import web, ClientSession
from aiohttp_basicauth_middleware import basic_auth_middleware

from src.asterisk_caller import asterisk_caller
from src.asterisk_caller.constants import (
    ASTERISK_USER,
    ASTERISK_PASS,
    ASTERISK_ARI_CHANNELS,
)

from src.asterisk_caller.asterisk_caller import gen_headers
from src.asterisk_caller.asterisk_caller import send_ari_continue
from src.asterisk_caller.asterisk_caller import OnCallPhoneUnavailable
from src.asterisk_caller.asterisk_caller import _resolve_oncall_phone

ASTERISK_CHAN = "1646889318"


@pytest.mark.asyncio
async def test_gen_headers():
    actual = await gen_headers("abc")
    expected = {"Authorization": "Basic YWJj"}
    assert actual == expected


@pytest.mark.asyncio
async def handler_send_ari_continue(request):
    return web.Response(body=b"body text", status=204)


async def test_send_ari_continue(aiohttp_server):
    # Server Part with HTTP Basic Authentication
    app = web.Application()
    app.router.add_route(
        "POST",
        f"/{ASTERISK_ARI_CHANNELS}/{ASTERISK_CHAN}/continue",
        handler_send_ari_continue,
    )
    app.middlewares.append(
        basic_auth_middleware(
            ("/",),
            {ASTERISK_USER: ASTERISK_PASS},
        )
    )
    server = await aiohttp_server(app)

    # Client Part
    url = f"http://127.0.0.1:{server.port}/{ASTERISK_ARI_CHANNELS}/{ASTERISK_CHAN}/continue"
    session = ClientSession()
    auth_string = f"{ASTERISK_USER}:{ASTERISK_PASS}"
    headers = {
        "Authorization": f"Basic {str(b64encode(bytearray(auth_string, 'utf8')), 'utf-8')}"
    }

    response = await send_ari_continue(headers, ASTERISK_ARI_CHANNELS, url)
    await session.close()
    assert response == 204


async def handler_empty_oncall_address_book(request):
    return web.json_response({"error": "No on-call contact found"}, status=404)


async def handler_empty_oncall_address_book_text(request):
    return web.Response(text="No on-call contact found", status=404)


async def test_resolve_oncall_phone_empty_address_book(aiohttp_server, monkeypatch):
    app = web.Application()
    app.router.add_route("GET", "/on_call_contact", handler_empty_oncall_address_book)
    server = await aiohttp_server(app)

    monkeypatch.setattr(
        "src.asterisk_caller.asterisk_caller.CALLER_ADDRESS_BOOK_URL",
        f"http://127.0.0.1:{server.port}",
    )
    monkeypatch.setattr(
        "src.asterisk_caller.asterisk_caller.CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT",
        "on_call_contact",
    )

    with pytest.raises(OnCallPhoneUnavailable) as exc_info:
        await _resolve_oncall_phone("oncall")

    assert "No on-call contact is available" in str(exc_info.value)


async def test_resolve_oncall_phone_empty_address_book_non_json(
    aiohttp_server, monkeypatch
):
    app = web.Application()
    app.router.add_route(
        "GET", "/on_call_contact", handler_empty_oncall_address_book_text
    )
    server = await aiohttp_server(app)

    monkeypatch.setattr(
        "src.asterisk_caller.asterisk_caller.CALLER_ADDRESS_BOOK_URL",
        f"http://127.0.0.1:{server.port}",
    )
    monkeypatch.setattr(
        "src.asterisk_caller.asterisk_caller.CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT",
        "on_call_contact",
    )

    with pytest.raises(OnCallPhoneUnavailable) as exc_info:
        await _resolve_oncall_phone("oncall")

    assert "No on-call contact found" in str(exc_info.value)


def test_manage_call_queue_logs_empty_oncall_as_warning(monkeypatch, caplog):
    class FakeQueue:
        def __init__(self):
            self.items = [
                {"phone": "oncall", "message": "test alert"},
                None,
            ]

        def get(self):
            return self.items.pop(0)

    async def fake_asterisk_call_start(phone, message):
        raise OnCallPhoneUnavailable("No on-call contact is available in the address book.")

    monkeypatch.setattr("src.asterisk_caller.asterisk_caller.CALL_QUEUE", FakeQueue())
    monkeypatch.setattr("src.asterisk_caller.asterisk_caller.WAIT_FOR_CALL_CYCLE", 0)
    monkeypatch.setattr(
        "src.asterisk_caller.asterisk_caller.asterisk_call_start",
        fake_asterisk_call_start,
    )

    with caplog.at_level("WARNING"):
        asterisk_caller.manage_call_queue()

    assert "Call queue item skipped because the on-call phone is unavailable" in caplog.text
    assert "Unable to process call queue payload" not in caplog.text


@pytest.mark.asyncio
async def test_initiate_asterisk_call(aiohttp_client):
    app = web.Application()

    registered_params = {}

    async def mock_ari(request):
        return web.json_response({"id": "chan-test-123"}, status=200)

    async def mock_register_call(request):
        registered_params.update(request.rel_url.query)
        return web.json_response({"status": 200})

    app.router.add_route("POST", "/ari/channels", mock_ari)
    app.router.add_route("POST", "/register_call", mock_register_call)
    client = await aiohttp_client(app)

    base_url = str(client.make_url("")).rstrip("/")

    with patch(
        "src.asterisk_caller.asterisk_caller.CALL_REGISTER_URL",
        base_url,
    ), patch(
        "src.asterisk_caller.asterisk_caller.CALL_REGISTER_APP_ROUTE_REGISTER_CALL",
        "register_call",
    ):
        from src.asterisk_caller.asterisk_caller import initiate_asterisk_call
        resp = await initiate_asterisk_call(
            asterisk_call_init=f"{base_url}/ari/channels",
            phone="00393349246425",
            resolved_phone="00393349246425",
            message="Test message",
            headers={"Authorization": "Basic xxx"},
            backup_callee="false",
        )
        assert resp.status == 200
        assert registered_params.get("phone") == "00393349246425"
        assert registered_params.get("message") == "Test message"
        assert registered_params.get("asterisk_chan") == "chan-test-123"


@pytest.mark.asyncio
async def test_asterisk_recaller_recall_post_integration(aiohttp_client):
    app = web.Application()
    received_params = {}

    async def mock_place_call(request):
        received_params.update(request.rel_url.query)
        return web.json_response({"status": 200})

    app.router.add_route("POST", "/place_call", mock_place_call)
    client = await aiohttp_client(app)

    with patch(
        "src.asterisk_recaller.asterisk_recaller.ASTERISK_CALL_URL",
        str(client.make_url("")).rstrip("/"),
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.ASTERISK_CALL_APP_ROUTE_PLACE_CALL",
        "place_call",
    ):
        from src.asterisk_recaller.asterisk_recaller import recall_post
        await recall_post(
            phone="00393349246425",
            message="Recall alert",
            backup_callee="false",
        )
        assert received_params.get("phone") == "00393349246425"
        assert received_params.get("message") == "Recall alert"
        assert received_params.get("backup_callee") == "false"
