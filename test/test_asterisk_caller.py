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
from src.asterisk_caller.asterisk_caller import _format_phone
from src.asterisk_caller.asterisk_caller import get_asterisk_query_string

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


@pytest.mark.asyncio
async def test_asterisk_caller_circuit_breaker_tripping(aiohttp_client, monkeypatch):
    """
    Test that ari_circuit_breaker in asterisk_caller trips to OPEN after 3 consecutive failures
    and returns HTTP 503 fast.
    """
    from src.asterisk_caller.asterisk_caller import init_app, ari_circuit_breaker
    from aiobreaker.state import CircuitBreakerState

    ari_circuit_breaker.close()

    # Create dummy server that simulates 500 error from Asterisk ARI
    app = web.Application()
    async def ari_failure_handler(request):
        return web.Response(status=500, text="Internal Server Error")

    app.router.add_route("POST", "/ari/channels", ari_failure_handler)
    mock_ari_server = await aiohttp_client(app)

    monkeypatch.setattr(
        "src.asterisk_caller.asterisk_caller.ASTERISK_URL",
        str(mock_ari_server.make_url("")).rstrip("/"),
    )
    monkeypatch.setattr(
        "src.asterisk_caller.asterisk_caller.ASTERISK_ARI_CHANNELS",
        "ari/channels",
    )

    caller_app = await init_app()
    caller_client = await aiohttp_client(caller_app)

    # Trigger failures to trip the circuit breaker (fail_max = 3)
    for _ in range(3):
        resp = await caller_client.post(
            "/place_call",
            json={"phone": "00393349246425", "message": "Test Failure"},
        )
        assert resp.status in (500, 503)

    assert ari_circuit_breaker.current_state == CircuitBreakerState.OPEN

    # 4th call should fail immediately with 503 from open circuit breaker
    resp4 = await caller_client.post(
        "/place_call",
        json={"phone": "00393349246425", "message": "Test Circuit Open"},
    )
    assert resp4.status == 503
    data = await resp4.json()
    assert "circuit breaker open" in data.get("error", "").lower()

    # Reset breaker to closed for subsequent tests
    ari_circuit_breaker.close()


@pytest.mark.asyncio
async def test_asterisk_caller_ready_probe_with_trunk(aiohttp_client, monkeypatch):
    """
    Test that /ready evaluates Asterisk ARI reachability and PJSIP trunk verification.
    """
    from src.asterisk_caller.asterisk_caller import init_app, ari_circuit_breaker

    ari_circuit_breaker.close()

    app = web.Application()
    async def ari_info_handler(request):
        return web.json_response({"system": {"version": "18.10"}}, status=200)

    async def ari_trunk_handler(request):
        return web.json_response({"technology": "PJSIP", "resource": "py-phone-caller", "state": "online"}, status=200)

    app.router.add_route("GET", "/ari/asterisk/info", ari_info_handler)
    app.router.add_route("GET", "/ari/endpoints/PJSIP/py-phone-caller", ari_trunk_handler)
    mock_ari_server = await aiohttp_client(app)

    monkeypatch.setattr(
        "src.asterisk_caller.asterisk_caller.ASTERISK_URL",
        str(mock_ari_server.make_url("")).rstrip("/"),
    )
    monkeypatch.setattr(
        "src.asterisk_caller.asterisk_caller.ASTERISK_CHAN_TYPE",
        "PJSIP/py-phone-caller",
    )

    caller_app = await init_app()
    caller_client = await aiohttp_client(caller_app)

    resp = await caller_client.get("/ready")
    assert resp.status == 200
    data = await resp.json()
    assert data["ready"] is True
    assert "asterisk_ari" in data["checks"]
    assert "pjsip_trunk" in data["checks"]
    assert data["checks"]["pjsip_trunk"]["ready"] is True


# ---------------------------------------------------------------------------
# Extra behavioral lock-in tests
# ---------------------------------------------------------------------------

def test_format_phone():
    assert _format_phone("+39123456789") == "0039123456789"
    assert _format_phone("0039123456789") == "0039123456789"
    assert _format_phone("12345") == "12345"


@pytest.mark.asyncio
async def test_get_asterisk_query_string():
    qs1 = await get_asterisk_query_string("PJSIP/provider-trunk", "+39123456")
    assert "endpoint=PJSIP/0039123456@provider-trunk" in qs1

    qs2 = await get_asterisk_query_string("SIP/{phone}@custom-trunk", "+39987654")
    assert "endpoint=SIP/0039987654@custom-trunk" in qs2

    qs3 = await get_asterisk_query_string("Local", "100")
    assert "endpoint=Local/100" in qs3


@pytest.mark.asyncio
async def test_endpoint_call_to_queue(aiohttp_client):
    from src.asterisk_caller.asterisk_caller import init_app
    app = await init_app()
    client = await aiohttp_client(app)

    resp = await client.post("/call_to_queue", json={"phone": "0039123456", "message": "Queue alert"})
    assert resp.status == 200
    assert await resp.json() == {"status": 200}

    # Should have queued item in asterisk_caller.CALL_QUEUE
    item = asterisk_caller.CALL_QUEUE.get(timeout=2.0)
    assert item["phone"] == "0039123456"
    assert item["message"] == "Queue alert"


@pytest.mark.asyncio
async def test_endpoint_place_call_missing_params(aiohttp_client):
    from src.asterisk_caller.asterisk_caller import init_app
    app = await init_app()
    client = await aiohttp_client(app)

    resp = await client.post("/place_call", json={"phone": "12345"})
    assert resp.status == 400


@pytest.mark.asyncio
async def test_endpoint_asterisk_play_success(aiohttp_client):
    from src.asterisk_caller.asterisk_caller import init_app
    app = await init_app()
    client = await aiohttp_client(app)

    with patch("src.asterisk_caller.asterisk_caller.ClientSession") as mock_session_cls, \
         patch("src.asterisk_caller.asterisk_caller.send_ari_continue", new_callable=AsyncMock) as mock_cont:
        mock_resp = AsyncMock()
        mock_resp.status = 201
        mock_session = AsyncMock()
        mock_session.post.return_value = mock_resp
        mock_session.__aenter__.return_value = mock_session
        mock_session_cls.return_value = mock_session

        resp = await client.post(
            "/play",
            json={"asterisk_chan": "PJSIP/chan-01", "msg_chk_sum": "hash123", "lang": "it"},
        )
        assert resp.status == 200
        assert await resp.json() == {"status": 201}
        mock_cont.assert_called_once()
