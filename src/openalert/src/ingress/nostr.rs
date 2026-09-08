//! # Nostr Ingress Subscriber
//!
//! Maintains persistent WebSocket connections to configured Nostr relays, subscribes to
//! specified event kinds (NIP-01), parses inbound alert events, and delivers them to the
//! routing engine.

use crate::config::NostrConfig;
use crate::engine::AlertEngine;
use crate::models::{Alert, AlertSeverity, AlertSource, NostrEvent};
use futures_util::{SinkExt, StreamExt};
use serde_json::json;
use std::sync::Arc;
use std::time::Duration;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::protocol::Message as WsMessage;
use tracing::{error, info, warn};

/// Background subscriber connecting to decentralized Nostr relays.
pub struct NostrSubscriber {
    config: NostrConfig,
    engine: Arc<AlertEngine>,
}

impl NostrSubscriber {
    /// Creates a new Nostr subscriber with the provided configuration and engine reference.
    pub fn new(config: NostrConfig, engine: Arc<AlertEngine>) -> Self {
        Self { config, engine }
    }

    /// Spawns asynchronous connection loops across all configured relay URLs.
    pub async fn start(self: Arc<Self>) {
        if !self.config.enable_subscriber {
            info!("Nostr subscriber is disabled in configuration.");
            return;
        }

        for relay in self.config.relays.clone() {
            let subscriber = self.clone();
            tokio::spawn(async move {
                subscriber.listen_relay_loop(relay).await;
            });
        }
    }

    /// Reconnecting event loop for a single Nostr relay WebSocket stream.
    async fn listen_relay_loop(&self, relay_url: String) {
        loop {
            info!("Connecting Nostr subscriber to [{}]...", relay_url);
            match connect_async(&relay_url).await {
                Ok((mut ws_stream, _)) => {
                    info!("✅ Subscribed to Nostr relay [{}]", relay_url);

                    let req_msg = json!([
                        "REQ",
                        "openalert-listener",
                        {
                            "kinds": self.config.subscription_filter_kinds,
                            "limit": 50
                        }
                    ]);

                    if let Err(err) = ws_stream
                        .send(WsMessage::Text(req_msg.to_string().into()))
                        .await
                    {
                        warn!("Failed to send REQ filter to [{}]: {}", relay_url, err);
                        tokio::time::sleep(Duration::from_secs(5)).await;
                        continue;
                    }

                    while let Some(msg_result) = ws_stream.next().await {
                        match msg_result {
                            Ok(WsMessage::Text(text)) => {
                                self.handle_relay_message(&text).await;
                            }
                            Ok(WsMessage::Close(_)) => {
                                warn!("Nostr relay [{}] closed connection.", relay_url);
                                break;
                            }
                            Err(err) => {
                                warn!("WebSocket error from [{}]: {}", relay_url, err);
                                break;
                            }
                            _ => {}
                        }
                    }
                }
                Err(err) => {
                    warn!(
                        "Failed to connect to Nostr relay [{}]: {}. Retrying in 5s...",
                        relay_url, err
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

    /// Extracts alert metadata and tags from a validated Nostr event.
    async fn process_nostr_event(&self, event: NostrEvent) {
        let mut alert_id = event.id[..12].to_string();
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
                            "critical" => AlertSeverity::Critical,
                            "emergency" => AlertSeverity::Emergency,
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
            starts_at: chrono::DateTime::from_timestamp(event.created_at, 0)
                .unwrap_or_else(chrono::Utc::now),
            destinations: vec!["webhook".to_string()],
        };

        if let Err(err) = self.engine.route_alert(alert).await {
            error!("Failed to route alert from Nostr: {}", err);
        }
    }
}
