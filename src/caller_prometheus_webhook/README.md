# Caller Prometheus Webhook

Alertmanager-compatible webhook that turns Prometheus alerts into phone calls
and SMS notifications.

## Responsibilities
- Accept Alertmanager payloads and dispatch notifications.
- Support call-only, SMS-only, SMS-before-call, and call-and-SMS workflows.
- Use asyncio queues to throttle and process notifications.

## HTTP API
Routes are configured in `settings.toml` under `[caller_prometheus_webhook]`:
- POST `/<prometheus_webhook_app_route_call_only>`
- POST `/<prometheus_webhook_app_route_sms_only>`
- POST `/<prometheus_webhook_app_route_sms_before_call>`
- POST `/<prometheus_webhook_app_route_call_and_sms>`

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m caller_prometheus_webhook.caller_prometheus_webhook
```

## Docker
```bash
docker build -t caller-prometheus-webhook -f src/caller_prometheus_webhook/Dockerfile src/
```
