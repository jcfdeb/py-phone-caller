# Py Phone Caller UI

Flask web UI for managing calls, SMS records, schedules, users, WS events, and the address
book.

## Responsibilities
- Provide login-protected pages for call history, SMS logs, and scheduling.
- Manage users and on-call contacts.
- Expose WS event, SMS, and call status views.

## Structure
- `app.py`: Flask app and blueprint wiring.
- `templates/` and `static/`: HTML and assets.
- Feature blueprints: `calls`, `sms`, `schedule_call`, `users`, `ws_events`, `address_book`.

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- Admin user setup uses `UI_ADMIN_USER` and related settings.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m py_phone_caller_ui.app
```

## Docker
```bash
docker build -t py-phone-caller-ui -f src/py_phone_caller_ui/Dockerfile src/
```
