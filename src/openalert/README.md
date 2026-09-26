# OpenAlert Daemon (`openalertd`)
### Mission-Critical Decentralized Alert Routing Daemon, Mesh Gateway & Telephony Bridge

[![License](https://img.shields.io/badge/license-MIT%20%2F%20Apache--2.0-blue.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/rust-1.80%2B-orange.svg)](https://www.rust-lang.org)
[![HRF Grant](https://img.shields.io/badge/supported%20by-HRF%20Bitcoin%20Dev%20Fund-f7931a.svg)](https://x.com/gladstein/status/2092304843037884677)
[![Tests](https://img.shields.io/badge/tests-82%20passed-success.svg)]()
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

### 📱 0xChat Mobile Integration & Embedded Nostr Micro-Relay
* **Tactical In-Process Micro-Relay (`[nostr.relay_server]`):** Zero-external-dependency Nostr WebSocket server embedded directly in `openalertd` on port `8088` (NIP-01, NIP-11 discovery, NIP-20 acknowledgments, SQLite persistence).
* **Modern E2EE Onion Encryption:** Dual-mode encrypted DM engine wrapping notifications in NIP-59 / NIP-17 Gift Wraps (`Kind 1059` Wrap $\rightarrow$ `Kind 13` Seal $\rightarrow$ `Kind 14` Rumor) using NIP-44 v2 ChaCha20-Poly1305 authenticated encryption.
* **Interactive Tactical C2 & Thread-Aware Replies:** Real-time authenticated C2 parsing (`status`, `ping`, `mesh <msg>`, `sms <num> <msg>`, `ack`, `help`) with prefix flexibility (`!`, `/`, or bare verbs). Thread-aware parent resolution enables instant 1-tap `ack`/`ok` by replying directly to alert cards in 0xChat.
* **Multi-Bearer Cross-Bridging:** Seamless translation across 0xChat (Nostr) $\longleftrightarrow$ BitChat (BLE Mesh) $\longleftrightarrow$ Cellular (4G LTE SMS).
* **Dual SSL / TLS Strategy:** Production deployments delegate WSS termination to reverse proxies (Caddy, Nginx). For single-box air-gapped field kits, `openalertd` features battle-ready native TLS (`[nostr.relay_server.tls]`) via `tokio-rustls` for direct `wss://` sockets without external services.

### 📡 Decentralized & Hybrid Transport Transceivers
* **Nostr Pub/Sub Mesh:** Publishes cryptographically signed BIP-340 Schnorr events (Kind 30000 / Kind 1) across multi-relay pools with NIP-20 delivery confirmation and dynamic relay health scoring.
* **BitChat Bluetooth LE Mesh:** Native Linux BlueZ D-Bus integration for off-grid BLE communications with mobile devices. Employs `Noise_XX_25519_ChaChaPoly_SHA256` for mutual authentication, forward secrecy, and 1-on-1 private emergency escalation.
* **Heterogeneous Peering Links:** Point-to-point and multi-point node peering over LAN (Ethernet/WiFi), encrypted WireGuard VPNs, and physical sub-GHz LoRa serial transceivers (`/dev/ttyUSB*` / `/dev/ttyS*`).
* **Hardware Regulation:** Physical LoRa drivers implement SLIP byte framing, micro-datagram compaction, and strict ETSI EN 300 220 duty-cycle tracking (1.0% air-time pacing).

### 🧭 Dynamic Multi-Hop Routing & Loop Suppression
* **Distance-Vector Routing:** Computes shortest-path metrics across heterogeneous peer links (accounting for link RTT, packet loss, and physical bandwidth).
* **Split-Horizon Loop Suppression:** Suppresses packet reflection to origin interfaces, preventing routing loops and broadcast storms in cyclic mesh topologies.
* **Hop Limit Enforcement:** Enforces decremental hop counters to bound packet propagation across wide-area peer networks.

### 📱 Cellular GSM/LTE AT Modem SMS Subsystem
* **Direct Hardware Interfacing:** Async serial AT command engine (`tokio-serial`) communicating directly with standard GSM/LTE cellular modems (e.g. SIMCom SIM7600, SIM7100, Quectel) attached via USB (`/dev/ttyUSB*`).
* **Bidirectional Operation:** Transparently delivers critical alerts as outbound SMS to designated phone numbers and continuously polls inbound SMS from the SIM card to ingest and route alerts into the OpenAlert engine.
* **Strict UTF-8 & UCS-2 Transcoding:** Full bidirectional conversion between internal UTF-8 strings and modem UCS-2 hexadecimal / 7-bit GSM, ensuring international accents, diacritics, and emojis are transmitted without data corruption.
* **Zero-Crash Resilience:** Serial hardware disconnects, loose cables, missing ports, or SIM errors will NEVER panic or crash `openalertd`. The daemon logs rate-limited warnings and continues running unaffected.
* **Dynamic Hot-Reload & Web UI:** Recipients and authorized senders can be updated live via the embedded NOC Dashboard or REST API, immediately taking effect in RAM and permanently persisting to SQLite across daemon restarts.
* **Configurable SQLite TTL:** All incoming and outgoing SMS transactions are recorded in the embedded SQLite database with a configurable retention TTL in minutes (`0` = never deleted).

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
`openalertd` maintains a comprehensive automated test suite of 80 unit and integration tests covering all encryption routines, routing algorithms, codecs, and API endpoints:

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

### Nostr Group Privacy & Encrypted Mode (`[nostr.privacy]`)
By default, Nostr publishes cleartext alert summaries (`mode = "public"`). For high-security environments, critical infrastructure monitoring, or operating across untrusted public relays, switch to **Encrypted Mode**:

1. Generate a 256-bit cryptographic hex key:
   ```bash
   cargo run -- generate-key
   ```
2. Enable encryption in `openalertd.toml`:
   ```toml
   [nostr.privacy]
   mode = "encrypted"
   shared_key = "<64-hex-character-key>"
   authorized_senders = []
   allow_unencrypted_fallback = false
   ```
   *Result: Alerts are sealed using `XChaCha20-Poly1305` AEAD with 192-bit random nonces before publishing to Nostr. Public relays only see opaque base64 ciphertext and cannot read the alert summary, description, severity, or node attributes.*

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

* **Day / Night High-Contrast Theme Engine:** 1-click tactical toggle between **Midnight NOC** (deep dark obsidian glass with cyan/violet glowing indicators) and **Day Mode** (crisp high-contrast slate & titanium white with bold legible text designed for harsh outdoor sunlight on mobile field devices). Persisted seamlessly in `localStorage`.
* **Zero-Dependency Web Audio Emergency Alarms (Muted by Default):** Pure HTML5 Web Audio API synthesized acoustic cues without external sound files. Operators can toggle **Sound ON / Muted** with 1 click. Distinctive frequencies for emergency sirens (880Hz/587Hz alternating warble), warnings, and soft chimes.
* **Active Incident Strobe Banner & 1-Tap Acknowledge (ACK):** High-severity critical alarms drop an animated pulsating red banner directly below the header with an instant **"Acknowledge & Silence"** trigger that suppresses audio, logs the operator ACK, and notifies the mesh.
* **Live Status Hero Panels:** Node identifier, uptime counter, software version, real-time link states, and a visual **LoRa Duty-Cycle Progress Meter** tracking against the 1.0% ETSI EN 300 220 airtime ceiling.
* **Persistent Spool Backlog Monitor:** Displays real-time flash backlog count with an interactive **Purge** button to drop spooled test datagrams.
* **Peer Link & Circuit Breakers:** Interactive table displaying peer names, transport classifications, consecutive failures, backlog counts, and an interactive **Reset** button to force circuits back to `Closed`.
* **Dynamic Distance-Vector Routing Table:** Displays learned destination nodes, next-hop neighbors, path metrics, and hop counts.
* **Nostr Relays Quorum:** Displays active relay URLs, M-of-N consensus scores, latency figures, and healthy/degraded badges.
* **Live Event Feed:** Streaming alert timeline updated dynamically over Server-Sent Events (SSE).
* **Test Alert Dispatcher:** Built-in modal dialog to fire test emergency alerts across the mesh directly from the browser.
* **💻 Interactive Console & Live Log Terminal:** Dedicated streaming terminal with real-time log filtering (by text or level: `ALL`, `INFO`, `WARN`, `ERROR`), auto-scroll locking, 1-click clipboard export, and buffer clearance.
* **🛠️ Operational Tools Tab:** Full parity with CLI tools accessible directly in the browser:
  * **Nostr Keypair Generator:** BIP-340 Secp256k1 key generation (`npub`, `nsec`, 64-char hex) with 1-click clipboard copy.
  * **Nostr Key Converter & Deriver:** Auto-detects Bech32 or Hex, validates BIP-340 checksums, and derives public keys from `nsec`.
  * **SMS UCS-2 Hex Codec:** Bi-directional translator between UTF-8 (accents/emojis) and GSM modem UCS-2 Big-Endian hex.
  * **Cryptographic PSK & Password Hasher:** Random 256-bit PSK generator and instant SHA-256 password hasher for `[dashboard.auth]`.
* **⚙️ Configuration & Access Control Tab:**
  * **Nostr 0xChat Operators (ACL):** Visual management of C2 authorized operators and alert DM recipients. Automatically accepts `npub1...` or hex, converts format, and persists to the running config.
  * **Cellular SMS Senders & Recipients:** Interactive form to update authorized inbound numbers and outbound emergency contacts with instant SQLite persistence.
  * **In-Browser TOML Config Editor:** Complete `openalertd.toml` editor with syntax validation (`/api/v1/config/validate`), automatic timestamped backup generation (`.bak.<timestamp>`), and safe disk persistence.

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
| `generate-keypair` | `gen-keypair`, `gen-id` | Generates full Nostr Secp256k1 identity (`nsec`/`npub`/hex) with ready-to-paste TOML |
| `convert-key <key>` | `convert` | Converts Nostr Bech32 (`npub`/`nsec`) to hex or 32-byte hex to `npub`, auto-deriving pubkeys |
| `convert-sms <data>` | `sms-codec` | Bi-directional codec: encodes UTF-8 text to UCS-2 hex & decodes raw UCS-2 modem hex to UTF-8 |
| `generate-key` | `gen-key` | Generates a 256-bit random hex key for peering or Nostr group privacy |
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

### Operational Tools & Configuration Endpoints
* **`GET /api/v1/config`**  
  Returns the active runtime configuration (JSON object, raw TOML string, and file path).
* **`POST /api/v1/config`**  
  Validates syntax, writes an automatic timestamped backup (`.bak.<ts>`), and saves updated TOML to disk.
* **`POST /api/v1/config/validate`**  
  Dry-run syntax validation of arbitrary TOML configuration strings without modifying disk.
* **`POST /api/v1/nostr/oxchat`**  
  Updates `c2_authorized_operators` and `recipients` lists directly within the active config file.
* **`POST /api/v1/tools/generate-keypair`**  
  Generates a fresh Secp256k1 Nostr keypair (`npub`, `pub_hex`, `nsec`, `priv_hex`).
* **`POST /api/v1/tools/convert-key`**  
  Accepts `{ "key": "..." }`, detects Bech32 (`npub`/`nsec`) or hex, derives public keys, and returns all representations.
* **`POST /api/v1/tools/convert-sms`**  
  Accepts `{ "payload": "..." }`, auto-detects text vs UCS-2 hex, and returns translated output.
* **`POST /api/v1/tools/hash-password`**  
  Accepts `{ "password": "..." }` and returns the SHA-256 hash.
* **`POST /api/v1/tools/generate-key`**  
  Returns a cryptographically secure 256-bit random hex string.

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

### Cellular GSM / SMS Gateway
* **`GET /api/v1/sms/status`** (or `GET /api/v1/sms/config`)  
  Returns live modem connectivity, port path, baud rate, retention TTL, recipients list, authorized senders, and recent error notices.
* **`POST /api/v1/sms/config`**  
  Dynamically hot-reloads and persists alert recipients and authorized senders into SQLite:
  ```json
  {
    "recipients": ["+393349246425"],
    "authorized_senders": ["+393349246425"]
  }
  ```
* **`GET /api/v1/sms/history`**  
  Retrieves the most recent SMS transactions (inbound and outbound) from SQLite.
* **`POST /api/v1/sms/send`**  
  Manually dispatches an ad-hoc test SMS to a specified phone number:
  ```json
  {
    "phone_number": "+393349246425",
    "message": "Allarme test OpenAlertD: temperatura 42C 🚨"
  }
  ```

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
    ├── storage.rs                # Embedded SQLite engine, SMS journal & sliding-window retention
    ├── cli.rs                    # CLI query client, formatting & hash generators
    ├── sms/
    │   ├── mod.rs                # Cellular SMS service coordinator & background poller
    │   ├── modem.rs              # Asynchronous AT command driver (tokio-serial)
    │   └── codec.rs              # UTF-8 and UCS-2 / GSM7 bidirectional transcoding
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
