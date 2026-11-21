# ARM64 Appliance Profile (Orange Pi 5 Plus / RK3588 — Qualified `2026-11-19`)

**Physical Orange Pi 5 Plus (RK3588 `aarch64`) hardware qualification PASSED on
`2026-11-19`** for both **connected (`online`)** and **100% air-gapped
(`airgapped`)** all-in-one deployments (`py-phone-caller` 11 Python services +
native ARM64 Rust SMS backend + Asterisk 22 + PostgreSQL 18 + Redis 8 + Caddy
internal TLS + `openalertd v1.0.0` `arm64`).

Start from the sanitized
[Orange Pi 5 Plus appliance example](../inventories/examples/appliance-orangepi5plus/hosts.yml),
follow the turnkey
[ARM64 Appliance & Air-Gapped Deployment Guide](../../docs/09-arm64-appliance-and-airgapped-deployment.md)
and
[12-Gate End-to-End Validation Checklist](../../docs/10-end-to-end-installation-validation.md),
and pair them with the [support matrix](support-matrix.md) and
[topology/offline contract](topologies.md).

## Scope and architectural boundaries

The appliance profile targets an all-in-one single-board computer (SBC) running a
64-bit (`aarch64` / `arm64`) Debian 13 or Ubuntu 26.04 LTS userspace with
working `systemd` and cgroup v2 resource controls:

- **All-in-one local service selection:** `stack_deploy_py_phone_caller: true`
  and `stack_deploy_asterisk: true`, with locally managed PostgreSQL and
  Redis/Valkey (`py_phone_caller_manage_postgresql: true`,
  `py_phone_caller_manage_queue: true`).
- **Co-located OpenAlert (`arm64`):** `stack_deploy_openalert: false` by default
  in the example inventory; verified with `stack_deploy_openalert: true` using
  a native `aarch64-unknown-linux-gnu` `openalertd v1.0.0` schema-1 release
  bundle. Enable hardware serial/BLE passthrough only with explicit device paths
  and supplementary groups.
- **Standard local authentication:** `py_phone_caller_topology: standard` with
  Caddy (`py_phone_caller_ingress: caddy`, `py_phone_caller_tls_mode: internal`
  or `provided`). Heavy enterprise gateway containers (APISIX, etcd, Keycloak)
  are disabled (`py_phone_caller_manage_gateway: false`).
- **No automatic field-network takeover:** Wi-Fi AP (`hostapd`/`dnsmasq`),
  WireGuard tunnels, bootloader/U-Boot updates, and RK3588 NPU acceleration
  remain outside role scope and untouched by deployment.
- **Full locked Python workspace retained:** `uv sync --frozen --all-packages --no-dev`
  installs the complete locked dependency graph on `aarch64` (217 wheels,
  Python `3.14.5`, `uv 0.11.15`). Both `install.yml` and `install_offline.yml`
  automatically normalize the upstream `nvidia-cusparselt-cu13==0.8.1`
  `.dist-info/WHEEL` tag (`manylinux2014_sbsa` → `manylinux2014_aarch64`) in the
  installed venv so subsequent reruns remain cleanly `changed=0`.

## Hardware and OS provisioning prerequisites

Before running `site.yml` against an Orange Pi 5 Plus or compatible ARM64 SBC:

1. **Userspace and kernel:** verify 64-bit `aarch64` Debian 13 (Trixie) or
   Ubuntu 26.04 LTS (Resolute) / Armbian 26.x with `systemd`, cgroup v2 unified
   hierarchy (`cgroup2fs`), Python 3.11+ for Ansible target modules, and NVMe or
   eMMC storage (avoid high-churn PostgreSQL/SQLite WAL and TTS audio writes on
   unrated microSD media).
2. **Armbian `/var/log` (`zram1`) advisory:** Armbian enables `armbian-ramlog`
   (`SIZE=50M`) by default on `/var/log`. On NVMe-backed appliances, raise
   `SIZE=256M` or set `ENABLED=false` in `/etc/default/armbian-ramlog` so logs
   persist directly on NVMe.
3. **Cooling and power:** ensure active heatsink/fan cooling and a rated 5V/4A
   USB-C PD or fixed barrel supply before running multi-core Rust/Python builds
   or concurrent CPU speech synthesis.
4. **Persistent serial device paths:** never configure volatile `/dev/ttyUSB0`
   or `/dev/ttyACM0` names in `caller_sms.modems` or `openalert_instances`.
   Enumeration order can change across USB resets or reboots when multiple
   modems (e.g., SIM7600 cellular + Meshtastic LoRa USB serial) are attached.
   Always reference `/dev/serial/by-id/usb-...` symlinks or explicit `udev`
   `SYMLINK+=` rules tied to `ATTRS{idVendor}`, `ATTRS{idProduct}` and
   `ATTRS{serial}`.
5. **Private internal bindings:** keep PostgreSQL (`127.0.0.1:5432`), Redis
   (`127.0.0.1:6379`), Asterisk ARI (`127.0.0.1:8088`), local SIP/IAX listeners,
   all Python microservice HTTP ports (`PPC_HTTP_BIND_HOST=127.0.0.1`), OpenAlert
   (`127.0.0.1:8090`), and the Gunicorn UI upstream (`127.0.0.1:5000`) bound to
   loopback. Expose only the reviewed Caddy HTTPS origin on the intended
   management or field VLAN.

## Configurable worker, speech and systemd resource limits

The Python role (`deploy_py-phone-caller`) exposes inventory-driven worker and
`systemd` cgroup controls so an appliance inventory can bound CPU and memory
consumption without editing role templates:

| Variable | Default | Appliance example | Purpose |
| --- | --- | --- | --- |
| `py_phone_caller_ui_workers` | `4` | `2` | Gunicorn worker processes for `py_phone_caller_ui`. |
| `py_phone_caller_ui_threads` | `16` | `8` | Gunicorn threads per worker. |
| `py_phone_caller_ui_timeout` | `120` | `120` | Gunicorn request timeout in seconds. |
| `py_phone_caller_celery_concurrency` | `0` (Celery default) | `2` | Optional `--concurrency=N` flag on `celery_worker` when `> 0`. |
| `py_phone_caller_config.generate_audio.num_of_cpus` | `2` | `2` | CPU threads passed to local TTS synthesis (`piper_tts` / `kokoro_tts`). |
| `py_phone_caller_service_cpu_quota` | `""` (unbounded) | `""` | Default `CPUQuota=` across Python units (e.g. `"100%"`). |
| `py_phone_caller_service_memory_high` | `""` (unbounded) | `"512M"` | Default `MemoryHigh=` throttle threshold across Python units. |
| `py_phone_caller_service_memory_max` | `""` (unbounded) | `"1G"` | Default `MemoryMax=` hard limit across Python units. |
| `py_phone_caller_service_tasks_max` | `""` (unbounded) | `256` | Default `TasksMax=` limit across Python units. |
| `py_phone_caller_service_resource_overrides` | `{}` | Per-unit map | Per-service dictionary (`cpu_quota`, `memory_high`, `memory_max`, `tasks_max`) keyed by service `name` (e.g. `generate_audio`, `celery_worker`). |

`tasks/validate.yml` validates all worker counts, `num_of_cpus`, global resource
limits, and `py_phone_caller_service_resource_overrides` keys/formats before
staging configuration or touching `systemd`.

## Recorded physical hardware qualification (`2026-11-19`)

All five hardware qualification gates passed on a physical **Orange Pi 5 Plus
(RK3588, 8 cores, 7.7 GiB RAM, Fanxiang S501Q 512 GB NVMe, Armbian 26.11.3 /
Ubuntu 26.04 LTS `aarch64`, kernel `6.1.115-vendor-rk35xx`, `systemd 259`,
`cgroup2fs`)** — see [`docs/support-matrix.md`](support-matrix.md) for full
hashes and command evidence:

1. **Native ARM64 builds verified:** `openalertd v1.0.0` (`aarch64-unknown-linux-gnu`,
   Rust `1.99.1`, `1m 19s`, peak `50.8°C`), full `uv sync --frozen --all-packages --no-dev`
   (Python `3.14.5`, `uv 0.11.15`, 217 wheels), and native `rust_engine` SMS extension
   (`rust_engine.cpython-314-aarch64-linux-gnu.so`) built both online and from scratch
   offline inside `unshare --net`.
2. **Connected (`online`) & Air-Gapped (`airgapped`) idempotency:** unchanged
   `site.yml` reruns achieved `ok=225 changed=0 failed=0` (`online`) and
   `ok=259 changed=0 failed=0` (`airgapped`) with identical start timestamps and
   `NRestarts=0` across all 16 services (`asterisk`, `postgresql`, `redis-server`,
   `caddy`, `openalertd`, and 11 `py-phone-caller-*` units).
3. **Offline Piper TTS & authentic Web UI login:** Piper `en_US.onnx` (`num_of_cpus=2`)
   synthesized Asterisk-ready 8 kHz 16-bit mono PCM WAVs (`7,438 ms` / `6,223 ms` online;
   `7,642 ms` / `6,372 ms` air-gapped strictly from the offline bundle at `45.3°C` peak).
   Caddy strict-TLS login (`https://appliance.internal/login` → `302` → `200`, `80,859 B`)
   succeeded with `last_login` recorded in PostgreSQL 18.
4. **Air-gap isolation & private listeners (`ss -tulpn`):** `IPAddressDeny=0.0.0.0/0 ::/0`,
   `IPAddressAllow=::1/128 127.0.0.0/8`, `PPC_OFFLINE=1`, `HF_HUB_OFFLINE=1` verified on
   all 11 Python services; only Caddy `:80`/`:443` listen externally.
5. **Cold-reboot recovery:** after `sudo reboot`, all 16 services auto-started cleanly
   (`ActiveState=active`, `NRestarts=0`, `2.1 GiB / 7.7 GiB` RAM, `0 B` swap), Asterisk
   ARI (`401`/`200`) + Stasis app `py-phone-caller` reconnected automatically, and
   `verify.yml` passed (`ok=11 changed=0 failed=0`).
6. **Live physical USB GSM SMS delivery (`2026-11-20`):** with a physical
   **SimTech `SIMCOM_SIM7600E-H`** (`1e0e:9001`, firmware `SIM7600M22_V2.0.1`)
   released from `ModemManager` via `ENV{ID_MM_DEVICE_IGNORE}="1"`, `caller_sms`
   + native ARM64 `rust_engine` transmitted a live cellular SMS on Attempt 1
   (`+CMGS` / `OK` in `14s`, SQLite `status=2`, PostgreSQL `status="sent"`,
   operator confirmed live handset receipt) while the appliance stayed 100%
   air-gapped (`IPAddressDeny=any`).
7. **Live VoIP/SIP voice call with offline Piper TTS playback (`2026-11-20`):**
   with Asterisk 22 PJSIP registered to a LAN mobile SIP softphone (Linphone,
   extension `1000`), `POST http://127.0.0.1:8081/place_call` originated an ARI
   call (`asterisk_caller` → `caller_register` → `Stasis(py-phone-caller)` →
   `asterisk_ws_monitor` → `generate_audio`), synthesized a `123 KiB` 16-bit
   mono 8 kHz PCM WAV offline in `8.6s` from the air-gapped Piper `en_US.onnx`
   bundle, streamed audio over RTP (`GET /audio/...wav` `200`, operator
   confirmed clear voice reception), and recorded `heard_at` in PostgreSQL via
   the Asterisk `CURL` `/heard` callback (`34s` answered call duration) while
   all 11 Python services remained under `IPAddressDeny=any`. Physical BLE and
   LoRa RF transmission remain separately out of scope until authorized.
