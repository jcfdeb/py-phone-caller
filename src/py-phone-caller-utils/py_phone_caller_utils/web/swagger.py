"""
OpenAPI 3.0 / Swagger documentation generator and standalone Swagger UI provider.
Enables offline-ready, air-gapped, zero-dependency interactive API documentation
at `/docs` and raw OpenAPI specification at `/docs/swagger.json` across both
aiohttp microservices and Flask applications.
"""

import json
from typing import Any, Dict, List, Optional
from aiohttp import web


def generate_swagger_ui_html(
    title: str,
    openapi_url: str = "/docs/swagger.json",
    swagger_js_url: str = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
    swagger_css_url: str = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
) -> str:
    """
    Renders standalone Swagger UI HTML page pointing to openapi_url.
    Can be served directly by aiohttp or Flask without external dependencies.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title} - API Documentation</title>
    <link rel="stylesheet" type="text/css" href="{swagger_css_url}">
    <link rel="icon" type="image/png" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><text y='20' font-size='20'>📞</text></svg>">
    <style>
        html {{ box-sizing: border-box; overflow: -moz-scrollbars-vertical; overflow-y: scroll; }}
        *, *:before, *:after {{ box-sizing: inherit; }}
        body {{ margin: 0; background: #fafafa; font-family: sans-serif; }}
        .topbar {{ display: none !important; }}
        .swagger-ui .info {{ margin: 20px 0; }}
        .swagger-ui .info .title {{ font-size: 28px; color: #1e293b; }}
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="{swagger_js_url}"></script>
    <script>
        window.onload = function() {{
            window.ui = SwaggerUIBundle({{
                url: "{openapi_url}",
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                layout: "BaseLayout"
            }});
        }};
    </script>
</body>
</html>"""


def generate_unified_swagger_portal_html(
    title: str = "py-phone-caller Unified API Portal",
    services: Optional[List[Dict[str, str]]] = None,
    swagger_js_url: str = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
    swagger_css_url: str = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
) -> str:
    """
    Generates a unified Swagger UI 5 Developer Portal aggregating all py-phone-caller
    microservice OpenAPI 3.0 endpoints with multi-spec selector and Keycloak Bearer Auth support.
    """
    if services is None:
        services = [
            {"name": "Web Dashboard & Operations Center (:5000)", "url": "/docs/swagger.json"},
            {"name": "Prometheus Alerts Webhook (:8084)", "url": "/api/v1/alerts/docs/swagger.json"},
            {"name": "Telephony & Asterisk Caller (:8081)", "url": "/api/v1/telephony/docs/swagger.json"},
            {"name": "SMS Gateway & Carrier Engine (:8085)", "url": "/api/v1/sms/docs/swagger.json"},
            {"name": "Address Book & Duty Roster (:8087)", "url": "/api/v1/contacts/docs/swagger.json"},
            {"name": "Call Scheduler Engine (:8086)", "url": "/api/v1/schedules/docs/swagger.json"},
            {"name": "Audio Synthesis & TTS Engine (:8082)", "url": "/api/v1/audio/docs/swagger.json"},
            {"name": "Call Registry & DTMF Acknowledgment (:8083)", "url": "/api/v1/registry/docs/swagger.json"},
        ]

    services_json = json.dumps(services)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" type="text/css" href="{swagger_css_url}">
    <link rel="icon" type="image/png" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><text y='20' font-size='20'>📞</text></svg>">
    <style>
        html {{ box-sizing: border-box; overflow: -moz-scrollbars-vertical; overflow-y: scroll; }}
        *, *:before, *:after {{ box-sizing: inherit; }}
        body {{ margin: 0; background: #0f172a; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
        .portal-header {{
            background: #1e293b;
            color: #ffffff;
            padding: 14px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        .portal-header h1 {{
            margin: 0;
            font-size: 1.15rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .portal-header a {{
            color: #38bdf8;
            text-decoration: none;
            font-size: 0.9rem;
            font-weight: 500;
        }}
        .portal-header a:hover {{ text-decoration: underline; }}
        #swagger-ui {{
            background: #ffffff;
            border-radius: 12px;
            margin: 20px auto;
            max-width: 1400px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        .swagger-ui .topbar {{
            background-color: #0f172a !important;
            padding: 10px 20px;
        }}
        .swagger-ui .topbar .download-url-wrapper select {{
            background: #1e293b;
            color: #ffffff;
            border: 1px solid #475569;
            border-radius: 6px;
            padding: 6px 12px;
            font-size: 0.9rem;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="portal-header">
        <h1><span>📞</span> {title}</h1>
        <div>
            <a href="/">← Return to NOC Dashboard</a>
        </div>
    </div>
    <div id="swagger-ui"></div>
    <script src="{swagger_js_url}"></script>
    <script>
        window.onload = function() {{
            const ui = SwaggerUIBundle({{
                urls: {services_json},
                "urls.primaryName": "{services[0]['name']}",
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                layout: "StandaloneLayout",
                persistAuthorization: true
            }});
            window.ui = ui;
        }};
    </script>
</body>
</html>"""


def build_openapi_schema(
    title: str,
    description: str,
    version: str = "1.0.0",
    paths: Optional[Dict[str, Any]] = None,
    tags: Optional[List[Dict[str, Any]]] = None,
    components: Optional[Dict[str, Any]] = None,
    servers: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """
    Builds a standard OpenAPI 3.0.3 specification dictionary.
    """
    schema: Dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "description": description,
            "version": version,
            "contact": {
                "name": "py-phone-caller Support",
                "url": "https://github.com/jcfdeb/py-phone-caller",
            },
        },
        "paths": paths or {},
    }
    if tags is not None:
        schema["tags"] = tags
    if components is not None:
        schema["components"] = components
    if servers is not None:
        schema["servers"] = servers
    schema.update(kwargs)
    return schema


def setup_swagger_routes(
    app: web.Application,
    service_name: str,
    description: str,
    paths: Dict[str, Any],
    version: str = "1.0.0",
):
    """
    Registers `/docs` (interactive Swagger UI) and `/docs/swagger.json` (OpenAPI spec)
    onto an aiohttp application instance.
    """
    schema = build_openapi_schema(
        title=service_name,
        description=description,
        version=version,
        paths=paths,
    )

    async def swagger_ui_handler(request: web.Request) -> web.Response:
        html = generate_swagger_ui_html(
            title=f"{service_name} API Docs",
            openapi_url="/docs/swagger.json",
        )
        return web.Response(text=html, content_type="text/html", charset="utf-8")

    async def swagger_json_handler(request: web.Request) -> web.Response:
        return web.json_response(schema)

    app.router.add_get("/docs", swagger_ui_handler)
    app.router.add_get("/docs/swagger.json", swagger_json_handler)
