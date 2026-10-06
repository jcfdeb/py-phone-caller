"""
HTTP request handlers and routing for caller_prometheus_webhook.

Defines REST webhook endpoints compatible with Prometheus Alertmanager:
call-only, SMS-only, SMS-before-call, and call-and-SMS.
"""

from __future__ import annotations
import sys
from typing import Any
from aiohttp import web

from py_phone_caller_utils.config import settings
from py_phone_caller_utils.web import create_service_catalog, setup_swagger_routes

from caller_prometheus_webhook.constants import (
    PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS,
    PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY,
    PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL,
    PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY,
    PROMETHEUS_WEBHOOK_RECEIVERS,
)
from caller_prometheus_webhook.schemas import NotificationMode
from caller_prometheus_webhook.services import AlertNotificationService


def _resolve_service(request: web.Request) -> AlertNotificationService:
    """Resolves AlertNotificationService instance from app state or module factory."""
    factory = request.app.get("alert_service_factory")
    if factory:
        return factory()
    mod = sys.modules.get("src.caller_prometheus_webhook.caller_prometheus_webhook") or sys.modules.get(
        "caller_prometheus_webhook.caller_prometheus_webhook"
    )
    if mod and hasattr(mod, "_get_active_service"):
        return mod._get_active_service()
    return request.app.get("alert_service")


async def response_for_alert_manager() -> web.Response:
    """Returns standardized JSON response for Alertmanager webhooks."""
    return web.json_response({"status": "200"})


async def handle_webhook_request(request: web.Request, action_mode: str) -> web.Response:
    """
    Common handler for processing Prometheus Alertmanager webhooks.

    Args:
        request: Incoming aiohttp Request.
        action_mode: Mode string (call_only, sms_only, sms_before_call, call_and_sms).

    Returns:
        JSON response with HTTP 200.
    """
    mod = sys.modules.get("src.caller_prometheus_webhook.caller_prometheus_webhook") or sys.modules.get(
        "caller_prometheus_webhook.caller_prometheus_webhook"
    )
    # Check if legacy data_from_alert_manager is monkeypatched
    if mod and hasattr(mod, "data_from_alert_manager"):
        await mod.data_from_alert_manager(request, action_mode)
    else:
        payload = await request.json()
        svc = _resolve_service(request)
        receivers = getattr(mod, "PROMETHEUS_WEBHOOK_RECEIVERS", PROMETHEUS_WEBHOOK_RECEIVERS)
        dedup_window = int(settings.get("DEDUPLICATION_WINDOW_SECONDS", 180))
        await svc.handle_alert_payload(
            payload_data=payload,
            action_mode=action_mode,
            receivers=receivers,
            dedup_window=dedup_window,
        )

    return await response_for_alert_manager()


async def call_only(request: web.Request) -> web.Response:
    """Handles POST requests to dispatch phone calls for firing alerts."""
    return await handle_webhook_request(request, NotificationMode.CALL_ONLY.value)


async def sms_only(request: web.Request) -> web.Response:
    """Handles POST requests to dispatch SMS text for firing alerts."""
    return await handle_webhook_request(request, NotificationMode.SMS_ONLY.value)


async def sms_before_call(request: web.Request) -> web.Response:
    """Handles POST requests to dispatch SMS followed by call after delay."""
    return await handle_webhook_request(request, NotificationMode.SMS_BEFORE_CALL.value)


async def call_and_sms(request: web.Request) -> web.Response:
    """Handles POST requests to dispatch simultaneous phone call and SMS."""
    return await handle_webhook_request(request, NotificationMode.CALL_AND_SMS.value)


def setup_routes(app: web.Application) -> None:
    """
    Configures and mounts all REST routes onto the aiohttp application.

    Args:
        app: The aiohttp Application instance.
    """
    async def root_catalog(request: web.Request) -> web.Response:
        catalog = create_service_catalog(
            service_name="caller_prometheus_webhook",
            description="Prometheus Alertmanager webhook receiver for py-phone-caller",
            version="1.0.0",
            docs_url="/docs",
            openapi_spec="/docs/swagger.json",
            endpoints={
                f"POST /{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}": "Dispatches phone calls for firing Prometheus alerts",
                f"POST /{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY}": "Dispatches SMS for firing Prometheus alerts",
                f"POST /{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL}": "Sends SMS first, then calls after configurable delay",
                f"POST /{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS}": "Dispatches simultaneous call and SMS",
                "GET /live": "Liveness health check",
                "GET /ready": "Readiness probe",
                "GET /metrics": "Prometheus telemetry metrics",
            },
        )
        return web.json_response(catalog)

    app.router.add_route("GET", "/", root_catalog)
    app.router.add_route(
        "POST", f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}", call_only
    )
    app.router.add_route("POST", f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY}", sms_only)
    app.router.add_route(
        "POST",
        f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL}",
        sms_before_call,
    )
    app.router.add_route(
        "POST",
        f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS}",
        call_and_sms,
    )

    setup_swagger_routes(
        app=app,
        service_name="caller_prometheus_webhook",
        description="Prometheus Alertmanager Webhook Ingestion Service",
        paths={
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY}": {
                "post": {
                    "summary": "Process alert for phone call dispatch",
                    "description": "Receives standard Prometheus Alertmanager JSON payload and queues phone calls to configured receivers.",
                    "responses": {"200": {"description": "Webhook received"}},
                }
            },
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY}": {
                "post": {
                    "summary": "Process alert for SMS dispatch",
                    "responses": {"200": {"description": "Webhook received"}},
                }
            },
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL}": {
                "post": {
                    "summary": "Process alert with SMS followed by call",
                    "responses": {"200": {"description": "Webhook received"}},
                }
            },
            f"/{PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS}": {
                "post": {
                    "summary": "Process alert with concurrent call and SMS",
                    "responses": {"200": {"description": "Webhook received"}},
                }
            },
        },
    )
