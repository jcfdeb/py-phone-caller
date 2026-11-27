# 📚 py-phone-caller Documentation Library

Welcome to the official documentation library for **py-phone-caller** and **OpenAlert (`openalertd`)**.

**py-phone-caller** is an automated phone call, SMS, and SIP `MESSAGE` incident dispatching platform designed for mission-critical IT infrastructure, SRE teams, air-gapped appliances, and emergency operations. It bridges monitoring systems (*Prometheus Alertmanager, Nagios, Zabbix, Grafana*) and decentralized field mesh networks (*OpenAlert LoRa RF, BitChat BLE, `/sos` Captive Portal, Nostr*) with telephony networks (*Asterisk 22 PBX, SIP Trunks, local SIP extensions, on-premise USB GSM/LTE modems with always-UCS-2 UTF-8 encoding, and Twilio*) so critical alerts reliably reach on-call personnel even when the public Internet is unavailable.

---

## 🧭 Documentation Map

```text
docs/
├── README.md                                # 📍 You are here: Master Documentation Index
├── ../CHANGELOG.md                          # 🏆 Unified Suite Changelog (v1.1.0)
├── 1.0.1-release.md                         # 📋 v1.0.1 Enhancement Deep-Dive Notes
│
├── 🏛️ Architecture & Technical Reference
│   ├── architecture-and-call-flows.md       # 📐 End-to-End Call, Dual-Channel SMS/SIP, DTMF & Mesh Flows
│   ├── services-and-endpoints.md            # 🔌 Complete Microservices & REST API Reference
│   ├── uv-migration-and-workspace-guide.md  # 🐍 Python 3.14 UV Workspace, Maturin Rust SMS & Packaging
│   └── appsec-and-supply-chain-guide.md     # 🛡️ AppSec, Supply-Chain & Non-Regression Developer Guide
│
├── 🚀 Operations, Gateway & Telephony Setup
│   ├── ../deploy/docs/README.md             # 🌟 Modular Deployment Hub (Ansible, Compose, K8s/Helm, DEB/RPM, PyPI, ARM64/Air-Gap, 12-Gate Validation)
│   ├── ENTERPRISE_GATEWAY_AND_IAM_GUIDE.md  # 🛡️ Apache APISIX Gateway & Keycloak OIDC SSO Guide
│   └── freepbx-asterisk-setup-guide.md      # 📞 FreePBX & Asterisk ARI / PJSIP / Ext 1000 Setup Guide
│
├── 🚨 OpenAlert Decentralized Mesh & Nostr Bridge
│   ├── openalert/README.md                  # 📡 OpenAlert (`openalertd`) Architecture, BLE/LoRa/Captive Portal
│   ├── openalert/NIP-ALERT.md               # 📜 Formal NIP-ALERT (Kind 30000) Nostr Specification
│   └── openalert/CONFIGURATION_GUIDE.md     # ⚙️ Multi-Layered Configuration, Embedded Relay & NIP-57 Zaps
│
├── 🖥️ Web Console & User Interface
│   └── web-ui-tour/README.md                # 🖥️ Visual Walkthrough of the Multilingual Web Management UI
│
├── 📊 Observability & Monitoring
│   ├── opentelemetry-guide.md               # 📈 Metrics (/metrics), Probes (/health, /ready), & OTel Tracing
│   └── tempo_traces.md                      # 🔍 Grafana Tempo & TraceQL Distributed Tracing
│
└── 🗄️ Archive
    └── archive/README.md                    # 🕰️ Historical Pre-Release, Audit & Superseded Documentation
```

---

## 📑 Core Documentation Index

### 1. 🚀 Operations & Deployment
- **[5-Minute Local Quickstart (Zero VoIP Trunk Needed)](quickstart-5-minutes.md)**  
  *Fastest way to experience the suite live.* Register the free **Linphone** softphone to local Asterisk PJSIP extension `1000`, receive a real offline-synthesized neural TTS voice alert, press **`4`** on your keypad to acknowledge, and receive an instant RFC 3428 SIP `MESSAGE` text alert.
- **[Centralized Deployment Documentation Hub (`deploy/docs/`)](../deploy/docs/README.md)**  
  *The canonical, verified installation and operations hub.* Covers modular guides `01`–`10`:
  - Native **Ansible** (`site.yml`) for Debian 13 (AllStarLink), Ubuntu 26.04 LTS, Rocky Linux 10, and AlmaLinux 10 (Tucny Asterisk `22.9.0-1.el10`, `SELinux Enforcing`) with ready-to-use local SIP extension `1000` (`asterisk_sip_exten_1000_enabled`), backup/restore/rollback, and OpenAlert adoption.
  - **Docker / Podman Compose** (full stack + hardware passthrough + gateway overlays).
  - **Kubernetes & Helm v3** (`43`-resource Kustomize manifests & `py-phone-caller-1.1.0.tgz` chart with `EndpointSlice`).
  - **Native Linux `.deb` / `.rpm` packages**, **PyPI wheels + `systemd`**, and **Release Packaging** (`build_all_releases.py`).
  - **Physical ARM64 & 100% Air-Gapped Appliances** (Orange Pi 5 Plus RK3588, offline signed `file:` APT mirror, offline TTS weights, `IPAddressDeny=any`).
  - **12-Gate End-to-End Validation Checklist** (`deploy/docs/10-end-to-end-installation-validation.md`).
- **[Enterprise Gateway & Keycloak SSO Guide](ENTERPRISE_GATEWAY_AND_IAM_GUIDE.md)**  
  Automated (Ansible `stack_topology: enterprise`) and manual copy-and-paste deployment guide for Apache APISIX unified API gateway, Keycloak OIDC IAM, 3-tier RBAC (`alert-admin`, `alert-operator`, `alert-viewer`), M2M Alertmanager OAuth2 tokens, and public TLS termination. Also see [`deploy/docs/07-enterprise-gateway-and-observability.md`](../deploy/docs/07-enterprise-gateway-and-observability.md).
- **[Asterisk PBX Configuration & Examples (Native Linux)](asterisk-pbx-configuration-guide.md)**  
  Complete, copy-pasteable `/etc/asterisk/` configurations (sanitized with `<PASSWORD>`) for standalone Asterisk 18–22 servers: `http.conf`, `ari_py_phone_caller.conf`, `pjsip_py_phone_caller.conf` (VoIP SIP trunks + mobile/VPN-ready local extension `1000`), `extensions_py_phone_caller.conf` (Stasis + TTS + DTMF `4` ACK `${CURL(...)}` callbacks), `iax_py_phone_caller.conf`, `modules.conf`, SELinux rules, and matching `settings.toml` / `.secrets.toml`.
- **[FreePBX & Asterisk GUI Setup Guide](freepbx-asterisk-setup-guide.md)**  
  Visual FreePBX configuration walkthrough (SIP/PJSIP Trunks, Extensions, Stasis Dialplan, ARI users, G.711 codecs) plus native Asterisk 22 Ansible automation and ready-to-use local SIP extension `1000` / RFC 3428 SIP `MESSAGE` setup.

---

### 2. 🏛️ Architecture & Technical Reference
- **[Architecture & Call Flows](architecture-and-call-flows.md)**  
  Comprehensive architecture guide detailing the 11 Python microservices + `openalertd` mesh bridge, domain-driven data boundaries, Mermaid sequence diagrams for outbound calls, real-time DTMF acknowledgment (`4` to ack, `5` to repeat), recaller/backup escalation, **dual-channel contact routing** (`phone_number` + `sms_phone_number`), **smart SMS/SIP `MESSAGE` failover**, always-UCS-2 70-unit chunked USB GSM SMS, multi-engine offline TTS (Kokoro, Silero, Piper, MMS), Celery `p0_emergency` scheduling, and air-gapped design principles.
- **[Services & Endpoints Reference](services-and-endpoints.md)** & **[Interactive OpenAPI 3.0 Explorer](api-explorer.md)**  
  Authoritative REST API reference and interactive multi-service OpenAPI 3.0.3 explorer (`curl` generator + downloadable `.json` specs) covering all 8 Python services + `openalertd`, exact port allocations (`8081`–`8087`, `5000`, `8090`/`8088`), `/ready` probes, and Piccolo ORM database tables.
- **[Hardware Compatibility & Sovereign Field-Kit BOM Guide](hardware-and-field-kit-bom.md)**  
  Reference BOM for NOC rack appliances, `/sos` emergency field kits, and hilltop solar repeaters: Orange Pi / Raspberry Pi sizing, SIM7600 / Quectel EC25 USB GSM modems + persistent `udev` rules, sub-GHz LoRa serial radios, BlueZ BLE adapters, and rugged SIP handsets.
- **[Day-2 SRE Runbook & Self-Monitoring ("Who Watches the Watchmen?")](sre-day2-operations-and-watchdog.md)**  
  Turnkey Prometheus self-monitoring alert rules ([`prometheus-alerting-rules.yml`](../deploy/dashboards/prometheus-alerting-rules.yml)), zero-downtime PostgreSQL & SQLite WAL backups, secret rotation, and DLQ/spool triage.
- **[Release Notes & Current Capabilities](1.0.1-release.md)**  
  Feature summary covering the Strategy-pattern TTS overhaul (Silero V3, `/languages`, cross-engine fallback), multilingual Flask-Babel RTL Web UI, Asterisk ARI circuit breaker, Redis distributed locks, dual-channel SMS/SIP routing, always-UCS-2 GSM SMS, OpenAlert mesh bridge, and upgrade guidance.
- **[UV Workspace & Packaging Guide](uv-migration-and-workspace-guide.md)**  
  Developer guide covering the Python 3.14 multi-package `uv` workspace, unified `uv.lock`, editable shared library linking (`py_phone_caller_utils`), `maturin` Rust SMS backend (`rust_engine`) builds, `pytest` / `ruff` workflows, wheel publishing, and multi-stage container builds.
- **[AppSec, Supply-Chain & Non-Regression Developer Guide](appsec-and-supply-chain-guide.md)**  
  Contributor onboarding and operations playbook for [`Taskfile.yml`](../Taskfile.yml), [`mise.toml`](../mise.toml), pre-commit hooks (`task sec:fast`), full SAST/SCA/IaC/SBOM/Cosign gates (`task sec:ci`, `task sec:release`), non-regression checks (`task verify:all`), and transactional single-package CVE upgrades with auto-rollback (`task sec:fix:py`, `task sec:fix:rust`).

---

### 3. 🚨 OpenAlert Decentralized Mesh & Nostr Bridge
- **[OpenAlert Architecture (`openalertd`)](openalert/README.md)**  
  Native Rust field mesh daemon bridging LoRa 868 MHz RF, BitChat BLE (Noise XX E2EE + BlueZ/Spreadtrum HCI self-healing), `/sos` Wi-Fi Captive Portal (offline SVG CAPTCHA + GPS + optional NIP-57 Zaps), Nostr (`NIP-ALERT` Kind 30000, 0xChat NIP-17 E2EE C2, Embedded Micro-Relay `:8088`), and direct USB GSM always-UCS-2 SMS to `py-phone-caller`.
- **[NIP-ALERT Specification (`Kind 30000`)](openalert/NIP-ALERT.md)**  
  Formal Nostr specification for parameterized replaceable alert events and `XChaCha20-Poly1305` group encryption.
- **[OpenAlert Configuration Guide](openalert/CONFIGURATION_GUIDE.md)**  
  Multi-layered configuration reference (`openalertd.toml`), webhook auth, peering, and NIP-57 Lightning Zap adapter setup.

---

### 4. 🖥️ Web Console & Operator Experience
- **[Web UI Operator Tour](web-ui-tour/README.md)**  
  Visual screenshot walkthrough of the Flask-Babel multilingual Web Management UI (with Arabic/Hebrew RTL support): Dashboard & live TTS preview, Managed Calls & bulk ACK, Incident Audit Reports, Call Diagnostics, PBX WebSocket Events, Scheduled Calls, Dual-Channel Address Book (`phone_number` + `sms_phone_number`) & On-Call Calendars, User Management, and Managed SMS with CSV export.

---

### 5. 📊 Observability & Monitoring Integration
- **[OpenTelemetry & Observability Guide](opentelemetry-guide.md)**  
  Dual-mode observability framework: Prometheus `/metrics` scraping, standardized `/health` and `/ready` probes, turnkey Grafana dashboard (`deploy/dashboards/`), and distributed OpenTelemetry tracing (OTLP gRPC).
- **[Grafana Tempo Tracing Guide](tempo_traces.md)**  
  Querying and visualizing end-to-end distributed call and SMS traces using Grafana Tempo and TraceQL.
- **Monitoring Script Integrations**:
  - [Prometheus Alertmanager Webhook Guide](../src/caller_prometheus_webhook/README.md)
  - [Nagios Event Handler Call Script](../assets/scripts/nagios/README.md)
  - [Zabbix Alert Action Script](../assets/scripts/zabbix/README.md)

---

### 6. 🗄️ Historical Archive
- **[Archived Documentation Index](archive/README.md)**  
  Preserved pre-release, historical audit, and superseded legacy guides (`OPERATOR_INSTALLATION_GUIDE.md`, `1.0.0-release.md`, `release-1.0.0-audit-report.md`, `deployment-validation-report.md`, `virtualbox-setup.md`, and 2025/2026 pre-release notes).

---

### 🎯 Quick Navigation by Role

| If you are... | Start here: |
| :--- | :--- |
| **Evaluating the project in 5 minutes (no SIP trunk)** | ➡️ **[5-Minute Local Quickstart (Linphone + Exten `1000`)](quickstart-5-minutes.md)** |
| **A Sysadmin / SRE installing for the first time** | ➡️ **[Centralized Deployment Documentation Hub (`deploy/docs/`)](../deploy/docs/README.md)** |
| **Deploying on ARM64 / 100% Air-Gapped hardware** | ➡️ **[ARM64 Appliance & Air-Gapped Guide](../deploy/docs/09-arm64-appliance-and-airgapped-deployment.md)** |
| **Deploying Enterprise SSO (APISIX + Keycloak)** | ➡️ **[Enterprise Gateway & Keycloak SSO Guide](ENTERPRISE_GATEWAY_AND_IAM_GUIDE.md)** |
| **A Telephony / PBX Administrator** | ➡️ **[Asterisk PBX Configuration & Examples](asterisk-pbx-configuration-guide.md)** & **[FreePBX GUI Guide](freepbx-asterisk-setup-guide.md)** |
| **Deploying Off-Grid Field Mesh (LoRa / BLE / Nostr)** | ➡️ **[OpenAlert Architecture Guide](openalert/README.md)** |
| **A Developer integrating with the REST API** | ➡️ **[Services & Endpoints Reference](services-and-endpoints.md)** |
| **A Software Engineer contributing code** | ➡️ **[UV Workspace & Packaging Guide](uv-migration-and-workspace-guide.md)** · **[AppSec & Supply-Chain Guide](appsec-and-supply-chain-guide.md)** |
| **An Operations Engineer setting up Monitoring** | ➡️ **[OpenTelemetry & Observability Guide](opentelemetry-guide.md)** |

---

## 🔒 Security & Deployment Notice

> [!WARNING]
> **py-phone-caller** is designed to run within **trusted local area networks (LANs)**, air-gapped segments, or isolated VLANs behind firewalls and gateways.
>
> - **Never expose internal microservice ports (`8081`–`8087`) directly to the public Internet.**
> - Use the **[Enterprise Gateway & Keycloak SSO Guide](ENTERPRISE_GATEWAY_AND_IAM_GUIDE.md)** (or **[Deployment Guide 07](../deploy/docs/07-enterprise-gateway-and-observability.md)**) for public ingress with TLS termination, Apache APISIX route protection, and OIDC RBAC authentication.
