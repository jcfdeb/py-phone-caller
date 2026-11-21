# 07. Enterprise Gateway (`APISIX` + `Keycloak`) & Observability (`deploy/gateway` & `deploy/dashboards`)

This guide explains how to deploy and operate the **Enterprise API Gateway & Single Sign-On (OIDC)** layer (`deploy/gateway/`) and the **NOC/SRE Prometheus + Grafana Observability Dashboard** (`deploy/dashboards/`).

---

## Part 1: Enterprise API Gateway (`Apache APISIX` + `Keycloak OIDC`)

For organizations requiring centralized Identity & Access Management (IAM), Multi-Factor Authentication (MFA), Role-Based Access Control (RBAC), and API rate-limiting, `py-phone-caller` integrates with **Keycloak 25** and **Apache APISIX 3.9**.

```mermaid
flowchart LR
    USER["Operator Browser / API Client"] --> TLS["Caddy / Ingress TLS (:443)"]
    TLS --> APISIX["Apache APISIX (:9080 / :9443)"]
    APISIX -->|"/realms/*, /resources/*"| KC["Keycloak OIDC (:8080 / :8180)"]
    APISIX -->|"/*"| UI["py_phone_caller_ui (:5000)"]
    APISIX -->|"/api/v1/telephony/*"| AC["asterisk_caller (:8081)"]
    APISIX -->|"/api/v1/tts/*"| GA["generate_audio (:8082)"]
    APISIX -->|"/api/v1/registry/*"| CR["caller_register (:8083)"]
    APISIX -->|"/api/v1/webhook/*"| CPW["caller_prometheus_webhook (:8084)"]
    APISIX -->|"/api/v1/sms/*"| SMS["caller_sms (:8085)"]
    APISIX -->|"/api/v1/scheduler/*"| SCH["caller_scheduler (:8086)"]
    APISIX -->|"/api/v1/contacts/*"| CAB["caller_address_book (:8087)"]
```

### 1. Three-Tier RBAC Model in Keycloak
The provisioning script (`deploy/gateway/keycloak/setup_keycloak.py`) configures the `py-phone-caller` realm with three roles:

| Role | Default Demo Username | Capabilities |
| :--- | :--- | :--- |
| **`alert-admin`** | `admin_user` | Full unrestricted platform administration, user management, and configuration |
| **`alert-operator`** | `operator_user` | Trigger outbound calls/SMS, manage schedules and contacts, and acknowledge alerts |
| **`alert-viewer`** | `viewer_user` | Read-only access to the NOC Wallboard, call registry, and incident audit logs |

### 2. Automated Provisioning via Ansible (`stack_topology_profile: enterprise`)
When deploying via **[02. Native Ansible Deployment](02-ansible-deployment.md)** with `stack_topology_profile: enterprise`, the `gateway` role automatically:
1. Starts digest-pinned `etcd`, `apisix`, `apisix-dashboard`, and `keycloak` containers bound strictly to loopback (`127.0.0.1`).
2. Runs `setup_keycloak.py` and `setup_apisix_routes.py`.
3. Wires `py_phone_caller_ui` to authenticate against Keycloak OIDC over your `stack_public_url`.

### 3. Provisioning with Docker Compose or Kubernetes
If you started the gateway via **Docker Compose** (`docker compose -f docker-compose.yml -f docker-compose.gateway.yml up -d`) or **Kubernetes** (`kubectl apply -f deploy/k8s/18_gateway_apisix_keycloak.yml` or Helm `--set gateway.enabled=true`), run the idempotent setup scripts once the containers are healthy:

```bash
# 1. Provision the Keycloak realm, clients, roles, and initial users
KEYCLOAK_URL="http://127.0.0.1:8080" \
KEYCLOAK_ADMIN_USER="admin" \
KEYCLOAK_ADMIN_PASS="YOUR_KEYCLOAK_ADMIN_PASS" \
KEYCLOAK_M2M_SECRET="YOUR_OIDC_CLIENT_SECRET" \
KEYCLOAK_PUBLIC_URL="https://alerts.example.internal" \
KEYCLOAK_USER_ADMIN_PASS="YOUR_ALERT_ADMIN_PASS" \
KEYCLOAK_USER_OPERATOR_PASS="YOUR_ALERT_OPERATOR_PASS" \
KEYCLOAK_USER_VIEWER_PASS="YOUR_ALERT_VIEWER_PASS" \
python3 deploy/gateway/keycloak/setup_keycloak.py

# 2. Provision the Apache APISIX routes and rate-limiting rules
APISIX_DASHBOARD_URL="http://127.0.0.1:9000" \
APISIX_DASHBOARD_USER="admin" \
APISIX_DASHBOARD_PASS="YOUR_APISIX_ADMIN_PASS" \
UPSTREAM_HOST="127.0.0.1" \
KEYCLOAK_PORT="8080" \
python3 deploy/gateway/apisix/setup_apisix_routes.py
```

*(For a comprehensive architectural walkthrough of the Enterprise Gateway, also see [`docs/ENTERPRISE_GATEWAY_AND_IAM_GUIDE.md`](../../docs/ENTERPRISE_GATEWAY_AND_IAM_GUIDE.md)).*

---

## Part 2: Prometheus & Turnkey Grafana Dashboard (`deploy/dashboards`)

Every HTTP microservice in `py-phone-caller` exposes Prometheus metrics at `/metrics`, and `deploy/dashboards/grafana-py-phone-caller.json` provides a turnkey NOC/SRE dashboard.

### Step 1: Configure Prometheus Scrape Targets (`prometheus.yml`)

Add the following jobs to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: "py-phone-caller-services"
    scrape_interval: 10s
    metrics_path: /metrics
    static_configs:
      - targets:
          - "127.0.0.1:8081" # asterisk_caller
          - "127.0.0.1:8082" # generate_audio (TTS synthesis metrics)
          - "127.0.0.1:8083" # caller_register (DTMF Ack & call lifecycle metrics)
          - "127.0.0.1:8084" # caller_prometheus_webhook (Alert ingestion metrics)
          - "127.0.0.1:8085" # caller_sms (USB GSM Modem & Twilio SMS metrics)
          - "127.0.0.1:8086" # caller_scheduler (Scheduled call metrics)
          - "127.0.0.1:8087" # caller_address_book (On-call roster metrics)

  - job_name: "apisix-gateway"
    scrape_interval: 10s
    metrics_path: /apisix/prometheus/metrics
    static_configs:
      - targets:
          - "127.0.0.1:9091" # Apache APISIX Prometheus exporter
```

### Step 2: Import the Grafana Dashboard (`grafana-py-phone-caller.json`)

#### Option A: Via Grafana Web UI
1. Open Grafana $\rightarrow$ **Dashboards** $\rightarrow$ **New** $\rightarrow$ **Import**.
2. Upload [`deploy/dashboards/grafana-py-phone-caller.json`](../dashboards/grafana-py-phone-caller.json).
3. Select your Prometheus data source and click **Import**.

#### Option B: Via Grafana HTTP API
```bash
curl -X POST http://admin:YOUR_GRAFANA_PASS@127.0.0.1:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d "{\"dashboard\": $(cat deploy/dashboards/grafana-py-phone-caller.json), \"overwrite\": true}"
```

### Visualized Telemetry Rows
- **Executive Overview**: Total calls dispatched, DTMF acknowledgment percentage, SMS delivery rate, and in-flight calls.
- **Call Lifecycle & DTMF Speed**: Throughput by status (`answered`, `failed`, `unacknowledged`, `busy`) and `p50`/`p90`/`p99` responder acknowledgment latency.
- **TTS Synthesis Latency**: Generation duration by engine (`piper_tts`, `kokoro_tts`, `silero_tts`, `mms_tts`, `aws_polly`, `gtts`).
- **SMS Gateway Health**: Throughput and failover metrics across `on_premise` USB GSM modems and `twilio`.
- **APISIX Gateway & System Resources**: HTTP status distribution (`2xx`/`4xx`/`5xx`), latency buckets, and per-service RSS memory/CPU usage.
