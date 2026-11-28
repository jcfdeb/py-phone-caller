# 03. Docker & Docker Compose Deployment Guide (`deploy/compose`)

This guide walks you step by step through deploying the complete **15-container `py-phone-caller` + `openalertd` stack** (plus optional **Hardware USB GSM/LoRa/BLE passthrough** and **Apache APISIX + Keycloak OIDC Gateway** overlays) using **Docker Compose** or **Podman Compose**.

> [!NOTE]
> **Live VM Qualification (`2026-11-08`)**
> Qualified on Debian 13 AMD64 (`ppc-pkg-debian13-20261108`) with Docker Engine `29.2.1` and Docker Compose `v5.0.0`. All 12 application images built cleanly from source, all 15 core containers + APISIX Gateway containers started healthy, and all HTTP `/health` and `/api/v1/status` endpoints returned `200 OK`.

---

## 1. What the Compose Stack Runs

The Compose directory (`deploy/compose/`) provides three composable YAML files:

| File | Containers Managed | Purpose |
| :--- | :--- | :--- |
| **[`docker-compose.yml`](../compose/docker-compose.yml)** | • **Infrastructure (3)**: `db` (`postgres:17-alpine`), `redis` (`redis:7-alpine`), `caddy` (`caddy:2-alpine`)<br>• **Python Services (11)**: `caller_register`, `generate_audio`, `caller_address_book`, `asterisk_caller`, `asterisk_ws_monitor`, `asterisk_recaller`, `caller_sms`, `caller_prometheus_webhook`, `caller_scheduler`, `py_phone_caller_ui`, `celery_worker`<br>• **OpenAlert (1)**: `openalertd` | Complete 15-container core alerting platform |
| **[`docker-compose.hardware.yml`](../compose/docker-compose.hardware.yml)** | Extends `openalertd` | Passes physical USB GSM (`/dev/ttyUSB2`), LoRa (`/dev/ttyACM0`), and BlueZ BLE (`hci0` + `/var/run/dbus`) devices into `openalertd` |
| **[`docker-compose.gateway.yml`](../compose/docker-compose.gateway.yml)** | • `apisix-etcd` (`etcd:v3.5.11`)<br>• `apisix` (`apisix:3.9.1-debian`)<br>• `apisix-dashboard` (`apisix-dashboard:3.0.1-alpine`)<br>• `keycloak` (`keycloak:25.0.2`) | Enterprise API Gateway (`:9080`/`:9443`) & Keycloak OIDC IAM (`:8080`/`:8443`) wired to the `db` PostgreSQL container |

> [!TIP]
> **Standalone `openalertd` Only**: If you only want to run `openalertd` without the Python/Asterisk stack, use the root-level [`docker-compose.yml`](../../docker-compose.yml) and [`docker-compose.hardware.yml`](../../docker-compose.hardware.yml) in the repository root.

---

## Step 1: Pull Prebuilt GHCR Images or Build from Source

All 12 application images (`asterisk_caller` … `py_phone_caller_ui` + `openalertd`) are published to **GitHub Container Registry (`ghcr.io/jcfdeb/<service>:1.1.0`)** on every tagged release. You can either pull them directly in seconds or build all 12 images locally from source.

### Option A: Pull Official Prebuilt Images from GHCR (Fastest — Zero Build Disk Needed)

Set `MY_DOCKER_REGISTRY=ghcr.io/jcfdeb` (in your shell or `deploy/compose/.env`) and pull:

```bash
export MY_DOCKER_REGISTRY=ghcr.io/jcfdeb
export VERSION=1.1.0
docker compose -f deploy/compose/docker-compose.yml pull
```

### Option B: Build from Source via `docker compose build`

Every Python microservice `Dockerfile` (`src/<service>/Dockerfile`) installs workspace dependencies from the repository root (`pyproject.toml` and `uv.lock`) and copies `/app/py-phone-caller/config/settings.toml` into the runtime image.

> **Disk Space Requirement for Local Builds**: Building all 12 images from source (including the PyTorch/HuggingFace TTS image `generate_audio` and the Rust `openalertd` builder cache) requires **at least 45–50 GB of free disk space** in `/var/lib/docker` (or `/var/lib/containerd`).

From `deploy/compose/`:

```bash
cd deploy/compose
docker compose build
```

> [!TIP]
> **Preloading Additional TTS Models in `generate_audio`**
> By default, `src/generate_audio/Dockerfile` preloads the fast **Piper ONNX (`piper_tts`)** voice model during `docker build` (`ARG PRELOAD_ALL_MODELS=false`) so builds finish quickly. If you want to bake **all 4 local neural TTS model families** (`piper_tts`, `kokoro_tts`, `silero_tts`, `mms_tts`) into the image at build time, run:
> ```bash
> docker compose build --build-arg PRELOAD_ALL_MODELS=true generate_audio
> ```

### Option C: Build via `./src/build_all_images.sh` (Supports Podman & Docker)

From the **repository root**, run the unified build script. Note that `deploy/compose/docker-compose.yml` defaults to image tag `1.1.0` (`${MY_DOCKER_REGISTRY:-localhost}/<service>:${VERSION:-1.1.0}`), so pass `IMAGE_TAG=1.1.0`:

```bash
# Using Docker:
CONTAINER_ENGINE=docker IMAGE_REGISTRY=localhost IMAGE_TAG=1.1.0 ./src/build_all_images.sh

# Or using Podman:
CONTAINER_ENGINE=podman IMAGE_REGISTRY=localhost IMAGE_TAG=1.1.0 ./src/build_all_images.sh
```

> [!NOTE]
> **Docker BuildKit (`docker-buildx`) & Gateway Dashboard Notes**:
> - Building `openalertd` via Docker uses conditional BuildKit globs in `src/openalert/Dockerfile` and requires `DOCKER_BUILDKIT=1` (defaulted automatically by `./src/build_all_images.sh`) plus the `docker-buildx` plugin on Debian/Ubuntu Docker hosts.
> - `deploy/compose/docker-compose.gateway.yml` mounts `deploy/gateway/apisix/dashboard_conf.yaml` so `apisix-dashboard` connects to `apisix-etcd:2379` (rather than loopback `127.0.0.1:2379`) and binds APISIX Admin API strictly to `127.0.0.1:9180`.

### Fast ARM64 (`aarch64`) Cross-Compilation for `openalertd`
If you are building `openalertd` for an ARM64 SBC (such as Orange Pi 5 Plus or Raspberry Pi 5) on an `x86_64` workstation, use `src/openalert/Dockerfile.arm64` (which cross-compiles at native `x86_64` speed without slow QEMU `rustc` emulation):

```bash
docker buildx build --platform linux/arm64 \
  -f src/openalert/Dockerfile.arm64 \
  -t localhost/openalertd:1.1.0 --load src/openalert
```

---

## Step 2: Configure Environment & Secrets

`deploy/compose/docker-compose.yml` is designed to work out of the box with sensible defaults while allowing full customization through **Dynaconf environment files** (`deploy/compose/env/py-phone-caller.env` and `deploy/compose/env/py-phone-caller.secrets.env`) or `.env` variables.

### 1. Generate Dynaconf Env Files from `src/config/` (Recommended)

From the **repository root**, convert your `src/config/settings.toml` and `src/config/.secrets.toml` into `deploy/compose/env/`:

```bash
python3 assets/scripts/config/toml_to_dynaconf_env.py \
  --input src/config/settings.toml \
  --output deploy/compose/env/py-phone-caller.env

python3 assets/scripts/config/toml_to_dynaconf_env.py \
  --ignore-missing \
  --input src/config/.secrets.toml \
  --output deploy/compose/env/py-phone-caller.secrets.env

chmod 600 deploy/compose/env/py-phone-caller.secrets.env
```

> [!IMPORTANT]
> **Container Networking Automatic Overrides**
> Even if your `src/config/settings.toml` has `db_host = "127.0.0.1"` or `queue_host = "127.0.0.1"`, `deploy/compose/docker-compose.yml` explicitly sets `DYNACONF_DATABASE__DB_HOST: db`, `DYNACONF_QUEUE__QUEUE_HOST: redis`, and internal service hostnames (`caller_register`, `generate_audio`, `asterisk_caller`, etc.) in the container `environment:` block, which takes precedence over `env_file:` so inter-container networking always works!

### 2. Review `deploy/compose/.env`

Check or customize `deploy/compose/.env` for your host:

```dotenv
# IP or hostname of your Asterisk PBX (defaults to host.containers.internal)
ASTERISK_HOST=192.0.2.10
ASTERISK_PASS=your_ari_password

# PostgreSQL & UI credentials
POSTGRES_PASSWORD=your_secure_postgres_password
UI_SECRET_KEY=your_32_char_random_session_secret
UI_ADMIN_PASSWORD=your_secure_admin_password

# Set UI_USER_RESET_PASSWORD=true on first boot to ensure the admin user is created/updated
UI_USER_RESET_PASSWORD=true

# Domain name for Caddy HTTPS reverse proxy
CADDY_DOMAIN_NAME=py-phone-caller.lan

# Image registry & version tag
MY_DOCKER_REGISTRY=localhost
VERSION=1.1.0
```

---

## Step 3: Start the Stack

From `deploy/compose/`:

### Standard 15-Container Stack
```bash
cd deploy/compose
docker compose up -d
```

### With Physical USB GSM / LoRa / BLE Hardware Passthrough
```bash
cd deploy/compose
OPENALERT_GSM_DEVICE=/dev/ttyUSB2 \
OPENALERT_LORA_DEVICE=/dev/ttyACM0 \
OPENALERT_BLE_HCI=hci0 \
docker compose -f docker-compose.yml -f docker-compose.hardware.yml up -d
```

### With Enterprise APISIX Gateway & Keycloak OIDC Overlay
```bash
cd deploy/compose
docker compose -f docker-compose.yml -f docker-compose.gateway.yml up -d
```

---

## Step 4: Verify Every Container and Endpoint

1. **Check Container Status**:
   ```bash
   docker compose ps
   ```
   Wait ~15–20 seconds for `db` and `redis` healthchecks to pass and `caller_register` to initialize the PostgreSQL schema.

2. **Probe Microservice Health Endpoints**:
   ```bash
   for port in 8081 8082 8083 8084 8085 8086 8087; do
     echo -n "Port $port: "
     curl -fsS "http://127.0.0.1:${port}/health" && echo ""
   done
   ```
   Every service should return:
   ```json
   {"status": "healthy", "version": "1.1.0"}
   ```

3. **Probe the Web UI (`:5000`) and OpenAlert Daemon (`:8090`)**:
   ```bash
   curl -fsS http://127.0.0.1:5000/health
   curl -fsS http://127.0.0.1:8090/api/v1/status
   ```
   `openalertd` returns `{"node_name":"openalertd-compose-hub","status":"operational",...}`.

4. **Log in to the Web UI**:
   Open `http://127.0.0.1:5000/login` (or `https://py-phone-caller.lan` via Caddy) and sign in with `admin@py-phone-caller.link` and your `UI_ADMIN_PASSWORD`. Once verified, set `UI_USER_RESET_PASSWORD=false` in `.env` and run `docker compose up -d py_phone_caller_ui`.
