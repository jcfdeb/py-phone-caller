# UV Workspace & Migration Guide

A comprehensive guide to the **Multi-Package UV Workspace** architecture in `py-phone-caller`, including instructions for local development, dependency management, service execution, testing, container builds, and building/publishing packages to PyPI.

---

## 1. Overview & Architecture

`py-phone-caller` is organized as a **Multi-Package UV Workspace** targeting **Python 3.14.x**. This modern packaging structure replaces legacy `requirements.in` and `requirements.txt` files with standard PEP 621 metadata, declarative dependency boundaries, and a single unified lockfile ([`uv.lock`](file:///home/jcf/Workspace/Antigravity/py-phone-caller/uv.lock)).

### Key Advantages of UV Workspaces

1. **Deterministic & Fast Dependency Resolution**:
   A single root [`uv.lock`](file:///home/jcf/Workspace/Antigravity/py-phone-caller/uv.lock) locks 187 dependencies across all microservices simultaneously in sub-second time, ensuring zero dependency drift across environments.
2. **Granular Microservice Isolation**:
   Heavy machine learning and audio libraries (`torch`, `torchaudio`, `transformers`, `piper-tts`, `soundfile`) are isolated to [`generate_audio`](file:///home/jcf/Workspace/Antigravity/py-phone-caller/src/generate_audio/pyproject.toml) and not forced onto lightweight REST APIs like `asterisk_caller` or `caller_register`.
3. **Automatic Editable Inter-Package Linking**:
   [`py_phone_caller_utils`](file:///home/jcf/Workspace/Antigravity/py-phone-caller/src/py-phone-caller-utils/pyproject.toml) is linked editably in the project `.venv`. Any change made inside the shared utility library is instantly reflected across all 11 microservices without manual re-installation.
4. **No Path Hacking**:
   Eliminates manual `sys.path.append` or custom `PYTHONPATH` tricks in Dockerfiles and development scripts.
5. **Python 3.14.x Native**:
   The workspace is pinned to Python 3.14 via [`.python-version`](file:///home/jcf/Workspace/Antigravity/py-phone-caller/.python-version) and `requires-python = ">=3.14, <3.15"`.

---

## 2. Workspace Package Catalog

The workspace consists of a root meta-project and **12 member packages** located under `src/`:

| Package Directory | Package Name (`pyproject.toml`) | Primary Role / Type | Key Dependencies |
| :--- | :--- | :--- | :--- |
| **`src/py-phone-caller-utils`** | `py_phone_caller_utils` | Core Shared Library | `piccolo`, `dynaconf`, `asyncpg`, `celery[redis]`, `opentelemetry-*`, `twilio`, `websockets` |
| **`src/asterisk_caller`** | `asterisk-caller` | REST Service (Port 8081) | `py_phone_caller_utils`, `aiohttp`, `requests` |
| **`src/asterisk_recaller`** | `asterisk-recaller` | Background Retry Daemon | `py_phone_caller_utils`, `aiohttp` |
| **`src/asterisk_ws_monitor`** | `asterisk-ws-monitor` | WebSocket ARI Listener | `py_phone_caller_utils`, `aiohttp`, `websockets` |
| **`src/caller_address_book`** | `caller-address-book` | REST Service (Port 8087) | `py_phone_caller_utils`, `aiohttp` |
| **`src/caller_prometheus_webhook`** | `caller-prometheus-webhook` | Alert Webhook (Port 8084) | `py_phone_caller_utils`, `aiohttp` |
| **`src/caller_register`** | `caller-register` | REST Service (Port 8083) | `py_phone_caller_utils`, `aiohttp` |
| **`src/caller_scheduler`** | `caller-scheduler` | REST Service (Port 8086) | `py_phone_caller_utils`, `aiohttp`, `pytz` |
| **`src/caller_sms`** | `caller-sms` | SMS Gateway (Port 8085) | `py_phone_caller_utils`, `aiohttp`, `twilio` |
| **`src/celery_worker`** | `celery-worker` | Celery Background Worker | `py_phone_caller_utils`, `celery[redis]` |
| **`src/generate_audio`** | `generate-audio` | TTS Engine (Port 8082) | `py_phone_caller_utils`, `torch`, `torchaudio`, `transformers`, `gTTS`, `piper-tts`, `audioop-lts` |
| **`src/py_phone_caller_ui`** | `py-phone-caller-ui` | Flask Web UI (Port 5000) | `py_phone_caller_utils`, `flask`, `flask-login`, `flask-session`, `asgiref`, `hypercorn`, `gunicorn` |

---

## 3. Installation & Environment Setup

### 3.1 Install `uv`

If `uv` is not already installed on your system:

```bash
# Standalone installer (Recommended for Linux/macOS)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via pip
pip install uv

# Verify installation
uv --version
```

### 3.2 Syncing the Workspace

Clone the repository and run `uv sync` from the repository root:

```bash
cd /path/to/py-phone-caller

# Install all workspace packages + development tools (pytest, ruff, etc.) on Python 3.14
uv sync --all-packages --group dev

# Install only production dependencies (no test tools)
uv sync --all-packages --no-dev
```

> [!NOTE]
> `uv` automatically downloads Python 3.14 if needed and manages a virtual environment at `.venv/`. You do **not** need to manually run `python -m venv` or source `.venv/bin/activate`.

---

## 4. Running Services

With `uv run`, commands execute inside the Python 3.14 managed environment automatically:

### 4.1 Launch Individual Microservices

```bash
# 1. Asterisk Caller (Port 8081)
uv run python -m asterisk_caller.asterisk_caller

# 2. Text-to-Speech Audio Generator (Port 8082)
uv run python -m generate_audio.generate_audio

# 3. Call Register (Port 8083)
uv run python -m caller_register.caller_register

# 4. Prometheus Alertmanager Webhook (Port 8084)
uv run python -m caller_prometheus_webhook.caller_prometheus_webhook

# 5. Caller SMS Service (Port 8085)
uv run python -m caller_sms.caller_sms

# 6. Caller Scheduler (Port 8086)
uv run python -m caller_scheduler.caller_scheduler

# 7. Caller Address Book (Port 8087)
uv run python -m caller_address_book.caller_address_book

# 8. Web UI Dashboard (Port 5000)
uv run python -m py_phone_caller_ui.app

# 9. Asterisk ARI WebSocket Monitor (Daemon)
uv run python -m asterisk_ws_monitor.asterisk_ws_monitor

# 10. Asterisk Recaller / Escalation Engine (Daemon)
uv run python -m asterisk_recaller.asterisk_recaller

# 11. Celery Worker (Background tasks via Redis)
uv run celery -A py_phone_caller_utils.tasks.celery_task worker --loglevel=info
```

### 4.2 Verify Full Deployment Health

Run the asynchronous deployment verification script:

```bash
uv run python verify_deployment.py
```

---

## 5. Managing Dependencies with UV

### 5.1 Adding Dependencies

To add a new package to a specific workspace member:

```bash
# Add a dependency to a specific microservice
uv add httpx --package asterisk-caller
uv add pydantic --package caller-register

# Add a shared dependency to the core utility library
uv add redis --package py_phone_caller_utils

# Add a development/testing tool to the root workspace
uv add --dev pytest-cov
```

### 5.2 Removing Dependencies

```bash
# Remove from a specific package
uv remove httpx --package asterisk-caller

# Remove a development dependency
uv remove --dev pytest-cov
```

### 5.3 Updating Dependencies & Lockfile

```bash
# Re-resolve and update the uv.lock file
uv lock

# Upgrade all packages to their latest compatible versions
uv lock --upgrade

# Verify lockfile consistency without modifying files (e.g. in CI)
uv lock --check
```

---

## 6. Testing & Quality Assurance

### 6.1 Running Pytest

Execute all unit and integration tests across the workspace:

```bash
# Run all tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run tests for a specific component
uv run pytest test/test_ui.py
uv run pytest test/test_asterisk_caller.py
uv run pytest test/test_caller_sms.py
```

### 6.2 Linting & Formatting with Ruff

```bash
# Check code for linting issues
uv run ruff check src test

# Format code automatically
uv run ruff format src test
```

---

## 7. Building & Publishing Packages to PyPI

Because every workspace component defines standard PEP 621 metadata, you can build source distributions (`.tar.gz`) and binary wheels (`.whl`) and publish them directly to **PyPI**, **TestPyPI**, or a private package registry (e.g., AWS CodeArtifact, GitLab Package Registry, JFrog Artifactory, Nexus) using `uv`.

### 7.1 Building Wheels and Source Distributions

```bash
# Build a specific package (e.g., the shared utilities library)
uv build --package py_phone_caller_utils

# Build a specific microservice package
uv build --package asterisk-caller
uv build --package py-phone-caller-ui

# Build all 12 workspace packages simultaneously
uv build --all-packages
```

The built distribution archives (`.tar.gz` and `.whl`) are placed into the `dist/` directory at the repository root.

### 7.2 Testing Distribution on TestPyPI

Before publishing to production PyPI, test the publishing and installation flow on TestPyPI:

```bash
# 1. Build the target package
uv build --package py_phone_caller_utils

# 2. Publish to TestPyPI using an API Token
uv publish --publish-url https://test.pypi.org/legacy/ --token "$TEST_PYPI_API_TOKEN"

# 3. Test installing from TestPyPI in a clean environment
uv pip install --index-url https://test.pypi.org/simple/ py_phone_caller_utils
```

### 7.3 Publishing to Official PyPI

```bash
# 1. Set your PyPI API token in an environment variable (Recommended)
export UV_PUBLISH_TOKEN="pypi-AgEIcHlwaS5vcmc..."

# 2. Build the package(s)
uv build --package py_phone_caller_utils

# 3. Publish to PyPI
uv publish

# Or pass the token directly:
uv publish --token "$PYPI_API_TOKEN"
```

### 7.4 Publishing to Private Package Indexes

For enterprise environments using private repositories:

```bash
# Using username & password
uv publish --publish-url "https://nexus.internal.lan/repository/pypi-hosted/" \
           --username "deployer" \
           --password "$REGISTRY_PASSWORD"

# Using token
uv publish --publish-url "https://gitlab.com/api/v4/projects/<PROJECT_ID>/packages/pypi" \
           --token "$GITLAB_JOB_TOKEN"
```

---

## 8. Rust SMS Engine (`sms_rust_backend`) with Maturin

The [`py_phone_caller_utils`](file:///home/jcf/Workspace/Antigravity/py-phone-caller/src/py-phone-caller-utils) package includes a high-performance native Rust extension used when `caller_sms` is configured with `caller_sms_carrier = "on_premise"`.

The Rust backend is built using **[Maturin](https://www.maturin.rs/)** and **PyO3**:

- **Graceful Fallback**: When the compiled Rust extension is not present, Python cleanly falls back to Twilio mode without crashing.
- **Local Development**:
  ```bash
  cd src/py-phone-caller-utils
  PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run maturin develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
  ```
- **Production Wheel Build**:
  ```bash
  cd src/py-phone-caller-utils
  PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run maturin build --release --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
  ```
  The built wheel is placed into `src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/target/wheels/`.

---

## 9. Container Builds (Docker / Podman)

Dockerfiles leverage multi-stage builds with `uv` for reproducible image builds from the root workspace lockfile:

```dockerfile
# Multi-stage builder example
FROM rockylinux:9-minimal AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src

# Sync only the target package and its workspace dependencies into /opt/venv
RUN uv python install 3.14 && \
    uv venv /opt/venv --python 3.14 --python-preference only-managed && \
    uv sync --frozen --no-dev --package asterisk-caller
```

To build all container images across the stack:

```bash
./src/build_all_images.sh
```

---

## 10. Troubleshooting & FAQ

### Q: `dynaconf.nodes.AccessError` when running tests or scripts locally?
**Answer**: Dynaconf expects credentials in `src/config/.secrets.toml` or via environment variables prefixed with `DYNACONF_`. For testing, [`pytest.ini`](file:///home/jcf/Workspace/Antigravity/py-phone-caller/pytest.ini) automatically injects dummy test credentials. For manual runs, copy sample settings:
```bash
cp src/config/settings.toml src/config/.secrets.toml
```

### Q: `ModuleNotFoundError: No module named 'audioop'` on Python 3.14?
**Answer**: Python 3.13 and 3.14 removed standard library `audioop`. The workspace automatically includes [`audioop-lts`](https://pypi.org/project/audioop-lts/) to maintain seamless compatibility with `pydub` and TTS engines.

### Q: How do I clean and reset the environment?
```bash
rm -rf .venv
uv cache clean
uv sync --all-packages --group dev
```
