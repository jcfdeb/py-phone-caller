"""
Domain exceptions for the caller_prometheus_webhook service.

Provides strongly-typed domain exception hierarchies to avoid generic
exception handling and clearly separate deduplication, notification dispatch,
and payload validation failures.
"""


class PrometheusWebhookError(Exception):
    """Base exception for all caller_prometheus_webhook domain failures."""


class InvalidAlertPayloadError(PrometheusWebhookError):
    """Raised when the incoming Alertmanager webhook payload is malformed or missing required keys."""


class NotificationDispatchError(PrometheusWebhookError):
    """Raised when dispatching phone calls or SMS alerts to external endpoints fails."""


class DeduplicationError(PrometheusWebhookError):
    """Raised when alert deduplication state cannot be verified or updated."""
