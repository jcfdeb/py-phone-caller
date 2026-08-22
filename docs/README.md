# 📚 py-phone-caller Documentation Library

Welcome to the official documentation library for **py-phone-caller** (Release 1.0.0).

**py-phone-caller** is an enterprise-grade automated phone call and SMS incident dispatching platform designed for mission-critical IT infrastructure, SRE teams, and emergency operations. It bridges monitoring systems (*Prometheus Alertmanager, Nagios, Zabbix, Grafana*) with telephony networks (*Asterisk PBX, SIP Trunks, Twilio, on-premise GSM/LTE modems*) to ensure high-priority alerts wake up the right people at the right time.

---

## 🧭 Documentation Map

```text
doc/
├── README.md                           # 📍 You are here: Master Documentation Index
│
├── 🚀 Operations & Deployment
│   ├── OPERATOR_INSTALLATION_GUIDE.md  # 🌟 Master A-to-Z Operator Installation & Runbook
│   ├── freepbx-asterisk-setup-guide.md # 📞 FreePBX & Asterisk ARI Dialplan Setup (Visual)
│   ├── virtualbox-setup.md             # 💻 Local VirtualBox Dual-NIC Lab Environment
│   └── 1.0.0-release.md                # 🛡️ Release 1.0.0 Architecture & Security Hardening
│
├── 🏛️ Architecture & Specifications
│   ├── architecture-and-call-flows.md  # 📐 End-to-End Call, SMS & DTMF Sequence Flows
│   ├── services-and-endpoints.md       # 🔌 Complete Microservices & REST API Reference
│   └── uv-migration-and-workspace-guide.md # 🐍 Python 3.14 UV Workspace & Packaging Guide
│
├── 🖥️ Web Console & User Interface
│   └── web-ui-tour/README.md           # 🖥️ Visual Walkthrough of the Web Management UI
│
├── 📊 Observability & Monitoring
│   ├── opentelemetry-guide.md          # 📈 Metrics (/metrics), Health (/health), & Tracing
│   └── tempo_traces.md                 # 🔍 Grafana Tempo & TraceQL Distributed Tracing
│
└── 📋 Validation & Audit Reports
    ├── release-1.0.0-audit-report.md   # 🏆 1.0.0 Codebase Audit & Readiness Report
    └── deployment-validation-report.md # 🧪 Multi-VM Validation (Ubuntu, Rocky Linux 10)
```

---

## 📑 Core Documentation Index

### 1. 🚀 Operations & Deployment
- **[Operator Installation Guide (A to Z)](OPERATOR_INSTALLATION_GUIDE.md)**  
  *The authoritative, beginner-friendly deployment guide.* Covers prerequisites, system sizing, network port allocations, automated Ansible on-VM deployments (Ubuntu/Debian/RHEL/Rocky/AlmaLinux), containerized Docker & Podman Compose stacks, unattended PostgreSQL 17 database provisioning, first-time admin account bootstrap, and smoke testing.
- **[FreePBX & Asterisk ARI Setup Guide](freepbx-asterisk-setup-guide.md)**  
  Step-by-step visual guide for configuring SIP/PJSIP Trunks, Custom Extensions, Asterisk REST Interface (ARI) users, WebSocket Stasis applications (`py-phone-caller`), and dialplans (`extensions_custom.conf`).
- **[VirtualBox Local Lab Setup Guide](virtualbox-setup.md)**  
  Instructions for setting up a local testing environment with isolated NAT Networks and Host-Only adapters for PBX and application virtual machines.
- **[1.0.0 Release Architecture & Hardening](1.0.0-release.md)**  
  Production hardening blueprint, network isolation principles, Caddy reverse-proxy gateway configuration, and future Apache APISIX integration roadmap.

---

### 2. 🏛️ Architecture & Technical Reference
- **[Architecture & Call Flows](architecture-and-call-flows.md)**  
  Comprehensive architecture guide detailing the 11 microservices stack, domain-driven data boundaries, Mermaid sequence diagrams for outbound calls, real-time DTMF acknowledgment ('4' key to ack, '5' key to repeat), exponential retry loops, multi-engine TTS synthesis, Twilio/Rust SMS dispatch, and Celery scheduling.
- **[Services and Endpoints Reference](services-and-endpoints.md)**  
  Exhaustive REST API reference covering all 11 microservices, exact port allocations (`8081` through `8087`, `5000`), request/response JSON schemas, query parameters, health checks (`/health`, `/healthz`, `/live`), and Prometheus metric endpoints (`/metrics`).
- **[UV Workspace & Packaging Guide](uv-migration-and-workspace-guide.md)**  
  Technical guide explaining the Python 3.14 multi-package `uv` workspace, unified `uv.lock` dependency locking, editable shared library linking (`py_phone_caller_utils`), wheel generation, and container build contexts.

---

### 3. 🖥️ Web Console & Operator Experience
- **[Web UI Operator Tour](web-ui-tour/README.md)**  
  Visual screenshot tour of the Flask Web Management UI: Dashboard, Managed Calls, PBX WebSocket Events, Scheduled Calls, Address Book & On-call Availability Calendars, User Management, and the Managed SMS table with CSV export.

---

### 4. 📊 Observability & Monitoring Integration
- **[OpenTelemetry & Observability Guide](opentelemetry-guide.md)**  
  Covers the dual-mode observability framework: Prometheus `/metrics` scraping, standardized `/health` probes, and distributed OpenTelemetry tracing (OTLP gRPC) across all HTTP, database, and background worker operations.
- **[Grafana Tempo Tracing Guide](tempo_traces.md)**  
  Guide to querying and visualizing distributed call lifecycle traces using Grafana Tempo and TraceQL syntax.
- **Monitoring Script Integrations**:
  - [Prometheus Alertmanager Webhook Guide](../src/caller_prometheus_webhook/README.md)
  - [Nagios Event Handler Call Script](../assets/scripts/nagios/README.md)
  - [Zabbix Alert Action Script](../assets/scripts/zabbix/README.md)

---

### 5. 📋 Reports & Audit Records
- **[1.0.0 Release Readiness & Codebase Audit Report](release-1.0.0-audit-report.md)**  
  Comprehensive technical audit covering code hygiene, security posture, offline/air-gapped asset verification, and automated test coverage.
- **[Multi-Environment Deployment Validation Report](deployment-validation-report.md)**  
  Real-world test results from validating Native Ansible Systemd and Docker/Podman Compose deployments across Ubuntu 26.04 and Rocky Linux 10 virtual machines with local OCI registry and PyPI mirror.

---

## 🎯 Quick Navigation by Role

| If you are... | Start here: |
| :--- | :--- |
| **A Sysadmin / SRE deploying for the first time** | ➡️ **[Operator Installation Guide (A to Z)](OPERATOR_INSTALLATION_GUIDE.md)** |
| **A Telephony / PBX Administrator** | ➡️ **[FreePBX & Asterisk ARI Setup Guide](freepbx-asterisk-setup-guide.md)** |
| **A Developer integrating with the REST API** | ➡️ **[Services and Endpoints Reference](services-and-endpoints.md)** |
| **A Software Engineer contributing code** | ➡️ **[UV Workspace & Migration Guide](uv-migration-and-workspace-guide.md)** |
| **An Operations Engineer setting up Monitoring** | ➡️ **[OpenTelemetry & Observability Guide](opentelemetry-guide.md)** |
| **A Security Auditor reviewing 1.0.0** | ➡️ **[1.0.0 Release Architecture & Hardening](1.0.0-release.md)** |

---

## 🔒 Security & Deployment Notice

> [!WARNING]
> **py-phone-caller** is designed to run exclusively within **trusted local area networks (LANs)** or isolated VLANs behind firewalls.
> 
> - **Never expose internal service ports (`8081`–`8087`) to the public Internet.**
> - Only the Web UI (`5000`) should be accessible to operators, ideally protected behind a reverse proxy (e.g. Caddy, Nginx) with TLS termination and authentication.
> - For full security recommendations, consult the [1.0.0 Release Hardening Document](1.0.0-release.md).
