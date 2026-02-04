# Caller Scheduler

HTTP service that schedules future calls using Celery tasks.

## Responsibilities
- Accept schedule requests with a target datetime.
- Convert local time to UTC and enqueue Celery tasks.
- Return status to the caller.

## HTTP API
Routes are configured in `settings.toml` under `[caller_scheduler]`:
- POST `/<scheduled_call_app_route>`

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- Celery broker settings are loaded from the shared config.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m caller_scheduler.caller_scheduler
```

## Docker
```bash
docker build -t caller-scheduler -f src/caller_scheduler/Dockerfile src/
```
