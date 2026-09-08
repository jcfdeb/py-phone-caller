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
//!                               | Alert Routing Engine  | <---> Deduplication Cache &
//!                               |                       |       Template Engine (Tera)
//!                               +-----------+-----------+
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
//! - [`engine`]: Central alert routing, deduplication cache, and dispatch pipeline.
//! - [`error`]: Unified error types and result aliases.
//! - [`ingress`]: Inbound alert listeners (HTTP REST API, Prometheus Alertmanager webhook, Nostr subscribers).
//! - [`egress`]: Outbound alert dispatchers (Prometheus webhook, Nostr broadcast, BitChat mesh).
//! - [`models`]: Canonical internal alert schema and network serialization models.
//! - [`templates`]: Jinja2/Tera template engine for dynamic HTTP webhook payload generation.

pub mod bitchat;
pub mod config;
pub mod egress;
pub mod engine;
pub mod error;
pub mod ingress;
pub mod models;
pub mod templates;

pub use bitchat::BitChatService;
pub use config::AppConfig;
pub use engine::AlertEngine;
pub use error::{OpenAlertError, Result};
