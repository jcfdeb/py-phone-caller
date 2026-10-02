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


def build_openapi_schema(
    title: str,
    description: str,
    version: str = "1.0.0",
    paths: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Builds a standard OpenAPI 3.0.3 specification dictionary.
    """
    schema = {
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
