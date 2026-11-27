# Security Policy

## Supported Versions

Security fixes and dependency advisories are actively maintained for the latest minor release line:

| Version | Supported | Notes |
| :--- | :--- | :--- |
| `1.1.x` | Yes | Current unified `py-phone-caller` + `openalertd` release line |
| `1.0.x` | Security fixes via upgrade to `1.1.x` | Upgrade recommended |
| `< 1.0` | No | Historical pre-release tags |

---

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Instead, report suspected vulnerabilities privately via **GitHub Private Vulnerability Reporting** (`Security` tab -> `Report a vulnerability` on <https://github.com/jcfdeb/py-phone-caller/security/advisories/new>).

When reporting an issue, please include:
1. Affected component(s) (e.g., `py_phone_caller_ui`, `openalertd`, `deploy/ansible`, `deploy/gateway`, or a specific microservice).
2. Deployment topology (`standard`, `enterprise` APISIX/Keycloak, `airgapped`, Docker Compose, or Kubernetes/Helm).
3. Minimal reproduction steps or proof-of-concept without targeting live infrastructure.

We aim to acknowledge reports within **72 hours** and coordinate remediation before public disclosure.

---

## Operational Security Boundaries

- **Network Segmentation**: Internal microservice ports (`8081`–`8087`), PostgreSQL (`5432`), Redis/Valkey (`6379`), Asterisk ARI (`8088`), and `openalertd` (`8090`) must bind to loopback or isolated private networks and **must never be exposed directly to the public Internet**.
- **Public Ingress & TLS**: Terminate public HTTPS exclusively at a hardened edge reverse proxy (**Caddy** or **Apache APISIX** + **Keycloak OIDC**; see [`deploy/docs/07-enterprise-gateway-and-observability.md`](deploy/docs/07-enterprise-gateway-and-observability.md)).
- **Secret Hygiene**: Never commit `.secrets.toml`, `.env`, Ansible Vault passwords, private keys, or real phone numbers/credentials. Keep pre-commit secret scanning enabled via `task sec:hooks:install`.

---

## Automated AppSec & Supply-Chain Verification

Every change in this repository is guarded by deterministic security checks defined in [`Taskfile.yml`](Taskfile.yml) (documented in [`docs/appsec-and-supply-chain-guide.md`](docs/appsec-and-supply-chain-guide.md)):

- `task sec:fast` — Pre-commit staged secrets scan (`gitleaks`) + Python `ruff` `S`-rules.
- `task sec:ci` — Full SAST (`Bandit`, `Semgrep`, `cargo clippy -D warnings`), SCA (`osv-scanner`, `cargo-audit`, `cargo-deny`), and IaC scanning (`trivy config`).
- `task sec:release` — Full git-history secret verification (`gitleaks` + `trufflehog`), CycloneDX SBOM generation (`syft`), and container image vulnerability scans (`trivy image`).
