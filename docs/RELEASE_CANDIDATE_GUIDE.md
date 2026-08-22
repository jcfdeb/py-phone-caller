# 🚀 Release Candidate & Standalone Execution Guide

> [!TIP]
> **Production Deployment Recommendation**:
> For production environments, automated Ansible deployments, or complete container stacks, please consult the primary **[Operator Installation Guide (A to Z)](OPERATOR_INSTALLATION_GUIDE.md)**.
>
> This guide is intended for developers and engineers running services individually in standalone mode over SSH.

---

## 📑 Table of Contents

1. [Environment Setup & UV Workspace](#1-environment-setup--uv-workspace)
2. [Configuration & Environment Variables](#2-configuration--environment-variables)
3. [Running Individual Microservices with UV](#3-running-individual-microservices-with-uv)
4. [Container Image Builds (Docker & Podman)](#4-container-image-builds-docker--podman)
5. [Key Hardening Highlights in Release 1.0.0](#5-key-hardening-highlights-in-release-100)
6. [Troubleshooting Remote Execution](#6-troubleshooting-remote-execution)

---

## 1. Environment Setup & UV Workspace

All services belong to the Python 3.14 multi-package `uv` workspace. When running services locally or over SSH:

```bash
# Sync all workspace packages and development tools
uv sync --all-packages --group dev

# Set mandatory Piccolo ORM configuration and python path
export PYTHONPATH="$(pwd)/src:$(pwd)/src/py-phone-caller-utils:${PYTHONPATH:-}"
export CALLER_CONFIG=src/config/settings.toml
export PICCOLO_CONF=py_phone_caller_utils.py_phone_caller_db.piccolo_conf
```

---

## 2. Configuration & Environment Variables

The platform uses `dynaconf`:
- **Local Runs**: `CALLER_CONFIG=src/config/settings.toml` or `CALLER_CONFIG_DIR=src/config`
- **Containers / Systemd**: Inject generated `DYNACONF_*` env files generated via `assets/scripts/config/toml_to_dynaconf_env.py`
- **First-Time Admin Bootstrap**: Set `UI_USER_RESET_PASSWORD=true` when starting `py_phone_caller_ui` to generate the initial admin password.

---

## 3. Running Individual Microservices with UV

All 11 microservices can be launched from the repository root:

```bash
# 1. Asterisk Caller (Port 8081)
uv run python -m asterisk_caller.asterisk_caller

# 2. Text-to-Speech Audio Generator (Port 8082)
uv run python -m generate_audio.generate_audio

# 3. Call Register & DB Migrations (Port 8083)
uv run python -m caller_register.caller_register

# 4. Prometheus Alertmanager Webhook (Port 8084)
uv run python -m caller_prometheus_webhook.caller_prometheus_webhook

# 5. Caller SMS Gateway (Port 8085)
uv run python -m caller_sms.caller_sms

# 6. Caller Scheduler (Port 8086)
uv run python -m caller_scheduler.caller_scheduler

# 7. Caller Address Book (Port 8087)
uv run python -m caller_address_book.caller_address_book

# 8. Web UI Management Console (Port 5000)
uv run python -m py_phone_caller_ui.app

# 9. Asterisk WebSocket Event Monitor (Background Client)
uv run python -m asterisk_ws_monitor.asterisk_ws_monitor

# 10. Asterisk Recaller (Background Retry Daemon)
uv run python -m asterisk_recaller.asterisk_recaller

# 11. Celery Background Worker
uv run python -m celery -A py_phone_caller_utils.tasks.celery_task worker --loglevel=info
```

---

## 4. Container Image Builds (Docker & Podman)

All Dockerfiles use the repository root as their build context:

```bash
# Build a single container image:
podman build -f src/caller_scheduler/Dockerfile . -t caller_scheduler:1.0.0

# Build all 11 container images simultaneously:
./assets/scripts/containers/build-containers.sh
```

---

## 5. Key Hardening Highlights in Release 1.0.0

1. **Deterministic UV Locking**: Fast, single-lockfile dependency resolution across all 11 microservices on Python 3.14.
2. **Domain-Driven Service Boundaries**: Independent service ownership of tables (`calls`, `address_book`, `sms`, `users`).
3. **Resilient Legacy DB Auto-Repair**: `caller_register` automatically reconciles schema differences and missing legacy columns (`call_backup_callee_number_calls`, `annotations`).
4. **Standardized Health & Metrics**: Every HTTP service exposes `/health`, `/healthz`, `/live`, and `/metrics`.
5. **Offline Neural Audio**: Kokoro-82M, Piper ONNX, and Facebook MMS pre-download models into `pre_trained_models/` for 100% offline air-gapped TTS synthesis.
6. **Robust SMS Engine**: Native PyO3 Rust extension with UCS-2 / UTF-8 encoding support and PostgreSQL audit logging.

---

## 6. Troubleshooting Remote Execution

- **Network Interfaces**: Ensure `host = "0.0.0.0"` is configured in `settings.toml` if accessing services across the LAN.
- **Port Conflicts**: Verify no other service occupies ports `8081` through `8087` or `5000` (`ss -tulpn`).
- **Asterisk ARI Connection**: Test with `curl -u py-phone-caller:password http://<asterisk-host>:8088/ari/asterisk/info`.
- **Database Connection**: Confirm PostgreSQL 17 is reachable on port 5432 and Piccolo migrations have executed.
