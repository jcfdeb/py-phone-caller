# Caller SMS Service

This service handles sending SMS notifications. It supports both Twilio and On-Premise (Direct USB Modem) backends.

## The On-Premise Backend (Rust Engine)

The On-Premise backend uses a high-performance Rust engine for queue management and direct serial communication (AT commands) with a USB modem. It is designed to be highly resilient, mirroring the "write and sleep" fire-and-forget timing of verified Python scripts, now enhanced with emergency `ESC` escape sequences, echo suppression (`ATE0`), and 10-second message spacing to prevent hardware "hangs" and ensure delivery confirmation. It includes advanced concurrency protection to prevent duplicate messages and atomic message picking. Interrupted messages are immediately recovered and retried on service restart. The engine starts automatically with the `caller_sms` service to ensure immediate availability. Robust Unicode support is implemented by dynamically switching to UCS2-HEX mode when non-standard characters are detected, ensuring reliability across all alphabets.

### The Unified Package
When you build or install the `py-phone-caller-utils` package, it includes:
1.  **Python Logic**: The high-level API and configuration management.
2.  **Rust Binary**: The compiled execution engine (`rust_engine`) optimized for your platform.

### Prerequisites

- **Python**: 3.12+
- **Rust**: 1.80+ (only required if building from source)
- **Maturin**: `pip install maturin` (only required if building from source)

### Local Development Build

To build the Rust module and install the utility library in your current environment:

```bash
cd src/py-phone-caller-utils
maturin develop
```

This command compiles the Rust code located in `py_phone_caller_utils/sms/rust_engine` and makes the `rust_engine` module available to the Python environment.

### Production Build

To create a self-contained distribution (Wheel) that can be easily moved to other machines:

```bash
cd src/py-phone-caller-utils
maturin build --release
```

The resulting `.whl` file will be located in `src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/target/wheels/`.

### Installation on Execution Host (CRITICAL: Clean Install)

To ensure the latest version of the Rust engine is used and to avoid conflicts with old builds or rogue source files, follow these steps strictly:

1.  **Uninstall old version**:
    ```bash
    pip uninstall -y py-phone-caller-utils
    ```

2.  **Clean rogue source directories**:
    If you have a `py_phone_caller_utils` directory inside your `src/` folder on the remote host, REMOVE IT. It can interfere with the installed package.
    ```bash
    rm -rf /home/rocky/py-phone-caller/src/py_phone_caller_utils
    ```

3.  **Install the new wheel**:
    Copy the `.whl` file to the remote host and install it:
    ```bash
    pip install --force-reinstall py_phone_caller_utils-0.1.0-cp312-cp312-manylinux_2_34_x86_64.whl
    ```

4.  **Verify the installation**:
    Run this command to verify that Python is using the installed package and NOT a local source directory:
    ```bash
    python3 -c "import py_phone_caller_utils; print(py_phone_caller_utils.__file__)"
    ```
    The output should point to `site-packages`, NOT to your `src/` directory.

## Running the Service

### 1. Configuration

Ensure your `src/config/settings.toml` is configured correctly:

```toml
[caller_sms]
caller_sms_carrier = "on_premise"  # or "twilio"
# ... other settings ...
```

### 2. Environment Variables

- `CALLER_CONFIG_DIR`: Path to the directory containing `settings.toml`.
- `SMS_DB_PATH`: (Optional) SQLite database path. Default is `sqlite:///data/sms.db`.

### 3. Execution

From the project root:

```bash
export CALLER_CONFIG_DIR=src/config
export PYTHONPATH=src
python3 -m caller_sms.caller_sms
```

## Docker Deployment

The `Dockerfile` in this directory is already configured to build the Rust engine during the image creation process. It uses a multi-stage build to keep the final image small.

To build the Docker image:

```bash
docker build -t caller-sms -f src/caller_sms/Dockerfile src/
```

## Hardware Compatibility (On-Premise)

Verified with **D-Link DWM-222** 4G LTE USB Adapter. See [on-premise implementation guide](../../tmp/caller_sms-improvement/sms_on_premise_implementation.md) for detailed hardware setup.

### Serial Port Permissions

In Linux, serial devices (like `/dev/ttyUSB2`) are usually owned by the `root` user and the `dialout` (or `uucp`) group. To allow the service to access the modem without root privileges:

1.  **Grant Group Access**: Add your user to the `dialout` group:
    ```bash
    sudo usermod -aG dialout $USER
    ```
    *Note: You must log out and log back in for this change to take effect.*

2.  **Production (udev Rule)**: To ensure permissions are persistent and the device is always correctly identified, create a udev rule (e.g., `/etc/udev/rules.d/99-usb-modem.rules`). Use `lsusb` to find your device's IDs:
    ```text
    # Example for D-Link DWM-222
    SUBSYSTEM=="tty", ATTRS{idVendor}=="2001", ATTRS{idProduct}=="7e35", MODE="0660", GROUP="dialout", SYMLINK+="sms_modem"
    ```
    Then you can use `/dev/sms_modem` in your `settings.toml`.
