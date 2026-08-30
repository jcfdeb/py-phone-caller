# OpenAlert: Nostr & Multi-Protocol Alerting Bridge

Development of OpenAlert is supported by a grant from the **Human Rights Foundation (HRF) Bitcoin Development Fund** ([View the Announcement](https://x.com/gladstein/status/2092304843037884677)).

OpenAlert is a decentralized alerting gateway designed to route critical system events across diverse transport layers. Originally conceived as a module for the `py-phone-caller` ecosystem, OpenAlert is architected as a standalone component that operates independently and integrates universally via standard alerting protocols.

## 1. Core Architecture

OpenAlert operates as a multi-protocol gateway, abstracting the transport layer of notifications to allow messages to flow fluidly between traditional IT infrastructure APIs and decentralized edge networks.

* **Universal Downstream Compatibility:** OpenAlert formats its outbound digital payloads using the industry-standard **Prometheus Alertmanager JSON schema**. This enables it to trigger `py-phone-caller` (which natively ingests Alertmanager webhooks) or seamlessly integrate with any other enterprise alerting and incident management system (e.g., Grafana, PagerDuty, or custom internal dashboards).
* **Standalone Capable:** OpenAlert's core daemon (`openalertd`) runs entirely on its own as a protocol translator—bridging local monitoring stacks to global networks—without requiring local telephony hardware.

## 2. Supported Protocols & Data Flow

OpenAlert is fundamentally bidirectional, acting as both a listener and a broadcaster across three primary transport layers:

### REST, Nostr, and Alertmanager Interfaces
* **Inbound (Receive):** The gateway listens for incoming JSON payloads via standard REST webhooks (compatible with existing IT watchdogs). Simultaneously, it monitors the Nostr network via persistent WebSocket connections to a configured relay pool.
* **Outbound (Send):** Upon processing an incoming decentralized event (from Nostr or BitChat), the system standardizes the payload into a Prometheus Alertmanager webhook and POSTs it to a configured local or remote endpoint. Alternatively, when ingesting a local IT alert, it can cryptographically sign and broadcast the alert globally as a Nostr event.

### BitChat Mesh Implementation
To guarantee event delivery when standard internet routing (TCP/IP) fails, OpenAlert natively implements the BitChat protocol. 
* BitChat is a peer-to-peer messaging architecture utilizing Bluetooth Low Energy (BLE) mesh networks for local, offline communication. 
* By running the BitChat integration, OpenAlert nodes send and receive critical alerts over an ad-hoc local Bluetooth mesh network, bypassing centralized servers, ISPs, and cellular data networks. 
* Messages transmitted over the BitChat mesh use the Noise Protocol Framework for end-to-end encryption, ensuring alerts remain secure while routing across peer devices.

## 3. Deployment Use Cases

* **Universal Protocol Translator (Standalone):** Ingesting Nostr/BitChat events and translating them into standard Alertmanager webhooks to trigger existing enterprise incident response stacks, or converting local REST monitoring alerts into Nostr broadcast events.
* **Off-Grid Telephony Bridge:** Catching offline BitChat mesh packets or Nostr events, securely decrypting the target recipient, and routing the Alertmanager payload into `py-phone-caller` to dial a physical Voice/SMS payload via a GSM modem.