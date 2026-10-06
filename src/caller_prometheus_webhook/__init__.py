"""
caller_prometheus_webhook package.

Receives Prometheus Alertmanager webhooks and dispatches calls, SMS, or combined notifications.
"""

from caller_prometheus_webhook.clients import (
    AsteriskCallClient,
    CallerSmsClient,
)
from caller_prometheus_webhook.exceptions import (
    DeduplicationError,
    InvalidAlertPayloadError,
    NotificationDispatchError,
    PrometheusWebhookError,
)
from caller_prometheus_webhook.schemas import (
    DispatchItem,
    NotificationMode,
    PrometheusAlert,
    WebhookPayload,
)
from caller_prometheus_webhook.services import (
    AlertNotificationService,
    DeduplicationService,
)
from caller_prometheus_webhook.routes import (
    call_and_sms,
    call_only,
    response_for_alert_manager,
    setup_routes,
    sms_before_call,
    sms_only,
)
from caller_prometheus_webhook.caller_prometheus_webhook import (
    consumer,
    data_from_alert_manager,
    do_call_and_sms,
    do_call_only,
    do_sms_before_call,
    do_the_call,
    init_app,
    is_duplicate_alert,
    notification_actions,
    process_the_queue,
    producer,
    schedule_sms_before_call,
    send_message_to_caller_sms,
    send_the_sms,
    start_the_asterisk_call,
    the_alert_description,
)

__all__ = [
    "AlertNotificationService",
    "AsteriskCallClient",
    "CallerSmsClient",
    "DeduplicationError",
    "DeduplicationService",
    "DispatchItem",
    "InvalidAlertPayloadError",
    "NotificationDispatchError",
    "NotificationMode",
    "PrometheusAlert",
    "PrometheusWebhookError",
    "WebhookPayload",
    "call_and_sms",
    "call_only",
    "consumer",
    "data_from_alert_manager",
    "do_call_and_sms",
    "do_call_only",
    "do_sms_before_call",
    "do_the_call",
    "init_app",
    "is_duplicate_alert",
    "notification_actions",
    "process_the_queue",
    "producer",
    "response_for_alert_manager",
    "schedule_sms_before_call",
    "send_message_to_caller_sms",
    "send_the_sms",
    "setup_routes",
    "sms_before_call",
    "sms_only",
    "start_the_asterisk_call",
    "the_alert_description",
]
