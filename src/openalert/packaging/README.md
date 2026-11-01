# OpenAlert Daemon Production Packaging & Deployment Guide

This directory contains production packaging manifests for `openalertd`:
* **Systemd**: Unprivileged hardened unit file (`packaging/systemd/openalertd.service`).
* **Docker & Podman Multi-Stage Containers**:
  * `Dockerfile` (`packaging/docker/Dockerfile`): Standard multi-stage Debian Bookworm Slim build for optimal image size (~35–40 MB) on native `x86_64` or `aarch64` hosts.
  * `Dockerfile.arm64` (`packaging/docker/Dockerfile.arm64`): Dedicated ARM64 (`aarch64`) multi-stage build that cross-compiles at native `x86_64` speed (without slow QEMU `rustc` emulation) or builds natively on ARM64 SBCs (Raspberry Pi 4/5, Orange Pi Zero 3, Rockchip).
  * `Containerfile` (`packaging/container/Containerfile`): Alpine musl ultra-minimal multi-stage build.
* **Docker Compose (`docker-compose.yml` + `docker-compose.hardware.yml`)**: Turnkey multi-container orchestration uniting `openalertd` with `py-phone-caller` and optional USB GSM / LoRa / BlueZ BLE hardware passthrough.
* **Optional Emergency SOS Wi-Fi AP & Port 80 Captive Portal**: Turnkey Linux network configuration (`packaging/wifi-ap/`) for ARM field nodes using `hostapd`, `dnsmasq`, and `nginx-light`.

---

## 1. Systemd Service Deployment (Bare Metal / VM)

### Automated Installer (`install.sh`)

```bash
# Standard installation of openalertd
sudo ./packaging/install.sh

# Or install openalertd AND provision the optional Emergency SOS Wi-Fi AP + Port 80 proxy
sudo ./packaging/install.sh --with-wifi-ap
```

### Manual Step 1: Install Binary & Assets

```bash
# 1. Build release binary
cd src/openalert
cargo build --release
sudo strip target/release/openalertd
sudo install -m 755 target/release/openalertd /usr/local/bin/openalertd

# 2. Create system user and groups
sudo groupadd --system openalert
sudo useradd --system -g openalert -d /var/lib/openalertd -s /usr/sbin/nologin openalert
# Add to dialout and bluetooth groups for serial LoRa/GSM and BlueZ D-Bus socket access
sudo usermod -aG dialout,bluetooth openalert 2>/dev/null || true

# 3. Create directories & copy configuration
sudo mkdir -p /etc/openalertd /var/lib/openalertd /var/log/openalertd /usr/share/openalertd/templates
sudo cp config/openalertd.toml /etc/openalertd/openalertd.toml
sudo cp templates/* /usr/share/openalertd/templates/
sudo chown -R openalert:openalert /etc/openalertd /var/lib/openalertd /var/log/openalertd /usr/share/openalertd
sudo chmod 750 /var/lib/openalertd /etc/openalertd
```

### Manual Step 2: Install and Start Systemd Unit

```bash
sudo cp packaging/systemd/openalertd.service /etc/systemd/system/openalertd.service
sudo systemctl daemon-reload
sudo systemctl enable --now openalertd
```

### Manual Step 3: Verify Status & Live Observability

```bash
# Check unit status and resource limits
systemctl status openalertd

# Check journal logs
journalctl -u openalertd -f

# Check Prometheus metrics
curl -s http://127.0.0.1:8090/metrics | grep openalert_
```

---

## 2. Optional: Emergency SOS Wi-Fi Access Point & Port 80 Proxy (`packaging/wifi-ap/`)

For off-grid field nodes (such as Orange Pi Zero 3 or Raspberry Pi units equipped with 868 MHz LoRa RF and BLE), `packaging/wifi-ap/` provides a standalone Linux OS configuration that turns `wlan0` into an **OpenAlert-SOS** Wi-Fi hotspot (`10.42.0.1/24`) and runs `nginx-light` on Port `80` to reverse-proxy exclusively to the simplified `/sos` endpoint (isolating the administrative NOC UI).

```bash
# Default provisioning (wlan0, SSID "OpenAlert-SOS", open network, openalertd on 127.0.0.1:8092)
sudo ./packaging/wifi-ap/setup_wifi_ap.sh
```

---

## 3. Containerized Deployment (Docker / Podman / ARM64)

### 3.1 Build Multi-Stage Production Image (Native Architecture)

```bash
cd src/openalert

# Using Docker:
docker build -t openalertd:1.0.0 -f Dockerfile .

# Using Podman:
podman build --format docker -t openalertd:1.0.0 -f Dockerfile .
```

### 3.2 Build ARM64 (`aarch64`) Image (`Dockerfile.arm64`)

`Dockerfile.arm64` uses `FROM --platform=$BUILDPLATFORM rust:1-slim-bookworm` in Stage 1 to run `rustc` natively on your build machine and cross-compile to `aarch64-unknown-linux-gnu` via `gcc-aarch64-linux-gnu`, avoiding slow QEMU emulation:

```bash
cd src/openalert

# Fast cross-compilation from an x86_64 workstation or CI runner into a linux/arm64 image:
docker buildx build --platform linux/arm64 -f Dockerfile.arm64 -t openalertd:1.0.0-arm64 --load .

# Or build directly on an ARM64 SBC (Raspberry Pi / Orange Pi / Hetzner Ampere):
docker build -f Dockerfile.arm64 -t openalertd:1.0.0-arm64 .
```

### 3.3 Run with Docker Compose (Software + Optional Hardware Overlay)

From the repository root:

```bash
# 1. Start default software stack (openalertd + py-phone-caller webhook + offline Piper TTS):
#    Includes NOC UI (:8090), /sos Portal (:8090/sos), NIP-57 Zap Adapter, and Embedded Nostr Relay (:8088)
docker compose up -d

# 2. Start with physical USB GSM (/dev/ttyUSB2), LoRa (/dev/ttyACM0), and BlueZ BLE passthrough:
docker compose -f docker-compose.yml -f docker-compose.hardware.yml up -d
```

### 3.4 Healthcheck & Metrics Validation

```bash
# Probe readiness & version
curl -s http://127.0.0.1:8090/health

# Probe Embedded Nostr Micro-Relay NIP-11 Information Document
curl -s -H "Accept: application/nostr+json" http://127.0.0.1:8088/

# Probe Prometheus metrics endpoint
curl -s http://127.0.0.1:8090/metrics
```
