# py-phone-caller Helm Chart (`v1.1.0`)

> **Centralized Step-by-Step Guide**: See **[`deploy/docs/04-kubernetes-and-helm-deployment.md`](../../docs/04-kubernetes-and-helm-deployment.md)** (and the **[Deployment Documentation Hub](../../docs/README.md)**) for the complete, verified step-by-step Helm v3 and Kubernetes installation guide.

Production Helm v3 chart for deploying the complete **py-phone-caller** and **OpenAlert (`openalertd`)** stack on Kubernetes.

## Components Managed

- **External PBX Endpoint**: `Service` + `EndpointSlice` (`discovery.k8s.io/v1`) pointing to your Asterisk ARI host (`asterisk.externalIp`).
- **Data Layer**: PostgreSQL 17 (`postgresql.enabled=true`) and Redis 7 (`redis.enabled=true`).
- **11 Python Microservices**: `caller_register`, `generate_audio`, `caller_address_book`, `asterisk_caller`, `asterisk_ws_monitor`, `asterisk_recaller`, `caller_sms`, `caller_prometheus_webhook`, `caller_scheduler`, `py_phone_caller_ui`, and `celery_worker`.
- **OpenAlert Daemon (`openalertd`)**: REST API (`:8090`), Nostr Micro-Relay (`:8088`), and UDP Peering (`:19876/udp`) bridged to `caller_prometheus_webhook`.
- **Optional Enterprise Gateway (`gateway.enabled=true`)**: Apache APISIX, etcd, and Keycloak OIDC IAM.

## Quick Start

```bash
helm upgrade --install py-phone-caller deploy/helm/py-phone-caller \
  --namespace py-phone-caller --create-namespace \
  --set asterisk.externalIp="10.10.0.50" \
  --set secrets.asteriskPass="your-ari-secret" \
  --set secrets.dbPassword="your-postgres-secret" \
  --set secrets.uiSecretKey="your-random-32-char-session-secret" \
  --set secrets.uiAdminPassword="your-admin-password"
```

## Packaging the Chart Archive

```bash
uv run python deploy/packaging/k8s/build_k8s_bundle.py --force
```
