# 09. ARM64 Appliance & Air-Gapped Deployment Guide (Orange Pi 5 Plus / RK3588)

This guide walks through deploying the complete **16-service all-in-one alerting appliance** (`py-phone-caller` 11 Python services + native ARM64 Rust SMS engine + Asterisk 22 PBX + PostgreSQL 18 + Redis 8 + Caddy TLS reverse proxy + `openalertd v1.1.0` `arm64`) on 64-bit ARM64 (`aarch64`) single-board computers—qualified end-to-end on a physical **Orange Pi 5 Plus (Rockchip RK3588)** in both **connected (`online`)** and **100% air-gapped (`airgapped`)** modes.

> [!IMPORTANT]
> **Physical Hardware Qualification (`2026-11-19`)**
> Every step in this guide was executed and verified on a physical **Orange Pi 5 Plus (RK3588, 8 cores, 8 GB RAM, 512 GB NVMe SSD)** running **Armbian 26.11.3 (`Ubuntu 26.04 LTS Resolute Raccoon`, `aarch64`, kernel `6.1.115-vendor-rk35xx`, `systemd 259`, `cgroup2fs`)**. Both connected (`online`) and from-scratch offline (`airgapped` inside `unshare --net`) deployments passed `verify.yml`, `changed=0` idempotency reruns, offline Piper TTS synthesis, authentic Caddy strict-TLS Web UI login, and full cold-reboot recovery.

---

## 1. Hardware & Operating System Prerequisites

| Requirement | Qualified Baseline | Operator Notes |
| :--- | :--- | :--- |
| **Board / SoC** | Orange Pi 5 Plus (Rockchip RK3588, 4× Cortex-A76 + 4× Cortex-A55, `aarch64`) | Any 64-bit ARM64 SBC with ≥ 4 GB RAM (8 GB recommended for local TTS) |
| **Operating System** | 64-bit Debian 13 (`trixie`) or Ubuntu 26.04 LTS (`resolute`) / Armbian 26.x | 32-bit `armhf` userspace is **not** supported |
| **Init & Cgroups** | `systemd` with unified cgroup v2 (`cgroup2fs`) | Required for `MemoryHigh`, `MemoryMax`, `CPUQuota`, `TasksMax`, and `IPAddressDeny=any` |
| **Storage** | M.2 NVMe SSD (e.g., 512 GB NVMe) or industrial eMMC | Avoid unrated microSD cards for PostgreSQL WAL, SQLite WAL, and TTS WAV writes; plan ≥ 10 GB free for connected installs or ≥ 25 GB free when storing offline air-gap bundles & APT mirrors locally |
| **Power & Cooling** | Rated 5V/4A USB-C PD or barrel supply + active heatsink/fan | Peak measured RK3588 SoC temperature during Rust release link: `50.8°C`; during back-to-back Piper TTS synthesis: `45.3°C` |
| **Ansible Target Python** | System Python `3.11+` (`python3` in `/usr/bin/python3`) | Used by Ansible modules; `py-phone-caller` itself uses pinned standalone Python `3.14.5` via `uv` |
| **USB Modems / Radio** | Persistent `/dev/serial/by-id/usb-...` symlinks | Never bind `/dev/ttyUSB0` or `/dev/ttyACM0`, which can renumber across reboots |

### Armbian `/var/log` (`zram1`) Production Advisory

Armbian images enable `armbian-ramlog` by default, which mounts a **50 MB compressed RAM filesystem** (`/dev/zram1`) on `/var/log` (`SIZE=50M` in `/etc/default/armbian-ramlog`). On an NVMe-backed long-running appliance running 16 services plus Asterisk and PostgreSQL logs, 50 MB can fill quickly.

Before putting an Armbian SBC into continuous service, either increase the RAM-log cap or store `/var/log` directly on the NVMe root filesystem:

```bash
# Option A: Increase armbian-ramlog size to 256M
sudo sed -i 's/^SIZE=.*/SIZE=256M/' /etc/default/armbian-ramlog
sudo systemctl restart armbian-ramlog

# Option B (Recommended on NVMe SSD): Disable armbian-ramlog so /var/log lives on NVMe
sudo sed -i 's/^ENABLED=.*/ENABLED=false/' /etc/default/armbian-ramlog
sudo reboot
```

### Verify Base OS, Architecture & Cgroups on the SBC

```bash
uname -a
cat /etc/os-release
stat -fc %T /sys/fs/cgroup     # Expected: cgroup2fs
free -h
df -h / /var/log
```

---

## 2. Building the Native ARM64 `openalertd` Release Bundle

If you are enabling `stack_deploy_openalert: true`, the Ansible `openalert` role requires an `aarch64` schema-1 release archive containing `release.json` metadata and matching SHA-256 verification.

Run the following natively on your ARM64 board (or an ARM64 Debian 13 / Ubuntu 26.04 build host):

```bash
# 1. Install native C/C++, D-Bus, libclang (required by oqs-sys), and packaging prerequisites
sudo apt-get update
sudo apt-get install -y \
  build-essential pkg-config libdbus-1-dev libudev-dev libssl-dev \
  clang libclang-dev cmake binutils

# 2. Install the locked Rust toolchain (1.99.1) via rustup if not already installed
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.99.1
source "$HOME/.cargo/env"

# 3. Build and package the verified ARM64 release tarball + .sha256 sidecar
cd /path/to/py-phone-caller
./src/openalert/packaging/build_release_bundle.sh \
  --target aarch64-unknown-linux-gnu \
  --toolchain 1.99.1 \
  --output-dir src/openalert/dist
```

On an Orange Pi 5 Plus (RK3588, 8 cores), the full release build and link completes in roughly **~1m 20s** and produces:

- `src/openalert/dist/openalertd-v1.1.0-linux-aarch64.tar.gz` (~12 MB)
- `src/openalert/dist/openalertd-v1.1.0-linux-aarch64.tar.gz.sha256`

Copy both files back to your Ansible controller and record the SHA-256 digest (`sha256sum openalertd-v1.1.0-linux-aarch64.tar.gz`) for `openalert_release.sha256`.

---

## 3. Mode A: Connected ARM64 Appliance Deployment (`online`)

### Step 3.1: Generate Your Inventory Vars from `settings.toml` & `.secrets.toml`

On your Ansible controller (with the controller venv from [Guide 02](02-ansible-deployment.md) activated):

```bash
mkdir -p ~/ppc-opi5-inventory/group_vars/stack

python3 deploy/ansible/tools/toml_to_ansible_vars.py \
  --input src/config/settings.toml \
  --input src/config/.secrets.toml \
  --output ~/ppc-opi5-inventory/group_vars/stack/config.yml \
  --secrets-output ~/ppc-opi5-inventory/group_vars/stack/secrets.yml

# Ensure no template placeholder secrets remain, then encrypt secrets.yml
ansible-vault encrypt ~/ppc-opi5-inventory/group_vars/stack/secrets.yml
```

### Step 3.2: Create `~/ppc-opi5-inventory/hosts.yml`

Use [`deploy/ansible/inventories/examples/appliance-orangepi5plus/hosts.yml`](../ansible/inventories/examples/appliance-orangepi5plus/hosts.yml) as your base. Below is the complete connected all-in-one ARM64 inventory:

```yaml
---
all:
  children:
    stack:
      hosts:
        orangepi5plus-appliance:
          ansible_host: 192.0.2.50          # Replace with your board's LAN IP
          ansible_user: armbian             # Replace with your SSH user
          ansible_become: true
          ansible_ssh_private_key_file: ~/.ssh/py-phone-caller
      vars:
        # 1. All-in-one component selection
        stack_deploy_py_phone_caller: true
        stack_deploy_asterisk: true
        stack_deploy_openalert: true

        # 2. Asterisk 22 PBX (Ubuntu 26.04 uses 'distro'; Debian 13 uses 'allstarlink')
        asterisk_package_provider: distro
        asterisk_http_bindaddr: "127.0.0.1"
        asterisk_sip_bindaddr: "127.0.0.1:5060"
        asterisk_sip_trunk_enabled: false
        local_sip: false
        local_iax: false

        # 3. Standard local-auth appliance topology with Caddy internal TLS
        py_phone_caller_topology: standard
        py_phone_caller_ingress: caddy
        py_phone_caller_tls_mode: internal
        py_phone_caller_connectivity: online
        py_phone_caller_public_url: "https://appliance.internal"
        caddy_domain_name: "appliance.internal"

        # 4. Controller-local source & pinned online checksums
        py_phone_caller_git_repo: ""
        py_phone_caller_local_src_path: /abs/path/to/py-phone-caller
        py_phone_caller_uv_installer_checksum: "sha256:1f2aa4d24003ae99e4979f87f5e3122d240ec6b1ef0bc06c4bee3e33bb9151f2"
        py_phone_caller_spacy_model_checksum: "sha256:1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"
        py_phone_caller_caddy_signing_key_checksum: "sha256:783dfee04b19e851a928cd87b34710213ebbe7628f98d9f34595ab83be578c00"

        # 5. Locally managed PostgreSQL, Redis, and Caddy (no heavy APISIX/Keycloak)
        py_phone_caller_manage_postgresql: true
        py_phone_caller_manage_queue: true
        py_phone_caller_manage_gateway: false
        py_phone_caller_manage_reverse_proxy: true
        py_phone_caller_manage_firewall: false

        # 6. Tuned ARM64 worker & systemd cgroup v2 resource controls
        py_phone_caller_ui_workers: 2
        py_phone_caller_ui_threads: 8
        py_phone_caller_ui_timeout: 120
        py_phone_caller_celery_concurrency: 2
        py_phone_caller_service_cpu_quota: ""
        py_phone_caller_service_memory_high: "512M"
        py_phone_caller_service_memory_max: "1G"
        py_phone_caller_service_tasks_max: 256
        py_phone_caller_service_resource_overrides:
          generate_audio:
            cpu_quota: "200%"
            memory_high: "2G"
            memory_max: "4G"
            tasks_max: 512
          celery_worker:
            cpu_quota: "200%"
            memory_high: "1G"
            memory_max: "2G"
            tasks_max: 512

        # 7. Single-node loopback & local Piper TTS overrides
        py_phone_caller_config_overrides:
          auth:
            provider: local
            oauth2:
              enabled: false
          gateway:
            behind_gateway: false
          commons:
            asterisk_host: "127.0.0.1"
          database:
            db_host: "127.0.0.1"
          queue:
            queue_host: "127.0.0.1"
            queue_url: "redis://127.0.0.1:6379/7"
          py_phone_caller_ui:
            ui_listen_on_host: "127.0.0.1"
            ui_listen_on_port: 5000
          caller_prometheus_webhook:
            prometheus_webhook_receivers: []
          caller_sms:
            caller_sms_carrier: on_premise
            modems:
              - id: sim7600_primary
                port: /dev/serial/by-id/usb-REPLACE_WITH_MODEM_ID-if02-port0
                baud_rate: 115200
                priority: 1
          generate_audio:
            tts_engine: piper_tts
            piper_language_code: en_US
            num_of_cpus: 2
            preload:
              piper_tts: []
          asterisk_recaller:
            times_to_dial: 0
            call_backup_callee_max_times: 0

        # 8. Verified ARM64 OpenAlert release bundle & loopback hub instance
        openalert_release:
          source: /abs/path/to/src/openalert/dist/openalertd-v1.1.0-linux-aarch64.tar.gz
          sha256: "REPLACE_WITH_YOUR_BUILT_ARM64_TARBALL_SHA256"
        openalert_instances:
          hub:
            service_name: openalertd.service
            config_template: "{{ playbook_dir }}/inventories/examples/templates/private.toml.j2"
            health_url: "http://127.0.0.1:8090/health"
            rest_port: 8090
            memory_high: "100M"
            memory_max: "256M"
            cpu_quota: "100%"
            tasks_max: 256
```

### Step 3.3: Deploy, Verify, and Confirm Idempotency

```bash
export ANSIBLE_CONFIG="$PWD/deploy/ansible/ansible.cfg"

# 1. Syntax check & deploy (first run downloads ~5.3 GB of ARM64 wheels into uv cache)
ansible-playbook -i ~/ppc-opi5-inventory/hosts.yml deploy/ansible/site.yml --syntax-check
ansible-playbook -i ~/ppc-opi5-inventory/hosts.yml deploy/ansible/site.yml --ask-vault-pass

# 2. Read-only post-deployment verification
ansible-playbook -i ~/ppc-opi5-inventory/hosts.yml deploy/ansible/verify.yml --ask-vault-pass

# 3. Unchanged rerun to prove idempotency (expected: changed=0, zero restarts)
ansible-playbook -i ~/ppc-opi5-inventory/hosts.yml deploy/ansible/site.yml --ask-vault-pass
```

> [!NOTE]
> **ARM64 `nvidia-cusparselt-cu13` Idempotency Handled Automatically**
> The upstream PyPI `aarch64` wheel for `nvidia-cusparselt-cu13==0.8.1` ships a `manylinux2014_sbsa` tag inside `.dist-info/WHEEL`, which normally forces `uv sync` to reinstall on every `aarch64` rerun. Both `install.yml` and `install_offline.yml` automatically normalize the installed venv's `.dist-info/WHEEL` tag to `manylinux2014_aarch64` after sync so repeated runs achieve `changed=0` cleanly.

---

## 4. Mode B: 100% Air-Gapped ARM64 Appliance Deployment (`airgapped`)

Air-gapped mode enforces **zero external network access** during installation and runtime:

- **Signed local `file:` APT mirror**: `stack_airgap_check.py` refuses any HTTP/HTTPS APT source, unsigned repository, or third-party APT hook.
- **Cryptographically verified offline bundle**: Every wheel, standalone Python `3.14.5`, `uv 0.11.15`, Rust `1.99.1-aarch64-unknown-linux-gnu` toolchain, Cargo crate cache, and Piper TTS `.onnx` model is pinned in `bundle-manifest.json` with a top-level SHA-256 checksum.
- **Kernel network namespace isolation during build**: Both `uv sync --offline` and `maturin build --offline` execute inside `unshare --net` (zero network interfaces besides `lo`).
- **Systemd runtime egress lockdown**: All 11 Python services run with `IPAddressDeny=any`, `IPAddressAllow=localhost`, `PPC_OFFLINE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `UV_OFFLINE=1`, `PIP_NO_INDEX=1`, and `CARGO_NET_OFFLINE=true`.

### Step 4.1: Build the Signed Local ARM64 `file:` APT Mirror (on a Connected Staging ARM64 Host)

Use the repository's `tests/files/prepare_airgap_fixture.py` helper (and `deploy/ansible/tests/prepare_airgap_fixture.yml`) on an online ARM64 staging host (or on the Orange Pi 5 Plus before disconnecting it from the internet):

```bash
sudo mkdir -p /srv/offline/tools /srv/offline/debs /srv/offline/apt-mirror /srv/offline/signing /srv/offline/export-v1
# Copy tests/files/prepare_airgap_fixture.py to /srv/offline/tools/
# Download target ARM64 .deb packages (plus dependencies, e.g. via apt-get download /
# apt-get install --download-only) into /srv/offline/debs/, then generate a GPG key and repo:

sudo python3 /srv/offline/tools/prepare_airgap_fixture.py apt \
  --debs /srv/offline/debs/*.deb \
  --output-root /srv/offline/apt-mirror \
  --signing-home /srv/offline/signing \
  --signing-key "airgap-signing@internal" \
  --architecture arm64
```

This indexes the ARM64 `.deb` packages, signs `Release` / `Release.gpg` / `InRelease` with the local GPG key, and exports the public key alongside the repository under `/srv/offline/apt-mirror`.

### Step 4.2: Build and Contract-Validate the ARM64 Offline Bundle

Prepare a clean staged source tree (with exact build constraint pinning in `pyproject.toml`, e.g. `build-constraint-dependencies = ["cython==3.0.12"]`), clean ephemeral directories and test fixture keys/gits from staging `uv` and Cargo caches, and write a JSON spec (`export-spec.json`) for `prepare_airgap_fixture.py export --spec`:

```bash
# 1. Clean ephemeral directories and unpacked test fixtures from staged uv & Cargo caches before export:
#    - Remove raw-cargo/registry/src (keep registry/cache/*.crate and registry/index/)
#    - Remove uv-cache/environments-v2, uv-cache/sdists-v9/editable, uv-cache/sdists-v9/.git
#    - Convert any absolute internal symlinks inside uv-cache to relative symlinks
python3 - <<'PY'
import os
root = "/srv/offline/raw-uv-cache"
for dirpath, dirnames, filenames in os.walk(root):
    for name in list(dirnames) + list(filenames):
        p = os.path.join(dirpath, name)
        if os.path.islink(p):
            target = os.readlink(p)
            if os.path.isabs(target) and target.startswith(root + os.sep):
                os.unlink(p)
                os.symlink(os.path.relpath(target, dirpath), p)
PY

# 2. Export & contract-validate the complete ARM64 offline bundle via --spec
#    (see deploy/ansible/tests/prepare_airgap_fixture.yml and tests/test_airgap_preparation.py
#     for the full export spec schema covering python, uv, uv_cache, rust_toolchain, cargo,
#     piper_models, spacy_wheel, openalert_release, and source_dir).
sudo python3 /srv/offline/tools/prepare_airgap_fixture.py export \
  --spec /srv/offline/export-spec.json
```

Verify the exported bundle-manifest and source-manifest JSON files (`bundle-manifest.json` and `source-manifest.json`), and record:
- `py_phone_caller_airgap_manifest_checksum` (SHA-256 of `/srv/offline/export-v1/bundle-manifest.json`)
- `py_phone_caller_airgap_source_manifest_checksum` (SHA-256 of `source-manifest.json`)

Copy the staged source directory and `source-manifest.json` to your Ansible controller (e.g., `/srv/airgap-release/source` and `/srv/airgap-release/source-manifest.json`). Note: when running pre-checks with Python directly against an extracted bundle's `python/` runtime, invoke Python with `-B` (`PYTHONDONTWRITEBYTECODE=1`) so `__pycache__` `.pyc` timestamps do not drift from strict bundle checksums.

### Step 4.3: Switch Target SBC to the Signed Local `file:` APT Mirror & Clean Desktop Hooks

On the target ARM64 appliance (or Ubuntu 26.04 air-gapped target), back up online APT sources and any desktop/Armbian/ESM APT hook files (such as `/etc/apt/apt.conf.d/20apt-esm-hook.conf` or `Invoke` / `Pre-Install-Pkgs` hooks) that `stack_airgap_check.py` deliberately rejects in strict air-gapped mode:

```bash
sudo mkdir -p /root/apt-backup/sources.list.d /root/apt-backup/apt.conf.d

# 1. Back up online APT sources
sudo mv /etc/apt/sources.list /root/apt-backup/ 2>/dev/null || true
sudo mv /etc/apt/sources.list.d/* /root/apt-backup/sources.list.d/ 2>/dev/null || true

# 2. Back up Armbian / desktop APT hook files (Post-Invoke, Pre-Install-Pkgs, apt-file)
for f in 02-armbian-postupdate 20dbus 20packagekit 50appstream 50apt-file.conf \
         70debconf 20auto-upgrades 50unattended-upgrades; do
  [ -f "/etc/apt/apt.conf.d/$f" ] && sudo mv "/etc/apt/apt.conf.d/$f" /root/apt-backup/apt.conf.d/
done

# 3. Install ONLY the signed local file: mirror source + keyring
sudo cp /srv/offline/apt-mirror/offline-mirror.gpg /etc/apt/keyrings/py-phone-caller-offline.gpg
sudo tee /etc/apt/sources.list.d/py-phone-caller-offline.sources >/dev/null <<'EOF'
Types: deb
URIs: file:/srv/offline/apt-mirror/mirror
Suites: ./
Signed-By: /etc/apt/keyrings/py-phone-caller-offline.gpg
EOF

sudo apt-get update
```

*(If you ever wish to return the board to online updates later, simply remove `py-phone-caller-offline.sources` and restore the files from `/root/apt-backup/`.)*

### Step 4.4: Create `hosts-airgapped.yml` and Run `site.yml`

Switch the inventory variables from Section 3.2 to air-gapped mode:

```yaml
        py_phone_caller_connectivity: airgapped
        py_phone_caller_git_repo: ""
        py_phone_caller_local_src_path: /srv/airgap-release/source
        py_phone_caller_airgap_networks: []
        py_phone_caller_airgap_bundle_dir: /srv/offline/export-v1/py-phone-caller
        py_phone_caller_airgap_manifest_path: /srv/offline/export-v1/bundle-manifest.json
        py_phone_caller_airgap_manifest_checksum: "sha256:REPLACE_WITH_BUNDLE_MANIFEST_SHA256"
        py_phone_caller_airgap_source_manifest_path: /srv/airgap-release/source-manifest.json
        py_phone_caller_airgap_source_manifest_checksum: "sha256:REPLACE_WITH_SOURCE_MANIFEST_SHA256"
        py_phone_caller_airgap_rust_toolchain: "1.99.1-aarch64-unknown-linux-gnu"
        py_phone_caller_python_version: "3.14.5"
        py_phone_caller_uv_version: "0.11.15"
```

And point `generate_audio` to the verified offline bundle models directory:

```yaml
          generate_audio:
            tts_engine: piper_tts
            pre_trained_models_folder: /srv/offline/export-v1/py-phone-caller/models
            piper_models_folder: piper
            piper_language_code: en_US
            num_of_cpus: 2
            preload:
              piper_tts: []
```

Run the air-gapped deployment and verification:

```bash
export ANSIBLE_CONFIG="$PWD/deploy/ansible/ansible.cfg"

ansible-playbook -i ~/ppc-opi5-inventory/hosts-airgapped.yml deploy/ansible/site.yml --ask-vault-pass
ansible-playbook -i ~/ppc-opi5-inventory/hosts-airgapped.yml deploy/ansible/verify.yml --ask-vault-pass

# Prove air-gapped idempotency (expected: changed=0, zero service restarts)
ansible-playbook -i ~/ppc-opi5-inventory/hosts-airgapped.yml deploy/ansible/site.yml --ask-vault-pass
```

---

## 5. USB GSM Modem Setup (`caller_sms` + `rust_engine` — SIM7600E-H)

When using `caller_sms_carrier: on_premise` with a USB LTE/GSM modem (such as the **SimTech SIM7600E-H**, USB ID `1e0e:9001`):

1. **Identify the persistent AT port** (never use `/dev/ttyUSB*`):
   ```bash
   ls -la /dev/serial/by-id/
   # On SIM7600 modems, interface -if02-port0 is the primary AT command interface
   ```
2. **Release the modem from `ModemManager`**: Ubuntu/Armbian images run `ModemManager` by default, which holds `/dev/ttyUSB2` and blocks `rust_engine`. Add a targeted udev rule so `ModemManager` ignores your SMS modem (replace `1e0e` / `9001` with your modem's `lsusb` vendor/product IDs):
   ```bash
   sudo tee /etc/udev/rules.d/99-py-phone-caller-sim7600-ignore-mm.rules >/dev/null <<'EOF'
   ACTION=="add|change|move|bind", SUBSYSTEM=="usb", ATTRS{idVendor}=="1e0e", ATTRS{idProduct}=="9001", ENV{ID_MM_DEVICE_IGNORE}="1"
   ACTION=="add|change|move|bind", SUBSYSTEM=="tty", ATTRS{idVendor}=="1e0e", ATTRS{idProduct}=="9001", ENV{ID_MM_DEVICE_IGNORE}="1"
   EOF
   sudo udevadm control --reload-rules
   sudo udevadm trigger --attr-match=idVendor=1e0e --attr-match=idProduct=9001
   sudo systemctl restart ModemManager
   sudo fuser -v /dev/ttyUSB*   # Must show no process holding the AT port
   ```
3. **Configure all four required `ModemConfig` fields** (`id`, `port`, `baud_rate`, `priority`) under `caller_sms.modems` and confirm `py-phone-caller` belongs to the `dialout` group (`id py-phone-caller`).
4. **Verify `rust_engine` starts cleanly**:
   ```bash
   sudo systemctl restart py-phone-caller-caller-sms py-phone-caller-celery-worker
   sudo journalctl -u py-phone-caller-caller-sms -n 20 --no-pager
   # Expected: "Starting engine with 1 modem(s)..." and "Rust SMS engine started successfully."
   ```

---

## 6. Local LAN SIP Softphone Call Validation (`asterisk_caller` + Offline Piper TTS)

Before connecting a production SIP trunk, you can validate the complete voice pipeline (`asterisk_caller` → Asterisk 22 ARI/Stasis → `asterisk_ws_monitor` → offline `generate_audio` Piper TTS → RTP playback → `caller_register` `/heard` & `/ack` callbacks) on your local LAN with any SIP softphone (such as **Linphone**):

1. **Provision local PJSIP extension `1000` via Ansible** (on a trusted management/test VLAN) by setting `asterisk_sip_bindaddr: "0.0.0.0:5060"` (or your LAN IP `:5060`) and `asterisk_sip_exten_1000_enabled: true` in your inventory (or via `-e '{"asterisk_sip_exten_1000_enabled": true}'`). The `asterisk_py_phone_caller` role automatically generates a 24-character random password (persisted in `/etc/asterisk/pjsip_py_phone_caller.conf` for `changed=0` idempotency across reruns), configures `allow=ulaw,alaw,gsm,g722`, `dtmf_mode=auto`, `rewrite_contact=yes`, `rtp_symmetric=yes`, `force_rport=yes`, `direct_media=no`, `max_contacts=1`, `remove_existing=yes`, and `qualify_frequency=0` (so mobile/VPN softphones are never falsely marked `Unavail`), verifies Asterisk loaded `Endpoint: 1000`, and prints the username/password in the Ansible execution log. Restart `asterisk` once if you changed `asterisk_sip_bindaddr`.
2. **Set `asterisk_chan_type` for local extensions**: in `settings.toml` (or inventory `py_phone_caller_config.asterisk_caller.asterisk_chan_type`), use `"PJSIP"` when dialing a local PJSIP endpoint (`PJSIP/1000`), or `"PJSIP/<trunk-name>"` when dialing external numbers through a configured SIP trunk (`PJSIP/<number>@<trunk-name>`).
3. **Register your softphone** to `<appliance-ip>:5060` (UDP, extension `1000`, using the password reported by Ansible) and verify registration:
   ```bash
   sudo asterisk -rx "pjsip show endpoints"
   # Expected: Endpoint: 1000 Not in use / Contact: 1000/sip:1000@<client-ip>:... NonQual
   ```
4. **Trigger a live test voice alert** on the appliance:
   ```bash
   curl -sS -X POST http://127.0.0.1:8081/place_call \
     -H 'Content-Type: application/json' \
     -d '{"phone":"1000","lang":"en_US","message":"Hello from your air-gapped appliance! Press four to acknowledge this alert."}'
   ```
5. **Confirm end-to-end persistence in PostgreSQL**:
   ```bash
   sudo -u postgres psql -d py_phone_caller -x -c \
     "SELECT phone, asterisk_chan, dialed_times, first_dial, heard_at, acknowledge_at, lang FROM calls ORDER BY first_dial DESC LIMIT 1;"
   ```
   After answering and listening to the offline Piper TTS message, `heard_at` is populated automatically via the Asterisk dialplan `/heard` callback; pressing **`4`** after the beep populates `acknowledge_at` via `/ack`.

---

## 7. Measured Orange Pi 5 Plus (RK3588) Reference Benchmarks (`2026-11-19` / `2026-11-21`)

The table below records real measurements captured on an **Orange Pi 5 Plus (RK3588, 8 GB RAM, 512 GB NVMe, Armbian 26.11.3 / Ubuntu 26.04 LTS `aarch64`)** running all 16 services simultaneously:

| Metric | Connected (`online`) | Air-Gapped (`airgapped`) |
| :--- | :--- | :--- |
| **Unchanged `site.yml` Rerun** | `ok=225 changed=0 failed=0` (16/16 identical timestamps) | `ok=259 changed=0 failed=0` (16/16 identical timestamps) |
| **`verify.yml` Read-Only Probe** | `ok=11 changed=0 failed=0` (11 units, 7 APIs, UI `200`, Caddy `200`) | `ok=11 changed=0 failed=0` (11 units, 7 APIs, UI `200`, Caddy `200`) |
| **System RAM Used (Steady State / Post-Reboot)** | `2.5 GiB / 7.7 GiB` (`5.2 GiB` available) | `2.1 GiB / 7.7 GiB` (`5.6 GiB` available, `0 B` swap after reboot) |
| **`openalertd v1.1.0` (`arm64`) RSS** | `3.3 MiB` (`MemoryHigh=100M`, `MemoryMax=256M`) | `5.6 MiB` (`MemoryHigh=100M`, `MemoryMax=256M`) |
| **`generate_audio` / `ui` / `celery_worker` RSS** | `566 MiB` / `172 MiB` / `148 MiB` | Within configured cgroup v2 bounds (`4G` / `1G` / `2G`) |
| **Piper TTS (`en_US.onnx`, `num_of_cpus=2`) Cold / Warm** | `7,438 ms` / `6,223 ms` (16-bit 8 kHz mono WAV) | `7,642 ms` (`86,828 B`) / `6,372 ms` (`51,756 B`) from offline bundle |
| **Live USB GSM SMS (`SIMCOM_SIM7600E-H`)** | — | Delivered on Attempt 1 in `14s` (`+CMGS` / `OK`, handset receipt confirmed, `IPAddressDeny=any`) |
| **Live VoIP/SIP Voice Call (Asterisk 22 + LAN Softphone)** | — | Answered (`34s`), live offline Piper TTS (`8.6s`, `123 KiB` WAV) played over RTP, `heard_at` persisted in PostgreSQL (`IPAddressDeny=any`) |
| **RK3588 Peak SoC Thermal** | `44.4°C` post-TTS (`50.8°C` during Rust release link) | `45.3°C` post-TTS |
| **Root NVMe Usage (`/`)** | `16 GB / 469 GB (4%)` | `30 GB / 469 GB (7%)` (includes `6.1 GB` offline bundle + APT mirror) |
| **Cold Reboot Recovery** | Verified via air-gapped full reboot | All 16/16 services `active`, `NRestarts=0`, ARI `200` + Stasis registered, `verify.yml` `ok=11 failed=0` |

Proceed to **[10. End-to-End Installation Validation Checklist](10-end-to-end-installation-validation.md)** to validate every single layer of your deployment step by step.
