# Asterisk Recaller

Background worker that retries failed or unacknowledged calls and optionally
triggers backup calls to on-call contacts once the primary call window expires.

## Responsibilities
- Query the call database for retry candidates.
- Enforce retry windows and backoff timing.
- Trigger Asterisk calls via the `asterisk_caller` service.
- Escalate to backup contacts when configured.

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- Key settings live under `[asterisk_recaller]` and `[call_register]`.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m asterisk_recaller.asterisk_recaller
```

## Docker
```bash
docker build -t asterisk-recaller -f src/asterisk_recaller/Dockerfile src/
```
