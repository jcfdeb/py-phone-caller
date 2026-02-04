# Caller Register

HTTP service that stores call attempts, message payloads, and call status
(acknowledged, heard). It owns the core call registry data.

## Responsibilities
- Register new calls and link them to voice messages.
- Track retries, acknowledgement, and heard status.
- Store scheduled call metadata.
- Initialize and migrate the database schema (Piccolo ORM).

## HTTP API
Routes are configured in `settings.toml` under `[call_register]`:
- POST `/<call_register_app_route_register_call>`
- POST `/<call_register_app_route_voice_message>`
- POST `/<call_register_scheduled_call_app_route>`
- GET `/<call_register_app_route_acknowledge>`
- GET `/<call_register_app_route_heard>`

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m caller_register.caller_register
```

## Docker
```bash
docker build -t caller-register -f src/caller_register/Dockerfile src/
```
