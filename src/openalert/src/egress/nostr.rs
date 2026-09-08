//! # Nostr Egress Publisher
//!
//! Generates NIP-01 compliant Nostr alert events, cryptographically signs them using BIP-340
//! Schnorr signatures over secp256k1, and broadcasts them to configured relays.

use crate::error::{OpenAlertError, Result};
use crate::models::{Alert, NostrEvent};
use chrono::Utc;
use futures_util::{SinkExt, StreamExt};
use secp256k1::rand::rngs::OsRng;
use secp256k1::{Keypair, Secp256k1};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::time::Duration;
use tokio::time::timeout;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::protocol::Message as WsMessage;
use tracing::{error, info, warn};

/// Schnorr-signed event publisher broadcasting to decentralized Nostr relays.
pub struct NostrPublisher {
    keypair: Keypair,
    pubkey_hex: String,
    relays: Vec<String>,
    kind: u64,
}

impl NostrPublisher {
    /// Generates an ephemeral cryptographic keypair and initializes the publisher.
    pub fn new(relays: Vec<String>, kind: u64) -> Self {
        let secp = Secp256k1::new();
        let (secret_key, _) = secp.generate_keypair(&mut OsRng);
        let keypair = Keypair::from_secret_key(&secp, &secret_key);
        let (xonly, _) = keypair.x_only_public_key();
        let pubkey_hex = hex::encode(xonly.serialize());

        Self {
            keypair,
            pubkey_hex,
            relays,
            kind,
        }
    }

    /// Returns the hex-encoded Schnorr public key of the publisher.
    pub fn public_key(&self) -> &str {
        &self.pubkey_hex
    }

    /// Constructs and signs a canonical NIP-01 event from an [`Alert`].
    pub fn sign_alert(&self, alert: &Alert) -> Result<NostrEvent> {
        let secp = Secp256k1::new();
        let created_at = Utc::now().timestamp();
        let tags = vec![
            vec!["d".to_string(), alert.alert_id.clone()],
            vec![
                "severity".to_string(),
                format!("{:?}", alert.severity).to_lowercase(),
            ],
            vec![
                "source".to_string(),
                format!("{:?}", alert.source).to_lowercase(),
            ],
            vec!["t".to_string(), "alert".to_string()],
        ];

        let serialized = serde_json::to_string(&json!([
            0,
            self.pubkey_hex,
            created_at,
            self.kind,
            tags,
            alert.summary
        ]))?;

        let mut hasher = Sha256::new();
        hasher.update(serialized.as_bytes());
        let id_bytes = hasher.finalize();
        let id_hex = hex::encode(id_bytes);

        let sig = secp.sign_schnorr(id_bytes.as_slice(), &self.keypair);
        let sig_hex = hex::encode(sig.as_ref());

        Ok(NostrEvent {
            id: id_hex,
            pubkey: self.pubkey_hex.clone(),
            created_at,
            kind: self.kind,
            tags,
            content: alert.summary.clone(),
            sig: sig_hex,
        })
    }

    /// Publishes a signed Nostr event concurrently to all configured relays.
    /// Returns the count of relays that confirmed acceptance.
    pub async fn publish_to_relays(&self, event: &NostrEvent) -> usize {
        let event_json = match serde_json::to_string(&json!(["EVENT", event])) {
            Ok(j) => j,
            Err(err) => {
                error!("Failed to serialize Nostr EVENT: {}", err);
                return 0;
            }
        };

        let mut successful_relays = 0;

        for relay_url in &self.relays {
            match self.send_to_single_relay(relay_url, &event_json).await {
                Ok(true) => {
                    info!(
                        "✅ Nostr relay [{}] accepted event [{}]",
                        relay_url,
                        &event.id[..8]
                    );
                    successful_relays += 1;
                }
                Ok(false) => {
                    warn!(
                        "⚠️ Nostr relay [{}] rejected event [{}]",
                        relay_url,
                        &event.id[..8]
                    );
                }
                Err(err) => {
                    warn!("❌ Could not send to Nostr relay [{}]: {}", relay_url, err);
                }
            }
        }

        successful_relays
    }

    /// Connects to a single relay and awaits the `["OK", <event_id>, true/false]` acknowledgment.
    async fn send_to_single_relay(&self, relay_url: &str, event_json: &str) -> Result<bool> {
        let (mut ws_stream, _) = timeout(Duration::from_secs(2), connect_async(relay_url))
            .await
            .map_err(|_| OpenAlertError::Config(format!("Timeout connecting to {}", relay_url)))?
            .map_err(OpenAlertError::from)?;

        ws_stream
            .send(WsMessage::Text(event_json.to_string().into()))
            .await?;

        if let Some(Ok(WsMessage::Text(text))) = ws_stream.next().await {
            let ack: serde_json::Value = serde_json::from_str(&text)?;
            if let Some(arr) = ack.as_array().filter(|a| a.len() >= 3 && a[0] == "OK") {
                return Ok(arr[2].as_bool().unwrap_or(false));
            }
        }

        Ok(false)
    }
}
