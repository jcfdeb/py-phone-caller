# Docker Compose deployment

This directory contains the Compose stack for running `py-phone-caller` with local builds or pre-published images.

## Build model

The service Dockerfiles are built from the repository root, not from `src/`, because they install packages from the root `uv` workspace metadata and frozen `uv.lock` file.

From the repository root, build one image with:

```bash
podman build -f src/caller_register/Dockerfile . -t localhost/caller_register:latest
```

Or build the full service image set with:

```bash
./src/build_all_images.sh
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
  --output assets/docker-compose/env/py-phone-caller.env

uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --ignore-missing \
  --input src/config/.secrets.toml \
  --output assets/docker-compose/env/py-phone-caller.secrets.env
```

From this directory:

```bash
podman compose up -d
```

or, with Docker Compose:

```bash
docker compose up -d
```

## Important environment variables

- `DYNACONF_*`: generated from `settings.toml` and `.secrets.toml` by `assets/scripts/config/toml_to_dynaconf_env.py`.
- `POSTGRES_PASSWORD`: overrides the default development database password.
- `MY_DOCKER_REGISTRY`: image registry prefix, defaults to `localhost`.
- `VERSION`: image tag, defaults to `latest`.
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
- Service images don't contain `src/config`; runtime configuration is injected through Compose `env_file` entries and explicit environment overrides.
- `generate_audio` stores generated WAV files in the `audio_data` volume.
- The root `.dockerignore` excludes local secrets and generated audio files from image build contexts.
