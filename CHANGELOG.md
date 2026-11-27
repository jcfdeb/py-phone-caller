# Changelog

All notable changes to **py-phone-caller** and **OpenAlert (`openalertd`)** are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.1.0] - 2026-11-26

### Added
- **Unified Suite Release (`v1.1.0`)**: Synchronized release versioning across all 13 Python packages (`py-phone-caller` workspace & meta-package), `openalertd` (`src/openalert`), `rust_engine` SMS native extension, Helm v3 chart (`py-phone-caller-1.1.0.tgz`), native `.deb`/`.rpm` packages, and container tags.
- **AlmaLinux 10 First-Class Qualification**: Enabled and live-qualified AlmaLinux 10 AMD64 (`SELinux Enforcing`) alongside Debian 13, Ubuntu 26.04 LTS, and Rocky Linux 10 across `deploy/ansible` (`site.yml`, `verify.yml`, Tucny Asterisk `22.9.0-1.el10`).
- **OpenAlert (`openalertd`) Off-Grid Mesh & Nostr Bridge**:
  - LoRa 868 MHz RF SLIP framing with ETSI EN 300 220 1.0% duty-cycle pacing, in-band RSSI/SNR link-cost routing, and 3-tier authenticated off-grid time sync.
  - BitChat Bluetooth LE mesh (`Noise_XX_25519_ChaChaPoly_SHA256`) with BlueZ/Spreadtrum HCI self-healing watchdog and clean `SIGTERM` GATT teardown.
  - Emergency `/sos` Web & Wi-Fi Captive Portal (`OpenAlert-SOS`) with offline HMAC-SHA256 distorted SVG CAPTCHA, one-tap GPS coordinates, and optional NIP-57 Lightning Zap receipt verifier (`Kind 9735`).
  - Embedded Nostr tactical micro-relay (`:8088`, native TLS `wss://` support), `NIP-ALERT` (`Kind 30000` with `XChaCha20-Poly1305` group encryption), and 0xChat NIP-17/59/44 encrypted C2 & thread-aware ACK.
- **Dual-Channel Contact Routing & Always-UCS-2 GSM SMS**:
  - Separate voice (`phone_number`) and cellular (`sms_phone_number`) fields in Address Book, `phone=oncall` dynamic resolution, RFC 3428 SIP `MESSAGE` (`asterisk_sip`) delivery/failover, and ready-to-use local SIP Extension `1000` provisioning in Ansible.
  - Always-UCS-2 16-bit Unicode encoding with 70 UTF-16 code-unit multipart splitting across both `rust_engine` and `openalertd` USB GSM modem drivers.
- **Hybrid GitHub Pages & Documentation Portal**:
  - Automated `.github/workflows/pages.yml` publishing unified product showcase pages (`/`, `/openalert/`) and a searchable MkDocs Material documentation manual (`/manual/`) covering both `docs/` and `deploy/docs/`.
- **AppSec, Supply-Chain & Coherence Gates**:
  - Unified `Taskfile.yml` + `mise.toml` security tiers (`sec:fast`, `sec:ci`, `sec:release`), CycloneDX SBOM generation, transactional CVE auto-rollback (`sec:fix:py`, `sec:fix:rust`), and `tests/test_docs_coherence.py` link/version enforcement.

### Changed
- **Kubernetes `EndpointSlice` Migration**: Replaced deprecated `v1 Endpoints` with `discovery.k8s.io/v1 EndpointSlice` in `deploy/k8s/01_asterisk_endpoint.yml` and `deploy/helm/py-phone-caller/templates/asterisk-endpoint.yaml` for warning-free Kubernetes `1.33+` / `1.36+` deployments.
- **Docker Compose Gateway & BuildKit Defaults**: Mounted `deploy/gateway/apisix/dashboard_conf.yaml` so `apisix-dashboard` connects directly to `apisix-etcd:2379`, bound APISIX Admin API strictly to loopback `127.0.0.1:9180`, and defaulted `DOCKER_BUILDKIT=1` in `src/build_all_images.sh`.
- **Air-Gap Build Determinism**: Pinned exact `cython==3.0.12` build constraint in `pyproject.toml` and `uv.lock` for strict `stack_airgap_check.py` compliance, and updated `openalert_contract.py` to support nullable git provenance fields on `prebuilt: true` release bundles.

---

## [1.0.1] - 2026-11-21

### Added
- Strategy-pattern modular refactor of `generate_audio` (`enums`, `languages`, `runners`, `discovery`, `strategies`, `preloading`).
- Offline **Silero TTS** (PyTorch V3) engine support alongside Kokoro-82M, Piper ONNX, Facebook MMS, AWS Polly, and gTTS, plus `GET /languages` live model discovery and cross-engine language fallback.
- Multilingual Web UI (`Flask-Babel`) supporting English, Spanish, German, French, Italian, Arabic, and Hebrew (with full RTL layout stylesheets), browser TTS preview, bulk call ACK, and incident audit reports.
- Asterisk ARI circuit breakers, Redis distributed locks (`redis_lock`), and Celery `p0_emergency` priority queue routing.
- See [1.0.1 Release Notes](docs/1.0.1-release.md) for full details.

---

## [1.0.0] - 2026-08-22

### Added
- Production 11-microservice Python architecture (`uv` workspace on Python 3.14), Piccolo ORM PostgreSQL persistence, Celery/Redis scheduling, Apache APISIX + Keycloak OIDC Enterprise Gateway, OpenTelemetry metrics/tracing, and native Rust on-premise GSM SMS engine (`rust_engine`).
- See [1.0.0 Archived Release Notes](docs/archive/1.0.0-release.md).

---

## [0.0.2] - 2023-05-01

### Added
- Initial multi-service Asterisk ARI outbound voice caller, Prometheus Alertmanager webhook, recaller retry loop, address book, and Flask management UI.
