# py_phone_caller_utils

Shared utility library for the py-phone-caller system. This package provides
configuration management, database access, telemetry, TTS helpers, and SMS
integrations used across services.

## Modules
- `config`: Dynaconf based settings loader (uses `CALLER_CONFIG_DIR`).
- `py_phone_caller_db`: Piccolo ORM models and query helpers.
- `py_phone_caller_voices`: TTS engine wrappers.
- `sms`: SMS integrations and the Rust modem engine.
- `tasks`: Celery task helpers.
- `telemetry`: OpenTelemetry setup and instrumentation.

## Install (Python only)
```bash
uv sync --package py-phone-caller-utils
```

## Build with Rust engine
The SMS modem backend ships as a Rust extension built with Maturin.

```bash
cd src/py-phone-caller-utils
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 uv run maturin develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

## Configuration
- Local development can use `CALLER_CONFIG=src/config/settings.toml`.
- Container and systemd deployments should inject generated `DYNACONF_*` environment files instead of copying config into images.

## Notes
- The module name is `py_phone_caller_utils`.
- Python 3.14.x is required.
