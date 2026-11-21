# 05. Native Linux Packages (`.deb` & `.rpm`) Deployment Guide (`deploy/packaging/linux`)

This guide walks you step by step through installing **`py-phone-caller`** and **`openalertd`** on **Debian / Ubuntu** (`.deb`) and **RHEL / Rocky Linux / AlmaLinux / openSUSE** (`.rpm`) using the native packages in `dist/linux/`.

> [!NOTE]
> **Live Cloud VM Qualification (`2026-11-10`)**
> Qualified end-to-end on **Debian 13 (`trixie`) AMD64**, **Ubuntu 26.04.1 LTS (`resolute`) AMD64**, and **Rocky Linux 10.2 AMD64** (`SELinux Enforcing`) with zero APT/RPM/DNF warnings, offline wheel installation from `/opt/py-phone-caller/wheels`, and verified systemd startup against PostgreSQL and Redis/Valkey.

---

## 1. What the Native `.deb` & `.rpm` Packages Install

`dist/linux/` provides two packages per distribution family:

| Package | Debian / Ubuntu (`.deb`) | RHEL / Rocky / AlmaLinux (`.rpm`) | Installed Files & System Accounts |
| :--- | :--- | :--- | :--- |
| **`py-phone-caller`** | `py-phone-caller_1.0.0-1_all.deb` | `py-phone-caller-1.0.0-1.noarch.rpm` | • System user/group: `py-phone-caller`<br>• Application tree: `/opt/py-phone-caller/py-phone-caller/`<br>• Bundled offline wheels: `/opt/py-phone-caller/wheels/*.whl`<br>• Env file: `/opt/py-phone-caller/py-phone-caller/config/py-phone-caller.env` (`CALLER_CONFIG_DIR=/etc/py-phone-caller`)<br>• Config directory: `/etc/py-phone-caller/settings.toml` & `.secrets.toml.example`<br>• Systemd units: `/lib/systemd/system/*.service` + `py-phone-caller.target` |
| **`openalertd`** | `openalertd_1.0.0-1_amd64.deb`<br>*(or `_arm64.deb`)* | `openalertd-1.0.0-1.x86_64.rpm`<br>*(or `.aarch64.rpm`)* | • System user/group: `openalert`<br>• Binary: `/usr/local/bin/openalertd`<br>• Config: `/etc/openalertd/openalertd.toml` & `/etc/openalertd/profiles/*.toml`<br>• Assets: `/usr/share/openalertd/templates/` & `wifi-ap/`<br>• State/log dirs: `/var/lib/openalertd`, `/var/log/openalertd`<br>• Systemd unit: `/lib/systemd/system/openalertd.service` |

---

## Step 1: Install OS Prerequisites (PostgreSQL, Redis/Valkey & `ffmpeg`)

### On Debian 13 / Ubuntu 24.04+ / 26.04 LTS
```bash
sudo apt-get update
sudo apt-get install -y postgresql redis-server ffmpeg espeak-ng curl ca-certificates
sudo systemctl enable --now postgresql redis-server
```

### On Rocky Linux 10 / RHEL 10 / AlmaLinux 10
```bash
sudo dnf install -y postgresql-server valkey curl ca-certificates
sudo postgresql-setup --initdb
sudo systemctl enable --now postgresql valkey
```
*(Note: On Rocky Linux 10, `valkey` is the official drop-in replacement for `redis` and listens on the standard `127.0.0.1:6379` port).*

---

## Step 2: Create the PostgreSQL User and Database

Run these commands once on the database host to create the `py_phone_caller` role and database:

```bash
sudo -u postgres psql << 'EOF'
CREATE USER py_phone_caller WITH PASSWORD 'CHANGE_ME_STRONG_DB_PASSWORD';
CREATE DATABASE py_phone_caller OWNER py_phone_caller;
GRANT ALL PRIVILEGES ON DATABASE py_phone_caller TO py_phone_caller;
EOF
```

> [!TIP]
> **RHEL / Rocky Linux `pg_hba.conf` Tip**
> On Rocky Linux / RHEL, `/var/lib/pgsql/data/pg_hba.conf` defaults to `ident` for `127.0.0.1/32` and `::1/128`. Change `ident` to `scram-sha-256` (or `md5`) for TCP loopback connections, then reload PostgreSQL:
> ```bash
> sudo sed -i 's/\(host\s\+all\s\+all\s\+127\.0\.0\.1\/32\s\+\)ident/\1scram-sha-256/' /var/lib/pgsql/data/pg_hba.conf
> sudo sed -i 's/\(host\s\+all\s\+all\s\+::1\/128\s\+\)ident/\1scram-sha-256/' /var/lib/pgsql/data/pg_hba.conf
> sudo systemctl reload postgresql
> ```

---

## Step 3: Install the `.deb` or `.rpm` Packages

### On Debian / Ubuntu
```bash
sudo apt-get install -y \
  ./dist/linux/py-phone-caller_1.0.0-1_all.deb \
  ./dist/linux/openalertd_1.0.0-1_amd64.deb
```

### On Rocky Linux / RHEL / AlmaLinux
```bash
sudo dnf install -y \
  ./dist/linux/py-phone-caller-1.0.0-1.noarch.rpm \
  ./dist/linux/openalertd-1.0.0-1.x86_64.rpm
```

---

## Step 4: Populate the Python 3.14 Virtual Environment (`/opt/py-phone-caller/venv`)

The systemd service units execute `/opt/py-phone-caller/venv/bin/python`. Because the `py-phone-caller` package already bundles all 13 prebuilt workspace wheels in `/opt/py-phone-caller/wheels/`, creating the virtual environment takes only seconds:

```bash
# 1. Install uv if not already installed on the host
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh

# 2. Provision Python 3.14 inside /opt/py-phone-caller/.uv/python (never under /root/.local!)
#    and create /opt/py-phone-caller/venv so the unprivileged py-phone-caller user can execute it
sudo env UV_PYTHON_INSTALL_DIR=/opt/py-phone-caller/.uv/python /usr/local/bin/uv python install 3.14
sudo env UV_PYTHON_INSTALL_DIR=/opt/py-phone-caller/.uv/python /usr/local/bin/uv venv --python 3.14 /opt/py-phone-caller/venv

# 3. Install all 12 bundled py-phone-caller workspace wheels and dependencies into /opt/py-phone-caller/venv
sudo /usr/local/bin/uv pip install --python /opt/py-phone-caller/venv/bin/python \
  --find-links /opt/py-phone-caller/wheels \
  "py-phone-caller[all]==1.0.0"

# 4. Also install the native Rust SMS engine wheel if present in /opt/py-phone-caller/wheels
if ls /opt/py-phone-caller/wheels/rust_sms_engine-*.whl >/dev/null 2>&1; then
  sudo /usr/local/bin/uv pip install --python /opt/py-phone-caller/venv/bin/python \
    --no-deps /opt/py-phone-caller/wheels/rust_sms_engine-*.whl
fi

# 5. Ensure ownership belongs to the py-phone-caller service user
sudo chown -R py-phone-caller:py-phone-caller /opt/py-phone-caller
```

---

## Step 5: Configure `/etc/py-phone-caller/` and `/etc/openalertd/`

### 1. Create `/etc/py-phone-caller/.secrets.toml`
Copy the example secrets file and set your real credentials:

```bash
sudo cp /etc/py-phone-caller/.secrets.toml.example /etc/py-phone-caller/.secrets.toml
sudo chown root:py-phone-caller /etc/py-phone-caller/.secrets.toml
sudo chmod 0640 /etc/py-phone-caller/.secrets.toml
```

Edit `/etc/py-phone-caller/.secrets.toml`:
```toml
[commons]
asterisk_pass = "YOUR_ASTERISK_ARI_PASSWORD"

[database]
db_password = "CHANGE_ME_STRONG_DB_PASSWORD"

[caller_sms]
twilio_account_sid = ""
twilio_auth_token = ""

[py_phone_caller_ui]
ui_secret_key = "YOUR_32_CHAR_RANDOM_SESSION_SECRET"
ui_admin_password = "YOUR_ADMIN_PASSWORD"
```

### 2. Review `/etc/py-phone-caller/settings.toml`
Ensure `[commons] asterisk_host`, `[database] db_host = "127.0.0.1"`, and `[queue] queue_host = "127.0.0.1"` match your environment:

```bash
sudo nano /etc/py-phone-caller/settings.toml
```

### 3. Review `/etc/openalertd/openalertd.toml`
The `openalertd` package installs `/etc/openalertd/openalertd.toml` (with ready-to-use profile templates under `/etc/openalertd/profiles/`). Verify these paths in `/etc/openalertd/openalertd.toml` for systemd operation:

```toml
[storage]
path = "/var/lib/openalertd/openalert.db"

[identity]
key_file = "/var/lib/openalertd/node_identity.key"

[templates]
dir = "/usr/share/openalertd/templates"
```
*(Remember: if Asterisk PBX is running on the same machine on port `8088`, change `[relay] listen = "0.0.0.0:8088"` in `/etc/openalertd/openalertd.toml` to `"127.0.0.1:8089"` or set `enabled = false`).*

---

## Step 6: Enable, Start & Verify the Systemd Services

1. **Start `caller-register` First (Initializes the PostgreSQL Schema)**:
   ```bash
   sudo systemctl enable --now caller-register.service
   sleep 3
   curl -fsS http://127.0.0.1:8083/health
   ```

2. **Enable and Start the Full Suite (`py-phone-caller.target` + `openalertd.service`)**:
   ```bash
   sudo systemctl enable --now \
     caller-address-book.service \
     caller-scheduler.service \
     caller-sms.service \
     caller-prometheus-webhook.service \
     asterisk-caller.service \
     asterisk-recaller.service \
     asterisk-ws-monitor.service \
     generate-audio.service \
     celery-worker.service \
     py-phone-caller-ui.service \
     py-phone-caller.target \
     openalertd.service
   ```

3. **Verify All Health Endpoints** *(Note: allow ~10–15 seconds on first boot for `generate-audio.service` on `:8082` to initialize its PyTorch/Kokoro TTS models)*:
   ```bash
   sleep 12
   for port in 8081 8082 8083 8084 8085 8086 8087; do
     echo -n "Port $port: "
     curl -fsS "http://127.0.0.1:${port}/health" && echo ""
   done
   curl -fsS http://127.0.0.1:5000/health && echo ""
   curl -fsS http://127.0.0.1:8090/api/v1/status && echo ""
   ```
