# OpenAlert: Nostr & Multi-Protocol Alerting Bridge

Development of OpenAlert is supported by a grant from the **Human Rights Foundation (HRF) Bitcoin Development Fund** ([View the Announcement](https://x.com/gladstein/status/2092304843037884677)).

OpenAlert is a decentralized alerting gateway designed to route critical system events across diverse transport layers. Originally conceived as a module for the `py-phone-caller` ecosystem, OpenAlert is architected as a standalone component that operates independently and integrates universally via standard alerting protocols.

---

## 1. Core Architecture

OpenAlert operates as a multi-protocol gateway, abstracting the transport layer of notifications to allow messages to flow fluidly between traditional IT infrastructure APIs and decentralized edge networks.

* **Universal Downstream Compatibility:** OpenAlert formats its outbound digital payloads using the industry-standard **Prometheus Alertmanager JSON schema**. This enables it to trigger `py-phone-caller` (which natively ingests Alertmanager webhooks) or seamlessly integrate with any other enterprise alerting and incident management system (e.g., Grafana, PagerDuty, or custom internal dashboards).
* **Standalone Capable:** OpenAlert's core daemon (`openalertd`, implemented in native Rust in `src/openalert`) runs entirely on its own as a protocol translator—bridging local monitoring stacks to global networks—without requiring local telephony hardware.

---

## 2. Supported Protocols & Data Flow

OpenAlert is fundamentally bidirectional, acting as both a listener and a broadcaster across three primary transport layers:

### REST, Nostr, and Alertmanager Interfaces
* **Inbound (Receive):** The gateway listens for incoming JSON payloads via standard REST webhooks (compatible with existing IT watchdogs). Simultaneously, it monitors the Nostr network via persistent WebSocket connections to a configured relay pool.
* **Outbound (Send):** Upon processing an incoming decentralized event (from Nostr or BitChat), the system standardizes the payload into a Prometheus Alertmanager webhook and POSTs it to a configured local or remote endpoint. Alternatively, when ingesting a local IT alert, it can cryptographically sign and broadcast the alert globally as a Nostr event.

### BitChat Bluetooth LE Mesh Implementation
To guarantee event delivery when standard internet routing (TCP/IP) fails, OpenAlert natively implements the BitChat protocol.
* **Offline-First Ad-Hoc Mesh:** Utilizes Bluetooth Low Energy (BLE) peripheral GATT services via Linux BlueZ D-Bus, bypassing ISPs, cellular networks, and centralized servers.
* **Noise XX End-to-End Encryption:** Direct private messages to `openalertd` are secured via the `Noise_XX_25519_ChaChaPoly_SHA256` pattern, providing mutual authentication, identity hiding, and forward secrecy.
* **1-on-1 Alert Ingress & Public Escalation:**
  - Emergency alerts sent via 1-on-1 encrypted private chat to `openalertd` are decrypted and acknowledged privately.
  - The daemon immediately escalates the alert to the **public BitChat mesh** (addressed to `[0xFF; 8]`), publishes it across **Nostr relays**, and dispatches it to **py-phone-caller**'s Prometheus webhook for automated telephony dispatch.
  - Public mesh broadcasts are filtered to prevent recursive alerting loops.

---

## 3. Quickstart & Building `openalertd`

The production daemon is located in [`src/openalert`](file:///home/jcf/Workspace/PyCharm/py-phone-caller_release-github/src/openalert):

```bash
cd src/openalert

# Build in release or dev mode
cargo build

# Run automated tests (unit + integration tests)
cargo test

# Launch openalertd with the default configuration
cargo run -- config/openalertd.toml
```