"""
OpenAPI 3.0 / Swagger documentation generator and standalone Swagger UI provider.
Provides interactive API documentation at `/docs` and raw OpenAPI specification
at `/docs/swagger.json` across aiohttp microservices and Flask applications.
With PPC_OFFLINE=1, documentation is static with same-origin JSON links instead
of interactive Swagger UI, which normally loads external assets.
"""

from html import escape
import json
import os
from typing import Any, Dict, List, Optional
from aiohttp import web


def _generate_offline_docs_html(title: str, services: List[Dict[str, str]]) -> str:
    escaped_title = escape(title)
    items = []
    for service in services:
        name = escape(service["name"])
        url = service["url"]
        escaped_url = escape(url)
        # Only root-relative paths are provably same-origin without request context.
        if (
            url.startswith("/")
            and not url.startswith("//")
            and "\\" not in url
            and all(ord(char) > 32 and ord(char) != 127 for char in url)
        ):
            items.append(f'<li><a href="{escaped_url}">{name} — OpenAPI JSON</a></li>')
        else:
            items.append(f"<li>{name}: <code>{escaped_url}</code> (not linked offline)</li>")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{escaped_title}</title>
</head>
<body>
    <h1>{escaped_title}</h1>
    <p>Interactive Swagger UI is unavailable in offline mode (PPC_OFFLINE=1).
    No external documentation assets are loaded. JSON APIs remain available.</p>
    <p>Only same-origin OpenAPI JSON paths are linked; other URLs are shown as text.</p>
    <ul>{''.join(items)}</ul>
</body>
</html>"""


def generate_swagger_ui_html(
    title: str,
    openapi_url: str = "/docs/swagger.json",
    swagger_js_url: str = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
    swagger_css_url: str = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
) -> str:
    """
    Renders standalone Swagger UI HTML page pointing to openapi_url.
    PPC_OFFLINE=1 returns static documentation without external assets.
    """
    if os.environ.get("PPC_OFFLINE") == "1":
        return _generate_offline_docs_html(
            f"{title} - API Documentation", [{"name": title, "url": openapi_url}],
        )
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
    PPC_OFFLINE=1 returns static documentation without external assets.
    """
    if services is None:
        services = [
            {"name": "Web Dashboard & Operations Center", "url": "/docs/swagger.json"},
            {"name": "Prometheus Alerts Webhook", "url": "/api/v1/alerts/docs/swagger.json"},
            {"name": "Telephony & Asterisk Caller", "url": "/api/v1/telephony/docs/swagger.json"},
            {"name": "SMS Gateway & Carrier Engine", "url": "/api/v1/sms/docs/swagger.json"},
            {"name": "Address Book & Duty Roster", "url": "/api/v1/contacts/docs/swagger.json"},
            {"name": "Call Scheduler Engine", "url": "/api/v1/schedules/docs/swagger.json"},
            {"name": "Audio Synthesis & TTS Engine", "url": "/api/v1/audio/docs/swagger.json"},
            {"name": "Call Registry & DTMF Acknowledgment", "url": "/api/v1/registry/docs/swagger.json"},
        ]

    if os.environ.get("PPC_OFFLINE") == "1":
        return _generate_offline_docs_html(title, services)

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
    version: str = "1.1.0",
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
    version: str = "1.1.0",
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
