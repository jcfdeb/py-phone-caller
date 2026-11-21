### Kubernetes Deployment Guide (py-phone-caller 1.0.0)

> **Centralized Step-by-Step Guide**: See **[`deploy/docs/04-kubernetes-and-helm-deployment.md`](../docs/04-kubernetes-and-helm-deployment.md)** (and the **[Deployment Documentation Hub](../docs/README.md)**) for the complete, verified step-by-step Kubernetes and Helm v3 installation guide.

This directory contains production-ready Kubernetes manifests for deploying the complete `py-phone-caller` stack:
- **Infrastructure**: PostgreSQL 17, Redis 7, HAProxy reverse proxy & Ingress.
- **Microservices**: `caller_register`, `caller_address_book`, `generate_audio`, `asterisk_caller`, `asterisk_ws_monitor`, `asterisk_recaller`, `caller_sms`, `caller_prometheus_webhook`, `caller_scheduler`, `py_phone_caller_ui`, `celery_worker`, and `openalertd`.

---

### Manifest Index

| Manifest | Component | Purpose |
| :--- | :--- | :--- |
| `00_py_phone_caller_namespace.yml` | Namespace | Creates the `py-phone-caller` namespace |
| `01_asterisk_endpoint.yml` | Service & Endpoints | Connects cluster to external Asterisk PBX (ARI/WebSocket) |
| `02_ingress.yml` | Ingress | Exposes HTTP routes through Ingress Controller |
| `03_postgresql.yml` | PostgreSQL 17 | Relational database deployment, service, and PVC |
| `03_redis.yml` | Redis 7 | Task queue broker for Celery and scheduled calls |
| `04_caller_config.yml` | ConfigMap | Central `settings.toml` configuration (non-secret) |
| `04_caller_secrets.yml` | Secret | Credentials (`.secrets.toml`, Asterisk ARI, PostgreSQL, Twilio, Keycloak) |
| `05_asterisk_ws_monitor.yml` | `asterisk_ws_monitor` | Listens to Asterisk Stasis events |
| `06_asterisk_recaller.yml` | `asterisk_recaller` | Manages unacknowledged call retries |
| `07_caller_register.yml` | `caller_register` | Central call/event registry & DB initializer (Port 8083) |
| `08_asterisk_caller.yml` | `asterisk_caller` | Outbound call initiator & queue worker (Port 8081) |
| `09_caller_prometheus_webhook.yml` | `caller_prometheus_webhook` | Prometheus Alertmanager webhook adapter (Port 8084) |
| `10_caller_sms.yml` | `caller_sms` | SMS dispatch service (Port 8085) |
| `11_generate_audio.yml` | `generate_audio` | TTS synthesis engine & audio storage (Port 8082) |
| `12_caller_address_book.yml` | `caller_address_book` | Contact & on-call availability manager (Port 8087) |
| `13_caller_scheduler.yml` | `caller_scheduler` | Celery task scheduler for future calls (Port 8086) |
| `14_py_phone_caller_ui.yml` | `py_phone_caller_ui` | Web management interface (Port 5000) |
| `15_celery_worker.yml` | `celery_worker` | Background Celery worker for scheduled jobs |
| `16_haproxy.yml` | HAProxy | Reverse proxy aggregating all APIs and Web UI (Port 8080) |
| `17_openalertd.yml` | `openalertd` | OpenAlert Nostr (`NIP-ALERT`), Micro-Relay (`:8088`), `/sos`, and Peering gateway |
| `18_gateway_apisix_keycloak.yml` | APISIX & Keycloak | Enterprise OIDC & API Gateway stack (`apisix`, `etcd`, `keycloak`) |
| `kustomization.yaml` | Kustomize | One-command declarative deployment (`kubectl apply -k .`) |

> **Helm Chart**: For parameterized Helm deployments, see [`../helm/py-phone-caller`](../helm/py-phone-caller/README.md).

---

### Deployment Steps

#### Option A: One-Command Kustomize Apply
Edit `01_asterisk_endpoint.yml` and `04_caller_secrets.yml`, then run:
```bash
kubectl apply -k deploy/k8s/
```

#### Option B: Step-by-Step Manifest Apply

##### 1. Configure External Asterisk PBX
Update the IP address of your Asterisk PBX in `01_asterisk_endpoint.yml`:
```yaml
subsets:
  - addresses:
      - ip: <ASTERISK_PBX_IP>
    ports:
      - port: 8088
```

##### 2. Apply Namespace, ConfigMap, and Secret
```bash
kubectl apply -f 00_py_phone_caller_namespace.yml
kubectl apply -f 01_asterisk_endpoint.yml
kubectl apply -f 04_caller_config.yml
kubectl apply -f 04_caller_secrets.yml
```

##### 3. Deploy Data Infrastructure
```bash
kubectl apply -f 03_postgresql.yml
kubectl apply -f 03_redis.yml
```

##### 4. Deploy Core Services, OpenAlert, & Workers
```bash
# Core database and audio services first
kubectl apply -f 07_caller_register.yml
kubectl apply -f 11_generate_audio.yml
kubectl apply -f 12_caller_address_book.yml

# Calling, monitoring, SMS, and OpenAlert services
kubectl apply -f 08_asterisk_caller.yml
kubectl apply -f 05_asterisk_ws_monitor.yml
kubectl apply -f 06_asterisk_recaller.yml
kubectl apply -f 09_caller_prometheus_webhook.yml
kubectl apply -f 10_caller_sms.yml
kubectl apply -f 17_openalertd.yml

# Scheduling and UI
kubectl apply -f 13_caller_scheduler.yml
kubectl apply -f 14_py_phone_caller_ui.yml
kubectl apply -f 15_celery_worker.yml
```

##### 5. Deploy Gateway & Ingress
```bash
kubectl apply -f 16_haproxy.yml
kubectl apply -f 18_gateway_apisix_keycloak.yml
kubectl apply -f 02_ingress.yml
```

---

### Verification and Health Checks

All HTTP-enabled microservices are equipped with Kubernetes `livenessProbe` and `readinessProbe` checking `/health`.

Verify pod status:
```bash
kubectl get pods -n py-phone-caller
```

Verify service endpoints and readiness:
```bash
kubectl get svc -n py-phone-caller
```

Check logs of any component (e.g. `caller_register` or `py_phone_caller_ui`):
```bash
kubectl logs -n py-phone-caller -l app=caller-register -f
kubectl logs -n py-phone-caller -l app=py-phone-caller-ui -f
```
