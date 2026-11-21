# 06. Python Wheels (`PyPI`) & Systemd Deployment Guide (`deploy/packaging/pypi` & `deploy/systemd`)

This guide explains how to deploy **`py-phone-caller`** directly from the prebuilt **Python Wheels / Source Distributions** (`dist/pypi/`) into a custom Python 3.14 virtual environment and manage the services using the systemd unit templates in `deploy/systemd/`.

---

## 1. The 13 PyPI Packages & Unified CLI Dispatcher

The `dist/pypi/` directory contains **13 publishable Python packages** (**1** umbrella meta-package `py-phone-caller` + **12** workspace packages: `py_phone_caller_utils` and the 11 services), built as 13 `.whl` wheels + 13 `.tar.gz` sdists:

| Package Name | CLI Binary | Unified CLI Command | Default Port | Description |
| :--- | :--- | :--- | :--- | :--- |
| **`py-phone-caller`** | `py-phone-caller` | `py-phone-caller list-services` | — | **Umbrella Meta-Package** with `[services]`, `[ui]`, `[audio]`, and `[all]` extras |
| `py_phone_caller_utils` | *(library)* | — | — | Shared config, Piccolo ORM DB, TTS, SMS, OIDC, and OpenTelemetry library |
| `asterisk-caller` | `ppc-asterisk-caller` | `py-phone-caller run asterisk-caller` | `8081` | Outbound call origination and playback via Asterisk ARI |
| `generate-audio` | `ppc-generate-audio` | `py-phone-caller run generate-audio` | `8082` | Multi-engine neural TTS synthesis service |
| `caller-register` | `ppc-caller-register` | `py-phone-caller run caller-register` | `8083` | Call attempt & status registry + DB schema initializer |
| `caller-prometheus-webhook` | `ppc-caller-prometheus-webhook` | `py-phone-caller run caller-prometheus-webhook` | `8084` | Prometheus Alertmanager & OpenAlert webhook receiver |
| `caller-sms` | `ppc-caller-sms` | `py-phone-caller run caller-sms` | `8085` | Twilio and on-premise USB GSM modem SMS gateway |
| `caller-scheduler` | `ppc-caller-scheduler` | `py-phone-caller run caller-scheduler` | `8086` | Celery-backed scheduled call service |
| `caller-address-book` | `ppc-caller-address-book` | `py-phone-caller run caller-address-book` | `8087` | Contact and on-call rotation management service |
| `py-phone-caller-ui` | `ppc-ui` | `py-phone-caller run ui` | `5000` | Multilingual Flask management Web UI |
| `asterisk-ws-monitor` | `ppc-asterisk-ws-monitor` | `py-phone-caller run asterisk-ws-monitor` | *(worker)* | Asterisk ARI WebSocket (`Stasis`) event consumer |
| `asterisk-recaller` | `ppc-asterisk-recaller` | `py-phone-caller run asterisk-recaller` | *(worker)* | Unacknowledged call retry and escalation worker |
| `celery-worker` | `ppc-celery-worker` | `py-phone-caller run celery-worker` | *(worker)* | Celery worker for priority and scheduled call tasks |

### Available Extras on `py-phone-caller`
- `py-phone-caller[services]==1.0.0`: Installs `py_phone_caller_utils` + all 9 backend/worker services (excludes UI and heavy neural TTS weights).
- `py-phone-caller[ui]==1.0.0`: Installs `py_phone_caller_utils` + `py-phone-caller-ui`.
- `py-phone-caller[audio]==1.0.0`: Installs `py_phone_caller_utils` + `generate-audio` (includes PyTorch, Kokoro, Piper, Transformers, AWS Boto3, gTTS).
- `py-phone-caller[all]==1.0.0`: Installs the `py-phone-caller` umbrella CLI plus **all 12 workspace packages** (all 13 PyPI packages) in one command.

---

## Step 1: Install `py-phone-caller` into `/opt/py-phone-caller/venv`

1. **Create System User & Directories**:
   ```bash
   sudo groupadd -r py-phone-caller || true
   sudo useradd -r -g py-phone-caller -d /opt/py-phone-caller -s /usr/sbin/nologin py-phone-caller || true
   sudo mkdir -p /opt/py-phone-caller/py-phone-caller/config /etc/py-phone-caller
   ```

2. **Create the Python 3.14 Virtual Environment & Install Wheels**:
   ```bash
   # Provision Python 3.14 inside /opt/py-phone-caller/.uv/python (never under /root/.local!)
   sudo env UV_PYTHON_INSTALL_DIR=/opt/py-phone-caller/.uv/python uv python install 3.14
   sudo env UV_PYTHON_INSTALL_DIR=/opt/py-phone-caller/.uv/python uv venv --python 3.14 /opt/py-phone-caller/venv

   # Install from local dist/pypi/ wheels (or your private PyPI index)
   sudo uv pip install --python /opt/py-phone-caller/venv/bin/python \
     --find-links ./dist/pypi \
     "py-phone-caller[all]==1.0.0"

   sudo chown -R py-phone-caller:py-phone-caller /opt/py-phone-caller
   ```

3. **Verify the Unified CLI**:
   ```bash
   /opt/py-phone-caller/venv/bin/py-phone-caller --version
   /opt/py-phone-caller/venv/bin/py-phone-caller list-services
   ```

---

## Step 2: Configure `/etc/py-phone-caller/`

Copy `src/config/settings.toml` into `/etc/py-phone-caller/settings.toml`, create `/etc/py-phone-caller/.secrets.toml` (see **[01. Architecture & Configuration](01-architecture-and-prerequisites.md)**), and point `/opt/py-phone-caller/py-phone-caller/config/py-phone-caller.env` to `/etc/py-phone-caller`:

```bash
sudo cp src/config/settings.toml /etc/py-phone-caller/settings.toml
echo "CALLER_CONFIG_DIR=/etc/py-phone-caller" | sudo tee /opt/py-phone-caller/py-phone-caller/config/py-phone-caller.env
sudo chown -R py-phone-caller:py-phone-caller /opt/py-phone-caller /etc/py-phone-caller
sudo chmod 0750 /etc/py-phone-caller
sudo chmod 0640 /etc/py-phone-caller/settings.toml /etc/py-phone-caller/.secrets.toml
```

---

## Step 3: Install & Start Systemd Units (`deploy/systemd/`)

The `deploy/systemd/` directory provides two unit styles:

### Style A: Native Host Systemd Units (`deploy/systemd/on-system/`)
Runs each Python service directly from `/opt/py-phone-caller/venv/bin/python` as the unprivileged `py-phone-caller` user, grouped under `py-phone-caller.target`:

```bash
sudo cp deploy/systemd/on-system/*.service deploy/systemd/on-system/py-phone-caller.target /etc/systemd/system/
sudo systemctl daemon-reload

# Start caller-register first to initialize PostgreSQL tables
sudo systemctl enable --now caller-register.service
sleep 3

# Enable and start the entire suite via the target unit
sudo systemctl enable --now \
  asterisk-caller.service \
  asterisk-recaller.service \
  asterisk-ws-monitor.service \
  caller-address-book.service \
  caller-prometheus-webhook.service \
  caller-scheduler.service \
  caller-sms.service \
  celery-worker.service \
  generate-audio.service \
  py-phone-caller-ui.service \
  py-phone-caller.target
```

### Style B: Rootless Podman Container Systemd Units (`deploy/systemd/as-non-root-container/`)
If you prefer to supervise rootless Podman containers via `systemd --user`, copy the templates from `deploy/systemd/as-non-root-container/` into `~/.config/systemd/user/` for your service account and enable `loginctl enable-linger <user>`.
