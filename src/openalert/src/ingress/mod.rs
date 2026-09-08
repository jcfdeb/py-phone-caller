//! # Alert Ingress Subsystem
//!
//! Exposes network and protocol listeners that ingest inbound alerts from HTTP REST clients,
//! Prometheus Alertmanager webhooks, and Nostr relays, translating them into canonical
//! internal [`Alert`](crate::models::Alert) structs.

pub mod nostr;
pub mod rest;

pub use nostr::NostrSubscriber;
pub use rest::RestServer;
