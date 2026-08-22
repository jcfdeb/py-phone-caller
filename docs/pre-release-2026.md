# py-phone-caller pre-release 2026

Date: 2026-08-17
Target milestone: `1.0.0`
Status: pre-release hardening and production-readiness review

## Purpose

This document summarizes the recent hardening work performed on `py-phone-caller`, the current release posture, and the main recommendations before declaring the project production-ready for `1.0.0`.

The main goal of the recent work was to move the project from a lab/development stack toward a consistent, reproducible, air-gapped-friendly, deployment-ready system.

## Executive summary

`py-phone-caller` is now in a much stronger pre-release state:

- The project is aligned around the `uv` workspace model.
- Docker images no longer depend on legacy `requirements.*` files.
- Runtime configuration is no longer baked into images.
- Dynaconf-compatible environment files can be generated from TOML configuration and secrets.
- Database initialization is centralized through `caller_register` and now handles legacy schema drift more safely.
- The Web UI has been improved visually and hardened around login and admin bootstrap behavior.
- Rust SMS support and Kokoro audio generation have been validated locally.
- Monitoring integrations for Nagios and Zabbix have been modernized and live-tested against the running API.
- Deployment tooling has fewer hardcoded values and is more suitable for lab, air-gapped, and controlled LAN environments.

The main remaining production gap is API authentication. The Web UI has password protection, but most internal API endpoints are currently unauthenticated and must remain private until an authentication layer is added.

## Current architecture overview

The application is composed of multiple focused services:

| Component | Role |
| --- | --- |
| `asterisk_caller` | Receives requests to place calls or queue calls. |
| `asterisk_ws_monitor` | Watches Asterisk events and coordinates audio playback/call flow. |
| `generate_audio` | Generates audio files from text using Kokoro/Piper/MMS TTS. |
| `caller_register` | Initializes and repairs the database schema and registers calls. |
| `caller_prometheus_webhook` | Alertmanager-compatible webhook receiver for voice and SMS alerts. |
| `asterisk_recaller` | Selects calls to retry or backup calls to execute. |
| `caller_sms` | Sends SMS messages and can use Twilio or the Rust on-premise SMS engine. |
| `caller_scheduler` | Handles scheduled calls. |
| `caller_address_book` | Manages address book/on-call contact data. |
| `py_phone_caller_ui` | Provides the Web UI. |
| `celery_worker` | Runs asynchronous task workers. |
| `py_phone_caller_utils` | Shared library for DB access, config, tasks, voice helpers, and Rust SMS integration. |

External dependencies include:

- PostgreSQL
- Redis
- Asterisk / ARI / AMI
- Kokoro TTS model/runtime
- `ffmpeg` or compatible audio tooling
- optional SMS modem/runtime resources
- optional monitoring systems such as Nagios and Zabbix

## Recent major changes

### 1. `uv` workspace alignment

The project has been moved toward a consistent `uv`-managed workflow.

Key outcomes:

- The root workspace is the main dependency source of truth.
- Service Dockerfiles were updated to install packages through `uv sync --frozen --no-dev --package ...`.
- Container builds now use the repository root as build context where needed.
- Legacy dependency flows based on service-local `requirements.txt` files were removed from the deployment path.
- `uv.lock` is now central to reproducible dependency resolution.
- Python `3.14` alignment was applied to the service build flow.

Why this matters:

- Reproducible builds are easier.
- Dependency drift between local development and containers is reduced.
- Workspace packages such as `py_phone_caller_utils` are installed consistently instead of copied ad hoc.

### 2. Container build cleanup

The service Dockerfiles under `src/` were modernized.

Important changes:

- Images install only the target service package and required workspace dependencies.
- Runtime config is no longer copied into images.
- `PICCOLO_CONF` is set for services using Piccolo.
- `.dockerignore` was expanded to avoid baking local secrets, caches, generated audio, and temporary artifacts into images.
- A representative image build was validated successfully.

The intended pattern is now:

```bash
uv sync --frozen --no-dev --package <service-package>
```

rather than:

```bash
pip install -r requirements.txt
```

### 3. Cloud-native configuration model

The project now supports a more cloud-native configuration approach.

Instead of copying `src/config` into containers, configuration can be converted into Dynaconf-compatible environment files.

Added utility:

```text
assets/scripts/config/toml_to_dynaconf_env.py
```

Purpose:

- Convert `settings.toml` and `.secrets.toml` values into environment variables.
- Generate variables using Dynaconf-style names such as `DYNACONF_SECTION__KEY`.
- Keep secrets outside images.
- Allow Docker Compose, Ansible, systemd, and other deployment systems to inject runtime config through env files.

Deployment outputs such as generated env files are ignored by Git.

This is a strong improvement for:

- air-gapped deployments
- cloud-native/container deployments
- secret hygiene
- reproducible images
- separating build-time and runtime concerns

### 4. Docker Compose updates

The Docker Compose stack was updated to match the new configuration model.

Important changes:

- Services use generated env files from `assets/docker-compose/env/`.
- Raw project config is not baked into images.
- Compose validation was run successfully.
- Documentation was added or updated under `assets/docker-compose/README.md`.

Current expectation:

1. Generate Dynaconf env files from TOML config/secrets.
2. Start infrastructure and application services with Compose.
3. Keep generated env files local and untracked.

### 5. Ansible deployment hardening

The Ansible deployment assets were improved to avoid hardcoded lab assumptions.

Important changes:

- Service hostnames are now variables rather than hardcoded values.
- `/etc/hosts` entries are optional and controlled through variables.
- Legacy forced mapping of service aliases to `127.0.0.1` was removed.
- Sensitive values in examples were replaced with vault/env-driven placeholders.
- Documentation now explains how to provide host aliases in air-gapped or lab environments.

Relevant variables include:

```yaml
py_phone_caller_service_host: "{{ caddy_domain_name }}"
py_phone_caller_pbx_host: "pbx.lan"
py_phone_caller_database_host: "postgresql.lan"
py_phone_caller_queue_host: "redis.lan"
py_phone_caller_hosts_entries: []
```

Example for lab or air-gapped host aliases:

```yaml
py_phone_caller_hosts_entries:
  - address: "<INFRA_SERVICES_IP>"
    names:
      - postgresql.lan
      - pbx.lan
      - redis.lan
  - address: "<REVERSE_PROXY_IP>"
    names:
      - nginx.lab.local
```

This matches the real deployment direction better than hardcoded IP addresses.

### 6. Database and Piccolo hardening

Several database-related issues were fixed.

#### Piccolo config discovery

Initial issue:

```text
ModuleNotFoundError: No module named 'piccolo_conf'
```

Root cause:

- Piccolo defaults to importing top-level `piccolo_conf`.
- The actual config module lives inside the workspace package:

```text
py_phone_caller_utils.py_phone_caller_db.piccolo_conf
```

Fix:

```bash
PICCOLO_CONF=py_phone_caller_utils.py_phone_caller_db.piccolo_conf
```

This was added to the database-using service container environments.

#### Legacy schema drift repair

Observed runtime errors included missing columns such as:

```text
calls.call_backup_callee_number_calls
users.annotations
```

Fixes added:

- idempotent schema repair for existing legacy databases
- repair migration for tracked migration flows
- direct repair fallback in `caller_register`
- baseline migration-history reconciliation for databases where tables existed but Piccolo migration metadata was incomplete

The project now treats `caller_register` as the central database initialization/repair component.

Operational rule:

1. Start/run `caller_register` first.
2. Then start DB-dependent services such as `asterisk_recaller`, `py_phone_caller_ui`, and `asterisk_ws_monitor`.

### 7. Web UI security and behavior fixes

The Web UI received several important fixes.

#### Legacy password hashes

Issue:

```text
ValueError: Invalid hash method 'sha512'.
```

Root cause:

- Existing users had legacy `sha512$salt$hash` password hashes.
- Current Werkzeug rejects that format as an unsupported hash method.

Fix:

- Added safe shared password verification logic.
- Supported legacy `sha512` verification.
- Rehashed legacy passwords using the current Werkzeug format after successful login.
- Updated login and password-change flows to use the shared verifier.
- Added regression tests.

#### Admin bootstrap behavior

Issue:

- If the admin user was deleted, the Web UI could create a new admin with a random password on normal startup.

Fix:

- The initial admin is created only when the `users` table is empty and `UI_USER_RESET_PASSWORD=true` is explicitly set.
- Missing admin with existing users no longer triggers silent recreation.
- Password reset skips safely if the admin account is missing.
- Startup avoids resetting the password immediately after initial creation.

Recommended behavior:

```bash
UI_USER_RESET_PASSWORD=true
```

Use this only for intentional first-time bootstrap or explicit admin password reset. Set it back to false immediately afterward.

### 8. Web UI look and feel

The UI was refreshed while preserving offline compatibility.

Important constraints:

- No CDN usage.
- No Google Fonts or external assets.
- All assets must remain local for air-gapped environments.

Changes included:

- updated shared layout/navigation/footer
- improved dashboard hero/cards
- modernized login screen
- expanded local CSS for cards, tables, buttons, forms, modals, pagination, and responsive polish

The result is a more curated and modern interface without compromising offline operation.

### 9. Rust SMS engine validation

The Rust SMS engine was built and validated.

Rust code location:

```text
src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine
```

Main build command:

```bash
cd src/py-phone-caller-utils
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run maturin develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

Important fixes and notes:

- `maturin` was added as a development dependency.
- Rust toolchain and C compiler requirements were documented.
- Python `3.14` / PyO3 compatibility was handled with `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`.
- The native module import was validated.
- The Rust SMS runtime was verified through `caller_sms` startup.

Documentation was expanded at:

```text
src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/BUILD.md
```

Observed successful runtime behavior:

```text
Starting Rust engine with DB: sqlite:///tmp/sms.db, Strategy: round_robin, Modems: 2
Rust SMS engine started successfully.
```

### 10. Kokoro audio generation fixes

The audio generation flow was validated and fixed.

Observed issue:

```text
Error: 'kokoro' package not found. Please install it via pip or uv.
```

Impact:

- `generate_audio` returned a response, but no audio file was generated.
- `asterisk_ws_monitor` kept polling for the file until timeout.
- Calls could not proceed with generated voice audio.

Fix:

- Added the missing `kokoro` dependency.
- Added explicit `huggingface-hub` dependency where needed.
- Validated import of `KPipeline`.
- Validated generation of an actual WAV file.
- Rebuilt the Rust SMS extension after dependency sync removed the native module.

Validation included a generated WAV with:

```text
RIFF WAVE, mono 8000 Hz PCM
```

### 11. `num2words` security hardening

A security warning was reviewed for `num2words`.

Finding:

- Malicious releases affect `num2words` `0.5.15` and `0.5.16`.
- The project lockfile resolved the safe version `0.5.14`.
- The previous dependency range was too broad.

Fix:

```toml
num2words>=0.5.13,<0.5.15
```

This prevents future dependency resolution from selecting known malicious releases.

### 12. Celery worker validation

The Celery worker was run successfully from a PyCharm-compatible command.

Equivalent command:

```bash
python -m celery -A py_phone_caller_utils.tasks.celery_task worker --loglevel=info
```

Observed successful behavior:

- Celery started.
- Redis connection succeeded.
- `py_phone_caller_utils.tasks.celery_task.do_this_call` was registered.
- Worker reached ready state.

### 13. Gunicorn / Web UI validation

The Web UI was run successfully through Gunicorn.

Equivalent command:

```bash
python -m gunicorn -w 4 -b 0.0.0.0:5000 py_phone_caller_ui.app:app
```

Observed successful behavior:

- Gunicorn started.
- Four workers booted.
- Flask app initialized.
- `/metrics` route was added.
- PostgreSQL connectivity succeeded.
- Admin setup no longer crashed after schema repair.

### 14. Nagios and Zabbix integrations

The monitoring call scripts were reviewed and updated.

Files:

```text
assets/scripts/nagios/nagios_event_handler_call.sh
assets/scripts/zabbix/zabbix_alert_call.sh
```

Improvements:

- Removed hardcoded API IP addresses.
- API endpoint is now configurable through environment variables or script arguments.
- Added `curl` availability checks.
- Added timeout configuration.
- Added HTTP failure handling.
- Switched to safer `curl --get --data-urlencode --request POST` usage.
- Updated component READMEs with setup, manual tests, and troubleshooting.

Live validation:

- `asterisk_caller` metrics endpoint responded at `http://192.168.101.17:8081/metrics`.
- Nagios and Zabbix scripts returned successful `{"status": 200}` responses against `http://192.168.101.17:8081/call_to_queue`.

## Current known network context

The current lab host mapping shared during validation was:

```text
192.168.101.160 nginx.lab.local
192.168.101.212 git.py-phone-caller.lan postgresql.lan pbx.lan redis.lan
```

During live service testing, all `py-phone-caller` services were running on:

```text
192.168.101.17
```

The deployment tooling should not hardcode these values. They are useful lab defaults/examples only.

## Offline and air-gapped posture

Air-gapped operation is an important project requirement.

Current good points:

- Web UI assets remain local.
- No CDN or external font dependency was added during UI refresh.
- Runtime configuration is externalized through env files.
- Docker images no longer need raw `src/config` copied into them.
- Kokoro model presence is checked and can be prepared ahead of runtime.
- Deployment docs increasingly account for local DNS or explicit `/etc/hosts` aliases.

Recommended release rule:

- Any new frontend dependency must be vendored locally or packaged with the app.
- Any new model/runtime dependency must have an offline preload procedure.
- Any deployment secret must come from env files, vault, or platform secret injection, not from baked images.

## Validation already performed

Recent validation included:

- project tests passing, most recently reported as `26 passed`
- Web UI focused tests passing after login/admin changes
- `git diff --check`
- shell syntax checks for helper scripts
- Docker Compose config validation
- representative container image build
- verification that built images do not contain `/app/src/config`
- Rust SMS build and import validation
- Kokoro TTS import and WAV generation validation
- live Nagios/Zabbix script calls against running services
- live service startup checks for Celery, Gunicorn/Web UI, `caller_sms`, `generate_audio`, and Asterisk-related components where possible

Full live stack launch remains environment-dependent because it requires external systems such as Asterisk, PostgreSQL, Redis, model/runtime assets, and optional SMS hardware.

## Production-readiness feedback

### What is strong now

The project is now much more coherent than before the recent hardening pass.

Strong points:

- Service boundaries are clear.
- `uv` gives a better dependency and build foundation.
- Docker and Ansible are moving toward the same runtime configuration model.
- Configuration and secrets are no longer baked into images.
- DB initialization is safer for legacy and partially migrated environments.
- Web UI login/admin behavior is safer.
- Offline UI requirements are respected.
- Rust SMS and Kokoro audio paths have been tested in real local runs.
- Monitoring integrations are now configurable and tested.

### Main remaining risk: unauthenticated APIs

The most important remaining production risk is API authentication.

Current state:

- The Web UI has password-based authentication.
- Internal service APIs are not yet protected.
- Any client that can reach `asterisk_caller` can potentially trigger calls.
- Monitoring integrations can submit call requests if they can reach the endpoint.

This is acceptable only when the stack is deployed inside a trusted LAN, air-gapped network, or tightly firewalled segment.

Before exposure to untrusted networks, add authentication for all non-public endpoints.

Recommended direction:

- Add a shared API token or signed request mechanism first.
- Require authentication on write/action endpoints such as `call_to_queue`, `place_call`, `make_audio`, `send_sms`, and registration endpoints.
- Use separate tokens/scopes for service-to-service calls and monitoring integrations.
- Keep network isolation even after authentication is added.

### Health and readiness checks

The project should standardize health endpoints.

Recommended endpoints per service:

- `/health` for process liveness
- `/ready` for dependency readiness
- `/metrics` for Prometheus metrics, where applicable

Readiness should check real dependencies where possible:

- PostgreSQL connectivity for DB-using services
- Redis connectivity for queue/Celery services
- Asterisk ARI connectivity for Asterisk services
- Kokoro/model availability for `generate_audio`
- Rust SMS engine/modem readiness for `caller_sms`

### Startup order

The release documentation should make startup order explicit.

Recommended order:

1. PostgreSQL
2. Redis
3. Asterisk
4. `caller_register`
5. `generate_audio`
6. `caller_sms`, if SMS is enabled
7. `asterisk_caller`
8. `asterisk_ws_monitor`
9. `asterisk_recaller`
10. `caller_scheduler`
11. `caller_address_book`
12. `celery_worker`
13. `py_phone_caller_ui`
14. reverse proxy / external access layer

The most important rule is to run `caller_register` before DB-dependent services.

## Recommended `1.0.0` release checklist

### Build and dependency checks

- [ ] Run `uv sync --frozen` from the project root.
- [ ] Confirm `uv.lock` is clean and committed.
- [ ] Run the full test suite.
- [ ] Build all service images.
- [ ] Confirm no image contains raw `src/config` or secret files.
- [ ] Confirm `num2words` remains capped below `0.5.15`.
- [ ] Confirm Rust SMS native module can be rebuilt from source.
- [ ] Confirm Kokoro model/runtime is available in the target environment.

### Configuration checks

- [ ] Generate Dynaconf env files from TOML settings and secrets.
- [ ] Confirm generated env files are not committed.
- [ ] Confirm `PICCOLO_CONF` is present for all Piccolo/database services.
- [ ] Confirm `UI_USER_RESET_PASSWORD` is false for normal production restarts.
- [ ] Confirm hostnames resolve through DNS or explicit `py_phone_caller_hosts_entries`.
- [ ] Confirm no deployment script has hardcoded lab IPs or credentials.

### Database checks

- [ ] Start PostgreSQL.
- [ ] Run/start `caller_register`.
- [ ] Confirm Piccolo migration/repair process completes.
- [ ] Confirm required columns exist in `calls` and `users`.
- [ ] Confirm Web UI admin user behavior is intentional.

### Runtime smoke checks

- [ ] Start Redis.
- [ ] Start Asterisk and confirm ARI/AMI connectivity.
- [ ] Start `generate_audio` and generate a test WAV.
- [ ] Start `caller_sms` and confirm backend readiness.
- [ ] Start `asterisk_caller` and verify `/metrics`.
- [ ] Start `asterisk_ws_monitor` and confirm WebSocket connection to Asterisk.
- [ ] Start Web UI and verify login.
- [ ] Place a queued test call in a controlled environment.
- [ ] Verify Nagios/Zabbix script call delivery if monitoring integration is enabled.

### Security checks

- [ ] Ensure API services are not exposed to untrusted networks.
- [ ] Restrict service ports with firewall rules.
- [ ] Rotate all default/example credentials.
- [ ] Use Ansible Vault, generated env files, or platform secrets for sensitive values.
- [ ] Plan or implement API authentication before public or semi-public exposure.
- [ ] Confirm generated audio files and logs do not leak sensitive data unexpectedly.

## Suggested post-release roadmap

The following improvements would make the project more robust after `1.0.0`:

1. Add API authentication for all service endpoints.
2. Add token scopes for monitoring, service-to-service, and admin operations.
3. Add standardized `/health` and `/ready` endpoints.
4. Add a formal smoke-test script that checks the whole stack in order.
5. Add structured error responses for background operations such as audio generation.
6. Add better observability around call lifecycle state.
7. Add documented backup/restore procedures for PostgreSQL and generated config.
8. Add a documented offline artifact preparation process for models, wheels, and images.
9. Add an explicit migration-history cleanup command or admin procedure for legacy databases.
10. Consider reducing implicit startup side effects in services where possible.

## Current release confidence

Current confidence is good for:

- trusted LAN deployments
- air-gapped/lab deployments
- controlled production environments with firewall isolation
- internal monitoring integration use
- local PyCharm/operator-driven service testing

Current confidence is not yet sufficient for:

- direct exposure to the public Internet
- untrusted network clients
- environments without firewall isolation
- deployments requiring endpoint-level authorization guarantees

## Final assessment

`py-phone-caller` is now close to a credible `1.0.0` release candidate.

The most important completed improvements are:

- reproducible `uv` dependency management
- cleaner container builds
- externalized runtime configuration
- safer database initialization and repair
- improved Web UI behavior and appearance
- validated Rust SMS engine
- validated Kokoro TTS path
- hardened monitoring scripts
- fewer hardcoded deployment assumptions

The most important remaining milestone is API authentication. Until that is implemented, the system should be treated as production-ready only inside a trusted, isolated, firewall-controlled network.
