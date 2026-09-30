//! # Alert Egress Subsystem
//!
//! Provides outbound dispatch adapters for sending alerts to external destinations:
//! - [`PrometheusWebhookDispatcher`]: HTTP POST client targeting `py-phone-caller`.
//! - [`NostrPublisher`]: Schnorr-signed event publisher broadcasting to decentralized relays.
//! - [`BitChatEgress`]: Bluetooth Low Energy mesh broadcast handler.

pub mod bitchat;
pub mod nostr;
pub mod webhook;

pub use bitchat::BitChatEgress;
pub use nostr::NostrPublisher;
pub use webhook::PrometheusWebhookDispatcher;
