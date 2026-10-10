# Caller Prometheus Webhook

Alertmanager-compatible webhook that turns Prometheus alerts into phone calls
and SMS notifications.

## Responsibilities
- Accept Alertmanager payloads and dispatch notifications.
- Support call-only, SMS-only, SMS-before-call, and call-and-SMS workflows.
- Use asyncio queues to throttle and process notifications.
- Support Machine-to-Machine (M2M) OAuth2 Bearer token authentication via Keycloak while maintaining 100% backward-compatibility for direct, unauthenticated LAN environments.

## HTTP API
Routes are configured in `settings.toml` under `[caller_prometheus_webhook]`:
- `POST /<prometheus_webhook_app_route_call_only>` (default: `/call_only`)
- `POST /<prometheus_webhook_app_route_sms_only>` (default: `/sms_only`)
- `POST /<prometheus_webhook_app_route_sms_before_call>` (default: `/sms_before_call`)
- `POST /<prometheus_webhook_app_route_call_and_sms>` (default: `/call_and_sms`)

When deployed behind Apache APISIX Gateway:
- `POST /api/v1/alerts/<route>`

## Prometheus Alertmanager Integration Examples

### 1. Direct Webhook (Standalone / Without APISIX or Keycloak)

Use this configuration when running in an isolated LAN or trusted internal network without an authentication gateway:

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'py-phone-caller'
  routes:
    - match:
        severity: critical
      receiver: 'py-phone-caller-call-and-sms'
    - match:
        severity: warning
      receiver: 'py-phone-caller-sms-only'

receivers:
  # Emergency Phone Call Only
  - name: 'py-phone-caller'
    webhook_configs:
      - url: 'http://192.168.1.100:8084/call_only'
        send_resolved: false

  # Simultaneous Phone Call & SMS
  - name: 'py-phone-caller-call-and-sms'
    webhook_configs:
      - url: 'http://192.168.1.100:8084/call_and_sms'
        send_resolved: false

  # SMS Only
  - name: 'py-phone-caller-sms-only'
    webhook_configs:
      - url: 'http://192.168.1.100:8084/sms_only'
        send_resolved: false
```

---

### 2. Enterprise M2M Webhook (With Apache APISIX & Keycloak OAuth2)

Modern versions of Prometheus Alertmanager support native OAuth2 client credentials grant via `http_config.oauth2`. Alertmanager automatically acquires, caches, and refreshes the Bearer token:

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'severity']
  receiver: 'py-phone-caller-m2m'

receivers:
  - name: 'py-phone-caller-m2m'
    webhook_configs:
      - url: 'https://alerts.example.com/api/v1/alerts/call_only'
        send_resolved: false
        http_config:
          oauth2:
            client_id: 'py-phone-caller-m2m'
            client_secret: '<YOUR_KEYCLOAK_M2M_SECRET>'
            token_url: 'https://alerts.example.com/realms/py-phone-caller/protocol/openid-connect/token'
            scopes: ['email', 'profile']
            tls_config:
              insecure_skip_verify: false
```

> [!TIP]
> The secret for `py-phone-caller-m2m` is generated automatically during deployment and can be displayed using `./show-credentials.sh` on the control node or retrieved from `/etc/py-phone-caller/credentials.env` on the server.

---

## Configuration & Settings

Configured in `src/config/settings.toml`:

```toml
[caller_prometheus_webhook]
prometheus_webhook_port = 8084
prometheus_webhook_app_route_call_only = "call_only"
prometheus_webhook_app_route_sms_only = "sms_only"
prometheus_webhook_app_route_sms_before_call = "sms_before_call"
prometheus_webhook_app_route_call_and_sms = "call_and_sms"
prometheus_webhook_receivers = ["+39123456789"]
require_auth = false   # Set to true to enforce M2M Bearer token validation
```

## Running Locally

```bash
export CALLER_CONFIG_DIR=src/config
uv run python -m caller_prometheus_webhook.caller_prometheus_webhook
```

## Docker Container

```bash
docker build -t caller-prometheus-webhook -f src/caller_prometheus_webhook/Dockerfile .
```
