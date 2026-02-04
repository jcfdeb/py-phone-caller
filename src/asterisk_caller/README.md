# Asterisk Caller

HTTP service that places outbound calls through Asterisk ARI, queues calls for
background processing, and plays audio on active channels.

## Responsibilities
- Place calls immediately or enqueue them for a worker cycle.
- Register call attempts with `caller_register`.
- Fetch and play generated audio from `generate_audio`.
- Resolve on-call contacts via `caller_address_book`.

## HTTP API
Routes are configured in `settings.toml` under `[asterisk_call]`:
- POST `/<asterisk_call_app_route_place_call>`
- POST `/<asterisk_call_app_route_call_to_queue>`
- POST `/<asterisk_call_app_route_play>`

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m asterisk_caller.asterisk_caller
```

## Docker
```bash
docker build -t asterisk-caller -f src/asterisk_caller/Dockerfile src/
```
