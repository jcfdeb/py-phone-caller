"""
Web request helpers and utilities for py-phone-caller microservices.
Provides unified dual-mode parameter extraction (supporting both JSON request
bodies and URL query parameters with zero breaking changes) and root catalog builders.
"""

from typing import Any, Dict, Optional, Tuple
from aiohttp import web


async def extract_params(request: web.Request) -> Dict[str, Any]:
    """
    Extracts parameters from an incoming aiohttp request with dual-mode support:
    1. If the request body is valid application/json, extracts and returns the JSON dictionary.
    2. Otherwise (or in addition for missing keys), falls back to URL query parameters.

    This ensures 100% backward compatibility with legacy query string calls
    while seamlessly enabling modern JSON POST bodies.
    """
    params: Dict[str, Any] = {}

    # Check if request has JSON payload
    if request.can_read_body:
        content_type = request.headers.get("Content-Type", "").lower()
        if "application/json" in content_type:
            try:
                body_json = await request.json()
                if isinstance(body_json, dict):
                    params.update(body_json)
            except Exception:
                # If JSON parsing fails, we let query parameters attempt fallback
                pass

    # Merge / fallback to URL query parameters for any missing keys
    for key, value in request.rel_url.query.items():
        if key not in params:
            params[key] = value

    return params


def get_param(
    params: Dict[str, Any],
    key: str,
    default: Optional[Any] = None,
    required: bool = False,
    error_reason: str = "Missing required parameter",
) -> Any:
    """
    Retrieves a parameter by key from the extracted params dictionary.
    Raises web.HTTPBadRequest if required and missing.
    """
    val = params.get(key)
    if val is None or (isinstance(val, str) and not val.strip() and default is None):
        if required:
            raise web.HTTPBadRequest(reason=f"{error_reason}: {key}")
        return default
    return val


def create_service_catalog(
    service_name: str,
    description: str,
    version: str = "1.0.0",
    docs_url: str = "/docs",
    openapi_spec: str = "/docs/swagger.json",
    endpoints: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Constructs a standardized JSON catalog payload for root (GET /) service self-discovery.
    """
    catalog = {
        "service": service_name,
        "description": description,
        "status": "online",
        "version": version,
        "docs_url": docs_url,
        "openapi_spec": openapi_spec,
        "endpoints": endpoints or {},
    }
    return catalog

from py_phone_caller_utils.web.swagger import setup_swagger_routes, generate_swagger_ui_html, build_openapi_schema
