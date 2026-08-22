# Build the Rust SMS engine

This directory contains the Rust/PyO3 engine used by the `caller_sms` on-premise backend.

## What this guide fixes

The Rust SMS engine is not a pure Python module. It is a native Python extension built from Rust with `maturin`, `cargo`, and `PyO3`.

During the uv migration / Python `3.14` setup, several independent issues had to be fixed before the engine could build and be imported correctly:

1. `uv run maturin develop` failed because `maturin` was not installed in the uv workspace environment.
2. After adding `maturin`, the build failed because the Rust compiler (`rustc`) and `cargo` were not installed.
3. After installing Rust, the build failed because the system C linker (`cc`) was missing.
4. After installing the C toolchain, plain `uv run maturin develop` still failed because `Cargo.toml` does not live directly in `src/py-phone-caller-utils`.
5. After pointing `maturin` to the nested `Cargo.toml`, PyO3 rejected the workspace Python version because this crate currently uses `pyo3` `0.20`, which predates Python `3.14`.
6. After the native extension was built, the Python facade had to import the installed top-level native module `rust_engine`, not the source directory namespace `py_phone_caller_utils.sms.rust_engine`.

The final working build command is:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller/src/py-phone-caller-utils
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
uv run maturin develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

The final working import checks are:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller
uv run python -c "import rust_engine; print(rust_engine); print(rust_engine.enqueue_sms, rust_engine.start_engine)"
uv run python -c "from py_phone_caller_utils.sms import enqueue_sms, start_engine; print(enqueue_sms, start_engine)"
```

## Location

Rust crate:

```text
src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine
```

Python backend that uses it:

```text
src/caller_sms/backend/rust_on_premise.py
```

The runtime call chain is:

```text
src/caller_sms/backend/rust_on_premise.py
  -> from py_phone_caller_utils.sms import RustBackend
  -> RustBackend.run_worker()
  -> RustBackend.send(...)
  -> native rust_engine.start_engine(...)
  -> native rust_engine.enqueue_sms(...)
```

So the important runtime requirement is not only that the Rust crate compiles, but also that this Python import works:

```python
from py_phone_caller_utils.sms import enqueue_sms, start_engine
```

If this import returns `None` or logs `Rust SMS engine not found`, the `on_premise` backend will not be able to enqueue or process SMS messages.

## Prerequisites

From the project root, make sure the `uv` workspace environment is available:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller
uv sync
```

You also need a working Rust toolchain:

```bash
rustc --version
cargo --version
```

If Rust is not installed, install it with `rustup` before building this module.

The user-local Rust installation used during this fix was:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
rustc --version
cargo --version
```

Expected result after installation:

```text
rustc 1.97.1 (...)
cargo 1.97.1 (...)
```

If a new terminal or PyCharm process does not see `rustc` / `cargo`, make sure `$HOME/.cargo/bin` is on `PATH`. For a shell session, run:

```bash
source "$HOME/.cargo/env"
```

On Linux, Rust native builds also need a C compiler / linker available as `cc`:

```bash
cc --version
```

On openSUSE, one way to install the required build toolchain is:

```bash
sudo zypper --non-interactive install -t pattern devel_basis
```

Expected result after installation:

```bash
cc --version
```

```text
cc (SUSE Linux) 15.3.0
```

The Python package is built with `maturin`. If `maturin` is not available in the workspace environment, add it as a development dependency from the project root:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller
uv add --dev maturin
```

This updates the root workspace files:

```text
pyproject.toml
uv.lock
```

Verify `maturin` is now available through `uv`:

```bash
uv run maturin --version
```

Expected result:

```text
maturin 1.14.1
```

Do not rely on a globally installed `maturin` for this project. Keeping it in the uv dev dependencies makes the build reproducible for other developers and CI jobs.

## Local development build

Use `maturin develop` from the `py_phone_caller_utils` package directory and point it to the nested Rust crate manifest:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller/src/py-phone-caller-utils
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
uv run maturin develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

This compiles the Rust extension and installs it into the active project virtual environment so local Python code can import it.

Why each part matters:

- `cd .../src/py-phone-caller-utils`: runs the build in the Python package that owns the Rust SMS engine.
- `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1`: allows the current `pyo3` `0.20` dependency to build with the workspace Python `3.14` interpreter.
- `uv run`: uses the project `.venv` and uv-managed dependencies.
- `maturin develop`: builds the Rust extension and installs it into the active development environment.
- `--manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml`: tells `maturin` where the nested Rust crate actually lives.

Without `--manifest-path`, `maturin` looks for:

```text
src/py-phone-caller-utils/Cargo.toml
```

but the real manifest is:

```text
src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

## Verify the build

After `maturin develop`, verify that Python can import the extension:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller
uv run python -c "import rust_engine; print(rust_engine); print(rust_engine.enqueue_sms, rust_engine.start_engine)"
```

Also verify that the Python facade can load the native functions:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller
uv run python -c "from py_phone_caller_utils.sms import enqueue_sms, start_engine; print(enqueue_sms, start_engine)"
```

Expected successful output looks like:

```text
<built-in function enqueue_sms> <built-in function start_engine>
```

If this check prints `None None` or logs a warning like:

```text
Rust SMS engine not found. 'on_premise' backend will not work correctly.
```

then the native module is not being imported by the Python facade, and `caller_sms` with `caller_sms_carrier = "on_premise"` will fail at runtime.

The compiled native module is installed as the top-level Python module:

```python
import rust_engine
```

The facade in `py_phone_caller_utils.sms` should therefore import:

```python
from rust_engine import enqueue_sms, start_engine
```

not:

```python
from .rust_engine import enqueue_sms, start_engine
```

The relative import can resolve to the source directory `py_phone_caller_utils/sms/rust_engine`, which is not the compiled extension and does not expose the native functions.

## Production wheel build

For a release artifact, build a wheel:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller/src/py-phone-caller-utils
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
uv run maturin build --release --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

The wheel is written under:

```text
src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/target/wheels/
```

## Install the wheel on an execution host

On the target host, install the generated wheel into the Python environment used by the services:

```bash
pip uninstall -y py-phone-caller-utils
pip install --force-reinstall py_phone_caller_utils-0.1.0-*.whl
python3 -c "import py_phone_caller_utils; print(py_phone_caller_utils.__file__)"
```

When using `uv`, prefer:

```bash
uv pip install --force-reinstall path/to/py_phone_caller_utils-0.1.0-*.whl
```

## Run `caller_sms` with the on-premise backend

Make sure the SMS carrier is configured as `on_premise` in the project settings:

```toml
caller_sms_carrier = "on_premise"
```

Then run the service from the project root:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller
CALLER_CONFIG_DIR=src/config \
PYTHONPATH="src:$PYTHONPATH" \
uv run python -m caller_sms.caller_sms
```

## PyCharm run configuration for the build

A convenient PyCharm configuration for local development is a Python module run configuration:

```text
Module name: maturin
Parameters: develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
Working directory: /home/jcf/Workspace/Antigravity/py-phone-caller/src/py-phone-caller-utils
Interpreter: /home/jcf/Workspace/Antigravity/py-phone-caller/.venv/bin/python
Environment: PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
```

If running `maturin` as a Python module is not available, use a shell/external-tool style configuration with:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller/src/py-phone-caller-utils && \
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
uv run maturin develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

## Hardware notes

The on-premise backend expects access to a serial modem device such as `/dev/ttyUSB*`.

For local Linux development, make sure your user has access to the device, commonly through the `dialout` group or an appropriate `udev` rule.

## Troubleshooting

### `maturin` is not found

Install it into the workspace development dependencies:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller
uv add --dev maturin
```

Then rerun:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller/src/py-phone-caller-utils
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
uv run maturin develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

### `Cargo.toml` is not found

The Rust crate is nested below the Python package, so plain `uv run maturin develop` from `src/py-phone-caller-utils` won't find a manifest. Use the explicit manifest path:

```bash
uv run maturin develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

### PyO3 rejects Python `3.14`

The current Rust crate uses `pyo3` `0.20`, which predates Python `3.14`. For the current workspace interpreter, set PyO3 forward compatibility while building:

```bash
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 \
uv run maturin develop --manifest-path py_phone_caller_utils/sms/rust_engine/Cargo.toml
```

### Python cannot import `rust_engine`

Rebuild the extension with `maturin develop`, then verify the selected interpreter is the project virtual environment:

```bash
/home/jcf/Workspace/Antigravity/py-phone-caller/.venv/bin/python -c "import sys; print(sys.executable)"
```

Also confirm the package import path:

```bash
cd /home/jcf/Workspace/Antigravity/py-phone-caller
uv run python -c "from py_phone_caller_utils.sms import enqueue_sms, start_engine; print(enqueue_sms, start_engine)"
```

### Serial modem permission errors

Check the modem device path and permissions:

```bash
ls -l /dev/ttyUSB*
```

If needed, add your user to the `dialout` group and restart the login session:

```bash
sudo usermod -aG dialout "$USER"
```
