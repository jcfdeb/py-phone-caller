# 📖 py-phone-caller Operator Installation Guide (A to Z)

Welcome to the comprehensive, step-by-step installation and operations guide for **py-phone-caller**. This document is designed for system administrators, DevOps engineers, and Site Reliability Engineers (SREs) who are deploying **py-phone-caller** for the first time.

Whether you are deploying onto bare-metal servers, virtual machines with native systemd services, or containerized environments using Docker/Podman Compose, this guide walks you through every single step from A to Z.

---

## 📑 Table of Contents

1. [Architectural Overview & The Big Picture](#1-architectural-overview--the-big-picture)
2. [Prerequisites & System Sizing](#2-prerequisites--system-sizing)
3. [Network Topology, Ports & Security](#3-network-topology-ports--security)
4. [Method A: Automated Deployment with Ansible (On-VM / Systemd)](#4-method-a-automated-deployment-with-ansible-on-vm--systemd)
   - [4.1 Inventory Configuration](#41-inventory-configuration)
   - [4.2 Credentials & Secret Management](#42-credentials--secret-management)
   - [4.3 Deploying Asterisk PBX with Ansible](#43-deploying-asterisk-pbx-with-ansible)
   - [4.4 Deploying py-phone-caller Services with Ansible](#44-deploying-py-phone-caller-services-with-ansible)
   - [4.5 Verifying Native Systemd Services](#45-verifying-native-systemd-services)
5. [Method B: Containerized Deployment with Docker / Podman Compose](#5-method-b-containerized-deployment-with-docker--podman-compose)
   - [5.1 Host Prerequisites & Container Engine](#51-host-prerequisites--container-engine)
   - [5.2 Building or Pulling Container Images](#52-building-or-pulling-container-images)
   - [5.3 Generating Cloud-Native Dynaconf Environment Files](#53-generating-cloud-native-dynaconf-environment-files)
   - [5.4 Starting the Compose Stack](#54-starting-the-compose-stack)
   - [5.5 First-Time Admin Account Bootstrap](#55-first-time-admin-account-bootstrap)
6. [Post-Installation Verification & Smoke Testing](#6-post-installation-verification--smoke-testing)
   - [6.1 Automated Health & Metric Verification Script](#61-automated-health--metric-verification-script)
   - [6.2 Navigating the Web UI](#62-navigating-the-web-ui)
   - [6.3 Configuring On-Call Contacts](#63-configuring-on-call-contacts)
   - [6.4 Triggering Your First Incident Call](#64-triggering-your-first-incident-call)
   - [6.5 Triggering Your First SMS Notification](#65-triggering-your-first-sms-notification)
7. [Monitoring Integrations (Alertmanager, Nagios, Zabbix)](#7-monitoring-integrations-alertmanager-nagios-zabbix)
   - [7.1 Prometheus Alertmanager Webhook](#71-prometheus-alertmanager-webhook)
   - [7.2 Nagios Event Handler Script](#72-nagios-event-handler-script)
   - [7.3 Zabbix Alert Script](#73-zabbix-alert-script)
8. [Air-Gapped & Offline Deployments](#8-air-gapped--offline-deployments)
9. [Troubleshooting & Operational Runbook](#9-troubleshooting--operational-runbook)

---

## 1. Architectural Overview & The Big Picture

**py-phone-caller** is an enterprise-grade automated voice call and SMS incident dispatch platform. It bridges monitoring systems (Prometheus, Nagios, Zabbix, Grafana) with telephony systems (Asterisk PBX, SIP Trunks, GSM modems, Twilio) to reliably alert on-call staff during critical infrastructure outages.

### The 11 Microservices Stack

```text
                                  +-----------------------+
                                  | Prometheus / Nagios / |
                                  | Zabbix Alert Systems  |
                                  +-----------------------+
                                              |
                                              v
                               +-----------------------------+
                               |  caller_prometheus_webhook  |
                               +-----------------------------+
                                     |               |
             +-----------------------+               +-----------------------+
             | (Enqueues Calls)                              | (Dispatches SMS)
             v                                               v
+-------------------------+                       +-------------------------+
|     asterisk_caller     |                       |       caller_sms        |
|  (Manages Call Queue)   |                       | (Twilio / Rust Engine)  |
+-------------------------+                       +-------------------------+
    |                 |                                       |
    | (ARI Outbound)  | (Queries On-Call)                     | (Writes SMS log)
    v                 v                                       v
+--------------+  +---------------------+         +-------------------------+
| Asterisk PBX |  | caller_address_book |         |  PostgreSQL 17 Database |
| (SIP Trunk / |  |   (Contacts Table)  |         | (Calls, Users, Contacts,|
| Stasis App)  |  +---------------------+         |  SMS, Events, Schedules)|
+--------------+              |                   +-------------------------+
    | (WS Events)             |                               ^
    v                         v                               |
+---------------------+   +---------------------+             |
| asterisk_ws_monitor |-->|   caller_register   |-------------+
+---------------------+   | (Central DB Schema) |
    |                     +---------------------+
    | (TTS Audio Req)                 ^
    v                                 |
+---------------------+   +---------------------+   +---------------------+
|   generate_audio    |   |  asterisk_recaller  |   |  caller_scheduler   |
| (Kokoro/MMS/Piper)  |   | (Auto-Retry Engine) |   |   & celery_worker   |
+---------------------+   +---------------------+   +---------------------+
                                                              ^
                                                              |
                                                    +-------------------+
                                                    |  Redis 7 / Valkey |
                                                    +-------------------+
```

### Domain-Driven Data Model
- **`caller_register`**: Central orchestrator for database migrations and schema reconciliation via Piccolo ORM. Manages the `calls`, `scheduled_calls`, and `asterisk_ws_events` tables.
- **`caller_address_book`**: Manages on-call personnel availability, rotations, and phone numbers (`address_book` table).
- **`caller_sms`**: Manages outbound SMS dispatch and message tracking (`sms` table).
- **`py_phone_caller_ui`**: Backend-For-Frontend web console providing real-time call dashboards, DTMF acknowledgment logs, SMS history, and user authentication (`users` table).

---

## 2. Prerequisites & System Sizing

### Minimum System Specifications

| Component | Minimum Spec | Recommended Production Spec |
| :--- | :--- | :--- |
| **CPU** | 2 vCPUs | 4+ vCPUs (faster TTS speech synthesis) |
| **RAM** | 4 GB | 8 GB (TTS ML models require ~1.5 GB in memory) |
| **Disk** | 20 GB SSD | 50 GB SSD (for audio caching and PostgreSQL data) |
| **Operating System** | Ubuntu 22.04 / 24.04 / 26.04 LTS<br>Debian 12<br>RHEL / Rocky Linux 9 / 10<br>AlmaLinux 9 / 10 | Ubuntu 24.04 LTS or Rocky Linux 9/10 |

### Software Prerequisites on Target Host
- **For Native Ansible Setup**: Python 3.10+ (installed automatically via `uv`), Git, curl.
- **For Containerized Setup**:
  - Docker Engine 24.0+ with Docker Compose v2 (`docker compose`), **OR**
  - Podman 4.5+ with Podman Compose (`podman compose`).
- **Python Workspace Tooling**: `uv` (modern fast Python package manager).

### Telephony & Infrastructure Requirements
- **Asterisk PBX (v18+ / v20+) / FreePBX**:
  - SIP/PJSIP trunk configured to dial outbound landlines and mobile numbers.
  - ARI enabled (`ari.conf`) with HTTP/WebSocket listeners (default port `8088`), username `py-phone-caller`, and password.
  - Stasis application context registered in `extensions.conf`.
- **PostgreSQL (v15+ / v17+)**: Relational store for calls, schedules, events, users, contacts, and SMS logs (migrations managed by `caller_register`).
- **Redis (v7+) / Valkey**: Celery task queue broker on port `6379`.

### Text-to-Speech (TTS) Requirements: Local vs. Cloud
- **Offline Local Neural TTS (Kokoro-82M, Piper, Facebook MMS)**:
  - **Zero cloud accounts needed.** Runs 100% on CPU locally in air-gapped environments.
  - Requires `ffmpeg` on the host/container and pre-trained model weights in `pre_trained_models/`.
- **Cloud TTS (AWS Polly)**:
  - Requires an active AWS account with IAM credentials (`aws_access_key_id`, `aws_secret_access_key`, `aws_polly_region_name`) and `polly:SynthesizeSpeech` permissions.

### SMS Dispatch Requirements: Hardware USB Modem vs. Cloud
- **On-Premise Hardware Modem (`on_premise`)**:
  - Physical USB GSM / 3G / 4G LTE Modem (e.g. Qualcomm / Option `1e0e:9001`, Huawei, SIMCom using Linux `option` kernel driver).
  - Active SIM card with an SMS texting plan.
  - Access to serial device nodes (`/dev/ttyUSB0`..`/dev/ttyUSB3`) with permissions in the `dialout` group.
- **Cloud SMS (`twilio`)**:
  - Active Twilio account with Account SID (`twilio_account_sid`), Auth Token (`twilio_auth_token`), and sender number (`twilio_sms_from`).
  - Outbound Internet access to `api.twilio.com`. Zero physical hardware required.

---

## 3. Network Topology, Ports & Security

### Port Allocation Chart

All services bind to localhost (`127.0.0.1`) or the internal container bridge network. Only the Reverse Proxy (Caddy/Nginx) and Asterisk PBX need external exposure within your trusted LAN.

| Port | Protocol | Service | Description |
| :--- | :--- | :--- | :--- |
| **80 / 443** | TCP | Caddy Reverse Proxy | Web UI and API entrypoint |
| **5000** | TCP | `py_phone_caller_ui` | Internal Web Management UI |
| **8081** | TCP | `asterisk_caller` | Call Queue & Outbound Call REST API |
| **8082** | TCP | `generate_audio` | Neural TTS Audio Generation API |
| **8083** | TCP | `caller_register` | Call Registry & DB Migration Controller |
| **8084** | TCP | `caller_prometheus_webhook` | Prometheus Alertmanager Receiver |
| **8085** | TCP | `caller_sms` | SMS Dispatcher (Twilio / GSM Modem) |
| **8086** | TCP | `caller_scheduler` | Celery Scheduled Call Coordinator |
| **8087** | TCP | `caller_address_book` | Contact Directory & On-Call Solver API |
| **5432** | TCP | PostgreSQL 17 | Relational Database |
| **6379** | TCP | Redis 7 / Valkey | Task Queue Broker |
| **8088** | TCP / WS | Asterisk PBX | Asterisk REST Interface (ARI) & Stasis WS |
| **5060 / 5160**| UDP/TCP | Asterisk PBX | SIP Signaling (PJSIP / chan_sip) |
| **10000-20000**| UDP | Asterisk PBX | RTP Audio Stream Range |

> 🔒 **Security Notice**: Never expose py-phone-caller REST APIs directly to the public Internet without an authentication gateway (such as Caddy, Nginx with mTLS/Basic Auth, or Apache APISIX). Always deploy within a private management VLAN or VPN.

---

## 4. Method A: Automated Deployment with Ansible (On-VM / Systemd)

The Ansible automation suite located in `assets/ansible/` provides a production-grade, unattended deployment that installs PostgreSQL 17, Redis/Valkey, Asterisk PBX, and all 11 Python systemd services.

### 4.1 Inventory Configuration

1. On your Ansible control node, clone the repository:
   ```bash
   git clone https://github.com/your-org/py-phone-caller.git
   cd py-phone-caller/assets/ansible/deploy_all
   ```

2. Configure your target servers in `../on-vm_py-phone-caller/inventory.ini`:
   ```ini
   [app_servers]
   alert-node-01 ansible_host=10.0.55.251 ansible_user=admin

   [app_servers:vars]
   ansible_become=yes
   ansible_python_interpreter=/usr/bin/python3
   ```

3. Test SSH connectivity:
   ```bash
   ansible -i ../on-vm_py-phone-caller/inventory.ini app_servers -m ping
   ```

---

### 4.2 Credentials & Secret Management

Create or edit `deploy_py-phone-caller_stack.yml` to specify passwords and credentials.

```yaml
---
- name: Deploy Complete py-phone-caller Production Stack
  hosts: app_servers
  become: yes
  vars:
    # Path to repository root on control node
    py_phone_caller_local_src_path: "{{ playbook_dir }}/../../.."

    # PostgreSQL administrative credentials for unattended provisioning
    py_phone_caller_db_admin_user: "postgres"
    py_phone_caller_db_admin_password: "YourSecurePostgresAdminPassword"

    # Application secrets
    vault_db_password: "StrongAppDatabasePassword123!"
    vault_ari_password: "StrongAsteriskAriPassword123!"

    # Configuration overrides
    py_phone_caller_config:
      commons:
        asterisk_host: "127.0.0.1"
        asterisk_port: "8088"
        asterisk_user: "py-phone-caller"
        asterisk_pass: "{{ vault_ari_password }}"
      database:
        db_host: "127.0.0.1"
        db_user: "py_phone_caller"
        db_password: "{{ vault_db_password }}"
        db_name: "py_phone_caller"
      queue:
        queue_host: "127.0.0.1"
        queue_url: "redis://127.0.0.1:6379/7"
      sms:
        caller_sms_carrier: "twilio" # Options: "twilio" or "on_premise"
        twilio_sms_from: "+15551234567"
        twilio_account_sid: "ACXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        twilio_auth_token: "your_twilio_auth_token"

  roles:
    - deploy_py-phone-caller
```

> 💡 **Best Practice**: Use `ansible-vault` to encrypt sensitive variables:
> ```bash
> ansible-vault encrypt_string 'StrongAppDatabasePassword123!' --name 'vault_db_password'
> ```

---

### 4.3 Deploying Asterisk PBX with Ansible

If your target VM is also hosting Asterisk PBX, deploy and configure Asterisk with ARI and custom dialplans:

```bash
cd ../asterisk_py-phone-caller
ansible-playbook -i ../on-vm_py-phone-caller/inventory.ini deploy_asterisk.yml
```

This playbook automatically:
1. Installs Asterisk packages (`asterisk`, `asterisk-pjsip`, `asterisk-sounds-core-en`).
2. Configures `http.conf` (enables ARI HTTP server on port 8088).
3. Configures `ari.conf` (creates ARI user `py-phone-caller` with read/write permissions).
4. Configures `extensions.conf` (sets up Stasis application `py-phone-caller`).
5. Installs sound files and prompts.
6. Starts and enables the `asterisk` systemd service.

---

### 4.4 Deploying py-phone-caller Services with Ansible

Deploy the full microservice ecosystem:

```bash
cd ../deploy_all
ansible-playbook -i ../on-vm_py-phone-caller/inventory.ini deploy_py-phone-caller_stack.yml
```

**What the role does automatically (Unattended):**
1. **OS Packages**: Installs PostgreSQL 17, Redis/Valkey, build tools, ffmpeg, libsndfile.
2. **Database Provisioning**: Idempotently creates the `py_phone_caller` PostgreSQL user, database, schema permissions, and activates `uuid-ossp` and `pgcrypto` extensions.
3. **Dedicated User**: Creates system user `py-phone-caller` with `/opt/py-phone-caller` home.
4. **Source Synchronization**: Syncs the workspace codebase into `/opt/py-phone-caller/app`.
5. **Python 3.14 Runtime**: Automatically installs managed Python 3.14 and runs `uv sync --frozen --all-packages --no-dev`.
6. **Rust SMS Compilation**: Compiles the native Rust modem acceleration engine via Maturin.
7. **Systemd Services**: Generates and enables 11 systemd unit files:
   - `py-phone-caller-caller-register.service`
   - `py-phone-caller-asterisk-caller.service`
   - `py-phone-caller-asterisk-ws-monitor.service`
   - `py-phone-caller-asterisk-recaller.service`
   - `py-phone-caller-caller-address-book.service`
   - `py-phone-caller-caller-scheduler.service`
   - `py-phone-caller-caller-prometheus-webhook.service`
   - `py-phone-caller-caller-sms.service`
   - `py-phone-caller-generate-audio.service`
   - `py-phone-caller-py-phone-caller-ui.service`
   - `py-phone-caller-celery-worker.service`
8. **Caddy Reverse Proxy**: Configures HTTPS reverse proxy terminating traffic to Web UI and APIs.

---

### 4.5 Verifying Native Systemd Services

SSH into the target host and inspect the status of all services:

```bash
ssh admin@10.0.55.251
sudo systemctl list-units 'py-phone-caller*' --all
```

To view logs for any individual service in real time:
```bash
sudo journalctl -u py-phone-caller-caller-register -f
sudo journalctl -u py-phone-caller-asterisk-caller -f
```

---

## 5. Method B: Containerized Deployment with Docker / Podman Compose

The containerized deployment packages the complete stack into 14 containers (11 microservices + PostgreSQL + Redis + Caddy) with isolated networks and healthchecks.

### 5.1 Host Prerequisites & Container Engine

Ensure either Docker with Compose v2 or Podman with Podman Compose is installed:

**On Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
```

**On Rocky Linux / AlmaLinux / RHEL:**
```bash
sudo dnf install -y podman podman-docker podman-compose
```

---

### 5.2 Building or Pulling Container Images

#### Option 1: Build Local Images from Source
From the root of the repository, execute the universal build script:

```bash
./src/build_all_images.sh
```

To customize the container engine, registry name, or image tag:
```bash
CONTAINER_ENGINE=podman IMAGE_REGISTRY=localhost IMAGE_TAG=1.0.0 ./src/build_all_images.sh
```

#### Option 2: Using Pre-Built Images from Local / Air-Gapped Registry
If images are hosted on an internal registry (e.g. `artifacts.py-phone-caller.lan:5000`), export the registry prefix:
```bash
export MY_DOCKER_REGISTRY="artifacts.py-phone-caller.lan:5000"
export VERSION="1.0.0"
```

---

### 5.3 Generating Cloud-Native Dynaconf Environment Files

`py-phone-caller` utilizes cloud-native environment variable injection. Configurations are generated from `settings.toml` and `.secrets.toml` into clean `.env` files:

```bash
# Create the environment directory
mkdir -p assets/docker-compose/env

# Convert base settings
uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --input src/config/settings.toml \
  --output assets/docker-compose/env/py-phone-caller.env

# Convert secrets (if present)
uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --ignore-missing \
  --input src/config/.secrets.toml \
  --output assets/docker-compose/env/py-phone-caller.secrets.env
```

If Asterisk is running on the host machine outside containers, ensure `settings.toml` or your environment overrides Asterisk host:
```bash
export ASTERISK_HOST="host.containers.internal" # For Docker/Podman host communication
```

---

### 5.4 Starting the Compose Stack

Navigate to `assets/docker-compose/` and start the stack in detached mode:

```bash
cd assets/docker-compose
docker compose up -d
```
*(Or `podman compose up -d`)*

Verify all containers reach healthy status:
```bash
docker compose ps
```

Expected output:
```text
NAME                                IMAGE                            STATUS
py-phone-caller-db                  postgres:17-alpine               Up (healthy)
py-phone-caller-redis               redis:7-alpine                   Up (healthy)
caller-register                     localhost/caller_register:1.0.0  Up (healthy)
asterisk-caller                     localhost/asterisk_caller:1.0.0  Up (healthy)
asterisk-ws-monitor                 localhost/asterisk_ws_monitor    Up (healthy)
asterisk-recaller                   localhost/asterisk_recaller      Up (healthy)
caller-address-book                 localhost/caller_address_book    Up (healthy)
caller-scheduler                    localhost/caller_scheduler       Up (healthy)
caller-prometheus-webhook           localhost/caller_prometheus_...  Up (healthy)
caller-sms                          localhost/caller_sms:1.0.0       Up (healthy)
generate-audio                      localhost/generate_audio:1.0.0   Up (healthy)
py-phone-caller-ui                  localhost/py_phone_caller_ui     Up (healthy)
celery-worker                       localhost/celery_worker:1.0.0    Up (healthy)
caddy                               caddy:2-alpine                   Up
```

---

### 5.5 First-Time Admin Account Bootstrap

On a fresh installation, create the default administrator user for the Web UI:

1. Launch with the admin bootstrap flag:
   ```bash
   UI_USER_RESET_PASSWORD=true docker compose up -d py_phone_caller_ui
   ```

2. Inspect the UI container log to retrieve the randomly generated temporary admin password:
   ```bash
   docker compose logs py_phone_caller_ui | grep "Admin user created"
   ```

3. Log in at `http://<server-ip>:5000` with:
   - **Username**: `admin@py-phone-caller.link`
   - **Password**: *(The generated password from logs)*

4. Change the admin password in the Web UI, then remove the environment override:
   ```bash
   UI_USER_RESET_PASSWORD=false docker compose up -d py_phone_caller_ui
   ```

---

## 6. Post-Installation Verification & Smoke Testing

### 6.1 Automated Health & Metric Verification Script

The repository includes a comprehensive verification test suite (`verify_deployment.py`) that probes all microservices for `/health` JSON responses, Prometheus `/metrics` scraping, and dynamic TTS audio generation:

From your workstation or control node:
```bash
VERIFY_HOST="10.0.55.251" uv run python verify_deployment.py
```

Expected output:
```text
======================================================================
🔎 Starting py-phone-caller deployment verification on 10.0.55.251
======================================================================

Checking asterisk_caller (port 8081)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'asterisk_caller', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2482 bytes)

Checking generate_audio (port 8082)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'generate_audio', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2410 bytes)

Checking caller_register (port 8083)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_register', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2515 bytes)

Checking caller_prometheus_webhook (port 8084)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_prometheus_webhook', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2390 bytes)

Checking caller_sms (port 8085)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_sms', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2412 bytes)

Checking caller_scheduler (port 8086)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_scheduler', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2405 bytes)

Checking caller_address_book (port 8087)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_address_book', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2520 bytes)

Checking py_phone_caller_ui (port 5000)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'py_phone_caller_ui', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2150 bytes)

Testing Audio Generation & Polling Flow...
  ✓ Audio generation request initiated (POST /make_audio) -> Checksum: 5b9a5cfb
  ✓ Audio file generation confirmed ready (GET /is_audio_ready)

======================================================================
🎉 ALL CHECKS PASSED: py-phone-caller deployment is 100% operational!
======================================================================
```

---

### 6.2 Navigating the Web UI

Access the Web console at `http://<server-ip>:5000` (or `https://py-phone-caller.lan` if using Caddy):

- **Dashboard**: Real-time view of call queue status, total calls placed, successful DTMF acknowledgments, and pending retries.
- **Call History**: Searchable, paginated audit log of every call attempt, duration, Asterisk channel ID, heard status, and acknowledged status.
- **Address Book**: Manage on-call engineers, phone numbers, backup escalation targets, and weekly schedule matrices.
- **Managed SMS**: Filter, inspect, and export all outbound SMS logs and carrier delivery receipts.
- **WebSocket Events**: Live Asterisk Stasis event log stream.
- **Scheduled Calls**: Review and manage future scheduled automated calls.

---

### 6.3 Configuring On-Call Contacts

Before placing alerts with `phone=oncall`, you must create at least one enabled contact in the Address Book:

1. In the Web UI, click **Address Book** -> **+ Add Contact**.
2. Fill in:
   - **Name**: `Primary On-Call Engineer`
   - **Phone Number**: `+393341234567` (Use E.164 international format)
   - **Enabled**: `Checked`
   - **On-Call Availability**: Set days and hours (or check 24/7 coverage).
3. Click **Save Contact**.

Alternatively, insert a contact via the REST API:
```bash
curl -X POST "http://10.0.55.251:8087/contact" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Alex",
    "surname": "Admin",
    "phone_number": "+393341234567",
    "enabled": true,
    "on_call_availability": {
      "monday": {"start": "00:00", "end": "23:59"},
      "tuesday": {"start": "00:00", "end": "23:59"},
      "wednesday": {"start": "00:00", "end": "23:59"},
      "thursday": {"start": "00:00", "end": "23:59"},
      "friday": {"start": "00:00", "end": "23:59"},
      "saturday": {"start": "00:00", "end": "23:59"},
      "sunday": {"start": "00:00", "end": "23:59"}
    }
  }'
```

---

### 6.4 Triggering Your First Incident Call

Always enqueue calls via the resilient `/call_to_queue` endpoint:

```bash
curl -X POST "http://10.0.55.251:8081/call_to_queue" \
  --data-urlencode "phone=oncall" \
  --data-urlencode "message=Emergency alert: Production database latency spike detected on cluster 01."
```

**What happens behind the scenes:**
1. `asterisk_caller` enqueues the request.
2. The worker resolves `phone=oncall` by querying `caller_address_book`.
3. An outbound call is placed via Asterisk ARI.
4. When the on-call engineer answers, Asterisk triggers a WebSocket event to `asterisk_ws_monitor`.
5. `generate_audio` converts the message text into a 16-bit 8000 Hz Asterisk WAV file using neural TTS.
6. Asterisk plays the message to the caller.
7. If the engineer presses `4` on their dialpad, `asterisk_ws_monitor` receives the DTMF digit and marks the call as **Acknowledged** in `caller_register`.

---

### 6.5 Triggering Your First SMS Notification

To test direct SMS dispatch:

```bash
curl -X POST "http://10.0.55.251:8085/send_sms" \
  --data-urlencode "phone=+393341234567" \
  --data-urlencode "message=TEST ALERT: Critical disk space on server storage-01"
```

Check the message record:
```bash
curl "http://10.0.55.251:8085/get_sms"
```

---

## 7. Monitoring Integrations (Alertmanager, Nagios, Zabbix)

### 7.1 Prometheus Alertmanager Webhook

In your Alertmanager configuration (`alertmanager.yml`), add a webhook receiver:

```yaml
receivers:
  - name: "py-phone-caller"
    webhook_configs:
      - url: "http://10.0.55.251:8084/sms_before_call" # Sends SMS, waits 120s, then calls if unacknowledged
        send_resolved: true
```

Available webhook routes:
- `/call_only`: Immediately triggers voice calls for alerts.
- `/sms_only`: Dispatches SMS notifications only.
- `/sms_before_call`: Sends an SMS first; if the alert remains firing after `sms_before_call_wait_seconds` (default 120s), places a voice call.
- `/call_and_sms`: Simultaneously sends an SMS and places a voice call.

---

### 7.2 Nagios Event Handler Script

Deploy `assets/scripts/nagios/nagios_event_handler_call.sh` to `/usr/local/nagios/libexec/`:

```bash
sudo cp assets/scripts/nagios/nagios_event_handler_call.sh /usr/local/nagios/libexec/
sudo chmod +x /usr/local/nagios/libexec/nagios_event_handler_call.sh
```

In your Nagios `commands.cfg`:
```ini
define command {
    command_name    notify_by_py_phone_caller
    command_line    PY_PHONE_CALLER_URL="http://10.0.55.251:8081/call_to_queue" /usr/local/nagios/libexec/nagios_event_handler_call.sh "$SERVICESTATE$" "$SERVICESTATETYPE$" "$SERVICEATTEMPT$" "$HOSTNAME$" "$SERVICEDESC$" "oncall"
}
```

---

### 7.3 Zabbix Alert Script

Deploy `assets/scripts/zabbix/zabbix_alert_call.sh` to your Zabbix `AlertScriptsPath` (e.g. `/usr/lib/zabbix/alertscripts/`):

```bash
sudo cp assets/scripts/zabbix/zabbix_alert_call.sh /usr/lib/zabbix/alertscripts/
sudo chmod +x /usr/lib/zabbix/alertscripts/zabbix_alert_call.sh
```

In Zabbix Administration -> Media Types -> Create Media Type:
- **Type**: Script
- **Script name**: `zabbix_alert_call.sh`
- **Script parameters**:
  - `{ALERT.SENDTO}` (e.g. `oncall` or `+393341234567`)
  - `{ALERT.SUBJECT}`
  - `{ALERT.MESSAGE}`
  - `http://10.0.55.251:8081/call_to_queue`

---

## 8. Air-Gapped & Offline Deployments

**py-phone-caller** is designed for fully air-gapped mission-critical environments without public Internet connectivity.

### Essential Air-Gapped Infrastructure
1. **Local OCI Registry**: (e.g. `artifacts.py-phone-caller.lan:5000`)
   - Pre-push the 11 container images tagged `1.0.0`.
2. **Local PyPI Server**: (e.g. `http://artifacts.py-phone-caller.lan:8080/simple`)
   - Pre-cache Python 3.14 wheels for `uv` sync.
3. **Pre-Cached Neural TTS Models**:
   - `generate_audio` containers bake the Kokoro TTS (`kokoro-v1_0.pth`), Facebook MMS, and Piper voices directly into the container image (`/app/src/generate_audio/pre_trained_models`).
4. **Local Web UI Assets**:
   - All Bootstrap, FontAwesome, and custom stylesheets in `py_phone_caller_ui` are stored locally in `src/py_phone_caller_ui/static/` with **zero external CDN dependencies**.

---

## 9. Troubleshooting & Operational Runbook

### Common Issues and Solutions

#### 1. `ModuleNotFoundError: No module named 'piccolo_conf'`
- **Cause**: Piccolo ORM did not receive the fully qualified path to the shared DB module.
- **Solution**: Ensure the environment variable `PICCOLO_CONF=py_phone_caller_utils.py_phone_caller_db.piccolo_conf` is present in your service environment or container definition.

#### 2. `Unable to resolve 'oncall' phone: Address book returned status 404`
- **Cause**: No contact in the Address Book has `enabled: true` with valid on-call schedule hours for the current timestamp.
- **Solution**: Add an enabled on-call contact in the Web UI or via `POST /contact`.

#### 3. Asterisk Calls Fail with `Connect call failed ('127.0.0.1', 8088)`
- **Cause**: Asterisk HTTP/ARI server is not running or listening on port 8088.
- **Solution**: Check Asterisk status:
  ```bash
  sudo asterisk -rx "http show status"
  sudo asterisk -rx "ari show users"
  ```
  Ensure `http.conf` has `enabled=yes` and `bindaddr=0.0.0.0` or `127.0.0.1`.

#### 4. Audio Generation Logs `Couldn't find ffmpeg`
- **Cause**: `ffmpeg` binary missing from system `$PATH`.
- **Solution**: Install ffmpeg:
  - Ubuntu/Debian: `sudo apt install -y ffmpeg`
  - RHEL/Rocky Linux: `sudo dnf install -y ffmpeg`

#### 5. Resetting Lost Administrator Password
- **Native Systemd**:
  ```bash
  sudo systemctl stop py-phone-caller-py-phone-caller-ui
  sudo -u py-phone-caller UI_USER_RESET_PASSWORD=true /opt/py-phone-caller/venv/bin/python -m gunicorn -w 1 -b 127.0.0.1:5000 py_phone_caller_ui.app:app
  # Note the generated password in console, then press Ctrl+C and restart normal systemd service:
  sudo systemctl start py-phone-caller-py-phone-caller-ui
  ```
- **Docker Compose**:
  ```bash
  UI_USER_RESET_PASSWORD=true docker compose restart py_phone_caller_ui
  docker compose logs py_phone_caller_ui | grep "Admin user"
  UI_USER_RESET_PASSWORD=false docker compose restart py_phone_caller_ui
  ```

---

## 🎯 Summary Checklist

- [ ] Target OS updated and network ports verified.
- [ ] Database credentials and ARI secrets configured.
- [ ] Asterisk PBX deployed with ARI user and Stasis app `py-phone-caller`.
- [ ] Microservices deployed via Ansible or Docker Compose.
- [ ] `verify_deployment.py` run and all 8 services reporting healthy.
- [ ] Initial on-call contact created in Address Book.
- [ ] Test call triggered via `/call_to_queue`.
- [ ] Monitoring webhooks (Prometheus/Nagios/Zabbix) connected.

You are now ready to operate **py-phone-caller** in production! 🚀
