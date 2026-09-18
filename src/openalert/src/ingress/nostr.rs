//! # Nostr Ingress Subscriber
//!
//! Subscribes to configured Nostr relays via WebSockets to ingest decentralized alerts.
//! Enforces NIP-40 expiration tags, alert TTL filtering, and prevents self-echo loops.

use crate::config::NostrConfig;
use crate::engine::AlertEngine;
use crate::error::Result;
use crate::models::{Alert, AlertSeverity, AlertSource, NostrEvent};
use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use std::time::Duration;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::protocol::Message;
use tracing::{error, info, warn};

/// Service managing persistent WebSocket subscriptions to configured Nostr relays.
pub struct NostrSubscriber {
    config: NostrConfig,
    engine: Arc<AlertEngine>,
}

impl NostrSubscriber {
    /// Creates a new subscriber instance referencing the given engine and configuration.
    pub fn new(config: NostrConfig, engine: Arc<AlertEngine>) -> Self {
        Self { config, engine }
    }

    /// Starts the background subscriber tasks.
    pub async fn start(self: Arc<Self>) -> Result<()> {
        self.run().await
    }

    /// Spawns background worker tasks connecting to each configured Nostr relay.
    pub async fn run(self: Arc<Self>) -> Result<()> {
        if !self.config.enable_subscriber {
            info!("Nostr subscriber is disabled in configuration");
            return Ok(());
        }

        for relay in &self.config.relays {
            let relay_url = relay.clone();
            let subscriber = self.clone();

            tokio::spawn(async move {
                subscriber.listen_relay_loop(relay_url).await;
            });
        }

        Ok(())
    }

    /// Continuous connection management loop with exponential/fixed backoff reconnection.
    async fn listen_relay_loop(&self, relay_url: String) {
        loop {
            info!("Connecting Nostr subscriber to [{}]...", relay_url);

            match connect_async(&relay_url).await {
                Ok((ws_stream, _)) => {
                    info!("✅ Subscribed to Nostr relay: {}", relay_url);
                    let (mut write, mut read) = ws_stream.split();

                    let now = chrono::Utc::now().timestamp() as u64;
                    let since_timestamp = now.saturating_sub(self.config.subscription_lookback_seconds);

                    let filter = serde_json::json!({
                        "kinds": self.config.subscription_filter_kinds,
                        "since": since_timestamp,
                        "limit": 50,
                    });

                    let sub_msg = serde_json::json!(["REQ", "openalert-ingress-sub", filter]);
                    if let Err(e) = write.send(Message::Text(sub_msg.to_string().into())).await {
                        warn!("Failed to send subscription filter to {}: {}", relay_url, e);
                    } else {
                        while let Some(msg) = read.next().await {
                            match msg {
                                Ok(Message::Text(text)) => {
                                    self.handle_relay_message(&text).await;
                                }
                                Ok(Message::Close(_)) => {
                                    warn!("Nostr relay {} closed connection", relay_url);
                                    break;
                                }
                                Err(e) => {
                                    warn!("Error reading from Nostr relay {}: {}", relay_url, e);
                                    break;
                                }
                                _ => {}
                            }
                        }
                    }
                }
                Err(e) => {
                    warn!(
                        "Failed to connect to Nostr relay {}: {}. Retrying in 5s...",
                        relay_url, e
                    );
                }
            }

            tokio::time::sleep(Duration::from_secs(5)).await;
        }
    }

    /// Deserializes incoming Nostr relay messages and dispatches EVENT payloads.
    async fn handle_relay_message(&self, raw: &str) {
        let Ok(value) = serde_json::from_str::<serde_json::Value>(raw) else {
            return;
        };

        let Some(arr) = value.as_array().filter(|a| a.len() >= 3 && a[0] == "EVENT") else {
            return;
        };

        if let Ok(event) = serde_json::from_value::<NostrEvent>(arr[2].clone()) {
            self.process_nostr_event(event).await;
        }
    }

    /// Extracts alert metadata and tags from a validated Nostr event, enforcing TTL and NIP-40 expiration.
    async fn process_nostr_event(&self, event: NostrEvent) {
        // 0. Drop self-published Nostr events (self-echo loop prevention)
        let my_pubkey = self.engine.nostr_publisher().public_key();
        if event.pubkey.eq_ignore_ascii_case(my_pubkey) {
            info!(
                "🔄 Ignoring self-published Nostr alert echo [{}] (author: {} matches daemon pubkey)",
                &event.id[..8.min(event.id.len())],
                &event.pubkey[..12.min(event.pubkey.len())]
            );
            return;
        }

        let now = chrono::Utc::now().timestamp();

        // 1. NIP-40: Check expiration tag
        for tag in &event.tags {
            if tag.len() >= 2 && tag[0] == "expiration"
                && let Ok(exp) = tag[1].parse::<i64>()
                && exp <= now {
                info!(
                    "⏳ Dropping expired Nostr alert [{}] (NIP-40 expired at {}, current time: {})",
                    &event.id[..8.min(event.id.len())],
                    exp,
                    now
                );
                return;
            }
        }

        // 2. Alert TTL: Check if event age exceeds configured TTL
        if self.config.alert_ttl_seconds > 0 {
            let event_created = event.created_at as i64;
            let age = now.saturating_sub(event_created);
            if age > self.config.alert_ttl_seconds as i64 {
                info!(
                    "⏳ Dropping stale Nostr alert [{}] (created {}s ago, exceeding TTL of {}s)",
                    &event.id[..8.min(event.id.len())],
                    age,
                    self.config.alert_ttl_seconds
                );
                return;
            }
        }

        let mut alert_id = event.id[..12.min(event.id.len())].to_string();
        let mut severity = AlertSeverity::Critical;
        let mut sender = event.pubkey.clone();

        for tag in &event.tags {
            if tag.len() >= 2 {
                match tag[0].as_str() {
                    "d" => alert_id = tag[1].clone(),
                    "severity" => {
                        severity = match tag[1].to_lowercase().as_str() {
                            "info" => AlertSeverity::Info,
                            "warning" => AlertSeverity::Warning,
                            _ => AlertSeverity::Critical,
                        }
                    }
                    "sender" => sender = tag[1].clone(),
                    _ => {}
                }
            }
        }

        let alert = Alert {
            alert_id,
            severity,
            summary: event.content.clone(),
            description: Some(event.content),
            source: AlertSource::Nostr,
            sender: Some(sender),
            node: None,
            starts_at: chrono::DateTime::from_timestamp(event.created_at as i64, 0)
                .unwrap_or_else(chrono::Utc::now),
            destinations: vec!["webhook".to_string()],
            origin_peer: None,
            hop: 3,
        };

        if let Err(err) = self.engine.route_alert(alert).await {
            error!("Failed to route alert from Nostr: {}", err);
        }
    }
}
