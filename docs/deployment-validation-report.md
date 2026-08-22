# 🚀 Multi-Environment Deployment & Validation Report (1.0.0 Pre-Release)

This document provides the complete, authoritative record of the end-to-end installation, configuration, troubleshooting, and verification tests conducted across all test nodes.

---

### 🌐 Test Environment Inventory

| Host Alias | IP Address | OS & Platform | Deployment Model | Components Deployed |
| :--- | :--- | :--- | :--- | :--- |
| **`ubuntu-artifact-repo`** | `10.0.55.188` (`artifacts.py-phone-caller.lan`) | Ubuntu 26.04 LTS | Standalone Services | Local OCI Registry (`:5000`), Local PyPI Server (`:8080`) |
| **`ubuntu-on-premise`** | `10.0.55.251` | Ubuntu 26.04 LTS | Ansible (`on-vm_py-phone-caller`) | Native Systemd: Asterisk, PostgreSQL 17, Redis 7, Python 3.14 + 11 Microservices |
| **`rocky10-on-premise`** | `10.0.55.179` | Rocky Linux 10 (EL10) | Ansible (`on-vm_py-phone-caller`) | Native Systemd: Asterisk, PostgreSQL 17, Redis 7, Python 3.14 + 11 Microservices |
| **`ubuntu-compose`** | `10.0.55.215` | Ubuntu 26.04 LTS | Asterisk Ansible + Docker Compose | Host Asterisk + 14 Docker Compose Containers (11 Microservices, DB, Redis, Caddy) |
| **`rocky10-compose`** | `10.0.55.252` | Rocky Linux 10 (EL10) | Asterisk Ansible + Podman Compose | Host Asterisk + 14 Podman Compose Containers (11 Microservices, DB, Redis, Caddy) |

---

### 🛠️ Key Fixes & Hardening Applied

During the initial installation runs on fresh virtual machines, several environment and configuration gaps were diagnosed and resolved:

#### 1. Air-Gapped Artifact Repository (`10.0.55.188`)
- Configured local OCI Registry on port `5000` (`artifacts.py-phone-caller.lan:5000`) and local PyPI server on port `8080` (`http://artifacts.py-phone-caller.lan:8080/simple`).
- Built all 11 microservice images with `VERSION=1.0.0`, tagged for `artifacts.py-phone-caller.lan:5000/*`, and pushed them to the local registry.
- Populated the PyPI repository with the Python 3.14 wheel cache so host VMs could run `uv sync` offline.

#### 2. Asterisk Ansible Role (`assets/ansible/asterisk_py-phone-caller`)
- **ARI General Configuration**: Added `community.general.ini_file` task to ensure `[general]` `enabled=yes`, `pretty=yes`, and `allowed_origins=*` are set in `ari.conf` alongside user authentication.
- **Enterprise Linux 10 Compatibility**: Added binary detection (`stat /usr/sbin/asterisk`) in `install_RedHat.yml` to skip EPEL package checks when Asterisk is already present or built from source on EL10.
- **Sound Asset Handling**: Corrected sound directory resolution in `configure.yml` to check `/var/lib/asterisk/sounds/en` and avoid unneeded external HTTP sound downloads.

#### 3. Host-Level On-VM Ansible Role (`assets/ansible/on-vm_py-phone-caller`)
- **Python 3.14 `uv` Runtime Setup**: Configured automated workspace synchronization via `uv sync --frozen --no-dev` using the local PyPI index (`http://artifacts.py-phone-caller.lan:8080/simple`).
- **Rust Engine Build**: Automated compilation of `librust_engine.so` via `cargo build --release` with `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` for Python 3.14 ABI stability.
- **Unattended Database Setup**: Configured automated role creation, database provisioning, permissions, and extensions (`uuid-ossp`, `pgcrypto`) before initializing Piccolo migrations with `caller_register`.

#### 4. Docker & Podman Compose Automation (`assets/docker-compose`)
- **Inter-Service Discovery**: Added standard Dynaconf environment variables (`DYNACONF_COMMONS__ASTERISK_HOST=host.containers.internal`, `DYNACONF_CALL_REGISTER__CALL_REGISTER_HOST=caller_register`, etc.) in `x-common-env` so containers automatically communicate across the bridge network.
- **Multi-Stage FFMPEG & TTS Pre-Packaging**: Updated `src/generate_audio/Dockerfile` with multi-stage static ffmpeg extraction and build-time model pre-caching for Facebook MMS, Piper, and Kokoro TTS.
- **Fully Qualified Image Identifiers**: Updated infrastructure services to `docker.io/library/postgres:17-alpine`, `docker.io/library/redis:7-alpine`, and `docker.io/library/caddy:2-alpine` to prevent registry resolution ambiguity under Podman.

#### 5. SMS Carrier Configuration (Twilio for Virtual Machines)
- Updated `caller_sms_carrier` to `twilio` in both `src/config/settings.toml` and Ansible defaults (`assets/ansible/on-vm_py-phone-caller/roles/deploy_py-phone-caller/defaults/main.yml`).
- Virtual machines without attached physical GSM/LTE serial modems (e.g., `/dev/ttyUSB*`) now route outbound SMS notifications through the Twilio backend instead of attempting hardware modem discovery.

---

### 📊 End-to-End Verification Matrix

Every target VM was validated using `VERIFY_HOST=<IP> uv run python verify_deployment.py`, testing all 8 HTTP service `/health` probes, `/metrics` endpoints, and dynamic audio generation:

```text
========================================================================================
Service Name                  Port   Type     ubuntu-on-premise  rocky10-on-premise  ubuntu-compose  rocky10-compose
========================================================================================
asterisk_caller               8081   HTTP     ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS
generate_audio                8082   HTTP     ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS
caller_register               8083   HTTP     ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS
caller_prometheus_webhook     8084   HTTP     ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS
caller_sms                    8085   HTTP     ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS
caller_scheduler              8086   HTTP     ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS
caller_address_book           8087   HTTP     ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS
py_phone_caller_ui            5000   HTTP/UI  ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS ✅ HEALTH + METRICS
asterisk_ws_monitor           -      Worker   ✅ CONNECTED TO ARI ✅ CONNECTED TO ARI ✅ CONNECTED TO ARI ✅ CONNECTED TO ARI
asterisk_recaller             -      Worker   ✅ ACTIVE POLLER    ✅ ACTIVE POLLER    ✅ ACTIVE POLLER    ✅ ACTIVE POLLER
celery_worker                 -      Worker   ✅ REDIS CONNECTED  ✅ REDIS CONNECTED  ✅ REDIS CONNECTED  ✅ REDIS CONNECTED
Asterisk PBX                  8088   ARI/HTTP ✅ ARI READY        ✅ ARI READY        ✅ ARI READY        ✅ ARI READY
PostgreSQL 17                 5432   Database ✅ MIGRATIONS OK    ✅ MIGRATIONS OK    ✅ MIGRATIONS OK    ✅ MIGRATIONS OK
Redis 7                       6379   Queue    ✅ QUEUE READY      ✅ QUEUE READY      ✅ QUEUE READY      ✅ QUEUE READY
========================================================================================
Audio Generation Test (WAV)   8082   API      ✅ PASSED           ✅ PASSED           ✅ PASSED           ✅ PASSED
========================================================================================
OVERALL STATUS                                🎉 100% PASSED      🎉 100% PASSED      🎉 100% PASSED      🎉 100% PASSED
========================================================================================
```

---

### 📖 Deployment Quick Guides

#### 1. Deploying on Host VMs with Ansible (`ubuntu-on-premise` / `rocky10-on-premise`)
```bash
# From assets/ansible/on-vm_py-phone-caller:
ansible-playbook -i "<target-ip>," deploy_on_vm.yml \
  -e "ansible_user=admin ansible_become=true" \
  -e "py_phone_caller_pbx_host=<target-ip>"
```

#### 2. Deploying with Docker Compose (`ubuntu-compose`)
```bash
# 1. Install Asterisk on the host via Ansible:
cd assets/ansible/asterisk_py-phone-caller
ansible-playbook -i "10.0.55.215," deploy_asterisk.yml -e "ansible_user=admin ansible_become=true"

# 2. Launch the 14-container stack on the host:
cd assets/docker-compose
MY_DOCKER_REGISTRY=artifacts.py-phone-caller.lan:5000 VERSION=1.0.0 docker compose up -d
```

#### 3. Deploying with Podman Compose (`rocky10-compose`)
```bash
# 1. Install Asterisk on the host via Ansible:
cd assets/ansible/asterisk_py-phone-caller
ansible-playbook -i "10.0.55.252," deploy_asterisk.yml -e "ansible_user=admin ansible_become=true"

# 2. Launch the 14-container stack with Podman:
cd assets/docker-compose
sudo env PATH=$PATH:/usr/local/bin MY_DOCKER_REGISTRY=artifacts.py-phone-caller.lan:5000 VERSION=1.0.0 podman-compose up -d
```

#### 4. Validating Any Target Host
```bash
VERIFY_HOST=<target-host-ip> uv run python verify_deployment.py
```
