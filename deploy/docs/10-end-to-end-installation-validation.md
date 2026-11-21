# 10. End-to-End Installation Validation Checklist

This guide provides a **complete, copy-pasteable 12-gate validation procedure** so any operator or community member can prove—from the OS and network layer up through Asterisk, OpenAlert, TTS audio synthesis, authenticated Web UI login, air-gap isolation, idempotency, and cold-reboot recovery—that their `py-phone-caller` + `openalertd` + Asterisk 22 installation is healthy and production-aligned.

Run **Gates 1 and 11** from your **Ansible controller**, and **Gates 2–10 and 12** directly on the **deployed host** via SSH.

---

## Quick Validation Scorecard

| Gate | Layer Validated | Pass Criterion |
| :--- | :--- | :--- |
| **Gate 1** | Automated Ansible Verification (`verify.yml`) | `failed=0`, `units active: 11`, `health endpoints OK: 7`, UI & Caddy `HTTP 200` |
| **Gate 2** | All 16 Systemd Services | Every unit `ActiveState=active` and `NRestarts=0` |
| **Gate 3** | Network & Private Listener Audit (`ss -tulpn`) | Only Caddy (`:80`, `:443`) listens publicly; all app/DB/Redis/ARI/OpenAlert ports bound to `127.0.0.1` |
| **Gate 4** | PostgreSQL & Redis/Valkey | `SELECT 1` succeeds on `py_phone_caller`; `redis-cli ping` returns `PONG` |
| **Gate 5** | Asterisk 22 PBX, ARI & Stasis App | Unauth ARI `401`, Auth ARI `200`, Stasis app `py-phone-caller` registered |
| **Gate 6** | OpenAlert Daemon (`openalertd`) | `/health` `{"status":"ok",...}`, `/api/v1/status` `HTTP 200`, cgroup v2 limits active |
| **Gate 7** | Python Microservices & Native Rust SMS Engine | 7/7 `/health` endpoints `HTTP 200`; `import rust_engine` loads native `.so` |
| **Gate 8** | Local Piper TTS WAV Synthesis | `POST /make_audio` `HTTP 200`; output verified as `RIFF WAVE, Microsoft PCM, 16 bit, mono 8000 Hz` |
| **Gate 9** | Admin Bootstrap, Strict-TLS Web UI, Health & `/api/docs` | Login `200`, `/health` & `/ready` `200`, `/api/cluster_health` `200`, 8/8 `/api/docs` OpenAPI specs `200` |
| **Gate 10** | Air-Gapped Isolation Audit *(air-gapped hosts)* | `IPAddressDeny=0.0.0.0/0 ::/0`, `PPC_OFFLINE=1`, `HF_HUB_OFFLINE=1`, signed `file:` APT only |
| **Gate 11** | Ansible Idempotency Rerun (`site.yml`) | `changed=0 failed=0`, identical `ExecMainStartTimestamp` across all 16 services |
| **Gate 12** | Cold Reboot Recovery & Thermal/Storage Health | All 16 services auto-start with `NRestarts=0` after `sudo reboot`, `verify.yml` passes |

---

## Gate 1: Automated Read-Only Ansible Verification (`verify.yml`)

Run from your **Ansible controller**:

```bash
export ANSIBLE_CONFIG="$PWD/deploy/ansible/ansible.cfg"
ansible-playbook -i /path/to/your/hosts.yml deploy/ansible/verify.yml --ask-vault-pass
```

**Expected output:**
```text
TASK [Summary] *****************************************************************
ok: [your-host] => {
    "msg": [
        "units active: 11",
        "health endpoints OK: 7",
        "web UI direct: HTTP 200",
        "web UI via Caddy: 200"
    ]
}
PLAY RECAP *********************************************************************
your-host : ok=11 changed=0 unreachable=0 failed=0 skipped=1
```

---

## Gate 2: Verify All 16 Systemd Services Are Active (`NRestarts=0`)

Run on the **deployed host** (omit `asterisk` or `openalertd` if you set their selectors to `false`):

```bash
UNITS=(
  asterisk postgresql redis-server caddy openalertd
  py-phone-caller-caller-register
  py-phone-caller-asterisk-caller
  py-phone-caller-asterisk-recaller
  py-phone-caller-asterisk-ws-monitor
  py-phone-caller-caller-address-book
  py-phone-caller-caller-prometheus-webhook
  py-phone-caller-caller-scheduler
  py-phone-caller-caller-sms
  py-phone-caller-generate-audio
  py-phone-caller-py-phone-caller-ui
  py-phone-caller-celery-worker
)

for u in "${UNITS[@]}"; do
  printf "%-44s %s\n" "$u" \
    "$(systemctl show -p ActiveState -p SubState -p NRestarts -p ExecMainStartTimestamp "$u" | tr '\n' ' ')"
done
```

*(On Rocky Linux 10, replace `redis-server` with `valkey`.)*

**Pass criterion:** Every deployed unit reports `ActiveState=active` and `NRestarts=0`.

---

## Gate 3: Private Listener & Network Surface Audit

Confirm that internal services bind strictly to loopback (`127.0.0.1` / `::1`) and that only Caddy (`:80`, `:443`) exposes application ingress:

```bash
sudo ss -tulpn | grep -E ':(80|443|5000|5038|5060|5432|6379|808[1-8]|8090)\b'
```

**Expected bindings (single-node / appliance profile):**

| Port | Service | Expected Bind Address |
| :--- | :--- | :--- |
| `80`, `443` | Caddy reverse proxy | `*` / `0.0.0.0` (only public ingress) |
| `5000` | `py-phone-caller-ui` (Gunicorn) | `127.0.0.1:5000` |
| `5060`, `5038`, `8088` | Asterisk SIP / AMI / ARI | `127.0.0.1` |
| `5432` | PostgreSQL | `127.0.0.1:5432` / `[::1]:5432` |
| `6379` | Redis / Valkey | `127.0.0.1:6379` / `[::1]:6379` |
| `8081`–`8087` | 7 Python aiohttp microservices | `127.0.0.1:8081` .. `127.0.0.1:8087` |
| `8090` | `openalertd` hub REST API | `127.0.0.1:8090` |

---

## Gate 4: Database (PostgreSQL) & Queue (Redis/Valkey) Health

```bash
# 1. Verify PostgreSQL accepts connections and core tables exist
sudo -u postgres psql -d py_phone_caller -c "\dt"

# 2. Verify Redis / Valkey responds PONG
redis-cli -h 127.0.0.1 -p 6379 ping
# (On Rocky Linux 10 with Valkey: valkey-cli -h 127.0.0.1 -p 6379 ping)
```

**Pass criterion:** PostgreSQL lists the `py_phone_caller` schema tables (`users`, `call_events`, `scheduled_calls`, `address_book`, etc.) and Redis/Valkey returns `PONG`.

---

## Gate 5: Asterisk 22 PBX, ARI Authentication & Stasis Registration

```bash
# 1. Confirm unauthenticated ARI requests are rejected (must be 401)
echo "ARI unauth HTTP: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/ari/asterisk/info)"

# 2. Confirm authenticated ARI succeeds (must be 200) and Stasis app is connected
ARI_USER=$(sudo python3 -c 'import tomllib; print(tomllib.load(open("/opt/py-phone-caller/app/config/settings.toml","rb"))["commons"]["asterisk_user"])')
ARI_PASS=$(sudo python3 -c 'import tomllib; print(tomllib.load(open("/opt/py-phone-caller/app/config/.secrets.toml","rb"))["commons"]["asterisk_pass"])')

echo "ARI auth HTTP: $(curl -s -u "$ARI_USER:$ARI_PASS" -o /dev/null -w '%{http_code}' http://127.0.0.1:8088/ari/asterisk/info)"
curl -s -u "$ARI_USER:$ARI_PASS" http://127.0.0.1:8088/ari/applications
echo ""
```

**Pass criterion:**
- `ARI unauth HTTP: 401`
- `ARI auth HTTP: 200`
- `/ari/applications` returns JSON containing `"name": "py-phone-caller"` (proving `py-phone-caller-asterisk-ws-monitor` holds a live WebSocket Stasis connection).

---

## Gate 6: OpenAlert Daemon (`openalertd`) Health & Cgroup Limits

```bash
# 1. Probe health & status endpoints
curl -s http://127.0.0.1:8090/health; echo ""
echo "Status HTTP: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8090/api/v1/status)"

# 2. Verify cgroup v2 resource controls & low memory footprint
systemctl show -p ActiveState -p MemoryCurrent -p MemoryHigh -p MemoryMax -p CPUQuotaPerSecUSec -p TasksMax openalertd
```

**Pass criterion:** `/health` returns `{"status":"ok",...,"version":"1.0.0"}`, `/api/v1/status` returns `200`, and cgroup limits (`MemoryHigh`, `MemoryMax`, `CPUQuota`, `TasksMax`) match your inventory.

---

## Gate 7: All 7 Python `/health` APIs & Native Rust SMS Engine

```bash
# 1. Probe all 7 aiohttp microservice health endpoints
for port in 8081 8082 8083 8084 8085 8086 8087; do
  printf "Port %s -> HTTP %s\n" "$port" "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${port}/health")"
done

# 2. Confirm native Rust SMS extension loads cleanly for this CPU architecture
SO_PATH=$(sudo -u py-phone-caller /opt/py-phone-caller/venv/bin/python -c 'import rust_engine.rust_engine as m; print(m.__file__)')
echo "Loaded: $SO_PATH"
file "$SO_PATH"
```

**Pass criterion:** All 7 ports return `HTTP 200`, and `file` confirms a native ELF shared object matching your architecture (`x86-64` or `ARM aarch64`).

---

## Gate 8: Local Text-to-Speech (Piper TTS) WAV Synthesis

Validate end-to-end speech synthesis through `generate_audio` (`:8082`) and confirm Asterisk-compatible WAV output (`RIFF WAVE, Microsoft PCM, 16 bit, mono 8000 Hz`):

```bash
# 1. Check active TTS engine and installed voices
curl -sS http://127.0.0.1:8082/languages; echo ""

# 2. Synthesize a test alert audio file
T0=$(date +%s%3N)
curl -sS -w "\nHTTP:%{http_code}\n" -X POST -G \
  --data-urlencode "message=End to end voice synthesis validation passed." \
  --data-urlencode "msg_chk_sum=validation-test-001" \
  --data-urlencode "lang=en_US" \
  http://127.0.0.1:8082/make_audio
T1=$(date +%s%3N)
echo "Elapsed: $((T1 - T0)) ms"

# 3. Verify readiness API and generated WAV format
curl -sS "http://127.0.0.1:8082/is_audio_ready?msg_chk_sum=validation-test-001&lang=en_US"; echo ""
file /opt/py-phone-caller/app/generate_audio/audio/validation-test-001_en_US.wav
stat -c "%n: %s bytes" /opt/py-phone-caller/app/generate_audio/audio/validation-test-001_en_US.wav
```

**Pass criterion:**
- `POST /make_audio` returns `{"status": 200, ...}` with `HTTP:200`.
- `GET /is_audio_ready` returns `{"exists": true}`.
- `file` reports: `RIFF (little-endian) data, WAVE audio, Microsoft PCM, 16 bit, mono 8000 Hz` (non-zero size).

*(You may delete the test file afterward: `sudo rm -f /opt/py-phone-caller/app/generate_audio/audio/validation-test-001_en_US.wav`.)*

---

## Gate 9: Initial Admin Bootstrap & Authentic Web UI Login over Strict TLS

> [!IMPORTANT]
> **First-Time Local Admin Account Creation (`standard` topology)**
> For security, `py-phone-caller-ui` does **not** silently create a default admin account with a hardcoded password when the `users` table is empty. You must explicitly trigger a one-shot bootstrap (either by running the command below once, or by temporarily setting `py_phone_caller_ui_reset_password: true` in Ansible for one run and then resetting it to `false`).

### Step 9.1: Bootstrap the Initial Admin User (One-Shot)

```bash
sudo -u py-phone-caller bash -c '
  cd /opt/py-phone-caller
  export CALLER_CONFIG_DIR=/opt/py-phone-caller/app/config
  export PICCOLO_CONF=py_phone_caller_utils.py_phone_caller_db.piccolo_conf
  export UI_USER_RESET_PASSWORD=true
  /opt/py-phone-caller/venv/bin/python -c "
import asyncio
from py_phone_caller_utils.config import settings
from py_phone_caller_utils.py_phone_caller_db.db_user import ensure_admin_user_exists
asyncio.run(ensure_admin_user_exists(settings.py_phone_caller_ui.ui_admin_user))
"
'
```

Save the generated 40-character admin password printed in the output securely (change it inside the Web UI after logging in).

### Step 9.2: Verify Authentic Web UI Login over Caddy Strict TLS

Replace `appliance.internal` with your configured `caddy_domain_name`, and set `CA` to Caddy's local root CA (for `py_phone_caller_tls_mode: internal`) or omit `--cacert` for public ACME certificates:

```bash
DOMAIN="appliance.internal"
CA="/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt"
ADMIN_EMAIL="admin@py-phone-caller.link"
read -rsp "Admin password: " ADMIN_PW; echo ""

COOKIES=$(mktemp)
trap 'rm -f "$COOKIES"' EXIT

# 1. GET /login with strict TLS certificate verification
echo "GET /login HTTP: $(sudo curl -sS --cacert "$CA" -c "$COOKIES" -o /dev/null -w '%{http_code}' "https://${DOMAIN}/login")"

# 2. POST /login -> expect HTTP 302 redirect to https://<domain>/
sudo curl -sS --cacert "$CA" -b "$COOKIES" -c "$COOKIES" -o /dev/null \
  -w "POST /login -> HTTP:%{http_code} LOCATION:%{redirect_url}\n" \
  -X POST \
  --data-urlencode "email=${ADMIN_EMAIL}" \
  --data-urlencode "password=${ADMIN_PW}" \
  "https://${DOMAIN}/login"

# 3. GET / (authenticated dashboard) -> expect HTTP 200 and Dashboard title
DASH_CODE=$(sudo curl -sS --cacert "$CA" -b "$COOKIES" -o /tmp/ppc-dash.html -w '%{http_code}' "https://${DOMAIN}/")
echo "GET / (authenticated) HTTP: $DASH_CODE ($(wc -c < /tmp/ppc-dash.html) bytes)"
grep -o '<title>[^<]*</title>' /tmp/ppc-dash.html | head -n 1
sudo rm -f /tmp/ppc-dash.html

# 4. Authenticated full-stack cluster health JSON (PostgreSQL, Redis, Asterisk, SMS, Gateway, IAM)
echo "GET /api/cluster_health:"
sudo curl -sS --cacert "$CA" -b "$COOKIES" "https://${DOMAIN}/api/cluster_health"; echo ""

# 5. Confirm PostgreSQL recorded last_login
sudo -u postgres psql -d py_phone_caller -c "SELECT email, is_active, last_login FROM users;"
```

### Step 9.3: Verify Public Health Probes & Unified `/api/docs` Portal (8/8 OpenAPI Specs)

```bash
DOMAIN="appliance.internal"
CA="/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt"

# 1. Public (unauthenticated) liveness & readiness probes over HTTPS
for p in /health /ready; do
  printf "%-10s " "$p"
  sudo curl -sS --cacert "$CA" -w " (HTTP %{http_code})\n" "https://${DOMAIN}${p}"
done

# 2. Unified OpenAPI portal + all 8 same-origin specs (plus negative 404 allowlist guard)
echo "GET /api/docs -> HTTP $(sudo curl -sS --cacert "$CA" -o /dev/null -w '%{http_code}' "https://${DOMAIN}/api/docs")"
for p in \
  /docs/swagger.json \
  /api/v1/alerts/docs/swagger.json \
  /api/v1/telephony/docs/swagger.json \
  /api/v1/sms/docs/swagger.json \
  /api/v1/contacts/docs/swagger.json \
  /api/v1/schedules/docs/swagger.json \
  /api/v1/audio/docs/swagger.json \
  /api/v1/registry/docs/swagger.json \
  /api/v1/unknown/docs/swagger.json; do
  printf "%-40s HTTP %s\n" "$p" \
    "$(sudo curl -sS --cacert "$CA" -o /dev/null -w '%{http_code}' "https://${DOMAIN}${p}")"
done
```

**Pass criterion:**
- `GET /login` → `200`, `POST /login` → `302` to `https://<domain>/`, `GET /` → `200` with `<title>py-phone-caller Dashboard</title>`, and `last_login` is populated in PostgreSQL.
- `GET /health` and `GET /ready` return `HTTP 200` without authentication; `GET /api/cluster_health` returns `HTTP 200` JSON when authenticated (and redirects to `/login` when unauthenticated).
- `GET /api/docs` and all 8 OpenAPI JSON paths return `HTTP 200` over the single HTTPS origin (with zero internal ports exposed), while `/api/v1/unknown/docs/swagger.json` returns `HTTP 404`.

*(For `enterprise` topology with Keycloak OIDC, follow the interactive OIDC login validation in [Guide 07](07-enterprise-gateway-and-observability.md).)*

---

## Gate 10: Air-Gapped Isolation Audit *(Air-Gapped Deployments Only)*

```bash
# 1. Confirm systemd network egress deny + localhost allow on all 11 Python services
for u in caller-register asterisk-caller asterisk-recaller asterisk-ws-monitor \
         caller-address-book caller-prometheus-webhook caller-scheduler \
         caller-sms generate-audio py-phone-caller-ui celery-worker; do
  printf "%-44s %s\n" "py-phone-caller-$u" \
    "$(systemctl show -p IPAddressDeny -p IPAddressAllow "py-phone-caller-$u" | tr '\n' ' ')"
done

# 2. Confirm offline runtime flags are enforced in unit files
grep -E 'PPC_OFFLINE|HF_HUB_OFFLINE|TRANSFORMERS_OFFLINE|UV_OFFLINE|PIP_NO_INDEX|CARGO_NET_OFFLINE' \
  /etc/systemd/system/py-phone-caller-generate-audio.service

# 3. Confirm ONLY signed file: APT repositories are active
grep -rnE '^(URIs:|deb )' /etc/apt/sources.list /etc/apt/sources.list.d/ 2>/dev/null
```

**Pass criterion:**
- Every Python service shows `IPAddressDeny=0.0.0.0/0 ::/0` and `IPAddressAllow=::1/128 127.0.0.0/8` (plus any explicit `py_phone_caller_airgap_networks` CIDRs).
- Offline environment variables (`PPC_OFFLINE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `UV_OFFLINE=1`, `PIP_NO_INDEX=1`, `CARGO_NET_OFFLINE=true`) are present.
- Only `file:` APT sources are configured.

---

## Gate 11: Deployment Idempotency Proof (`changed=0`)

1. On the **deployed host**, snapshot current service start timestamps:
   ```bash
   for u in asterisk postgresql redis-server caddy openalertd \
     py-phone-caller-caller-register py-phone-caller-asterisk-caller \
     py-phone-caller-asterisk-recaller py-phone-caller-asterisk-ws-monitor \
     py-phone-caller-caller-address-book py-phone-caller-caller-prometheus-webhook \
     py-phone-caller-caller-scheduler py-phone-caller-caller-sms \
     py-phone-caller-generate-audio py-phone-caller-py-phone-caller-ui \
     py-phone-caller-celery-worker; do
     printf "%-44s %s\n" "$u" "$(systemctl show -p ExecMainStartTimestamp -p NRestarts "$u" | tr '\n' ' ')"
   done > /tmp/before-rerun.txt
   ```
2. On your **Ansible controller**, re-run `site.yml` with zero inventory changes:
   ```bash
   ansible-playbook -i /path/to/your/hosts.yml deploy/ansible/site.yml --ask-vault-pass
   ```
3. On the **deployed host**, compare timestamps:
   ```bash
   for u in asterisk postgresql redis-server caddy openalertd \
     py-phone-caller-caller-register py-phone-caller-asterisk-caller \
     py-phone-caller-asterisk-recaller py-phone-caller-asterisk-ws-monitor \
     py-phone-caller-caller-address-book py-phone-caller-caller-prometheus-webhook \
     py-phone-caller-caller-scheduler py-phone-caller-caller-sms \
     py-phone-caller-generate-audio py-phone-caller-py-phone-caller-ui \
     py-phone-caller-celery-worker; do
     printf "%-44s %s\n" "$u" "$(systemctl show -p ExecMainStartTimestamp -p NRestarts "$u" | tr '\n' ' ')"
   done > /tmp/after-rerun.txt

   diff -u /tmp/before-rerun.txt /tmp/after-rerun.txt && echo "IDENTICAL_ALL_16_SERVICES"
   rm -f /tmp/before-rerun.txt /tmp/after-rerun.txt
   ```

**Pass criterion:** Ansible recap reports `changed=0 failed=0`, and `diff -u` prints empty output (`IDENTICAL_ALL_16_SERVICES`).

---

## Gate 12: Cold-Reboot Recovery & System Resource Health

Reboot the host and verify that the entire 16-service stack comes back unattended without manual intervention:

```bash
# On the deployed host:
sudo reboot
```

Wait ~45–60 seconds, SSH back in, and run:

```bash
uptime -s
free -h
df -h / /var/log

# Check thermal sensors (ARM64 SBCs / bare-metal servers)
for z in /sys/class/thermal/thermal_zone*; do
  [ -r "$z/temp" ] && echo "$(cat "$z/type"): $(awk '{printf "%.1f°C", $1/1000}' "$z/temp")"
done
```

Then re-run **Gate 1 (`verify.yml`)**, **Gate 2 (all 16 services `active`, `NRestarts=0`)**, and **Gate 5 (Asterisk ARI `200` + Stasis app `py-phone-caller`)**.

---

## Troubleshooting Quick-Reference

| Symptom | Root Cause | Resolution |
| :--- | :--- | :--- |
| `users` table is empty and Web UI login fails | `UI_USER_RESET_PASSWORD` defaults to `false` on fresh installs | Run the one-shot bootstrap in **Gate 9.1** (or set `py_phone_caller_ui_reset_password: true` for one Ansible run, then back to `false`). |
| Air-gap preflight rejects `Dir::Etc::apt-file-main` or `Post-Invoke` hooks | Desktop/Armbian images ship extra hooks under `/etc/apt/apt.conf.d/` | Move the hook files (`02-armbian-postupdate`, `20dbus`, `20packagekit`, `50appstream`, `50apt-file.conf`, `70debconf`, `20auto-upgrades`, `50unattended-upgrades`) to `/root/apt-backup/apt.conf.d/` (see [Guide 09 §4.3](09-arm64-appliance-and-airgapped-deployment.md#step-43-switch-target-sbc-to-the-signed-local-file-apt-mirror--clean-desktop-hooks)). |
| `curl https://<domain>/` fails TLS verification with `internal` TLS | Caddy's internal CA is not yet in the client OS trust store | Pass `--cacert /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt`, or copy `root.crt` into `/usr/local/share/ca-certificates/caddy-local.crt` and run `sudo update-ca-certificates`. |
| `openalertd` native build fails in `oqs-sys` (`Unable to find libclang`) | Missing LLVM/Clang development headers | `sudo apt-get install -y clang libclang-dev cmake`. |
| `/var/log` reaches 100% on Armbian SBCs | Armbian's default 50 MB `zram1` RAM-log (`armbian-ramlog`) | Raise `SIZE=256M` or set `ENABLED=false` in `/etc/default/armbian-ramlog` on NVMe-backed SBCs (see [Guide 09 §1](09-arm64-appliance-and-airgapped-deployment.md#armbian-varlog-zram1-production-advisory)). |
| Asterisk ARI returns `401` right after changing credentials | `res_ari.so` needs reload when `ari.conf` updates | `deploy/ansible/roles/asterisk_py_phone_caller` flushes handlers automatically; manually you can run `sudo asterisk -rx "module reload res_ari.so"`. |
| `caller_sms` logs `Invalid Modem Config JSON: missing field 'id'` | `caller_sms.modems` entry is missing `id`/`priority` or uses `baudrate` instead of `baud_rate` | Set all four required fields per modem: `id`, `port` (`/dev/serial/by-id/...`), `baud_rate` (e.g. `115200`), and `priority` (`1`, `2`, ...). |
| On-premise GSM SMS fails to open `/dev/ttyUSB*` (`Device or resource busy` / AT timeout) | `ModemManager` is holding the modem's AT serial port | Add an `ID_MM_DEVICE_IGNORE="1"` udev rule for the modem's `idVendor`/`idProduct`, restart `ModemManager`, and confirm `sudo fuser -v /dev/ttyUSB*` is empty (see [Guide 09 §5](09-arm64-appliance-and-airgapped-deployment.md#5-usb-gsm-modem-setup-caller_sms--rust_engine--sim7600e-h)). |
