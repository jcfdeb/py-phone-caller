//! # OpenAlert Daemon (`openalertd`)
//!
//! `openalertd` is a resilient, low-latency alert aggregation and dispatch daemon written in Rust.
//! It functions as a central messaging hub connecting decentralized communication channels
//! (Nostr relays, BitChat Bluetooth Low Energy mesh networks) and standard HTTP REST / Prometheus Alertmanager
//! webhooks to the `py-phone-caller` Prometheus voice and SMS alert engine.
//!
//! ## Architecture Overview
//!
//! ```text
//!  +------------------------+  +-------------------------+  +--------------------------+
//!  | Prometheus Alertmgr    |  | Nostr Relays (NIP-01)   |  | BitChat BLE Mesh         |
//!  | Webhooks & REST Ingress|  | (WebSocket Subscriber)  |  | (GATT Mesh Receiver)     |
//!  +-----------+------------+  +------------+------------+  +------------+-------------+
//!              |                            |                            |
//!              +----------------------------+----------------------------+
//!                                           |
//!                                           v
//!                               +-----------------------+
//!                               | Ingress Subsystem     |
//!                               +-----------+-----------+
//!                                           |
//!                                           v
//!                               +-----------------------+
//!                               | Alert Routing Engine  | <---> Deduplication Cache,
//!                               |                       |       Storage (SQLite/RAM), &
//!                               +-----------+-----------+       Template Engine (Tera)
//!                                           |
//!                            +--------------+--------------+
//!                            |                             |
//!                            v                             v
//!               +-------------------------+   +----------------------------+
//!               | Nostr / BitChat Egress  |   | Prometheus Webhook Egress  |
//!               | (Mesh Peer Broadcasts)  |   | (py-phone-caller Dispatch) |
//!               +-------------------------+   +----------------------------+
//! ```
//!
//! ## Core Modules
//!
//! - [`bitchat`]: Native BlueZ Linux GATT server and BitChat BLE mesh binary protocol parser/encoder.
//! - [`config`]: Strongly-typed daemon configuration loader (TOML).
//! - [`crypto`]: Cryptographic primitives (NIP-04 ECDH + AES-256-CBC for 0xChat).
//! - [`engine`]: Central alert routing, deduplication cache, and dispatch pipeline.
//! - [`error`]: Unified error types and result aliases.
//! - [`ingress`]: Inbound alert listeners (HTTP REST API, Prometheus Alertmanager webhook, Nostr subscribers).
//! - [`egress`]: Outbound alert dispatchers (Prometheus webhook, Nostr broadcast, BitChat mesh).
//! - [`metrics`]: Prometheus and OpenTelemetry-aligned metrics exposition.
//! - [`models`]: Canonical internal alert schema and network serialization models.
//! - [`storage`]: Embedded SQLite storage with sliding-window retention, RAM fallback, and crash recovery.
//! - [`templates`]: Jinja2/Tera template engine for dynamic HTTP webhook payload generation.
//! - [`peering`]: Decentralized UDP peering and out-of-band failover backhaul.
//! - [`cli`]: Operational diagnostics and status inspection CLI.
//! - [`sms`]: Cellular GSM/LTE SMS gateway (serial AT modem ingress, egress, and persistence).

pub mod bitchat;
pub mod cli;
pub mod config;
pub mod crypto;
pub mod egress;
pub mod engine;
pub mod error;
pub mod ingress;
pub mod metrics;
pub mod nostr_relay;
pub mod models;
pub mod peering;
pub mod sms;
pub mod storage;
pub mod templates;

pub use bitchat::BitChatService;
pub use config::AppConfig;
pub use engine::AlertEngine;
pub use metrics::OpenAlertMetrics;
pub use sms::SmsService;
pub use storage::Storage;

pub use nostr_relay::EmbeddedNostrRelay;
