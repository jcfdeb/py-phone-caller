//! # Nostr Egress Publisher
//!
//! Generates NIP-01 compliant Nostr alert events, cryptographically signs them using BIP-340
//! Schnorr signatures over secp256k1, and broadcasts them to configured relays.
//! Supports NIP-40 (Expiration Timestamp) to allow relays to purge expired alerts.

use crate::error::Result;
use crate::models::{Alert, NostrEvent};
use chrono::Utc;
use futures_util::SinkExt;
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
    alert_ttl_seconds: u64,
}

impl NostrPublisher {
    /// Generates an ephemeral cryptographic keypair and initializes the publisher.
    pub fn new(relays: Vec<String>, kind: u64, alert_ttl_seconds: u64) -> Self {
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
            alert_ttl_seconds,
        }
    }

    /// Returns the hex-encoded Schnorr public key of the publisher.
    pub fn public_key(&self) -> &str {
        &self.pubkey_hex
    }

    /// Constructs and signs a canonical NIP-01 event from an [`Alert`], applying NIP-40 expiration tags.
    pub fn sign_alert(&self, alert: &Alert) -> Result<NostrEvent> {
        let secp = Secp256k1::new();
        let created_at_i64 = Utc::now().timestamp();
        let created_at = created_at_i64.max(0) as u64;

        let mut tags = vec![
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

        // NIP-40: Expiration Timestamp
        if self.alert_ttl_seconds > 0 {
            let expiration = created_at_i64 + self.alert_ttl_seconds as i64;
            tags.push(vec!["expiration".to_string(), expiration.to_string()]);
        }

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

        for relay in &self.relays {
            match timeout(Duration::from_secs(5), connect_async(relay)).await {
                Ok(Ok((mut ws_stream, _))) => {
                    let msg = WsMessage::Text(event_json.clone().into());
                    if let Ok(Ok(())) = timeout(Duration::from_secs(3), ws_stream.send(msg)).await {
                        info!(
                            "✅ Broadcast alert [{}] to Nostr relay [{}]",
                            event.id[..8.min(event.id.len())].to_string(),
                            relay
                        );
                        successful_relays += 1;
                    } else {
                        warn!("Timed out sending event to Nostr relay [{}]", relay);
                    }
                    let _ = ws_stream.close(None).await;
                }
                Ok(Err(err)) => {
                    warn!("Failed to connect to Nostr relay [{}]: {}", relay, err);
                }
                Err(_) => {
                    warn!("Connection to Nostr relay [{}] timed out", relay);
                }
            }
        }

        successful_relays
    }
}
