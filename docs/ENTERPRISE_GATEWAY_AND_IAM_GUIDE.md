# Enterprise Gateway & IAM Deployment Guide: Apache APISIX & Keycloak SSO for py-phone-caller

This guide is designed for **all experience levels**—from curious beginners to seasoned DevOps engineers. It provides both an **automated 1-command deployment** (via Ansible & Ansible Vault) and a **complete, step-by-step manual "copy-and-paste" walkthrough** to help you understand every moving part under the hood.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Role-Based Access Control (RBAC) Model](#2-role-based-access-control-rbac-model)
3. [Method A: Automated Deployment with Ansible (Recommended)](#3-method-a-automated-deployment-with-ansible-recommended)
4. [Method B: Step-by-Step Manual Deployment Guide](#4-method-b-step-by-step-manual-deployment-guide)
   - [Step 1: System Prerequisites & Dependencies](#step-1-system-prerequisites--dependencies)
   - [Step 2: Database Preparation (PostgreSQL)](#step-2-database-preparation-postgresql)
   - [Step 3: Container Infrastructure (etcd, APISIX, Keycloak)](#step-3-container-infrastructure-etcd-apisix-keycloak)
   - [Step 4: Apache 2 / Caddy Public TLS Ingress](#step-4-apache-2--caddy-public-tls-ingress)
   - [Step 5: Keycloak Realm, Roles, and Users Provisioning](#step-5-keycloak-realm-roles-and-users-provisioning)
   - [Step 6: APISIX Route Provisioning](#step-6-apisix-route-provisioning)
   - [Step 7: Configuring py-phone-caller for OIDC](#step-7-configuring-py-phone-caller-for-oidc)
5. [Live Verification & Smoke Tests](#5-live-verification--smoke-tests)
6. [Day-2 Operations & Security](#6-day-2-operations--security)
7. [Troubleshooting & Common Pitfalls](#7-troubleshooting--common-pitfalls)
8. [Machine-to-Machine (M2M) & Prometheus Alertmanager Integration](#8-machine-to-machine-m2m--prometheus-alertmanager-integration)

---

## 1. Architecture Overview

In an enterprise environment, internal application services should not be directly exposed to the public internet. Instead, traffic flows through a dedicated Reverse Proxy, an API Gateway, and an Identity and Access Management (IAM) broker:

```mermaid
flowchart TB
    User(["Browser User / Mobile"])
    Prometheus(["Prometheus Alertmanager / API"])

    subgraph Internet ["Public Edge (Port 443 / 80)"]
        EdgeProxy["Apache 2 / Caddy Reverse Proxy\n(Let's Encrypt TLS Termination)"]
    end

    subgraph GatewayLayer ["Gateway & IAM Layer (Loopback / Private LAN)"]
        APISIX["Apache APISIX Unified Gateway\n(Port 9080 / 9443)"]
        ETCD[("etcd v3\n(APISIX State Store)")]
        Keycloak["Keycloak OIDC IAM Provider\n(Port 8180 / 8443)"]
        APISIXDash["APISIX Dashboard\n(Port 9001)"]
        APISIX <--> ETCD
        APISIXDash <--> ETCD
    end

    subgraph AppLayer ["py-phone-caller Core Services"]
        WebUI["py_phone_caller_ui\n(Flask/Gunicorn Port 5000)"]
        Webhook["caller_prometheus_webhook\n(Port 8084)"]
        Register["caller_register\n(Port 8083)"]
        Scheduler["caller_scheduler\n(Port 8086)"]
        AsteriskCaller["asterisk_caller\n(Port 8081)"]
        Celery["celery_worker\n(Background Tasks)"]
    end

    subgraph InfraLayer ["Infrastructure & Telephony"]
        Postgres[("Consolidated PostgreSQL\n• py_phone_caller DB\n• keycloak DB")]
        Redis[("Redis Queue")]
        Asterisk["Asterisk PBX / FreePBX\n(ARI & PJSIP)"]
    end

    User -->|HTTPS :443| EdgeProxy
    Prometheus -->|HTTPS :443 / M2M Bearer Token| EdgeProxy
    EdgeProxy -->|HTTP :9080\nX-Forwarded-Proto: https| APISIX

    APISIX -->|/realms/*, /resources/*, /admin/*| Keycloak
    APISIX -->|/* (UI Pages)| WebUI
    APISIX -->|/api/v1/*| Webhook

    WebUI -->|OIDC Token Exchange| Keycloak
    WebUI --> Postgres
    Webhook --> AsteriskCaller
    AsteriskCaller --> Asterisk
    Celery --> Redis
    Keycloak --> Postgres
```

### Key Architectural Benefits
- **Single Public URL**: All traffic enters through `https://your-domain.com`. Users don't have to juggle weird ports like `:8080` or `:5000`.
- **Zero Port Conflict**: Keycloak management runs on port `9009`, HTTP on `8180`, APISIX Dashboard on `9001`, avoiding standard port collisions.
- **Enterprise SSO & Local Fallback**: Operators can log in using Keycloak OIDC (SSO). If Keycloak is undergoing maintenance, a local database fallback account remains available.
- **Microservices Isolation**: Backend daemons (`caller_register`, `asterisk_caller`, etc.) bind only to loopback (`127.0.0.1`), protected by the gateway.

---

## 2. Role-Based Access Control (RBAC) Model

Keycloak defines 3 standardized roles inside the `py-phone-caller` realm:

| Role Name | Description | Key Capabilities |
| :--- | :--- | :--- |
| `alert-admin` | **Platform Administrator** | Full unrestricted access: user management, global configuration, diagnostic call triggers, raw audit logs. |
| `alert-operator` | **Duty Operations Engineer** | Operational access: manually dispatch calls, acknowledge (ACK) active alerts, view wallboard, manage address book. |
| `alert-viewer` | **NOC / Auditor Viewer** | Read-only access: view active calls, telemetry metrics, and status wallboards. Cannot trigger calls or modify contacts. |

---

## 3. Method A: Automated Deployment with Ansible (Recommended)

If you have Ansible installed on your workstation, the provided role will automate the entire setup in **under 3 minutes**:

### Step A.1: Configure Inventory & Public Domain
Edit `deploy/ansible/on-vm_py-phone-caller/inventory`:
```ini
[app_servers]
openalert ansible_host=your-server-ip ansible_port=22 ansible_user=root
```

In `deploy/ansible/on-vm_py-phone-caller/group_vars/app_servers/config.yml`, ensure the gateway feature is turned on:
```yaml
py_phone_caller_manage_gateway: true
py_phone_caller_public_url: "https://your-domain.com"
```

### Step A.2: Run the Playbook
From `deploy/ansible/on-vm_py-phone-caller/`:
```bash
ansible-playbook -i inventory deploy_py-phone-caller.yml
```

The playbook will:
1. Generate cryptographically strong 32-character random passwords on your control node in `credentials/`.
2. Provision container images (`etcd`, `apisix`, `apisix-dashboard`, `keycloak`) using Podman.
3. Consolidate Keycloak's database into PostgreSQL.
4. Execute `setup_keycloak.py` and `setup_apisix_routes.py`.
5. Render server credentials to `/etc/py-phone-caller/credentials.env` (`0600 root:root`).
6. Print a formatted summary table with all login accounts and passwords.

### Step A.3: Encrypt Secrets with Ansible Vault
```bash
ansible-vault encrypt credentials/*
```
To inspect credentials anytime on your control machine:
```bash
./show-credentials.sh
```

---

## 4. Method B: Step-by-Step Manual Deployment Guide

Follow these steps if you want to deploy manually on a clean Ubuntu 22.04 / 24.04 or Debian 12 server.

---

### Step 1: System Prerequisites & Dependencies

Run as `root` on your server:

```bash
# 1. Update OS package lists
apt update && apt upgrade -y

# 2. Install container runtime and system tools
apt install -y podman postgresql postgresql-contrib apache2 certbot python3-certbot-apache curl jq git
```

Ensure Podman and PostgreSQL are active:
```bash
systemctl enable --now podman
systemctl enable --now postgresql
```

---

### Step 2: Database Preparation (PostgreSQL)

Consolidate both `py_phone_caller` and `keycloak` databases into the local PostgreSQL instance:

```bash
sudo -u postgres psql <<'EOF'
-- Create application user & database
CREATE USER py_phone_caller WITH PASSWORD 'YourStrongPpcPasswordHere123!';
CREATE DATABASE py_phone_caller OWNER py_phone_caller;
GRANT ALL PRIVILEGES ON DATABASE py_phone_caller TO py_phone_caller;

-- Create Keycloak user & database
CREATE USER keycloak WITH PASSWORD 'YourStrongKeycloakPasswordHere123!';
CREATE DATABASE keycloak OWNER keycloak;
GRANT ALL PRIVILEGES ON DATABASE keycloak TO keycloak;

-- Connect to keycloak database and grant schema privileges
\c keycloak
GRANT ALL ON SCHEMA public TO keycloak;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Connect to py_phone_caller database and grant schema privileges
\c py_phone_caller
GRANT ALL ON SCHEMA public TO py_phone_caller;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
EOF
```

Allow loopback password authentication in `/etc/postgresql/*/main/pg_hba.conf`:
```text
host    all             all             127.0.0.1/32            md5
host    all             all             ::1/128                 md5
```
Reload PostgreSQL:
```bash
systemctl reload postgresql
```

---

### Step 3: Container Infrastructure (etcd, APISIX, Keycloak)

Create the required directories:
```bash
mkdir -p /etc/py-phone-caller/certs /etc/py-phone-caller/apisix /var/lib/py-phone-caller/etcd /var/lib/py-phone-caller/keycloak
```

Generate internal self-signed TLS certificates for container communication:
```bash
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/py-phone-caller/certs/gateway.key \
  -out /etc/py-phone-caller/certs/gateway.crt \
  -subj "/CN=localhost" \
  -addext "subjectAltName = DNS:localhost,IP:127.0.0.1"

chmod 0644 /etc/py-phone-caller/certs/gateway.key
```

#### 3.1 Start etcd (APISIX State Store)
Create `/etc/systemd/system/py-phone-caller-etcd.service`:
```ini
[Unit]
Description=etcd Key-Value Store for APISIX Gateway
After=network.target

[Service]
Restart=always
ExecStartPre=-/usr/bin/podman stop etcd
ExecStartPre=-/usr/bin/podman rm etcd
ExecStart=/usr/bin/podman run --name etcd --net=host \
  -v /var/lib/py-phone-caller/etcd:/etcd-data:Z \
  quay.io/coreos/etcd:v3.5.11 \
  /usr/local/bin/etcd \
  --data-dir=/etcd-data \
  --listen-client-urls=http://127.0.0.1:2379 \
  --advertise-client-urls=http://127.0.0.1:2379
ExecStop=/usr/bin/podman stop -t 10 etcd

[Install]
WantedBy=multi-user.target
```

#### 3.2 Configure & Start Apache APISIX
Create `/etc/py-phone-caller/apisix/config.yaml`:
```yaml
apisix:
  node_listen:
    - 127.0.0.1:9080
  enable_ipv6: false
  enable_admin: true
  enable_control: true
  control:
    ip: "127.0.0.1"
    port: 9090

deployment:
  role: traditional
  role_traditional:
    config_provider: etcd
  admin:
    admin_key:
      - name: admin
        key: edd1c9f034335f136f87ad84b625c8f1
        role: admin
  etcd:
    host:
      - "http://127.0.0.1:2379"
    prefix: "/apisix"
    timeout: 30
```

Create `/etc/systemd/system/py-phone-caller-apisix.service`:
```ini
[Unit]
Description=Apache APISIX API Gateway
After=network.target py-phone-caller-etcd.service
Requires=py-phone-caller-etcd.service

[Service]
Restart=always
ExecStartPre=-/usr/bin/podman stop apisix
ExecStartPre=-/usr/bin/podman rm apisix
ExecStart=/usr/bin/podman run --name apisix --net=host \
  -v /etc/py-phone-caller/apisix/config.yaml:/usr/local/apisix/conf/config.yaml:ro,Z \
  -v /etc/py-phone-caller/certs:/opt/certs:ro,Z \
  docker.io/apache/apisix:latest
ExecStop=/usr/bin/podman stop -t 10 apisix

[Install]
WantedBy=multi-user.target
```

#### 3.3 Configure & Start APISIX Dashboard
Create `/etc/py-phone-caller/apisix/dashboard_conf.yaml`:
```yaml
conf:
  listen:
    host: 127.0.0.1
    port: 9001
  etcd:
    endpoints:
      - 127.0.0.1:2379
  authentication:
    secret: "change_this_secret_key_32_chars_long!"
    users:
      - username: admin
        password: "YourDashboardAdminPassword123!"
```

Create `/etc/systemd/system/py-phone-caller-apisix-dashboard.service`:
```ini
[Unit]
Description=Apache APISIX Dashboard
After=network.target py-phone-caller-etcd.service
Requires=py-phone-caller-etcd.service

[Service]
Restart=always
ExecStartPre=-/usr/bin/podman stop apisix-dashboard
ExecStartPre=-/usr/bin/podman rm apisix-dashboard
ExecStart=/usr/bin/podman run --name apisix-dashboard --net=host \
  -v /etc/py-phone-caller/apisix/dashboard_conf.yaml:/usr/local/apisix-dashboard/conf/conf.yaml:ro,Z \
  docker.io/apache/apisix-dashboard:3.0.1-alpine
ExecStop=/usr/bin/podman stop -t 10 apisix-dashboard

[Install]
WantedBy=multi-user.target
```

#### 3.4 Configure & Start Keycloak IAM
Create `/etc/systemd/system/py-phone-caller-keycloak.service` (replace `your-domain.com` with your real domain):
```ini
[Unit]
Description=Keycloak IAM Service for py-phone-caller
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Restart=always
ExecStartPre=-/usr/bin/podman stop keycloak
ExecStartPre=-/usr/bin/podman rm keycloak
ExecStart=/usr/bin/podman run --name keycloak --net=host \
  -v /etc/py-phone-caller/certs:/opt/keycloak/certs:ro,Z \
  -v /var/lib/py-phone-caller/keycloak:/opt/keycloak/data:Z \
  -e KC_DB=postgres \
  -e KC_DB_URL=jdbc:postgresql://127.0.0.1:5432/keycloak \
  -e KC_DB_USERNAME=keycloak \
  -e KC_DB_PASSWORD=YourStrongKeycloakPasswordHere123! \
  -e KEYCLOAK_ADMIN=admin \
  -e KEYCLOAK_ADMIN_PASSWORD=YourMasterAdminPassword123! \
  -e KC_HTTPS_CERTIFICATE_FILE=/opt/keycloak/certs/gateway.crt \
  -e KC_HTTPS_CERTIFICATE_KEY_FILE=/opt/keycloak/certs/gateway.key \
  -e KC_HTTPS_PORT=8443 \
  -e KC_HTTP_PORT=8180 \
  -e KC_HEALTH_ENABLED=true \
  -e KC_METRICS_ENABLED=true \
  -e KC_PROXY_HEADERS=xforwarded \
  -e KC_HOSTNAME=https://your-domain.com \
  -e KC_HOSTNAME_STRICT=true \
  quay.io/keycloak/keycloak:latest \
  start-dev --http-management-port=9009
ExecStop=/usr/bin/podman stop -t 30 keycloak

[Install]
WantedBy=multi-user.target
```

Enable and start the container stack:
```bash
systemctl daemon-reload
systemctl enable --now py-phone-caller-etcd py-phone-caller-apisix py-phone-caller-apisix-dashboard py-phone-caller-keycloak
```

---

### Step 4: Apache 2 / Caddy Public TLS Ingress

#### Using Apache 2:
Enable the required Apache modules:
```bash
a2enmod proxy proxy_http proxy_wstunnel headers ssl rewrite
```

Create `/etc/apache2/sites-available/py-phone-caller.conf`:
```apache
<VirtualHost *:80>
    ServerName your-domain.com
    RewriteEngine On
    RewriteRule ^(.*)$ https://%{HTTP_HOST}$1 [R=301,L]
</VirtualHost>

<VirtualHost *:443>
    ServerName your-domain.com

    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/your-domain.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/your-domain.com/privkey.pem

    # Proxy headers for APISIX & Keycloak Hostname v2
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-Port "443"

    ProxyPreserveHost On

    # Forward WebSocket connections
    RewriteEngine On
    RewriteCond %{HTTP:Upgrade} websocket [NC]
    RewriteCond %{HTTP:Connection} upgrade [NC]
    RewriteRule ^/?(.*) ws://127.0.0.1:9080/$1 [P,L]

    # Forward all HTTP requests to APISIX Gateway
    ProxyPass / http://127.0.0.1:9080/
    ProxyPassReverse / http://127.0.0.1:9080/
</VirtualHost>
```

Enable the site and reload Apache:
```bash
a2ensite py-phone-caller.conf
systemctl reload apache2
```

---

### Step 5: Keycloak Realm, Roles, and Users Provisioning

Run the automated provisioning script [`setup_keycloak.py`](file:///home/jcf/Workspace/PyCharm/py-phone-caller_release-github/deploy/gateway/keycloak/setup_keycloak.py):

```bash
KEYCLOAK_URL="http://127.0.0.1:8180" \
KEYCLOAK_ADMIN_USER="admin" \
KEYCLOAK_ADMIN_PASS="YourMasterAdminPassword123!" \
KEYCLOAK_REALM="py-phone-caller" \
KEYCLOAK_PUBLIC_URL="https://your-domain.com" \
KEYCLOAK_USER_ADMIN_PASS="SecretAdminPassword123!" \
KEYCLOAK_USER_OPERATOR_PASS="SecretOperatorPassword123!" \
KEYCLOAK_USER_VIEWER_PASS="SecretViewerPassword123!" \
python3 /opt/py-phone-caller/deploy/gateway/keycloak/setup_keycloak.py
```

This will automatically create:
- Realm: `py-phone-caller`
- Roles: `alert-admin`, `alert-operator`, `alert-viewer`
- OIDC Client: `py-phone-caller-ui` (Public, PKCE standard flow)
- M2M Client: `py-phone-caller-m2m` (Client credentials flow)
- Users: `admin_user`, `operator_user`, `viewer_user`

---

### Step 6: APISIX Route Provisioning

Run [`setup_apisix_routes.py`](file:///home/jcf/Workspace/PyCharm/py-phone-caller_release-github/deploy/gateway/apisix/setup_apisix_routes.py) to configure routing inside APISIX:

```bash
APISIX_DASHBOARD_URL="http://127.0.0.1:9001" \
APISIX_DASHBOARD_USER="admin" \
APISIX_DASHBOARD_PASS="YourDashboardAdminPassword123!" \
UPSTREAM_HOST="127.0.0.1" \
KEYCLOAK_PORT="8180" \
python3 /opt/py-phone-caller/deploy/gateway/apisix/setup_apisix_routes.py
```

This configures APISIX to route:
- `/realms/*`, `/resources/*`, `/admin/*` $\to$ Keycloak (`127.0.0.1:8180`)
- `/*` $\to$ Web UI (`127.0.0.1:5000`)
- `/api/v1/*` $\to$ Backend microservice endpoints

---

### Step 7: Configuring py-phone-caller for OIDC

In your application configuration `/opt/py-phone-caller/app/config/settings.toml`:

```toml
[auth]
provider = "keycloak"
local_fallback_enabled = true

[auth.oauth2]
enabled = true
issuer_url = "https://your-domain.com/realms/py-phone-caller"
client_id = "py-phone-caller-ui"
client_secret = ""
redirect_uri = "https://your-domain.com/oauth2/callback"
scopes = ["openid", "profile", "email", "roles"]
username_claim = "preferred_username"
roles_claim = "roles"

[auth.oauth2.role_mapping]
admin_role = "alert-admin"
operator_role = "alert-operator"
viewer_role = "alert-viewer"
```

Restart the UI service:
```bash
systemctl restart py-phone-caller-py-phone-caller-ui.service
```

---

## 5. Live Verification & Smoke Tests

Verify each component from your terminal:

### 1. Check Keycloak OIDC Discovery:
```bash
curl -s https://your-domain.com/realms/py-phone-caller/.well-known/openid-configuration | grep '"issuer"'
# Expected output: "issuer": "https://your-domain.com/realms/py-phone-caller"
```

### 2. Verify SSO Token Issuance:
```bash
curl -s -X POST https://your-domain.com/realms/py-phone-caller/protocol/openid-connect/token \
  -d "client_id=py-phone-caller-ui" \
  -d "username=admin_user" \
  -d "password=SecretAdminPassword123!" \
  -d "grant_type=password" | jq .access_token
```

### 3. Verify in Browser:
1. Navigate to: `https://your-domain.com/login`
2. Click **"Sign in with Single Sign-On"**
3. Log in with `admin_user` / `SecretAdminPassword123!`
4. You should be redirected directly into the dashboard with the **Administrator** badge!

---

## 6. Day-2 Operations & Security

### Managing Users in Keycloak Admin Console
1. Navigate to: `https://your-domain.com/admin`
2. Log in as master `admin`.
3. In the top-left dropdown, switch from `master` to the `py-phone-caller` realm.
4. Go to **Users** $\to$ **Add user** to create operators or engineers.
5. In the user's **Role mapping** tab, assign either `alert-admin`, `alert-operator`, or `alert-viewer`.

### Federating with Enterprise Identity Providers (GitHub, Google, Entra ID)
In the Keycloak Admin Console (`py-phone-caller` realm):
1. Go to **Identity Providers** $\to$ Click **GitHub** / **Google** / **OpenID Connect v1.0**.
2. Paste your corporate Client ID and Client Secret.
3. Users will now see a *"Log in with GitHub"* or *"Log in with Google"* button automatically on your portal login page!

### Inspecting Deployment Credentials
If you deployed using Ansible, check credentials on your server:
```bash
cat /etc/py-phone-caller/credentials.env
```
Or on your control workstation:
```bash
./show-credentials.sh
```

---

## 7. Troubleshooting & Common Pitfalls

| Issue | Root Cause | Solution |
| :--- | :--- | :--- |
| **502 Bad Gateway on Keycloak routes** | Keycloak Quarkus JVM takes 15–30 seconds to boot on container start. | Wait 30 seconds and check `podman logs keycloak`. Ensure it says `Listening on: http://0.0.0.0:8180`. |
| **Invalid Parameter: redirect_uri** | The browser redirect URI does not match the allowed list in Keycloak client. | In Keycloak Admin UI, open `py-phone-caller-ui` client $\to$ check **Valid redirect URIs**. Add `https://your-domain.com/*`. |
| **Port Conflict on 9000** | APISIX Dashboard default (9000) conflicts with Keycloak management port. | We run APISIX Dashboard on port `9001` and Keycloak management on `9009`. |
| **Infinite Login Loop** | Reverse proxy is stripping `X-Forwarded-Proto` header. | In Apache, ensure `RequestHeader set X-Forwarded-Proto "https"` is configured inside the `<VirtualHost *:443>`. |
| **Local Fallback Admin Password Forgotten** | Local database password needs reset. | Set `UI_USER_RESET_PASSWORD=true` in `/etc/py-phone-caller/credentials.env` and restart `py-phone-caller-py-phone-caller-ui.service`. |

---

## 8. Machine-to-Machine (M2M) & Prometheus Alertmanager Integration

In an enterprise monitoring stack, external systems like **Prometheus Alertmanager** should authenticate securely using OAuth2 client credentials before dispatching incident alerts.

### How M2M Works:
1. Keycloak provides a dedicated confidential client `py-phone-caller-m2m` with `serviceAccountsEnabled = true`.
2. The service account user is assigned the `alert-operator` realm role.
3. Prometheus Alertmanager requests a short-lived JWT token from Keycloak.
4. Alertmanager sends the alert payload to APISIX (`POST /api/v1/alerts/call_only`) with `Authorization: Bearer <TOKEN>`.
5. The request is processed by `caller_prometheus_webhook` and queued for telephone/SMS dispatch.

### Testing Token Generation & Webhook Dispatch Manually:

```bash
# 1. Fetch OAuth2 Bearer Token from Keycloak
M2M_SECRET=$(cat /etc/py-phone-caller/credentials.env | grep KEYCLOAK_M2M_CLIENT_SECRET | cut -d= -f2)

TOKEN=$(curl -k -s -X POST https://your-domain.com/realms/py-phone-caller/protocol/openid-connect/token \
  -d "grant_type=client_credentials" \
  -d "client_id=py-phone-caller-m2m" \
  -d "client_secret=${M2M_SECRET}" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")

echo "Acquired M2M Bearer Token: ${TOKEN:0:30}..."

# 2. Dispatch a Test Alert Payload via APISIX Gateway
curl -s -X POST https://your-domain.com/api/v1/alerts/call_only \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "ProductionDatabaseHighLoad",
          "severity": "critical"
        },
        "annotations": {
          "description": "Production PostgreSQL active connections exceeded 95%"
        }
      }
    ]
  }'
```

### Production `alertmanager.yml` Webhook Configuration:

```yaml
# /etc/alertmanager/alertmanager.yml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'cluster', 'service']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'py-phone-caller-m2m'
  routes:
    - match:
        severity: critical
      receiver: 'py-phone-caller-call-and-sms'
    - match:
        severity: warning
      receiver: 'py-phone-caller-sms-only'

receivers:
  # Emergency Phone Call via M2M OAuth2
  - name: 'py-phone-caller-m2m'
    webhook_configs:
      - url: 'https://alerts.example.com/api/v1/alerts/call_only'
        send_resolved: false
        http_config:
          oauth2:
            client_id: 'py-phone-caller-m2m'
            client_secret: '<YOUR_M2M_CLIENT_SECRET>'
            token_url: 'https://alerts.example.com/realms/py-phone-caller/protocol/openid-connect/token'
            scopes: ['email', 'profile']

  # Emergency Call & SMS via M2M OAuth2
  - name: 'py-phone-caller-call-and-sms'
    webhook_configs:
      - url: 'https://alerts.example.com/api/v1/alerts/call_and_sms'
        send_resolved: false
        http_config:
          oauth2:
            client_id: 'py-phone-caller-m2m'
            client_secret: '<YOUR_M2M_CLIENT_SECRET>'
            token_url: 'https://alerts.example.com/realms/py-phone-caller/protocol/openid-connect/token'
            scopes: ['email', 'profile']

  # SMS Only via M2M OAuth2
  - name: 'py-phone-caller-sms-only'
    webhook_configs:
      - url: 'https://alerts.example.com/api/v1/alerts/sms_only'
        send_resolved: false
        http_config:
          oauth2:
            client_id: 'py-phone-caller-m2m'
            client_secret: '<YOUR_M2M_CLIENT_SECRET>'
            token_url: 'https://alerts.example.com/realms/py-phone-caller/protocol/openid-connect/token'
            scopes: ['email', 'profile']
```

> [!NOTE]
> **Complete Standalone Compatibility**: If deployed without APISIX or Keycloak, simply point Alertmanager directly at `http://<internal-ip>:8084/<route>` without the `http_config.oauth2` block. The system accepts unauthenticated requests within trusted internal networks automatically.
