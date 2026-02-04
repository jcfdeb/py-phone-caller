# Caller SMS

HTTP service for sending SMS notifications. Supports Twilio and an on-premise
USB modem backend powered by a Rust engine.

## Responsibilities
- Expose a simple SMS API for other services.
- Send SMS via Twilio or the on-premise modem backend.
- Handle async dispatch and retries on the backend.

## Backends
- Twilio: uses account credentials from `settings.toml`.
- On-premise: uses a Rust engine that manages the serial modem queue.

## Build the Rust engine (on-premise)
The Rust engine lives in `py_phone_caller_utils/sms/rust_engine` and is built
with Maturin.

### Local development build
```bash
cd src/py-phone-caller-utils
maturin develop
```

### Production wheel
```bash
cd src/py-phone-caller-utils
maturin build --release
```

The wheel is written to
`src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/target/wheels/`.

## Clean install on execution host (recommended)
```bash
pip uninstall -y py-phone-caller-utils
pip install --force-reinstall py_phone_caller_utils-0.1.0-*.whl
python3 -c "import py_phone_caller_utils; print(py_phone_caller_utils.__file__)"
```

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- Set `caller_sms_carrier` to `twilio` or `on_premise`.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m caller_sms.caller_sms
```

## Docker
```bash
docker build -t caller-sms -f src/caller_sms/Dockerfile src/
```

## Hardware notes (on-premise)
- Verified with D-Link DWM-222 4G LTE USB Adapter.
- Ensure your user can access `/dev/ttyUSB*` via the `dialout` group or udev.
