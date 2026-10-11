import pytest
from aiohttp import web
from py_phone_caller_utils.web import extract_params, create_service_catalog, get_param


@pytest.mark.asyncio
async def test_create_service_catalog():
    catalog = create_service_catalog(
        service_name="test_service",
        description="A test service catalog",
        version="1.0.0",
        docs_url="/docs",
        openapi_spec="/docs/swagger.json",
        endpoints={"POST /test": "Test endpoint"},
    )
    assert catalog["service"] == "test_service"
    assert catalog["status"] == "online"
    assert catalog["version"] == "1.0.0"
    assert catalog["docs_url"] == "/docs"
    assert "/docs/swagger.json" in catalog["openapi_spec"]
    assert "POST /test" in catalog["endpoints"]


@pytest.mark.asyncio
async def test_dual_mode_param_extraction_from_query(aiohttp_client):
    async def handler(request):
        params = await extract_params(request)
        return web.json_response(params)

    app = web.Application()
    app.router.add_post("/test", handler)
    client = await aiohttp_client(app)

    # Legacy URL query string call
    resp = await client.post("/test?phone=0039123456789&message=FireAlert")
    assert resp.status == 200
    data = await resp.json()
    assert data["phone"] == "0039123456789"
    assert data["message"] == "FireAlert"


@pytest.mark.asyncio
async def test_dual_mode_param_extraction_from_json(aiohttp_client):
    async def handler(request):
        params = await extract_params(request)
        return web.json_response(params)

    app = web.Application()
    app.router.add_post("/test", handler)
    client = await aiohttp_client(app)

    # Modern JSON body call
    resp = await client.post(
        "/test",
        json={"phone": "0039987654321", "message": "ServerRoomOverheat", "oncall": True},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["phone"] == "0039987654321"
    assert data["message"] == "ServerRoomOverheat"
    assert data["oncall"] is True


@pytest.mark.asyncio
async def test_dual_mode_param_extraction_hybrid_fallback(aiohttp_client):
    async def handler(request):
        params = await extract_params(request)
        return web.json_response(params)

    app = web.Application()
    app.router.add_post("/test", handler)
    client = await aiohttp_client(app)

    # JSON body with query parameter fallback
    resp = await client.post(
        "/test?backup_callee=true",
        json={"phone": "0039987654321", "message": "PowerCut"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["phone"] == "0039987654321"
    assert data["message"] == "PowerCut"
    assert data["backup_callee"] == "true"


@pytest.mark.asyncio
async def test_swagger_endpoints_on_aiohttp_app(aiohttp_client):
    from py_phone_caller_utils.web import setup_swagger_routes
    app = web.Application()
    setup_swagger_routes(
        app=app,
        service_name="test_service",
        description="Test service description",
        paths={"/test": {"get": {"summary": "A test endpoint"}}},
    )
    client = await aiohttp_client(app)

    # Test /docs HTML page
    resp_docs = await client.get("/docs")
    assert resp_docs.status == 200
    assert "text/html" in resp_docs.headers.get("Content-Type", "")
    html = await resp_docs.text()
    assert "swagger-ui" in html.lower()
    assert "/docs/swagger.json" in html

    # Test /docs/swagger.json
    resp_json = await client.get("/docs/swagger.json")
    assert resp_json.status == 200
    spec = await resp_json.json()
    assert spec["openapi"] == "3.0.3"
    assert spec["info"]["title"] == "test_service"
    assert "/test" in spec["paths"]


@pytest.mark.asyncio
async def test_readiness_probe_healthy(aiohttp_client):
    from py_phone_caller_utils.web.readiness import ReadinessRegistry

    app = web.Application()
    reg = ReadinessRegistry("test_service")

    async def mock_check_ok():
        return True, "All systems operational"

    reg.register("mock_dep", mock_check_ok)

    async def ready_handler(request):
        all_ready, details = await reg.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    app.router.add_get("/ready", ready_handler)
    client = await aiohttp_client(app)

    resp = await client.get("/ready")
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ready"
    assert data["ready"] is True
    assert data["checks"]["mock_dep"]["ready"] is True


@pytest.mark.asyncio
async def test_readiness_probe_degraded_503(aiohttp_client):
    from py_phone_caller_utils.web.readiness import ReadinessRegistry

    app = web.Application()
    reg = ReadinessRegistry("test_service")

    async def mock_check_fail():
        return False, "Connection refused on port 5432"

    reg.register("postgres", mock_check_fail)

    async def ready_handler(request):
        all_ready, details = await reg.evaluate()
        status_code = 200 if all_ready else 503
        return web.json_response(details, status=status_code)

    app.router.add_get("/ready", ready_handler)
    client = await aiohttp_client(app)

    resp = await client.get("/ready")
    assert resp.status == 503
    data = await resp.json()
    assert data["status"] == "degraded"
    assert data["ready"] is False
    assert data["checks"]["postgres"]["ready"] is False
    assert "Connection refused" in data["checks"]["postgres"]["message"]
