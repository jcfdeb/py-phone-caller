# OpenAlert Daemon (`openalertd`)
### Mission-Critical Decentralized Alert Routing Daemon, Mesh Gateway & Telephony Bridge

[![License](https://img.shields.io/badge/license-MIT%20%2F%20Apache--2.0-blue.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-1.80%2B-orange.svg)](https://www.rust-lang.org)
[![HRF Grant](https://img.shields.io/badge/supported%20by-HRF%20Bitcoin%20Dev%20Fund-f7931a.svg)](https://x.com/gladstein/status/2092304843037884677)
[![Tests](https://img.shields.io/badge/tests-52%20passed-success.svg)]()
[![Clippy](https://img.shields.io/badge/clippy-0%20warnings-brightgreen.svg)]()

> **OpenAlert** is a decentralized, resilient alerting daemon designed to bridge emergency notifications across isolated networks and physical air gaps. Developed with the support of a grant from the **[Human Rights Foundation (HRF) Bitcoin Development Fund](https://x.com/gladstein/status/2092304843037884677)**, `openalertd` ensures that life-safety alarms, disaster advisories, and critical infrastructure telemetries reach first responders even under total internet blackouts, grid collapses, or adversarial censorship.

---

## Table of Contents

1. [Architectural Overview](#1-architectural-overview)
2. [Core Capabilities](#2-core-capabilities)
3. [System Architecture Diagram](#3-system-architecture-diagram)
4. [Quickstart Guide](#4-quickstart-guide)
5. [Configuration & Profiles](#5-configuration--profiles)
   - [Turnkey Profiles Matrix](#turnkey-profiles-matrix)
   - [Disabling Absent Hardware](#disabling-absent-hardware)
   - [Dashboard Authentication](#dashboard-authentication)
6. [Web UI Mission Control](#6-web-ui-mission-control)
7. [CLI Utility Reference](#7-cli-utility-reference)
8. [REST API Specification](#8-rest-api-specification)
9. [Production Deployment & Hardening](#9-production-deployment--hardening)
10. [Developer Guide & Codebase Layout](#10-developer-guide--codebase-layout)

---

## 1. Architectural Overview

Traditional alerting stacks rely heavily on centralized SaaS endpoints, public cloud infrastructure, and uninterrupted TCP/IP backhauls. In crisis scenarios (severe weather, network partitioning, power outages, conflict zones), these brittle uplinks fail first.

`openalertd` resolves this single point of failure by operating as an **autonomous multi-protocol store-and-forward mesh router**:
* **Universal Translation:** Translates between IT monitoring watchdogs (Prometheus Alertmanager, Grafana, custom webhooks), decentralized relays (**Nostr**), peer-to-peer radio meshes (**LoRa**), and ad-hoc Bluetooth meshes (**BitChat**).
* **Zero External Dependencies:** Built in pure, memory-safe Rust with an embedded SQLite engine and an embedded HTML5/CSS3 real-time dashboard. No external web server, Node.js, database server, or broker required.
* **Telephony Integration:** Natively cascades alerts to `py-phone-caller`, dispatching automated voice calls and SMS alerts over SIP/Asterisk trunking.

---

## 2. Core Capabilities

### 📡 Decentralized & Hybrid Transport Transceivers
* **Nostr Pub/Sub Mesh:** Publishes cryptographically signed BIP-340 Schnorr events (Kind 30000 / Kind 1) across multi-relay pools with NIP-20 delivery confirmation and dynamic relay health scoring.
* **BitChat Bluetooth LE Mesh:** Native Linux BlueZ D-Bus integration for off-grid BLE communications with mobile devices. Employs `Noise_XX_25519_ChaChaPoly_SHA256` for mutual authentication, forward secrecy, and 1-on-1 private emergency escalation.
* **Heterogeneous Peering Links:** Point-to-point and multi-point node peering over LAN (Ethernet/WiFi), encrypted WireGuard VPNs, and physical sub-GHz LoRa serial transceivers (`/dev/ttyUSB*` / `/dev/ttyS*`).
* **Hardware Regulation:** Physical LoRa drivers implement SLIP byte framing, micro-datagram compaction, and strict ETSI EN 300 220 duty-cycle tracking (1.0% air-time pacing).

### 🧭 Dynamic Multi-Hop Routing & Loop Suppression
* **Distance-Vector Routing:** Computes shortest-path metrics across heterogeneous peer links (accounting for link RTT, packet loss, and physical bandwidth).
* **Split-Horizon Loop Suppression:** Suppresses packet reflection to origin interfaces, preventing routing loops and broadcast storms in cyclic mesh topologies.
* **Hop Limit Enforcement:** Enforces decremental hop counters to bound packet propagation across wide-area peer networks.

### 🛡️ Resilience, Storage & Ingress Hardening
* **Embedded SQLite Flash Spool:** Zero-loss persistence for outbound packets during network outages. Spooled items are automatically flushed upon link recovery.
* **Self-Healing Circuit Breakers:** Independent per-peer circuit breakers (Closed $\rightarrow$ Open $\rightarrow$ Half-Open) with exponential cooldown backoff prevent cascading buffer bloat when peers go offline.
* **Cryptographic Ingress Protection:** Supports HTTP Bearer tokens and HMAC-SHA256 signature verification with anti-replay timestamp validation windows.
* **Sliding-Window Retention:** Background database cleaner prunes historical alerts and spooled records to protect disk space on embedded flash drives.

### 🎛️ Observability & Control Plane
* **Real-Time Embedded Web Dashboard:** Single-page Mission Control served directly by the daemon (`/`) with live Server-Sent Events (SSE) streaming peer states, circuit breakers, routing tables, and spool backlogs every 2s.
* **Operator Actions:** Browser-based interactive buttons to manually reset tripped peer circuit breakers and purge persistent spool queues.
* **Dashboard Authentication (`[dashboard.auth]`):** Zero-friction unauthenticated default for local/trusted networks; cryptographically constant-time HTTP Basic and Bearer authentication backed by SHA-256 password hashing.
* **Prometheus Metrics (`/metrics`):** Production instrumentation tracking alert ingress/egress, delivery latency histograms, spool sizes, and peer drop counters.

---

## 3. System Architecture Diagram

```text
       ┌─────────────────────────────────────────────────────────────┐
       │                       Ingress Sources                       │
       │   Prometheus / Grafana / Webhooks / Nostr / BitChat BLE     │
       └──────────────────────────────┬──────────────────────────────┘
                                      │
                                      ▼
                      ┌──────────────────────────────┐
                      │   Bearer / HMAC Ingress Auth │
                      └───────────────┬──────────────┘
                                      │
                                      ▼
                      ┌──────────────────────────────┐
                      │   Deduplication Engine       │
                      │   (Memory Cache + SQLite)    │
                      └───────────────┬──────────────┘
                                      │
                                      ▼
                      ┌──────────────────────────────┐
                      │   Multi-Hop Alert Engine     │
                      │   - Distance-Vector Shortest │
                      │   - Split-Horizon Filter     │
                      │   - Template Rendering       │
                      └───────┬──────────────┬───────┘
                              │              │
              ┌───────────────┘              └───────────────┐
              ▼                                              ▼
┌──────────────────────────────┐               ┌──────────────────────────────┐
│       SQLite Flash Spool     │               │   Egress & Dispatch Drivers  │
│   (Store-and-Forward Buffer) │               │   - Nostr Relay Quorum (NIP20│
└─────────────┬────────────────┘               │   - BitChat BLE Broadcast    │
              │ (drain on reconnect)           │   - py-phone-caller Webhooks │
              ▼                                │   - Heterogeneous Peering    │
┌──────────────────────────────┐               └──────────────────────────────┘
│    Peer Circuit Breakers     │
│   (Closed/Open/Half-Open)    │
└─────────────┬────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Heterogeneous Physical Peering                        │
│   Local Ethernet (LAN)  │  WireGuard Tunnels (VPN)  │  LoRa RF (/dev/ttyUSB)│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Quickstart Guide

### Prerequisites
* **Operating System:** Linux (Kernel 5.4+, glibc 2.31+ or musl)
* **Rust Toolchain:** Stable 1.80 or newer (`rustup default stable`)
* **Bluetooth Dependencies (optional, only if BitChat BLE is used):** `libdbus-1-dev` / `dbus-devel`
* **SQLite:** Bundled automatically by `rusqlite` (no system installation needed)

### Building the Project

```bash
# Clone the repository and enter the crate directory
cd src/openalert

# Build in debug mode
cargo build

# Build optimized production binary
cargo build --release
```

### Running the Test Suite
`openalertd` maintains a comprehensive automated test suite of 52 unit and integration tests covering all encryption routines, routing algorithms, codecs, and API endpoints:

```bash
# Run all unit and integration tests
cargo test

# Verify zero compiler and clippy warnings
cargo clippy --all-targets
```

### Launching the Daemon

```bash
# Validate your configuration syntax before starting
cargo run -- check-config config/openalertd.toml

# Start the daemon in the foreground
cargo run -- config/openalertd.toml
```

Once running, access the **Embedded Mission Control Web UI** at:
👉 **`http://localhost:8090/`**

---

## 5. Configuration & Profiles

Configuration is managed via a single TOML file (`config/openalertd.toml`).

### Turnkey Profiles Matrix
`openalertd` provides 3 curated, ready-to-use profiles in `config/profiles/`:

| Profile | File Path | Hardware Requirements | Primary Role |
| :--- | :--- | :--- | :--- |
| **Edge Sensor** | `config/profiles/edge-sensor.toml` | LoRa Serial (`/dev/ttyUSB0`) + Bluetooth LE | Solar stations, remote sensors, battery IoT |
| **Mesh Repeater**| `config/profiles/mesh-repeater.toml` | LoRa Serial + Ethernet LAN | Mountain towers, hilltops, bridge between RF and IP |
| **Central Gateway**| `config/profiles/central-gateway.toml`| Internet / VPN + Server Host | NOC control room, Asterisk telephony, Nostr quorum |

To test or run a specific profile:
```bash
# Validate profile syntax
cargo run -- check-config config/profiles/edge-sensor.toml

# Boot with profile
cargo run -- config/profiles/central-gateway.toml
```

### Disabling Absent Hardware
If running on a system without Bluetooth or LoRa hardware, simply toggle their flags in your configuration:

1. **Disable Bluetooth (BitChat):**
   ```toml
   [bitchat]
   enabled = false
   ```
   *Result: Bypasses all BlueZ D-Bus initialization. The daemon will not query or fail on missing Bluetooth adapters.*

2. **Disable LoRa Hardware:**
   Set `link_type = "lan"` or `"vpn"` on configured peers instead of `"lora_serial"`, or disable peering entirely:
   ```toml
   [peering]
   enabled = false
   ```
   *Result: Prevents probing `/dev/ttyUSB*` serial devices while keeping local REST and Nostr active.*

### Dashboard Authentication
By default, dashboard access is open with zero setup friction. To require authentication:

1. Generate a SHA-256 password hash using the CLI:
   ```bash
   cargo run -- hash-password "MySecretPassword"
   ```
2. Enable authentication in `openalertd.toml`:
   ```toml
   [dashboard.auth]
   enabled = true
   username = "admin"
   password_hash = "7d3b0e14a29a0e6918804c8f5539d91f27e504c558c42ce0ffdb06b4b4594241"
   ```
3. When accessing `http://localhost:8090/`, your browser will prompt for credentials via standard HTTP Basic Auth. Passwords and tokens are verified in constant time (`subtle::ConstantTimeEq`).

---

## 6. Web UI Mission Control

`openalertd` serves an embedded, dependency-free single-page control plane directly on `/`:

* **Live Status Hero Panels:** Node identifier, uptime counter, software version, and real-time link states.
* **Persistent Spool Backlog Monitor:** Displays real-time flash backlog count with an interactive **Purge** button to drop spooled test datagrams.
* **Peer Link & Circuit Breakers:** Interactive table displaying peer names, transport classifications, consecutive failures, backlog counts, and an interactive **Reset** button to force circuits back to `Closed`.
* **Dynamic Distance-Vector Routing Table:** Displays learned destination nodes, next-hop neighbors, path metrics, and hop counts.
* **Nostr Relays Quorum:** Displays active relay URLs, M-of-N consensus scores, latency figures, and healthy/degraded badges.
* **Live Event Feed:** Streaming alert timeline updated dynamically over Server-Sent Events (SSE).
* **Test Alert Dispatcher:** Built-in modal dialog to fire test emergency alerts across the mesh directly from the browser.

---

## 7. CLI Utility Reference

`openalertd` provides operational command-line subcommands:

```bash
openalertd [COMMAND] [OPTIONS]
```

### Subcommands
| Command | Alias | Description |
| :--- | :--- | :--- |
| `check [config_path]` | `check-config` | Validates syntax, directories, templates, and consistency of configuration |
| `hash-password <secret>` | `hash` | Computes a SHA-256 hash formatted for `[dashboard.auth]` |
| `status [--url <api>]` | — | Queries live uptime, health status, and configured routes from running daemon |
| `peers [--url <api>]` | — | Queries live peering link states and circuit breaker counters |
| `spool [--url <api>]` | — | Queries persistent peering spool backlog count |
| `run [config_path]` | — | Starts the daemon in the foreground (default behavior) |
| `help` | `--help`, `-h` | Prints command usage and options |

---

## 8. REST API Specification

All HTTP endpoints bind to unprivileged ports ($\ge 1024$), default `8090`.

### Health & Metrics
* **`GET /health`**  
  Returns `{ "status": "ok", "version": "0.1.0", "uptime_seconds": 124 }`. Unauthenticated.
* **`GET /metrics`**  
  Prometheus exposition format (`openalert_alerts_received_total`, `openalert_alerts_routed_total`, `openalert_peering_spool_backlog`, etc.).

### Alert Ingestion
* **`POST /api/v1/alerts`**  
  Ingests an alert payload. Accepts standard Alertmanager schema or OpenAlert JSON schema:
  ```json
  {
    "alert_id": "disaster-fire-01",
    "severity": "critical",
    "summary": "Brush fire approaching perimeter",
    "description": "Evacuation corridor Bravo active",
    "destinations": ["webhook", "nostr", "peering", "bitchat"]
  }
  ```
  *Headers (optional, when configured):*  
  `Authorization: Bearer <token>`  
  `x-openalert-signature: <hmac-sha256-hex>`  
  `x-openalert-timestamp: <unix-timestamp>`  
  *Returns:* `202 Accepted`

### Operational Diagnostics & Actions
* **`GET /api/v1/status`**  
  Comprehensive operational state (storage type, active webhook strategies, relays count, peer list).
* **`GET /api/v1/peers`**  
  Active peering nodes, link types, circuit breaker states, and spool backlogs.
* **`GET /api/v1/spool`**  
  Number of spooled packets queued on disk.
* **`POST /api/v1/peers/{name}/reset`**  
  Manually resets peer circuit breaker to `Closed` state and clears failure counters.  
  *Returns:* `200 OK` `{ "status": "ok", "message": "Circuit breaker for peer '...' reset to Closed" }`
* **`POST /api/v1/spool/purge`**  
  Purges all unacknowledged stored packets from the SQLite spool database.  
  *Returns:* `200 OK` `{ "status": "ok", "purged_count": 5, "message": "Purged 5 spooled packet(s)" }`
* **`GET /api/v1/events/live`**  
  Server-Sent Events (SSE) telemetry stream emitting real-time diagnostics every 2 seconds.

---

## 9. Production Deployment & Hardening

The repository includes enterprise-grade deployment assets in `packaging/`:

### 1. Hardened Systemd Service
The systemd service (`packaging/systemd/openalertd.service`) enforces strict Linux kernel sandboxing:
* **Unprivileged User:** Runs as `openalert:openalert` (`NoNewPrivileges=yes`, `DynamicUser=no`).
* **Ambient Capabilities:** `CAP_NET_BIND_SERVICE` (port binding), `CAP_NET_RAW` / `CAP_NET_ADMIN` (Bluetooth HCI configuration without root).
* **Filesystem Protection:** `ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes`. Read-only root filesystem with write access granted only to `/var/lib/openalertd` and `/var/log/openalertd`.
* **Memory & Kernel Isolation:** `MemoryDenyWriteExecute=yes`, `ProtectKernelTunables=yes`, `ProtectControlGroups=yes`.

### 2. Standalone Release Bundle Builder
To generate a production-ready, stripped binary distribution tarball with SHA-256 checksums:
```bash
bash packaging/build_release_bundle.sh
```
Outputs `openalertd-v0.1.0-linux-<arch>.tar.gz` containing the binary, templates, turnkey profiles, systemd service, installer, and verification scripts.

### 3. Automated POSIX Installer
```bash
# Install binary, systemd unit, and configure permissions
sudo bash packaging/install.sh

# Run the 7-point post-installation verification audit
sudo bash packaging/verify_install.sh
```

---

## 10. Developer Guide & Codebase Layout

### Crate Structure
```text
src/openalert/
├── Cargo.toml                    # Crate manifest & dependencies
├── config/
│   ├── openalertd.toml           # Default full-featured configuration
│   └── profiles/                 # Turnkey profiles
│       ├── edge-sensor.toml      # LoRa / BitChat sensor profile
│       ├── mesh-repeater.toml    # Hilltop router / LoRa-to-LAN relay
│       └── central-gateway.toml  # Datacenter NOC gateway
├── templates/                    # Tera alert rendering templates
├── packaging/                    # Systemd units, installer, and bundle builder
├── tests/
│   └── integration_test.rs       # 28 end-to-end integration test scenarios
└── src/
    ├── main.rs                   # Entry point, CLI subcommands & signal handling
    ├── lib.rs                    # Public crate exports
    ├── config.rs                 # TOML configuration structs & validation
    ├── models.rs                 # Core alert domain types & severities
    ├── engine.rs                 # Alert routing core, deduplication & orchestration
    ├── storage.rs                # Embedded SQLite engine & sliding-window retention
    ├── cli.rs                    # CLI query client, formatting & hash generators
    ├── bitchat.rs                # BitChat BLE GATT peripheral & Noise XX engine
    ├── ingress/
    │   ├── rest.rs               # Axum REST API, Bearer & HMAC auth, operator endpoints
    │   ├── nostr.rs              # Nostr subscriber websocket client
    │   └── dashboard.rs          # Embedded Web UI HTML/JS & SSE stream
    ├── egress/
    │   ├── nostr.rs              # Nostr publisher, NIP-20 parser & relay health
    │   └── webhook.rs            # py-phone-caller Alertmanager webhook dispatcher
    └── peering/
        ├── mod.rs                # Peering service coordinator & dispatch
        ├── wire.rs               # Compact binary postcard wire protocol
        ├── crypto.rs             # XChaCha20-Poly1305 packet encryption
        ├── worker.rs             # Per-peer UDP transmission worker
        ├── lora.rs               # Physical LoRa serial driver & duty-cycle limiter
        ├── circuit_breaker.rs    # Link state machine & exponential cooldown
        └── routing.rs            # Multi-hop distance-vector shortest-path routing
```

### Critical Maintenance Invariants
* **BitChat Codec Invariance:** Do NOT alter the packet structures, Noise XX handshake state machine, Ed25519 signatures, or 256-byte payload bucket sizes in `src/bitchat.rs`. These guarantee binary wire compatibility with native BitChat mobile clients.
* **Timing-Safe Cryptography:** Any credential or secret comparison (Bearer tokens, HMAC signatures, dashboard passwords) MUST use constant-time comparison (`subtle::ConstantTimeEq`).
* **Unprivileged Ports:** The daemon default port MUST remain $\ge 1024$ (default `8090`).

---

## License

Dual-licensed under either:
* [MIT License](LICENSE-MIT)
* [Apache License, Version 2.0](LICENSE-APACHE)

at your option.

Development funded and supported by the **[Human Rights Foundation (HRF) Bitcoin Development Fund](https://hrf.org/)**.
