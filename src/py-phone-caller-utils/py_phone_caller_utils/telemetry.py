"""
Telemetry initialization and instrumentation helpers using OpenTelemetry.
"""

import logging
import os
from typing import Optional

from opentelemetry import trace, metrics
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.aiohttp_server import AioHttpServerInstrumentor
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor

from py_phone_caller_utils.config import settings

logger = logging.getLogger(__name__)


def init_telemetry(service_name: str) -> Optional[TracerProvider]:
    """
    Initializes OpenTelemetry for the service.

    It sets up:
    1. TracerProvider with an OTLP Exporter (gRPC) for traces.
    2. MeterProvider with a PrometheusMetricReader for metrics.
    3. Automatic instrumentation for common libraries.

    Configuration is driven by environment variables or settings.toml:
    - OTEL_EXPORTER_OTLP_ENDPOINT: URL of the collector (default: http://jaeger:4317)
    - ENABLE_TELEMETRY: Set to 'true' to enable (default: false)

    :param service_name: The name of the service (e.g., 'asterisk_caller')
    :return: The configured TracerProvider or None if disabled.
    """

    enabled = os.environ.get("ENABLE_TELEMETRY", "").lower() == "true"
    if not enabled:
        try:
            enabled = settings.telemetry.enabled
        except AttributeError:
            enabled = False

    if not enabled:
        logger.info(f"Telemetry disabled for {service_name}")
        return None

    logger.info(f"Initializing OpenTelemetry for {service_name}...")

    resource = Resource(
        attributes={
            SERVICE_NAME: service_name,
        }
    )

    provider = TracerProvider(resource=resource)
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4317")

    try:
        otlp_exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        span_processor = BatchSpanProcessor(otlp_exporter)
        provider.add_span_processor(span_processor)
        trace.set_tracer_provider(provider)

        reader = PrometheusMetricReader()
        meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(meter_provider)

        RequestsInstrumentor().instrument()
        AioHttpClientInstrumentor().instrument()
        AsyncPGInstrumentor().instrument()
        SystemMetricsInstrumentor().instrument()

        logger.info(
            f"OpenTelemetry initialized for {service_name} sending traces to {endpoint} and exposing metrics via Prometheus"
        )
        return provider

    except Exception as e:
        logger.error(f"Failed to initialize OpenTelemetry: {e}")
        return None


def instrument_aiohttp_app(app, service_name: Optional[str] = None):
    """Helper to instrument a specific aiohttp web application and add /metrics and /health routes."""
    try:
        from aiohttp import web

        async def health_handler(request):
            return web.json_response(
                {
                    "status": "healthy",
                    "service": service_name or "py-phone-caller",
                    "version": "1.0.0",
                }
            )

        app.router.add_get("/health", health_handler)
        app.router.add_get("/healthz", health_handler)
        app.router.add_get("/live", health_handler)

        async def metrics_handler(request):
            data = generate_latest()
            content_type = CONTENT_TYPE_LATEST.split(";")[0]
            return web.Response(
                body=data, content_type=content_type, charset="utf-8"
            )

        app.router.add_get("/metrics", metrics_handler)
        logger.info(
            f"Added /health and /metrics routes to aiohttp app ({service_name or 'py-phone-caller'})"
        )

        if trace.get_tracer_provider():
            AioHttpServerInstrumentor().instrument()
    except Exception as e:
        logger.error(f"Failed to instrument aiohttp app: {e}")


def instrument_flask_app(app, service_name: Optional[str] = "py_phone_caller_ui"):
    """Helper to instrument a specific flask application and add /metrics and /health routes."""
    try:
        from flask import jsonify, Response

        @app.route("/health")
        @app.route("/healthz")
        @app.route("/live")
        def health_view():
            return jsonify(
                {
                    "status": "healthy",
                    "service": service_name or "py_phone_caller_ui",
                    "version": "1.0.0",
                }
            )

        @app.route("/metrics")
        def metrics_view():
            data = generate_latest()
            return Response(data, mimetype=CONTENT_TYPE_LATEST)

        logger.info(
            f"Added /health and /metrics routes to Flask app ({service_name or 'py_phone_caller_ui'})"
        )

        if trace.get_tracer_provider():
            FlaskInstrumentor().instrument_app(app)
    except Exception as e:
        logger.error(f"Failed to instrument Flask app: {e}")


def instrument_celery_app(app):
    """Helper to instrument a specific celery application."""
    try:
        if trace.get_tracer_provider():
            CeleryInstrumentor().instrument()
    except Exception as e:
        logger.error(f"Failed to instrument Celery app: {e}")
