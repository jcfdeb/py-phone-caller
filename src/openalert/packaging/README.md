# OpenAlert Daemon Production Packaging & Deployment Guide

This directory contains production packaging manifests for `openalertd`:
* **Systemd**: Unprivileged hardened unit file (`packaging/systemd/openalertd.service`).
* **Container**: Vendor-neutral multi-stage `Containerfile` (`packaging/container/Containerfile`) compatible with Podman, Docker, Buildah, and Kubernetes.
* **Optional Emergency SOS Wi-Fi AP & Port 80 Captive Portal**: Turnkey Linux network configuration (`packaging/wifi-ap/`) for ARM field nodes (e.g., Orange Pi Zero 3, Raspberry Pi) using `hostapd`, `dnsmasq`, and `nginx-light`.

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
# Add to bluetooth group for BlueZ D-Bus socket access if needed on your distro
sudo usermod -aG bluetooth openalert 2>/dev/null || true

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

### Security Sandboxing Highlights
The systemd unit runs under strict Linux sandboxing:
* **Unprivileged User**: Runs as `openalert:openalert` with `DynamicUser=no` and `NoNewPrivileges=yes`.
* **Ambient Capabilities**: `CAP_NET_BIND_SERVICE`, `CAP_NET_ADMIN`, `CAP_NET_RAW` allow port binding and Bluetooth HCI configuration without root privileges.
* **Strict Filesystem Isolation**: `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`. Write access is restricted solely to `/var/lib/openalertd` and journal.
* **Kernel & Memory Protection**: `ProtectKernelTunables=yes`, `ProtectControlGroups=yes`, `MemoryDenyWriteExecute=yes`.
* **Resource Hard Quotas**: `MemoryHigh=100M`, `MemoryMax=150M`, `CPUQuota=50%`, `LimitNOFILE=65536`.

---

## 2. Optional: Emergency SOS Wi-Fi Access Point & Port 80 Proxy (`packaging/wifi-ap/`)

For off-grid field nodes (such as Orange Pi Zero 3 or Raspberry Pi units equipped with 868 MHz LoRa RF and BLE), `packaging/wifi-ap/` provides a standalone Linux OS configuration that turns `wlan0` into an **OpenAlert-SOS** Wi-Fi hotspot (`10.42.0.1/24`) and runs `nginx-light` on Port `80` to reverse-proxy exclusively to the simplified `/sos` endpoint (isolating the administrative NOC UI).

### Included Files in `packaging/wifi-ap/`
* `setup_wifi_ap.sh`: Idempotent provisioning script for Debian/Ubuntu/Armbian systems.
* `20-openalert-wlan0-ap.network.example`: `systemd-networkd` static IP (`10.42.0.1/24`) for `wlan0`.
* `hostapd.conf.example`: 2.4 GHz 802.11n Access Point configuration (`SSID: OpenAlert-SOS`).
* `dnsmasq-openalert-ap.conf.example`: DHCP server (`10.42.0.50–10.42.0.150`) and wildcard DNS resolver (`address=/#/10.42.0.1`) bound strictly to `wlan0` (coexists cleanly with `systemd-resolved`).
* `nginx-openalert-sos.conf.example`: Lightweight Port 80 HTTP reverse proxy and Captive Portal redirect that exposes only `/sos` (`GET`/`POST`) and `/api/v1/health` while redirecting all other paths (`/` and iOS/Android/Windows captive portal probes) to `/sos`.

### Usage

```bash
# Default provisioning (wlan0, SSID "OpenAlert-SOS", open network, openalertd on 127.0.0.1:8092)
sudo ./packaging/wifi-ap/setup_wifi_ap.sh

# Custom parameters via environment variables:
sudo WIFI_IFACE=wlan0 \
     AP_SSID="OpenAlert-SOS" \
     AP_CHANNEL=6 \
     AP_IP="10.42.0.1" \
     OPENALERT_PORT=8092 \
     SOS_ENDPOINT="/sos" \
     ./packaging/wifi-ap/setup_wifi_ap.sh
```

---

## 3. Containerized Deployment (Podman / Docker)

### Build the Image

```bash
# Using Podman (Rootless):
podman build -t openalertd:latest -f packaging/container/Containerfile .

# Or using Docker:
docker build -t openalertd:latest -f packaging/container/Containerfile .
```

### Run Container

```bash
podman run -d \
  --name openalertd \
  -p 8090:8090 \
  -v /var/run/dbus/system_bus_socket:/var/run/dbus/system_bus_socket:ro \
  -v ./data:/var/lib/openalertd:Z \
  --cap-add=NET_ADMIN \
  --cap-add=NET_RAW \
  openalertd:latest
```

### Healthcheck & Metrics Validation

```bash
# Inspect container health
podman inspect --format '{{.State.Health.Status}}' openalertd

# Probe Prometheus metrics endpoint
curl -s http://127.0.0.1:8090/metrics
```
