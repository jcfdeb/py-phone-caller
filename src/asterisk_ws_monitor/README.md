# Asterisk WS Monitor

WebSocket listener for Asterisk ARI events. It reacts to call lifecycle events,
requests audio generation, and triggers playback on the active channel.

## Responsibilities
- Connect to the Asterisk ARI WebSocket and consume events.
- Fetch message data from `caller_register`.
- Ask `generate_audio` to create message audio when needed.
- Trigger `asterisk_caller` playback and log events to the database.

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- WebSocket settings live under `[asterisk_ws_monitor]` and `[commons]`.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m asterisk_ws_monitor.asterisk_ws_monitor
```

## Docker
```bash
docker build -t asterisk-ws-monitor -f src/asterisk_ws_monitor/Dockerfile src/
```
