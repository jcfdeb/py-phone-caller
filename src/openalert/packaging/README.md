# OpenAlert Native Release Packaging & Deployment Guide

This directory produces release artifacts for `openalertd`. Packaging does not
certify a board, operating system image, peripheral or production deployment.
The modular Ansible installer consumes these bundles and owns host configuration
and service lifecycle; it must not invoke `install.sh` or the Wi-Fi setup script.
The standalone installer remains available for manually managed hosts.

This directory contains:
* **Systemd**: Unprivileged hardened unit file (`packaging/systemd/openalertd.service`).
* **Container**: Vendor-neutral multi-stage `Containerfile` (`packaging/container/Containerfile`) compatible with Podman, Docker, Buildah, and Kubernetes.
* **Optional Emergency SOS Wi-Fi AP & Port 80 Captive Portal**: Turnkey Linux network configuration (`packaging/wifi-ap/`) for ARM field nodes (e.g., Orange Pi Zero 3, Raspberry Pi) using `hostapd`, `dnsmasq`, and `nginx-light`.

---

## Release contract (schema version 1)

Run from the repository root. Requirements: Linux, Python 3.11+, GNU binutils
(`readelf`), Git and an installed Rust **1.99.1** toolchain. Source builds need
a C compiler, CMake, pkg-config, libclang and D-Bus development libraries for the
locked dependency graph. SQLite is bundled by the crate.

```bash
rustup toolchain install 1.99.1 --profile minimal
src/openalert/packaging/build_release_bundle.sh \
  --target x86_64-unknown-linux-gnu --output-dir ./release-amd64
```

The builder uses `cargo build --release --locked --target ...`. It verifies the
compiler version even when `--toolchain stable` selects an already-installed
toolchain. `PYTHON` can select an explicit Python executable. `--target-dir`
selects Cargo's output directory; `--output-dir` selects bundle output. Existing
archives are never silently replaced. No host installation or daemon is started.

| Rust target | ELF machine | Metadata architecture | Archive suffix |
|---|---|---|---|
| `x86_64-unknown-linux-gnu` | x86-64 | `amd64` | `linux-x86_64` |
| `aarch64-unknown-linux-gnu` | AArch64 | `arm64` | `linux-aarch64` |

An omitted target means the builder's native architecture **only for source
builds**. Cross-compilation requires you to provision the matching Rust target,
linker, C toolchain and D-Bus/pkg-config sysroot first. The builder never installs
cross-toolchains, invokes emulation or compiles on the managed node. Prefer native
builders until the cross-build environment has been qualified.

To package a previously built binary (never executed by the packager):

```bash
src/openalert/packaging/build_release_bundle.sh \
  --target aarch64-unknown-linux-gnu --binary /srv/build/openalertd \
  --source-revision <full-source-commit> --rustc-version 1.99.1 \
  --build-baseline 'Debian 13; recorded builder image digest and sysroot revision' \
  --output-dir ./release-arm64
```

Replace the provenance placeholders with the **actual producer's** values; do
not infer them from the packaging controller. A prebuilt compiler/provenance
declaration is an attestation, not something ELF inspection can prove. Its
`source_dirty` and `cargo_locked` fields are `null` rather than falsely claiming
a clean, locked build. Publish only artifacts from a controlled build process.

The archive retains `bin/`, `templates/`, `profiles/`, `systemd/`, `wifi-ap/`,
the example TOML, README and standalone scripts. Added `release.json` records:

- `schema_version`, package/version, `release_id`, source revision and dirty state;
- Rust target and normalized architecture (metadata, not the filename, is authoritative);
- compiler/build baseline and whether a prebuilt binary was supplied;
- GNU dynamic loader, minimum glibc version and required shared-library SONAMEs;
- binary path and SHA-256.

Binary inspection rejects wrong-target, non-ELF, relocatable and non-GNU-loader
inputs before creating an archive. It never runs `ldd` on supplied executables.
The binary is not stripped or modified, so its recorded hash matches the input.
The **archive hash**, rather than `release_id` alone, also identifies templates,
unit files and other assets.

### Build/runtime baseline and trust

Use a recorded Debian 13 build image/sysroot and pinned Rust 1.99.1 for initial
Debian 13 / Ubuntu 26.04 qualification. An explicit target is not an ABI guarantee:
actual minimum glibc and dependencies are inspected and recorded in every bundle.
Source builds record the build OS unless `--build-baseline` supplies a more
specific image/sysroot identity. The current helper does not provision or pin OS
packages; preserve the builder image digest/package manifest in release evidence.

Distribute the archive SHA-256 through a trusted, separately controlled channel
(for example a reviewed inventory change). A `.sha256` downloaded beside an
archive detects corruption but **does not establish authenticity**. Ansible must
verify its inventory-pinned checksum **before extraction**, then check schema,
architecture and runtime compatibility before executing `openalertd check`.

For a standalone download, first compare the checksum with that trusted value,
then extract and inspect the bundled assets. `install.sh` does not enforce the
Ansible release contract, perform adoption or provide rollback.

### Verification evidence

On 2026-10-30, offline packaging fixtures passed on AMD64 and a real locked
native build completed with Rust 1.99.1 on openSUSE Leap 16.0. The validation
artifact required glibc 2.38 and its archive checksum verified successfully.
This is **build evidence only**, not Debian/Ubuntu runtime qualification. ARM64
artifact production and physical-board qualification have not been run.

```bash
python3 -m unittest discover -s src/openalert/packaging/tests -p test_release_bundle.py -v
bash src/openalert/packaging/tests/test_install_verify.sh
bash -n src/openalert/packaging/build_release_bundle.sh
bash -n src/openalert/packaging/install.sh
bash -n src/openalert/packaging/verify_install.sh
```

The tests use temporary local fixtures, native ELF inspection and isolated
command stubs for privileged operations. They do not install services or probe
hardware. They do not substitute for disposable-systemd-host testing.

## 1. Systemd Service Deployment (Bare Metal / VM)

### Automated Installer (`install.sh`)

Run from `src/openalert` or from an extracted bundle. Source-tree installation
can use a prebuilt `target/release/openalertd`, or fall back to the installed
Cargo with `--locked`; use the release builder for the pinned production build.
The installer does not enable/start the daemon and is not a migration tool.
Review listener/authentication settings, secrets and hardware permissions before
starting it. Existing configuration is retained, but templates/binary/unit files
are replaced. Do not use it to adopt existing custom deployments.

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
cargo +1.99.1 build --release --locked
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

The audit requires `curl` and `jq` for health verification. It only uses a health
GET and configuration checks, never alert submission. Named instances can use:

```bash
sudo ./packaging/verify_install.sh \
  --config /etc/openalertd-public/openalertd.toml \
  --unit openalertd-public.service --health-url http://127.0.0.1:8092/health \
  --user openalert-public --group openalert-public \
  --state-dir /var/lib/openalertd-public \
  --templates-dir /etc/openalertd-public/templates --log-dir /var/log/openalertd-public
```

Use `--binary` for a non-default executable. Validation output and HTTP response
bodies are suppressed. A missing/inactive service, invalid config or failed
health probe returns failure; checks run without account-switching privileges
cannot prove service-account permissions. `openalertd check` only warns about
some missing templates, so separately verify all required assets.

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
* **Ambient Capabilities**: The standalone base unit grants `CAP_NET_BIND_SERVICE`, `CAP_NET_ADMIN`, `CAP_NET_RAW` and `CAP_SYS_TIME`. These include network and clock privileges; review them for your features. The installer no longer applies file capabilities to the executable. Ansible instance drop-ins must reset these inherited sets before adding explicitly required capabilities.
* **Strict Filesystem Isolation**: `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`. Write access is restricted solely to `/var/lib/openalertd` and journal.
* **Kernel & Memory Protection**: `ProtectKernelTunables=yes`, `ProtectControlGroups=yes`, `MemoryDenyWriteExecute=yes`.
* **Resource Hard Quotas**: `MemoryHigh=100M`, `MemoryMax=150M`, `CPUQuota=50%`, `LimitNOFILE=65536`.

---

## 2. Optional: Emergency SOS Wi-Fi Access Point & Port 80 Proxy (`packaging/wifi-ap/`)

For off-grid field nodes (such as Orange Pi Zero 3 or Raspberry Pi units equipped with 868 MHz LoRa RF and BLE), `packaging/wifi-ap/` provides a standalone Linux OS configuration that turns `wlan0` into an **OpenAlert-SOS** Wi-Fi hotspot (`10.42.0.1/24`) and runs `nginx-light` on Port `80` to reverse-proxy exclusively to the simplified `/sos` endpoint (isolating the administrative NOC UI).

**Disruptive, separate opt-in operation:** this script can disable
`wpa_supplicant`, flush interface addresses and replace Nginx's default site.
Do not run it over your sole management connection. It is outside the modular
Ansible refactor and existing field networking remains unmanaged.

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
