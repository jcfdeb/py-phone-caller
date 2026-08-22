import pytest
from aiohttp import web
from flask import Flask

from py_phone_caller_utils.telemetry import (
    instrument_aiohttp_app,
    instrument_flask_app,
)
from src.asterisk_caller.asterisk_caller import init_app as init_asterisk_caller
from src.caller_address_book.caller_address_book import (
    init_app as init_caller_address_book,
)
from src.caller_prometheus_webhook.caller_prometheus_webhook import (
    init_app as init_caller_prometheus_webhook,
)
from src.caller_register.caller_register import (
    init_app as init_caller_register,
)
from src.caller_scheduler.caller_scheduler import (
    init_app as init_caller_scheduler,
)
from src.caller_sms.caller_sms import init_app as init_caller_sms
from src.generate_audio.generate_audio import init_app as init_generate_audio
from src.py_phone_caller_ui.app import app as flask_ui_app


@pytest.mark.asyncio
async def test_instrument_aiohttp_app_health_and_metrics(aiohttp_client):
    app = web.Application()
    instrument_aiohttp_app(app, "test_service")
    client = await aiohttp_client(app)

    for endpoint in ["/health", "/healthz", "/live"]:
        resp = await client.get(endpoint)
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "test_service"
        assert data["version"] == "1.0.0"

    resp_metrics = await client.get("/metrics")
    assert resp_metrics.status == 200
    metrics_text = await resp_metrics.text()
    assert isinstance(metrics_text, str)


def test_instrument_flask_app_health_and_metrics():
    test_flask_app = Flask(__name__)
    instrument_flask_app(test_flask_app, "test_flask_service")
    test_client = test_flask_app.test_client()

    for endpoint in ["/health", "/healthz", "/live"]:
        resp = test_client.get(endpoint)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert data["service"] == "test_flask_service"
        assert data["version"] == "1.0.0"

    resp_metrics = test_client.get("/metrics")
    assert resp_metrics.status_code == 200


@pytest.mark.asyncio
async def test_services_expose_health_endpoints(aiohttp_client):
    # Test asterisk_caller app health
    app_ac = await init_asterisk_caller()
    client_ac = await aiohttp_client(app_ac)
    resp = await client_ac.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["service"] == "asterisk_caller"

    # Test caller_prometheus_webhook app health
    app_pw = await init_caller_prometheus_webhook()
    client_pw = await aiohttp_client(app_pw)
    resp = await client_pw.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["service"] == "caller_prometheus_webhook"

    # Test caller_scheduler app health
    app_cs = await init_caller_scheduler()
    client_cs = await aiohttp_client(app_cs)
    resp = await client_cs.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["service"] == "caller_scheduler"

    # Test generate_audio app health
    app_ga = await init_generate_audio()
    client_ga = await aiohttp_client(app_ga)
    resp = await client_ga.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["service"] == "generate_audio"


def test_ui_flask_app_health():
    test_client = flask_ui_app.test_client()
    resp = test_client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["service"] == "py_phone_caller_ui"
