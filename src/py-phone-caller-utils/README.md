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
cd src/py-phone-caller-utils
pip install -e .
```

## Build with Rust engine
The SMS modem backend ships as a Rust extension built with Maturin.

```bash
cd src/py-phone-caller-utils
maturin develop
```

## Configuration
- `CALLER_CONFIG_DIR=src/config`
- `CALLER_CONFIG=/path/to/settings.toml`

## Notes
- The module name is `py_phone_caller_utils`.
- Python 3.12+ is required.
