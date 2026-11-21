# Docker Compose deployment

> **Centralized Step-by-Step Guide**: See **[`deploy/docs/03-docker-compose-deployment.md`](../docs/03-docker-compose-deployment.md)** (and the **[Deployment Documentation Hub](../docs/README.md)**) for the complete, verified step-by-step installation, configuration, and health-verification guide.

This directory contains the Compose stack for running `py-phone-caller` with local builds or pre-published images.

## Build model

The service Dockerfiles are built from the repository root, not from `src/`, because they install packages from the root `uv` workspace metadata and frozen `uv.lock` file.

From the repository root, build one image with:

```bash
podman build -f src/caller_register/Dockerfile . -t localhost/caller_register:1.0.0
```

Or build the full service image set with:

```bash
CONTAINER_ENGINE=docker IMAGE_REGISTRY=localhost IMAGE_TAG=1.0.0 ./src/build_all_images.sh
```

Or build directly via Docker Compose from `deploy/compose/`:

```bash
docker compose build
```

### Building `openalertd` (Multi-Stage x86_64 & Fast ARM64 Cross-Compilation)

`openalertd` includes both a standard multi-stage `Dockerfile` and a dedicated `Dockerfile.arm64` that cross-compiles at native `x86_64` speed without slow QEMU `rustc` emulation:

```bash
# Native architecture multi-stage build (~35-40 MB runtime image):
docker build -t localhost/openalertd:1.0.0 -f src/openalert/Dockerfile src/openalert

# Fast ARM64 (aarch64) cross-compilation from x86_64 (or native build on ARM64 SBCs):
docker buildx build --platform linux/arm64 -f src/openalert/Dockerfile.arm64 \
  -t localhost/openalertd:1.0.0-arm64 --load src/openalert
```

Optional build-script environment variables:

```bash
CONTAINER_ENGINE=podman IMAGE_REGISTRY=localhost IMAGE_TAG=1.0.0 ./src/build_all_images.sh
```

## Start the stack

Generate the runtime Dynaconf env files before starting the stack:

```bash
uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --input src/config/settings.toml \
  --output deploy/compose/env/py-phone-caller.env

uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --ignore-missing \
  --input src/config/.secrets.toml \
  --output deploy/compose/env/py-phone-caller.secrets.env
```

From this directory:

```bash
podman compose up -d
```

or, with Docker Compose:

```bash
docker compose up -d
```

To enable physical USB GSM (`/dev/ttyUSB2`), LoRa (`/dev/ttyACM0`), and BlueZ BLE (`hci0` + `/var/run/dbus`) passthrough into `openalertd`, include `docker-compose.hardware.yml`:

```bash
docker compose -f docker-compose.yml -f docker-compose.hardware.yml up -d
```

To enable the Enterprise API Gateway (`Apache APISIX` + `etcd` + `Keycloak OIDC`), include `docker-compose.gateway.yml`:

```bash
docker compose -f docker-compose.yml -f docker-compose.gateway.yml up -d
```

## Important environment variables

- `DYNACONF_*`: generated from `settings.toml` and `.secrets.toml` by `assets/scripts/config/toml_to_dynaconf_env.py`.
- `POSTGRES_PASSWORD`: overrides the default development database password.
- `MY_DOCKER_REGISTRY`: image registry prefix, defaults to `localhost`.
- `VERSION`: image tag, defaults to `1.0.0`.
- `ENABLE_TELEMETRY`: defaults to `false`.
- `OTEL_EXPORTER_OTLP_ENDPOINT`: optional OpenTelemetry collector endpoint.
- `OTEL_EXPORTER_OTLP_PROTOCOL`: defaults to `grpc`.
- `UI_USER_RESET_PASSWORD`: defaults to `false`; set it to `true` only for intentional first-time admin bootstrap or password reset, then set it back to `false`.

Database-aware services also receive:

```text
PICCOLO_CONF=py_phone_caller_utils.py_phone_caller_db.piccolo_conf
```

## Notes

- The stack uses `postgres:17-alpine` and `redis:7-alpine`.
- Service images include `/app/py-phone-caller/config/settings.toml` (base non-secret defaults); runtime overrides and secrets are injected through Compose `env_file` entries and explicit `environment:` variables.
- `generate_audio` stores generated WAV files in the `audio_data` volume and preloads `piper_tts` by default (`--build-arg PRELOAD_ALL_MODELS=true` preloads all local neural TTS engines).
- The root `.dockerignore` excludes local secrets and generated audio files from image build contexts.
