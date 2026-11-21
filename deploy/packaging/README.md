# Release Packaging Suite (`py-phone-caller` v1.0.0)

> **Centralized Step-by-Step Guides**: See **[`deploy/docs/08-release-packaging.md`](../docs/08-release-packaging.md)** and the **[Deployment Documentation Hub](../docs/README.md)** for full step-by-step installation guides across every pillar.

This directory centralizes release packaging across all five distribution targets:

1. **Ansible**: [`deploy/ansible/packaging/`](../ansible/packaging/README.md) — Deterministic, secret-scrubbed Ansible release tarball (`py-phone-caller-ansible-v1.0.0.tar.gz`) + optional offline Galaxy collections bundle (`-offline.tar.gz`).
2. **PyPI**: [`deploy/packaging/pypi/`](pypi/README.md) — `py-phone-caller` meta-package (`[all]`, `[services]`, `[audio]`, `[ui]` extras + unified CLI) and all 12 workspace packages (`py_phone_caller_utils` + 11 microservices with `ppc-*` CLI entrypoints).
3. **RPM / DEB**: [`deploy/packaging/linux/`](linux/README.md) — Native `.deb` and `.rpm` system packages for `py-phone-caller` (`all`/`noarch`) and `openalertd` (`amd64`/`x86_64`, `arm64`/`aarch64`), plus `nfpm`, `.spec`, and `debian/` maintainer definitions.
4. **Docker & Docker Compose**: [`docker-compose.yml`](../../docker-compose.yml) and [`deploy/compose/`](../compose/README.md) — Full stack, hardware passthrough overlay (`docker-compose.hardware.yml`), and pinned APISIX + Keycloak OIDC gateway overlay (`docker-compose.gateway.yml`).
5. **Kubernetes & Helm**: [`deploy/k8s/`](../k8s/README.md), [`deploy/helm/py-phone-caller/`](../helm/py-phone-caller/README.md), and `deploy/packaging/k8s/` — Kustomize-ready raw manifests (with `Secret`, `openalertd`, and APISIX/Keycloak gateway) and packaged Helm v3 chart (`py-phone-caller-1.0.0.tgz`).

## Build All Release Artifacts in One Command

From the repository root:

```bash
uv run python deploy/packaging/build_all_releases.py
```

Outputs are written to `dist/` (`dist/ansible/`, `dist/pypi/`, `dist/linux/`, `dist/k8s/`) with a unified `dist/SHA256SUMS` and `dist/RELEASE_MANIFEST.json`.

---

## Live Cloud VM Qualification (`2026-11-08`)

All five distribution pillars have been live-qualified on real Google Cloud Platform (`jcf-gcloud`, `us-central1-a`) AMD64 virtual machines:

| Pillar | Target Environment | Qualification Method & Verified Result |
|---|---|---|
| **1. Ansible Role & Release Tarball** | Debian 13 (`trixie`) + Rocky Linux 10.2 (`Enforcing`) | Qualified on `2026-11-07` (`11/11` services active, `failed=0`, idempotent re-run `changed=0`). |
| **2. Native Linux Packages (`RPM` / `DEB`)** | `ppc-pkg-debian13-20261108` (Debian 13 AMD64) & `ppc-pkg-rocky10-20261108` (Rocky Linux 10.2 AMD64, SELinux `Enforcing`) | Installed `py-phone-caller_1.0.0-1_all.deb` + `openalertd_1.0.0-1_amd64.deb` via `apt-get install` and `py-phone-caller-1.0.0-1.noarch.rpm` + `openalertd-1.0.0-1.x86_64.rpm` via `dnf install` with zero warnings. Verified system users (`pyphonecaller`, `openalert`), `/etc/py-phone-caller`, `/etc/openalertd`, and systemd units. |
| **3. PyPI Wheels & Meta-Package** | Debian 13 (Python 3.14.10, PostgreSQL 17, Redis 8) & Rocky Linux 10.2 (Python 3.14.10, PostgreSQL 16.15, Valkey 8.0.11) | Installed `py-phone-caller[services,ui]==1.0.0` offline from `/opt/py-phone-caller/wheels` into `/opt/py-phone-caller/venv`. Verified `py-phone-caller list-services`, `ppc-*` CLI entrypoints, and live HTTP endpoints (`:8083`–`:8087/health` `200 OK`, `:5000/login` `200 OK`, `openalertd :8090/api/v1/status` `200 OK`). |
| **4. Docker & Docker Compose (+ APISIX Gateway)** | `ppc-pkg-debian13-20261108` (Docker Engine 29 + Compose v5) | Built all 12 application images (`caller_register`, `generate_audio`, `caller_address_book`, `asterisk_caller`, `asterisk_ws_monitor`, `asterisk_recaller`, `caller_sms`, `caller_prometheus_webhook`, `caller_scheduler`, `py_phone_caller_ui`, `celery_worker`, `openalertd`) from source, started `deploy/compose/docker-compose.yml` + `docker-compose.gateway.yml` (`apisix-etcd`, `apisix`), and verified `:8081`–`:8087/health`, `:5000/health`, `:5000/login`, `:8090/api/v1/status`, and APISIX `:9080`. |
| **5. Kubernetes & Helm v3 Chart** | `ppc-pkg-debian13-20261108` (`k3s v1.37.2+k3s1`, `helm v3.22.1`) | Validated all 43 Kubernetes objects in `py-phone-caller-k8s-manifests-v1.0.0.tar.gz` via `kubectl apply -k --dry-run=server`, ran `helm lint` (`0 failed`), deployed `py-phone-caller-1.0.0.tgz` (`helm upgrade --install`), rolled out all 13 deployments to `1/1 Running` (`0` restarts) with `Bound` PVCs (`openalertd-data-pvc`, `postgresql-data-pvc`), and verified all `ClusterIP` HTTP health endpoints inside the cluster. |

### Issues Discovered & Fixed During Live VM Qualification

1. **RPMv4 Immutable Region & File Metadata Tables (`deploy/packaging/linux/build_linux_packages.py`)**:
   - *Symptom*: RPM 4.19 (`dnf`/`rpm` on Rocky Linux 10.2) rejected minimal RPMv3 headers with `package has 0 files` and `Header SHA1 digest: BAD` after `rpmdb` appended `INSTALLTID`.
   - *Fix*: Upgraded the pure-Python RPM builder to emit full RPMv4 `RPMTAG_HEADERSIGNATURES` (`62`) and `RPMTAG_HEADERIMMUTABLE` (`63`) negative-offset region trailers, `RPMTAG_SHA256HEADER` (`273`), `PAYLOADDIGEST`/`PAYLOADDIGESTALT` (`5092`/`5097`), and full file metadata tables (`BASENAMES`, `DIRNAMES`, `DIRINDEXES`, `FILESIZES`, `FILEMODES`, `FILEDIGESTS`, etc.) while excluding OS-owned root directories from package ownership.
2. **System Configuration Directory Resolution (`src/py-phone-caller-utils/py_phone_caller_utils/config.py` & `deploy/packaging/linux/build_linux_packages.py`)**:
   - *Symptom*: Native DEB/RPM installs place `settings.toml` and `.secrets.toml` under `/etc/py-phone-caller`, which was not checked when `CALLER_CONFIG_DIR` was unset.
   - *Fix*: Added `/etc/py-phone-caller` and `py-phone-caller/config` fallbacks to `get_config_dir()` and staged `/opt/py-phone-caller/py-phone-caller/config/py-phone-caller.env` (`CALLER_CONFIG_DIR=/etc/py-phone-caller`) in the native Linux packages.
3. **Python Microservice `Dockerfile`s & `.dockerignore` (`src/*/Dockerfile`, `.dockerignore`)**:
   - *Symptom*: Runtime stages in the 11 Python `src/*/Dockerfile`s did not copy `settings.toml` from the builder stage, no root `.dockerignore` existed, and `src/generate_audio/Dockerfile` unconditionally downloaded all 4 TTS model families during `docker build`.
   - *Fix*: Added root `.dockerignore`, copied runtime code and `/app/py-phone-caller/config/settings.toml` under `/app/py-phone-caller/` in all 11 Python runtime stages, and defaulted `src/generate_audio/Dockerfile` to preload `piper_tts` (with `ARG PRELOAD_ALL_MODELS=false` for optional full model preloading).
4. **OpenAlert `Dockerfile` & Self-Contained Logo Assets (`src/openalert/Dockerfile`, `src/openalert/Dockerfile.arm64`, `src/openalert/src/ingress/dashboard.rs`)**:
   - *Symptom*: `oqs-sys` (via `bitchat-qudag`) required `cmake`, `ninja-build`, `clang`, `libclang-dev`, and `libssl-dev` in the Rust builder stage, and `dashboard.rs` used `include_bytes!("../../../../docs/openalert/openalert-logo*.png")` outside the `src/openalert` Docker build context.
   - *Fix*: Added `cmake`, `ninja-build`, `clang`, `libclang-dev`, `libssl-dev`, `CMAKE_GENERATOR=Ninja`, and `CMAKE_BUILD_PARALLEL_LEVEL=4` to `src/openalert/Dockerfile` and `Dockerfile.arm64`, placed `openalert-logo.png` and `openalert-logo-day.png` inside `src/openalert/templates/`, and updated `dashboard.rs` to embed from `../../templates/openalert-logo*.png`.
5. **Docker Compose, Kubernetes Manifests & Helm Chart Config/Secret Completeness (`deploy/compose/docker-compose.yml`, `deploy/k8s/*.yml`, `deploy/helm/py-phone-caller/`)**:
   - *Symptom*: Missing default `DYNACONF_COMMONS__ASTERISK_PASS`, `DYNACONF_CALLER_SMS__TWILIO_*`, and `DYNACONF_PY_PHONE_CALLER_UI__UI_*` env vars in `deploy/compose/docker-compose.yml`; `asterisk_callerid` typo (instead of `asterisk_caller_id`) and missing `is_audio_ready_endpoint` / `[logs]` / `[py_phone_caller_ui]` secrets in `deploy/k8s/` and `deploy/helm/`; and missing `OPENALERT_TEMPLATES__TEMPLATE_DIR=/templates` + `fsGroup: 10001` when mounting a Kubernetes PVC at `/var/lib/openalertd`.
   - *Fix*: Fixed all of the above across `deploy/compose/docker-compose.yml`, `deploy/k8s/`, and `deploy/helm/py-phone-caller/`.

