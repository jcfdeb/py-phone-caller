# Application Security, Supply-Chain & Non-Regression Developer Guide

Welcome to the **Application Security (AppSec), Software Supply-Chain, and Non-Regression Verification Guide** for `py-phone-caller` and `openalertd`.

This guide is a practical, copy-and-paste handbook for **current developers, new contributors, and release maintainers**. It explains how to bootstrap the security toolchain in 5 minutes, run fast local checks before committing or pushing, upgrade vulnerable dependencies safely with **automatic rollback**, and handle findings across Python, Rust, Docker, Kubernetes, and Helm without breaking working functionality.

> [!TIP]
> Looking for the architectural rationale behind tool choices and design decisions? Read the companion High-Level Design: [`docs/openalert/dist/AppSec_for_py-phone-caller/app-sec_HLD.md`](openalert/dist/AppSec_for_py-phone-caller/app-sec_HLD.md).

---

## Table of Contents

1. [How the Pipeline Works at a Glance](#1-how-the-pipeline-works-at-a-glance)
2. [5-Minute First-Time Contributor Onboarding](#2-5-minute-first-time-contributor-onboarding)
3. [Day-to-Day Developer Workflow](#3-day-to-day-developer-workflow)
4. [Complete `Taskfile.yml` Command Reference](#4-complete-taskfileyml-command-reference)
5. [Non-Regression Guardrails ("Do Not Break Working Stuff")](#5-non-regression-guardrails-do-not-break-working-stuff)
6. [Playbook: Safely Fixing Dependency CVEs (With Auto-Rollback)](#6-playbook-safely-fixing-dependency-cves-with-auto-rollback)
7. [Playbook: Resolving Scanner Findings by Domain](#7-playbook-resolving-scanner-findings-by-domain)
8. [Exception Governance & Automated Contract Tests](#8-exception-governance--automated-contract-tests)
9. [CI/CD & GitHub Code Scanning Integration](#9-cicd--github-code-scanning-integration)
10. [Troubleshooting & Common Workspace Gotchas](#10-troubleshooting--common-workspace-gotchas)

---

## 1. How the Pipeline Works at a Glance

Every security check and non-regression gate in this repository is orchestrated through a **single root [`Taskfile.yml`](../Taskfile.yml)** so your local terminal and GitHub Actions execute the exact same commands.

The pipeline covers the entire polyglot repository:
- **12 Python 3.14 Workspace Packages** (`src/*`, locked in root [`uv.lock`](../uv.lock))
- **`openalertd` Native Rust Daemon** (`src/openalert/`, locked in [`src/openalert/Cargo.lock`](../src/openalert/Cargo.lock))
- **`sms_rust_backend` PyO3 Native SMS Engine** (`rust_engine`, locked in [`src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/Cargo.lock`](../src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/Cargo.lock))
- **46 Infrastructure-as-Code & Container Manifests** (`Dockerfile`s, `docker-compose*.yml`, `deploy/k8s/`, `deploy/helm/`)

### Execution Tiers

```text
+-----------------------------------------------------------------------------------+
| 1. INNER LOOP (Every Commit — ~0.4s)                                              |
|    .git/hooks/pre-commit -> task sec:fast                                         |
|    ├── gitleaks protect --staged  (blocks staged API keys, tokens, private keys)  |
|    └── ruff check --select S      (catches SQLi, shell=True, unsafe YAML/pickle)  |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 2. PRE-PUSH / PR GATE (~30-90s)                                                   |
|    task verify:all  +  task sec:ci                                                |
|    ├── verify:smoke / verify:py / verify:rust (300 Python + 114 Rust tests)       |
|    ├── sec:sast:full  (Ruff S + Bandit SARIF + Semgrep OSS + Cargo Clippy -D W)   |
|    ├── sec:sca:all    (uv export -> pip-audit, cargo-deny, cargo-audit, OSV)      |
|    └── sec:iac        (Trivy config across Dockerfiles, Compose, K8s, Helm)       |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| 3. RELEASE GATE (Tagging / Packaging)                                             |
|    task sec:release  (+ optional sec:dast / sec:sign:release)                     |
|    ├── Full git history secret scan (Gitleaks + TruffleHog live verification)     |
|    ├── CycloneDX SBOM generation (Syft -> .security-reports/sbom-source.cdx.json) |
|    ├── Multi-service container CVE scan (Trivy image HIGH/CRITICAL)               |
|    └── Keyless Sigstore artifact signing (Cosign sign-blob)                       |
+-----------------------------------------------------------------------------------+
```

All machine-readable reports (`*.sarif`, `*.json`, `*.cdx.json`) are written to `.security-reports/` (which is gitignored).

---

## 2. 5-Minute First-Time Contributor Onboarding

Follow these steps once after cloning the repository to set up Python 3.14, Rust, the native SMS engine, all pinned AppSec CLI tools, and the local `pre-commit` hook.

### Step 1: Ensure `uv` and `rustup` Are Installed

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Rust stable + Clippy (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
rustup component add clippy
```

> [!NOTE]
> **Linux native build packages (needed to compile `openalertd` and `rust_engine`):**
> - **Debian / Ubuntu:** `sudo apt-get install -y build-essential pkg-config libdbus-1-dev libudev-dev libssl-dev cmake ninja-build clang libclang-dev`
> - **openSUSE:** `sudo zypper install -t pattern devel_basis && sudo zypper install dbus-1-devel systemd-devel libopenssl-devel cmake ninja clang`
> - **Rocky / RHEL / Fedora:** `sudo dnf groupinstall -y "Development Tools" && sudo dnf install -y dbus-devel systemd-devel openssl-devel cmake ninja-build clang`

### Step 2: Install Pinned AppSec Binaries via `mise`

The repository includes a root [`mise.toml`](../mise.toml) that downloads exact, pinned versions of `task`, `gitleaks`, `trufflehog`, `osv-scanner`, `trivy`, `syft`, `cosign`, `nuclei`, `cargo-audit`, and `cargo-deny` into `~/.local/share/mise`—no `sudo` or Docker daemon required:

```bash
# 1. Install mise into ~/.local/bin (if not already installed)
curl https://mise.run | sh

# 2. Ensure ~/.local/bin, mise shims, and cargo are on your shell PATH
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# (Recommended) Persist PATH in ~/.bashrc or ~/.zshrc:
echo 'export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"' >> ~/.bashrc

# 3. Trust mise.toml and install all pinned security & task binaries
cd /path/to/py-phone-caller
mise trust
mise install
```

### Step 3: Sync the Full Python 3.14 Workspace & Build the Native SMS Module

Because `py-phone-caller` is a **12-member virtual `uv` workspace**, always pass `--all-packages` when syncing, then compile the editable PyO3 `rust_engine` SMS module once:

```bash
# 1. Sync all 12 workspace microservices + dev tools from uv.lock
uv sync --frozen --all-packages

# 2. Compile & install the native Rust SMS extension (rust_engine) into .venv
task verify:build:sms-rust
```

### Step 4: Verify Your Toolchain & Install the Git Pre-Commit Hook

```bash
# Check that all required AppSec tools are found
task sec:doctor

# Install .git/hooks/pre-commit -> runs 'task sec:fast' on every commit (~0.4s)
task sec:hooks:install

# Run a quick 15-second smoke test across Python + Rust
task verify:smoke
```

You are ready to contribute!

---

## 3. Day-to-Day Developer Workflow

### 3.1 Writing Code & Committing (Inner Loop)

Just work normally and commit with `git commit`:

```bash
git add src/caller_register/caller_register.py
git commit -m "feat(caller_register): add call filter parameter"
```

Behind the scenes, `.git/hooks/pre-commit` automatically runs `task sec:fast` (~0.4 seconds):
1. **`gitleaks protect --staged`** scans your staged diff so accidental passwords, tokens, webhook secrets, or private keys never enter git history.
2. **`uv run ruff check --select S`** checks Python files for Bandit security rules (raw SQL string formatting `S608`, `subprocess(..., shell=True)` `S602`, unsafe `yaml.load` `S506`, `eval`/`exec`, etc.).

If `task sec:fast` fails, the commit is aborted with the exact file and line number so you can fix it immediately.

> [!CAUTION]
> **Never bypass the hook with `git commit --no-verify`** to force a secret or security lint error into a branch—the CI workflow ([`.github/workflows/appsec.yml`](../.github/workflows/appsec.yml)) runs full commit-history secret scanning and SAST on every PR and will reject the build anyway.

### 3.2 Before Opening or Updating a Pull Request

Run the non-regression and static/IaC/Python-SCA gates locally before pushing:

```bash
# 1. Verify nothing is broken across Python (300 tests), Rust (114 tests), and fast SAST/secrets
task verify:all

# 2. Run deep SAST (Bandit + Semgrep + Clippy), IaC scan (Trivy), and Python CVE audit (pip-audit)
task sec:sast:full sec:iac sec:sca:py
```

*(Or run `task sec:ci` to run the entire CI security suite including `cargo-audit`, `cargo-deny`, and `osv-scanner`.)*

### 3.3 Before Cutting a Release or Building Production Images

```bash
# Generate CycloneDX SBOM (.security-reports/sbom-source.cdx.json + dist/SBOM.cdx.json)
task sec:sbom

# Audit full git commit history + live credential verification
task sec:secrets:history

# Scan built Docker Compose core images (or all 12 service images)
task sec:image:core
# or:
task sec:image:all REGISTRY=localhost VERSION=1.0.0
```

---

## 4. Complete `Taskfile.yml` Command Reference

Run `task --list` anytime from the repository root to view all tasks.

### 4.1 Tier Entrypoints & Onboarding

| Command | Purpose | Typical Runtime | Key Artifacts Generated |
| :--- | :--- | :--- | :--- |
| `task sec:doctor` | Verify `uv`, `cargo`, `gitleaks`, `osv-scanner`, `trivy`, `syft`, `cargo-audit`, `cargo-deny` (and optional `trufflehog`, `nuclei`, `cosign`) | < 1s | Terminal status table |
| `task sec:hooks:install` | Install `.git/hooks/pre-commit` executing `task sec:fast` | < 1s | `.git/hooks/pre-commit` |
| `task sec:fast` | Pre-commit gate: staged secrets + Ruff `S` security rules | ~0.4–2s | — |
| `task sec:ci` | Full PR/CI security gate (`sec:sast:full` + `sec:sca:all` + `sec:iac`) | ~30–60s | `.security-reports/*.sarif`, `*.json` |
| `task sec:release` | Full release gate (`sec:ci` + `sec:secrets:history` + `sec:sbom` + `sec:image:core`) | ~60–120s | All reports + `dist/SBOM.cdx.json` |

### 4.2 Domain-Specific Security Tasks

| Command | Domain | Underlying Tooling | Output Report |
| :--- | :--- | :--- | :--- |
| `task sec:secrets:staged` | Secrets | `gitleaks protect --staged --config .gitleaks.toml` | — |
| `task sec:secrets:history` | Secrets | `gitleaks detect` + `trufflehog git --only-verified` | `.security-reports/gitleaks.sarif` |
| `task sec:sast:fast` | Python SAST | `uv run ruff check --select S src/ test/ tests/ deploy/` | — |
| `task sec:sast:py` | Deep SAST | Bandit (`pyproject.toml`) + Semgrep OSS (`p/python`, `p/rust`, `p/owasp-top-ten`) | `bandit.sarif`, `semgrep.sarif` |
| `task sec:sast:rust` | Rust Lint | `cargo clippy --manifest-path src/openalert/Cargo.toml --all-targets --locked -- -D warnings` | — |
| `task sec:sca:py` | Python SCA | `uv export --all-packages --no-emit-workspace` piped into `pip-audit` (prod & all) | `pip-audit-prod.json`, `pip-audit-all.json` |
| `task sec:sca:rust` | Rust SCA | `cargo deny check` (`deny.toml`) + `cargo audit` on `openalertd` & `sms_rust_backend` | `cargo-audit.json`, `cargo-audit-sms.json` |
| `task sec:sca:osv` | Multi-SCA | `osv-scanner scan source` across `uv.lock` + both `Cargo.lock` files | `osv.sarif` |
| `task sec:iac` | IaC Config | `trivy config` across Dockerfiles, Compose, K8s, Helm (`HIGH,CRITICAL`) | `trivy-iac.sarif` |
| `task sec:sbom` | SBOM | `syft dir:.` (CycloneDX JSON, excluding `.venv`, `target`, `dist`, `data`) | `sbom-source.cdx.json` |
| `task sec:image IMAGE=...` | Container | `trivy image --severity HIGH,CRITICAL --ignore-unfixed` | `trivy-image-<name>.sarif` |
| `task sec:dast TARGET_URL=...` | Live DAST | `nuclei -tags cve,misconfig,exposure,headers` against a live service | `nuclei.sarif` |
| `task sec:sign:release` | Signing | `cosign sign-blob` over `dist/SHA256SUMS`, `RELEASE_MANIFEST.json`, `SBOM.cdx.json` | `dist/*.sigstore.json` |

### 4.3 Non-Regression & Safe Remediation Tasks

| Command | What It Verifies / Does |
| :--- | :--- |
| `task verify:build:sms-rust` | Compiles and installs the editable `rust_engine` (`sms_rust_backend`) PyO3 extension into `.venv` |
| `task verify:smoke` | ~15s smoke gate: `uv lock --check` + headless import of all 12 Python services & `rust_engine` + `cargo check --locked` |
| `task verify:py` | Runs all **300** Python unit, Web UI, SMS Rust engine, AppSec contract, and packaging tests (`test/`, `tests/`, Ansible bundle) |
| `task verify:rust` | Runs `cargo clippy -- -D warnings` + all **114** `openalertd` unit & integration tests |
| `task verify:all` | Runs `verify:smoke` -> `verify:py` -> `verify:rust` -> `sec:fast` |
| `task sec:fix:py PKG=<name>` | Upgrades **one** Python package in `uv.lock`, runs `verify:smoke` + `verify:py`, and **auto-rolls back `uv.lock`** if anything fails |
| `task sec:fix:rust PKG=<crate>` | Upgrades **one** Rust crate in `src/openalert/Cargo.lock`, runs `verify:rust` + `cargo deny`, and **auto-rolls back `Cargo.lock`** on failure |

---

## 5. Non-Regression Guardrails ("Do Not Break Working Stuff")

Security hardening and dependency updates must never break alerting, telephony, TTS audio synthesis, or mesh routing. Always rely on the built-in `verify:*` tasks when modifying dependencies or security-sensitive code:

1. **Fast Headless Service Import Check (`task verify:smoke`):**
   - Verifies [`uv.lock`](../uv.lock) matches all `pyproject.toml` manifests (`uv lock --check`).
   - Imports every microservice entrypoint (`py_phone_caller_utils`, `asterisk_caller`, `asterisk_recaller`, `asterisk_ws_monitor`, `caller_address_book`, `caller_prometheus_webhook`, `caller_register`, `caller_scheduler`, `caller_sms`, `celery_worker`, `generate_audio`, `py_phone_caller_ui`) plus the native PyO3 `rust_engine` (`enqueue_sms is not None`) using synthetic test environment variables—catching broken imports, missing transitive packages, or ABI mismatches in seconds.
   - Runs `cargo check --all-targets --locked` on `openalertd`.
2. **Full Python & Packaging Suite (`task verify:py`):**
   - Runs the 300-test regression suite covering Asterisk ARI callers/recallers, WebSocket monitoring, Prometheus webhooks, Kokoro/Silero/Piper TTS generation, Flask Web UI routes, OIDC/gateway integration, SQLite/Rust SMS queueing, AppSec pipeline contracts, and PyPI/DEB/RPM/K8s/Air-gap/Ansible packaging.
3. **Full Rust Suite (`task verify:rust`):**
   - Enforces zero Clippy warnings (`-D warnings`) and executes all 64 unit tests + 50 integration tests in `src/openalert`.

---

## 6. Playbook: Safely Fixing Dependency CVEs (With Auto-Rollback)

> [!IMPORTANT]
> **Golden Rule:** Never run blanket `uv lock --upgrade` or unscoped `cargo update` to fix a single CVE. Upgrade one package at a time using `sec:fix:py` or `sec:fix:rust` so git diffs remain auditable and regressions roll back automatically.

### 6.1 Remediating a Python Vulnerability (`uv.lock`)

1. **Inspect the finding** in `.security-reports/pip-audit-prod.json`, `.security-reports/pip-audit-all.json`, or `.security-reports/osv.sarif`:
   ```bash
   task sec:sca:py
   ```
2. **Check which microservice pulls in the package:**
   ```bash
   uv tree --package aiohttp
   ```
3. **Run the transactional single-package upgrader:**
   ```bash
   task sec:fix:py PKG=aiohttp
   ```
   What `sec:fix:py` does automatically:
   - Backs up `uv.lock` to `.security-reports/uv.lock.bak`.
   - Runs `uv lock --upgrade-package aiohttp`.
   - Syncs `.venv` via `uv sync --frozen --all-packages --inexact` (preserving all 12 workspace members **and** the compiled `rust_engine` extension).
   - Runs `task verify:smoke` and `task verify:py` (300 tests).
   - **If any test fails:** automatically restores the backup `uv.lock`, re-syncs `.venv`, and exits non-zero!
4. **Confirm the vulnerability is gone:**
   ```bash
   task sec:sca:py
   ```

*(Note: If the patched version exceeds a minimum/upper constraint in a member `src/<service>/pyproject.toml`, update that bound first, then run `task sec:fix:py PKG=<name>`.)*

### 6.2 Remediating a Rust Crate Advisory (`Cargo.lock`)

1. **Inspect the advisory and trace its dependency tree:**
   ```bash
   # Trace in openalertd (including target-specific and dev dependencies)
   cargo tree --manifest-path src/openalert/Cargo.toml --target all --edges all -i rustls

   # Or trace in sms_rust_backend
   cargo tree --manifest-path src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/Cargo.toml --target all --edges all -i tokio
   ```
2. **If a semver-compatible patch exists for `openalertd`, run:**
   ```bash
   task sec:fix:rust PKG=rustls
   ```
   *(If multiple major versions of the same crate exist in `Cargo.lock`, pass the versioned spec, e.g., `task sec:fix:rust PKG=rustix@1.1.4`.)*
   If `cargo clippy`, `cargo test`, or `cargo deny` fails, `sec:fix:rust` automatically restores `src/openalert/Cargo.lock`.
3. **For `sms_rust_backend` (`src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/Cargo.lock`):**
   ```bash
   cargo update --manifest-path src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine/Cargo.toml -p <crate>
   task verify:build:sms-rust
   uv run --no-sync pytest test/test_caller_sms.py
   ```
4. **When an advisory is blocked by an upstream major dependency** (for example, transitive crates pinned inside `bitchat-qudag = "0.1.0"` or major `pyo3`/`sqlx`/`rusqlite` upgrades):
   - Do **not** blindly bump major versions in `Cargo.toml` during a routine patch PR.
   - Coordinate a dedicated, tested upgrade PR for that direct dependency, or document a time-boxed advisory entry in [`deny.toml`](../deny.toml) with an issue link and rationale (see [Section 8](#8-exception-governance--automated-contract-tests)).

---

## 7. Playbook: Resolving Scanner Findings by Domain

### 7.1 Secrets (`sec:secrets:staged` / `sec:secrets:history`)

- **Real secret staged (not yet committed):**
  1. Unstage and replace the hardcoded value with an environment variable / Dynaconf setting (`settings.commons...` or `os.environ[...]`).
  2. Re-stage and run `task sec:secrets:staged`.
- **Real secret already committed/pushed:**
  1. **Rotate/revoke the credential immediately** in the target system (Asterisk ARI, PostgreSQL, Twilio, Keycloak, Nostr nsec, etc.)—removing it from a later commit does **not** erase git history.
  2. Rewrite local branch history if unmerged, and verify with `task sec:secrets:history`.
- **Synthetic test fixture false positive:**
  - Use clearly synthetic placeholders in unit tests (`test_password`, `dummy_token`, `EXAMPLE_KEY`).
  - If a high-entropy test vector (such as a deterministic Nostr/crypto test vector) triggers Gitleaks, add a narrowly scoped path/regex rule in [`.gitleaks.toml`](../.gitleaks.toml) with a comment explaining why it is synthetic.

### 7.2 Python SAST (`sec:sast:fast` / `sec:sast:py`)

Follow these secure coding patterns across `src/` so Ruff `S`, Bandit, and Semgrep pass cleanly:

- **Database Queries (`S608` — Piccolo ORM):**
  Never interpolate variables into `Table.raw(f"SELECT ... {user_val}")`. Always use Piccolo `{}` parameter placeholders (which bind safely as PostgreSQL `$1`, `$2` parameters):
  ```python
  # BAD — triggers S608 & Bandit B608
  await Calls.raw(f"SELECT * FROM calls WHERE phone = '{phone}' LIMIT {limit}")

  # GOOD — parameterized query
  await Calls.raw("SELECT * FROM calls WHERE phone = {} LIMIT {}", phone, int(limit))
  ```
- **Internal Microservice HTTP Calls (Flask UI / `aiohttp` / `requests`):**
  - Pass query parameters via `params={"asterisk_chan": chan}` instead of f-string URL concatenation.
  - Validate path segments (reject `/`, `\`, `..`) and URL-encode dynamic path segments with `urllib.parse.quote(segment, safe="")`.
  - Always set an explicit `timeout=` on `requests.get`/`post`/`put`/`delete` (`S113`).
- **Subprocesses (`S602` / `S603`):**
  - Never use `shell=True`. Pass argument lists (`["ffmpeg", "-i", input_path, output_path]`) with validated paths.

### 7.3 Rust Static Analysis & Supply-Chain Policy (`sec:sast:rust` & `deny.toml`)

- **Clippy (`-D warnings`):** Run `task sec:sast:rust` after editing `src/openalert/**/*.rs`. Every compiler or Clippy warning is treated as an error so real defects are never buried in noise.
- **Adding a New Crate to `src/openalert/Cargo.toml`:**
  Run `cargo deny --manifest-path src/openalert/Cargo.toml --config deny.toml check licenses bans sources`.
  - [`deny.toml`](../deny.toml) rejects copyleft licenses (`GPL-*`, `AGPL-*`), wildcard version specs (`*`), yanked crates, and non-`crates.io` git/registry sources across both `x86_64-unknown-linux-gnu` and `aarch64-unknown-linux-gnu`.

### 7.4 Infrastructure-as-Code & Containers (`sec:iac` & `sec:image`)

- **IaC (`task sec:iac`):** Whenever you edit a `Dockerfile`, `docker-compose*.yml`, `deploy/k8s/*.yml`, or `deploy/helm/py-phone-caller/`, run `task sec:iac`.
- **Container Image Scanning (`task sec:image`):**
  ```bash
  # Build and scan a single service image
  docker build -t localhost/openalertd:1.0.0 src/openalert
  task sec:image IMAGE=localhost/openalertd:1.0.0

  # Or scan the core Compose images (openalertd, caller_prometheus_webhook, generate_audio, py_phone_caller_ui)
  task sec:image:core REGISTRY=localhost VERSION=1.0.0
  ```
  `trivy image` fails only on `HIGH` or `CRITICAL` vulnerabilities that **have an upstream fix available** (`--ignore-unfixed`), avoiding unactionable base-OS noise.

### 7.5 Optional Live Runtime Probing (`sec:dast`)

When running `openalertd`, the Flask Web UI, or `caller_prometheus_webhook` locally in Docker Compose or a staging VM, you can run non-destructive Nuclei HTTP/header/misconfiguration probes:

```bash
# Probe openalertd REST / Dashboard / /sos portal (default: http://127.0.0.1:8090)
task sec:dast

# Probe the Flask Web Management UI
task sec:dast TARGET_URL=http://127.0.0.1:5000

# Probe the Prometheus Alertmanager Webhook service
task sec:dast TARGET_URL=http://127.0.0.1:8084
```

---

## 8. Exception Governance & Automated Contract Tests

To prevent "ignore-and-forget" security drift, [`tests/test_appsec_pipeline.py`](../tests/test_appsec_pipeline.py) automatically enforces strict governance rules during `pytest` / `task verify:py`:

1. **High-Risk Python Rules Cannot Be Ignored in `src/`:**
   [`pyproject.toml`](../pyproject.toml) `[tool.ruff.lint.per-file-ignores]` is **forbidden** from ignoring `S608` (SQL injection), `S602` (`shell=True`), `S301` (`pickle`), `S307` (`eval`), `S102` (`exec`), or `S506` (unsafe `yaml.load`) on any production `src/` path.
2. **Every `.trivyignore.yaml` Entry Must Be Path-Scoped & Time-Boxed:**
   Global ignores are prohibited. Every entry in [`.trivyignore.yaml`](../.trivyignore.yaml) **must** include all four fields:
   ```yaml
   misconfigurations:
     - id: AVD-DS-0002
       paths:
         - docker-compose.hardware.yml
         - deploy/compose/docker-compose.hardware.yml
       expired_at: 2027-06-01
       statement: >-
         openalertd hardware overlay intentionally requires CAP_NET_ADMIN and
         CAP_NET_RAW for BlueZ BLE HCI/L2CAP mesh sockets (bluer crate).
   ```
3. **Every Advisory Baseline in `osv-scanner.toml` and `deny.toml` Must Be Time-Boxed & Justified:**
   When an upstream crate advisory requires a breaking major upgrade or affects an inactive/non-compiled feature, temporary baselines in [`osv-scanner.toml`](../osv-scanner.toml) (shared by `osv-scanner` and `cargo-audit` in `sec:sca:rust`) and [`deny.toml`](../deny.toml) **must** carry a future `ignoreUntil = YYYY-MM-DD` / `Expires YYYY-MM-DD` review trigger and a detailed `reason`:
   ```toml
   [[IgnoredVulns]]
   id = "RUSTSEC-2026-0459"
   ignoreUntil = 2027-06-01
   reason = "rand 0.8.8 via snow 0.9 / ed25519-dalek 2.2; openalertd never invokes custom logger inside thread_rng(). Upgrade when upstream moves to rand 0.10."
   ```
   *(Contract tests verify `ignoreUntil` / `Expires` is strictly in the future so stale ignores fail CI automatically on expiration.)*
4. **SCA Tasks Never Skip on Cached Lockfiles:**
   `sec:sca:py`, `sec:sca:rust`, `sec:sca:osv`, and `sec:sca:all` are contract-tested to ensure `sources:` caching is never added—because new CVEs are published daily even when `uv.lock` and `Cargo.lock` have not changed.

---

## 9. CI/CD & GitHub Code Scanning Integration

The GitHub Actions workflow [`.github/workflows/appsec.yml`](../.github/workflows/appsec.yml) runs automatically on:
- Every `pull_request` targeting `main`
- Every `push` to `main`
- Every **Monday at `06:00 UTC`** (`cron: "0 6 * * 1"`) to catch newly disclosed advisories against unchanged lockfiles
- Manual `workflow_dispatch`

In CI, the workflow:
1. Installs native Linux headers (`libdbus-1-dev`, `libudev-dev`, `libssl-dev`), Python `3.14` + `3.12` (`astral-sh/setup-uv@v7`), Rust `stable`, and pinned `mise` tools (`jdx/mise-action@v5`).
2. Executes the exact same `task` targets (`sec:doctor`, `sec:sast:full`, `sec:secrets:history`, `sec:iac`, `sec:sbom`, `sec:sca:all`).
3. Uploads all `.security-reports/*.sarif` files (`gitleaks.sarif`, `bandit.sarif`, `semgrep.sarif`, `osv.sarif`, `trivy-iac.sarif`) to **GitHub Security -> Code scanning** (`github/codeql-action/upload-sarif@v4`, `if: always()`).
4. Publishes `.security-reports/*.sarif`, `*.json`, and `sbom-source.cdx.json` as downloadable workflow artifacts (`actions/upload-artifact@v7` with `include-hidden-files: true`).

---

## 10. Troubleshooting & Common Workspace Gotchas

### Q1: `task: command not found` or `task sec:doctor` reports `[MISSING]` tools
Ensure `~/.local/share/mise/shims`, `~/.local/bin`, and `~/.cargo/bin` are on your `PATH`, then run `mise install`:
```bash
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
mise trust && mise install
task sec:doctor
```

### Q2: `ModuleNotFoundError: No module named 'dynaconf'` (or `piccolo`, `flask`, `torch`)
You ran bare `uv sync` or `uv sync --frozen` **without `--all-packages`**. Because the root [`pyproject.toml`](../pyproject.toml) is a virtual workspace (`dependencies = []`), bare `uv sync` only installs root `dev` tools and removes microservice runtime dependencies! Fix it immediately with:
```bash
uv sync --frozen --all-packages
task verify:build:sms-rust
```

### Q3: `test/test_caller_sms.py` fails with `TypeError: 'NoneType' object is not callable` (`enqueue_sms` is `None`)
Running an exact `uv sync` (without `--inexact`) removes packages not tracked in `uv.lock`, including the locally compiled PyO3 `rust_engine` (`sms_rust_backend`) wheel. Rebuild it in ~5 seconds:
```bash
task verify:build:sms-rust
```
*(Tip: `task sec:fix:py`, `task verify:smoke`, and `task verify:py` automatically use `--inexact` / `--no-sync` to preserve `rust_engine`.)*

### Q4: Why does `Taskfile.yml` run Semgrep with `--python 3.12`?
While the `py-phone-caller` workspace runs natively on **Python 3.14**, `semgrep` wheels currently target Python `<= 3.13`. `uv tool run --python 3.12 semgrep ...` automatically runs Semgrep in an isolated tool environment without touching your workspace `.venv`! (If Python 3.12 is not cached yet, `uv` downloads it automatically on first run, or run `uv python install 3.12`.)

### Q5: Running `pip-audit` manually fails on `kokoro==0.9.4`
Always run `task sec:sca:py` (or pass `--no-deps --disable-pip` to `pip-audit`). `uv export --frozen --all-packages --no-emit-workspace` already resolves the exact transitive graph for Python 3.14, whereas `pip`'s internal resolver trips over upstream `Requires-Python` metadata on transitive ML/TTS packages.
