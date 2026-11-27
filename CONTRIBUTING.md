# Contributing to py-phone-caller & OpenAlert

Thank you for your interest in contributing to **py-phone-caller** and **OpenAlert (`openalertd`)**!

---

## 1. Development Prerequisites

- **Linux (`x86_64` or `aarch64`)**
- **Python `3.14`** managed via [`uv`](https://docs.astral.sh/uv/)
- **Rust stable toolchain (`1.85+`)** with `clippy` and `rustfmt` (for `src/openalert` and `rust_engine`)
- **[`mise`](https://mise.jdx.dev/)** & **[`task`](https://taskfile.dev/)** (installs pinned AppSec and build tools declared in [`mise.toml`](mise.toml))
- System headers on Debian/Ubuntu when compiling `openalertd`: `pkg-config`, `libdbus-1-dev`, `libudev-dev`, `libssl-dev`

---

## 2. Quick Bootstrap

```bash
# 1. Install pinned developer & AppSec CLI tools
mise install

# 2. Create/sync the frozen Python 3.14 workspace virtualenv
uv sync --frozen --all-packages

# 3. Install the fast pre-commit security hook (Gitleaks + Ruff S-rules)
task sec:hooks:install

# 4. Verify your toolchain
task sec:doctor
```

---

## 3. Running Tests & Verification Gates

Before opening a pull request, rebuild the documentation site and run the full coherence, non-regression, and AppSec gates in order:

```bash
# 1. Regenerate docs/assets/openapi/*.json in place via deploy/pages/export_openapi.py
#    and build the hybrid GitHub Pages site (_site/) so test_docs_coherence.py also
#    validates the rendered /manual/ HTML, nav tabs, and View-source links
task docs:build

# 2. Run Python + packaging + documentation coherence + Rust + Clippy + fast security checks
task verify:all

# 3. Run the full AppSec gate (Bandit, Semgrep, Clippy, pip-audit, cargo-deny/audit, OSV, Trivy IaC)
task sec:ci

# 4. Run the offline Ansible contract & role unit test suite
python3 -m unittest discover -s deploy/ansible/tests -v
```

*(Preview the built site locally anytime on `http://127.0.0.1:8008` with `task docs:serve`, or verify version parity only with `task version:check`.)*

Key developer references:
- **Python Workspace & Maturin Rust SMS Engine**: [`docs/uv-migration-and-workspace-guide.md`](docs/uv-migration-and-workspace-guide.md)
- **AppSec, SBOM & Supply-Chain Workflows**: [`docs/appsec-and-supply-chain-guide.md`](docs/appsec-and-supply-chain-guide.md)
- **Architecture & Call Flows**: [`docs/architecture-and-call-flows.md`](docs/architecture-and-call-flows.md)
- **Deployment Pillars (`deploy/*`)**: [`deploy/docs/README.md`](deploy/docs/README.md)

---

## 4. Coding & Security Guidelines

1. **Never commit secrets or personal data**: Use `settings.toml` for safe defaults, `.secrets.toml` / Vault / env vars for credentials, and RFC 5737 / E.164 test placeholders (`192.0.2.x`, `+15550100100`) in examples and tests.
2. **Keep lockfiles deterministic**: Any dependency change must update `uv.lock` or `Cargo.lock` cleanly (`uv lock --check` and `cargo test --locked` must pass). For air-gap compatibility, build constraints in `pyproject.toml` must use exact `==` pins.
3. **Zero warnings in Rust**: `cargo clippy --manifest-path src/openalert/Cargo.toml --all-targets --locked -- -D warnings` must pass cleanly.
4. **Documentation & Version Coherence**: Keep docs, OpenAPI specs (`docs/assets/openapi/*.json`), and manifests synchronized (`task docs:build` regenerates the OpenAPI specs in place from service routes and `pyproject.toml`; `task version:check` and `tests/test_docs_coherence.py` enforce version parity, OpenAPI zero drift, and zero broken relative links).

---

## 5. Licensing

- Contributions to **`py-phone-caller`** (Python microservices, `rust_engine`, Web UI, and deployment automation) are licensed under the **[BSD 3-Clause License](LICENSE)**.
- Contributions to **`OpenAlert` (`src/openalert/`)** are dual-licensed under **[MIT](src/openalert/LICENSE-MIT) OR [Apache-2.0](src/openalert/LICENSE-APACHE)**.
