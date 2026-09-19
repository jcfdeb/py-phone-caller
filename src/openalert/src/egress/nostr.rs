//! # Nostr Egress Publisher with NIP-20 Quorum Confirmation and Relay Health Scoring
//!
//! Generates NIP-01 compliant Nostr alert events, cryptographically signs them using BIP-340
//! Schnorr signatures over secp256k1, broadcasts them to configured relays, and verifies
//! NIP-20 command results (`["OK", event_id, true/false, message]`) to achieve M-of-N quorum.
//! Supports NIP-40 (Expiration Timestamp) to allow relays to purge expired alerts.

use crate::error::Result;
use crate::models::{Alert, NostrEvent};
use chrono::Utc;
use futures_util::{SinkExt, StreamExt};
use secp256k1::rand::rngs::OsRng;
use secp256k1::{Keypair, Secp256k1};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::RwLock;
use tokio::time::timeout;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::protocol::Message as WsMessage;
use tracing::{error, info, warn};

/// Parsed NIP-20 Command Result from a Nostr relay.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Nip20Result {
    /// 32-byte hex event ID confirmed by the relay.
    pub event_id: String,
    /// Boolean indicating whether the event was accepted and persisted.
    pub accepted: bool,
    /// Reason string supplied by the relay (e.g. prefix `duplicate:`, `blocked:`, `rate-limited:`).
    pub message: String,
}

/// Parses an inbound WebSocket text message into a [`Nip20Result`].
/// Format: `["OK", "<event_id>", <true|false>, "<message>"]`
pub fn parse_nip20_response(raw: &str) -> Option<Nip20Result> {
    let val: serde_json::Value = serde_json::from_str(raw).ok()?;
    let arr = val.as_array()?;
    if arr.len() >= 3 && arr[0].as_str() == Some("OK") {
        let event_id = arr[1].as_str()?.to_string();
        let accepted = arr[2].as_bool()?;
        let message = arr
            .get(3)
            .and_then(|m| m.as_str())
            .unwrap_or("")
            .to_string();
        Some(Nip20Result {
            event_id,
            accepted,
            message,
        })
    } else {
        None
    }
}

/// Dynamic health and performance statistics for an individual Nostr relay.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RelayHealth {
    /// WebSocket URI of the relay.
    pub url: String,
    /// Lifetime count of accepted publications.
    pub successes: u64,
    /// Lifetime count of failed attempts (network error, timeout, or NIP-20 rejection).
    pub failures: u64,
    /// Consecutive failures count.
    pub consecutive_failures: u32,
    /// Normalized health score between 0.0 (dead) and 1.0 (flawless).
    pub score: f32,
    /// Round-trip latency in milliseconds from last successful interaction.
    pub last_latency_ms: u64,
}

impl RelayHealth {
    /// Creates a new health tracker instance with neutral score.
    pub fn new(url: String) -> Self {
        Self {
            url,
            successes: 0,
            failures: 0,
            consecutive_failures: 0,
            score: 1.0,
            last_latency_ms: 0,
        }
    }

    /// Records a successful delivery and adjusts score.
    pub fn record_success(&mut self, latency_ms: u64) {
        self.successes = self.successes.saturating_add(1);
        self.consecutive_failures = 0;
        self.last_latency_ms = latency_ms;
        // Exponential moving average toward 1.0
        self.score = (self.score * 0.8) + 0.2;
    }

    /// Records a failed delivery attempt and penalizes score.
    pub fn record_failure(&mut self) {
        self.failures = self.failures.saturating_add(1);
        self.consecutive_failures = self.consecutive_failures.saturating_add(1);
        // Exponential decay toward 0.0
        self.score *= 0.6;
    }
}

/// Schnorr-signed event publisher broadcasting to decentralized Nostr relays with quorum verification.
pub struct NostrPublisher {
    keypair: Keypair,
    pubkey_hex: String,
    relays: Vec<String>,
    kind: u64,
    alert_ttl_seconds: u64,
    quorum_min_relays: usize,
    nip20_timeout: Duration,
    privacy: crate::config::NostrPrivacyConfig,
    health: Arc<RwLock<HashMap<String, RelayHealth>>>,
}

impl NostrPublisher {
    /// Generates an ephemeral cryptographic keypair and initializes the publisher.
    pub fn new(
        relays: Vec<String>,
        kind: u64,
        alert_ttl_seconds: u64,
        quorum_min_relays: usize,
        nip20_timeout_secs: u64,
        privacy: crate::config::NostrPrivacyConfig,
    ) -> Self {
        let secp = Secp256k1::new();
        let (secret_key, _) = secp.generate_keypair(&mut OsRng);
        let keypair = Keypair::from_secret_key(&secp, &secret_key);
        let (xonly, _) = keypair.x_only_public_key();
        let pubkey_hex = hex::encode(xonly.serialize());

        let mut health_map = HashMap::new();
        for r in &relays {
            health_map.insert(r.clone(), RelayHealth::new(r.clone()));
        }

        Self {
            keypair,
            pubkey_hex,
            relays,
            kind,
            alert_ttl_seconds,
            quorum_min_relays: quorum_min_relays.max(1),
            nip20_timeout: Duration::from_secs(nip20_timeout_secs.max(1)),
            privacy,
            health: Arc::new(RwLock::new(health_map)),
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

        let (content, mut tags) = if self.privacy.mode == crate::config::NostrPrivacyMode::Encrypted {
            let key = self.privacy.get_key_bytes().ok_or_else(|| {
                crate::error::OpenAlertError::Config(
                    "Nostr publisher set to encrypted mode but lacks a valid 32-byte shared_key".to_string(),
                )
            })?;
            let alert_json = serde_json::to_vec(alert)?;
            let encrypted_bytes = crate::peering::crypto::encrypt_datagram(&key, &alert_json)?;
            use base64::Engine;
            let b64 = base64::engine::general_purpose::STANDARD.encode(&encrypted_bytes);

            let enc_tags = vec![
                vec!["d".to_string(), alert.alert_id.clone()],
                vec!["t".to_string(), "openalert".to_string()],
                vec!["enc".to_string(), "xchacha20poly1305".to_string()],
                vec!["v".to_string(), "1".to_string()],
            ];
            (b64, enc_tags)
        } else {
            let pub_tags = vec![
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
            (alert.summary.clone(), pub_tags)
        };

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
            content
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
            content,
            sig: sig_hex,
        })
    }

    /// Returns current health snapshots of all configured relays.
    pub async fn get_relay_health(&self) -> Vec<RelayHealth> {
        let health = self.health.read().await;
        health.values().cloned().collect()
    }

    /// Publishes a signed Nostr event concurrently to all configured relays,
    /// parses NIP-20 command results, updates relay health metrics, and verifies quorum.
    pub async fn publish_to_relays(&self, event: &NostrEvent) -> usize {
        let event_json = match serde_json::to_string(&json!(["EVENT", event])) {
            Ok(j) => j,
            Err(err) => {
                error!("Failed to serialize Nostr EVENT: {}", err);
                return 0;
            }
        };

        let mut tasks = Vec::new();
        let short_id = event.id[..8.min(event.id.len())].to_string();

        for relay in &self.relays {
            let relay = relay.clone();
            let event_json = event_json.clone();
            let nip20_timeout = self.nip20_timeout;
            let target_event_id = event.id.clone();
            let short_id = short_id.clone();

            tasks.push(tokio::spawn(async move {
                let start = Instant::now();
                match timeout(nip20_timeout, connect_async(&relay)).await {
                    Ok(Ok((mut ws_stream, _))) => {
                        let msg = WsMessage::Text(event_json.into());
                        if let Err(e) = ws_stream.send(msg).await {
                            warn!("Failed to send EVENT to Nostr relay [{}]: {}", relay, e);
                            return (relay, false, 0);
                        }

                        // Wait for NIP-20 ["OK", event_id, true/false, message]
                        let mut confirmed = false;
                        while let Ok(Some(msg_res)) = timeout(nip20_timeout, ws_stream.next()).await {
                            if let Ok(WsMessage::Text(txt)) = msg_res
                                && let Some(nip20) = parse_nip20_response(&txt)
                                && nip20.event_id == target_event_id {
                                    if nip20.accepted {
                                        let latency = start.elapsed().as_millis() as u64;
                                        info!(
                                            "✅ [NIP-20 Quorum] Relay [{}] confirmed alert [{}] in {}ms",
                                            relay, short_id, latency
                                        );
                                        confirmed = true;
                                    } else {
                                        warn!(
                                            "🛑 [NIP-20 Quorum] Relay [{}] rejected alert [{}]: {}",
                                            relay, short_id, nip20.message
                                        );
                                    }
                                    break;
                            }
                        }

                        let latency = start.elapsed().as_millis() as u64;
                        let _ = ws_stream.close(None).await;
                        (relay, confirmed, latency)
                    }
                    Ok(Err(err)) => {
                        warn!("Failed to connect to Nostr relay [{}]: {}", relay, err);
                        (relay, false, 0)
                    }
                    Err(_) => {
                        warn!("Connection to Nostr relay [{}] timed out", relay);
                        (relay, false, 0)
                    }
                }
            }));
        }

        let mut successful_relays = 0;

        for task in tasks {
            if let Ok((relay, success, latency)) = task.await {
                let mut health_guard = self.health.write().await;
                if let Some(h) = health_guard.get_mut(&relay) {
                    if success {
                        h.record_success(latency);
                        successful_relays += 1;
                    } else {
                        h.record_failure();
                    }
                }
            }
        }

        let target_quorum = self.quorum_min_relays.min(self.relays.len());
        if successful_relays >= target_quorum {
            info!(
                "🎯 Nostr alert [{}] achieved delivery quorum ({}/{} confirmed, required: {})",
                short_id, successful_relays, self.relays.len(), target_quorum
            );
        } else {
            warn!(
                "⚠️ Nostr alert [{}] failed to achieve quorum ({}/{} confirmed, required: {})",
                short_id, successful_relays, self.relays.len(), target_quorum
            );
        }

        successful_relays
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_nip20_response() {
        // Valid accepted
        let raw_ok = r#"["OK", "b1a6447890abcdef", true, ""]"#;
        let res = parse_nip20_response(raw_ok).expect("Should parse OK");
        assert_eq!(res.event_id, "b1a6447890abcdef");
        assert!(res.accepted);
        assert_eq!(res.message, "");

        // Valid rejected with reason
        let raw_fail = r#"["OK", "b1a6447890abcdef", false, "blocked: rate-limited"]"#;
        let res_fail = parse_nip20_response(raw_fail).expect("Should parse rejection");
        assert_eq!(res_fail.event_id, "b1a6447890abcdef");
        assert!(!res_fail.accepted);
        assert_eq!(res_fail.message, "blocked: rate-limited");

        // Non-OK message
        let raw_eose = r#"["EOSE", "sub-1"]"#;
        assert!(parse_nip20_response(raw_eose).is_none());

        // Malformed
        assert!(parse_nip20_response("not json").is_none());
    }

    #[test]
    fn test_relay_health_scoring() {
        let mut health = RelayHealth::new("wss://relay.damus.io".to_string());
        assert_eq!(health.score, 1.0);

        // Success updates score and resets consecutive failures
        health.record_success(45);
        assert_eq!(health.successes, 1);
        assert_eq!(health.last_latency_ms, 45);
        assert_eq!(health.consecutive_failures, 0);

        // Failures decay score
        health.record_failure();
        health.record_failure();
        assert_eq!(health.failures, 2);
        assert_eq!(health.consecutive_failures, 2);
        assert!(health.score < 1.0);

        // Recovery raises score back
        health.record_success(30);
        assert_eq!(health.consecutive_failures, 0);
    }
}
