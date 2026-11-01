//! # Nostr Ingress Subscriber
//!
//! Subscribes to configured Nostr relays via WebSockets to ingest decentralized alerts.
//! Enforces NIP-40 expiration tags, alert TTL filtering, and prevents self-echo loops.
//! Implements periodic heartbeat pings and exponential backoff with jitter for network resilience.
//! Includes a 6-stage cryptographic NIP-57 Lightning Zap Receipt (`Kind 9735`) verifier.

use crate::config::{NostrConfig, NostrZapsConfig};
use crate::engine::AlertEngine;
use crate::error::Result;
use crate::models::{Alert, AlertSeverity, AlertSource, NostrEvent};
use futures_util::{SinkExt, StreamExt};
use rand::Rng;
use sha2::{Digest, Sha256};
use std::sync::Arc;
use std::time::Duration;
use subtle::ConstantTimeEq;
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::protocol::Message;
use tracing::{debug, error, info, warn};

const BECH32_CHARSET: &[u8; 32] = b"qpzry9x8gf2tvdw0s3jn54khce6mua7l";

/// Parsed summary of a BOLT-11 Lightning invoice.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Bolt11Summary {
    pub amount_msats: u64,
    pub amount_sats: u64,
    pub description_hash: Option<[u8; 32]>,
}

/// Verified NIP-57 Lightning Zap metadata extracted from a `Kind 9735` receipt and inner `Kind 9734` request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VerifiedZapAlert {
    pub receipt_id: String,
    pub zap_request_id: String,
    pub sender_pubkey: String,
    pub provider_pubkey: String,
    pub amount_sats: u64,
    pub amount_msats: u64,
    pub severity: AlertSeverity,
    pub message: String,
    pub custom_recipient_hex: Option<String>,
}

/// Computes the Bech32 polymod checksum over expanded HRP and 5-bit data words.
fn bech32_polymod(values: &[u8]) -> u32 {
    const GEN: [u32; 5] = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
    let mut chk: u32 = 1;
    for &v in values {
        let top = chk >> 25;
        chk = ((chk & 0x01ff_ffff) << 5) ^ (v as u32);
        for (i, &g) in GEN.iter().enumerate() {
            if ((top >> i) & 1) != 0 {
                chk ^= g;
            }
        }
    }
    chk
}

fn bech32_hrp_expand(hrp: &str) -> Vec<u8> {
    let mut out = Vec::with_capacity(hrp.len() * 2 + 1);
    for b in hrp.bytes() {
        out.push(b >> 5);
    }
    out.push(0);
    for b in hrp.bytes() {
        out.push(b & 0x1f);
    }
    out
}

fn bech32_verify_checksum(hrp: &str, data_words: &[u8]) -> bool {
    let mut combined = bech32_hrp_expand(hrp);
    combined.extend_from_slice(data_words);
    bech32_polymod(&combined) == 1
}

/// Converts 8-bit bytes into 5-bit Bech32 words (with zero-padding if `pad` is true).
pub fn bytes_to_u5(data: &[u8], pad: bool) -> Vec<u8> {
    let mut acc: u32 = 0;
    let mut bits: u32 = 0;
    let mut out = Vec::with_capacity((data.len() * 8).div_ceil(5));
    for &byte in data {
        acc = (acc << 8) | (byte as u32);
        bits += 8;
        while bits >= 5 {
            bits -= 5;
            out.push(((acc >> bits) & 0x1f) as u8);
        }
    }
    if pad && bits > 0 {
        out.push(((acc << (5 - bits)) & 0x1f) as u8);
    }
    out
}

/// Converts 5-bit Bech32 words into 8-bit bytes (ignoring up to 4 trailing zero padding bits).
fn u5_to_bytes32(words: &[u8]) -> Option<[u8; 32]> {
    if words.len() != 52 {
        return None;
    }
    let mut acc: u32 = 0;
    let mut bits: u32 = 0;
    let mut out = Vec::with_capacity(32);
    for &w in words {
        if w >= 32 {
            return None;
        }
        acc = (acc << 5) | (w as u32);
        bits += 5;
        while bits >= 8 {
            bits -= 8;
            out.push(((acc >> bits) & 0xff) as u8);
        }
    }
    if out.len() != 32 {
        return None;
    }
    let mut arr = [0u8; 32];
    arr.copy_from_slice(&out);
    Some(arr)
}

/// Parses and validates a BOLT-11 invoice string, extracting its amount and `h` (`description_hash`) tag.
pub fn parse_bolt11_invoice(raw_bolt11: &str) -> std::result::Result<Bolt11Summary, String> {
    let trimmed = raw_bolt11.trim();
    let stripped = trimmed
        .strip_prefix("lightning:")
        .or_else(|| trimmed.strip_prefix("LIGHTNING:"))
        .unwrap_or(trimmed)
        .trim();

    if stripped.is_empty() {
        return Err("Empty BOLT-11 invoice".to_string());
    }

    let has_lower = stripped.bytes().any(|b| b.is_ascii_lowercase());
    let has_upper = stripped.bytes().any(|b| b.is_ascii_uppercase());
    if has_lower && has_upper {
        return Err("Mixed-case BOLT-11 invoice is invalid".to_string());
    }

    let lower = stripped.to_ascii_lowercase();
    let Some(sep_idx) = lower.rfind('1') else {
        return Err("BOLT-11 invoice missing '1' separator".to_string());
    };

    let hrp = &lower[..sep_idx];
    let data_part = &lower[sep_idx + 1..];

    let amount_str = if let Some(rest) = hrp.strip_prefix("lnbcrt") {
        rest
    } else if let Some(rest) = hrp.strip_prefix("lntbs") {
        rest
    } else if let Some(rest) = hrp.strip_prefix("lntb") {
        rest
    } else if let Some(rest) = hrp.strip_prefix("lnbc") {
        rest
    } else {
        return Err(format!("Unsupported BOLT-11 currency prefix in HRP '{}'", hrp));
    };

    if amount_str.is_empty() {
        return Err("BOLT-11 invoice does not specify an amount".to_string());
    }

    let mut data_words = Vec::with_capacity(data_part.len());
    for ch in data_part.bytes() {
        let Some(idx) = BECH32_CHARSET.iter().position(|&c| c == ch) else {
            return Err(format!("Invalid Bech32 character '{}' in BOLT-11 data", ch as char));
        };
        data_words.push(idx as u8);
    }

    // 7 words timestamp + 104 words signature + 6 words checksum = 117 words minimum
    if data_words.len() < 117 {
        return Err(format!(
            "BOLT-11 data part too short ({} words, minimum 117)",
            data_words.len()
        ));
    }

    if !bech32_verify_checksum(hrp, &data_words) {
        return Err("BOLT-11 Bech32 checksum verification failed".to_string());
    }

    let (digits_str, multiplier) = match amount_str.chars().last() {
        Some(c @ ('m' | 'u' | 'n' | 'p')) => (&amount_str[..amount_str.len() - 1], Some(c)),
        _ => (amount_str, None),
    };

    let amount_num: u64 = digits_str
        .parse()
        .map_err(|_| format!("Invalid numeric amount '{}' in BOLT-11 HRP", digits_str))?;

    let amount_msats: u64 = match multiplier {
        None => amount_num
            .checked_mul(100_000_000_000)
            .ok_or_else(|| "BOLT-11 BTC amount overflow".to_string())?,
        Some('m') => amount_num
            .checked_mul(100_000_000)
            .ok_or_else(|| "BOLT-11 mBTC amount overflow".to_string())?,
        Some('u') => amount_num
            .checked_mul(100_000)
            .ok_or_else(|| "BOLT-11 uBTC amount overflow".to_string())?,
        Some('n') => amount_num
            .checked_mul(100)
            .ok_or_else(|| "BOLT-11 nBTC amount overflow".to_string())?,
        Some('p') => {
            if amount_num % 10 != 0 {
                return Err("Sub-millisatoshi pBTC amount is not divisible by 10".to_string());
            }
            amount_num / 10
        }
        Some(_) => unreachable!(),
    };

    let amount_sats = amount_msats / 1000;

    // Parse tagged fields between word 7 and word (len - 110)
    let tags_end = data_words.len() - 110;
    let mut pos = 7;
    let mut description_hash: Option<[u8; 32]> = None;

    while pos + 3 <= tags_end {
        let tag_code = data_words[pos];
        let data_len = ((data_words[pos + 1] as usize) << 5) | (data_words[pos + 2] as usize);
        pos += 3;
        if pos + data_len > tags_end {
            return Err("Malformed BOLT-11 tagged field length exceeds payload boundary".to_string());
        }
        let field_words = &data_words[pos..pos + data_len];
        pos += data_len;

        // Tag 'h' has Bech32 index 23 and length 52 words (256 bits)
        if tag_code == 23 && data_len == 52 {
            description_hash = u5_to_bytes32(field_words);
        }
    }

    Ok(Bolt11Summary {
        amount_msats,
        amount_sats,
        description_hash,
    })
}

/// Encodes a valid BOLT-11 invoice string with the given satoshi amount and 32-byte `description_hash` (`h` tag).
/// Used by local mock LNURLp test servers and unit/integration tests.
pub fn encode_bolt11_with_description_hash(amount_sats: u64, description_hash: &[u8; 32]) -> String {
    // 1 sat = 10 nBTC
    let amount_nbtc = amount_sats.saturating_mul(10);
    let hrp = format!("lnbc{}n", amount_nbtc);

    let mut words: Vec<u8> = Vec::new();
    // 35-bit timestamp (7 words)
    let ts = crate::time_sync::now_utc_secs().max(0) as u64;
    for shift in (0..7).rev() {
        words.push(((ts >> (shift * 5)) & 0x1f) as u8);
    }

    // Tagged field 'h' (code 23), length 52 (1 * 32 + 20)
    words.push(23);
    words.push(1);
    words.push(20);
    words.extend_from_slice(&bytes_to_u5(description_hash, true));

    // 104 words dummy signature (65 bytes)
    words.extend(std::iter::repeat_n(0u8, 104));

    // Compute 6-word Bech32 checksum
    let mut chk_input = bech32_hrp_expand(&hrp);
    chk_input.extend_from_slice(&words);
    chk_input.extend_from_slice(&[0, 0, 0, 0, 0, 0]);
    let polymod = bech32_polymod(&chk_input) ^ 1;
    for i in 0..6 {
        words.push(((polymod >> (5 * (5 - i))) & 0x1f) as u8);
    }

    let mut out = String::with_capacity(hrp.len() + 1 + words.len());
    out.push_str(&hrp);
    out.push('1');
    for w in words {
        out.push(BECH32_CHARSET[w as usize] as char);
    }
    out
}

/// Verifies the NIP-01 Event ID (SHA-256) and BIP-340 Schnorr signature of a [`NostrEvent`].
pub fn verify_nostr_event_signature(event: &NostrEvent) -> bool {
    let Ok(serialized) = serde_json::to_string(&serde_json::json!([
        0,
        event.pubkey,
        event.created_at,
        event.kind,
        event.tags,
        event.content
    ])) else {
        return false;
    };

    let expected_id_bytes = Sha256::digest(serialized.as_bytes());
    let expected_id_hex = hex::encode(expected_id_bytes);
    if !expected_id_hex.eq_ignore_ascii_case(event.id.trim()) {
        return false;
    }

    let Ok(pubkey_bytes) = hex::decode(event.pubkey.trim()) else {
        return false;
    };
    if pubkey_bytes.len() != 32 {
        return false;
    }
    let Ok(xonly) = secp256k1::XOnlyPublicKey::from_slice(&pubkey_bytes) else {
        return false;
    };

    let Ok(sig_bytes) = hex::decode(event.sig.trim()) else {
        return false;
    };
    let Ok(sig) = secp256k1::schnorr::Signature::from_slice(&sig_bytes) else {
        return false;
    };

    let secp = secp256k1::Secp256k1::verification_only();
    secp.verify_schnorr(&sig, expected_id_bytes.as_slice(), &xonly)
        .is_ok()
}

/// Executes Stages 2 through 6 of the NIP-57 `Kind 9735` Zap Receipt verification pipeline.
pub fn verify_and_extract_nip57_zap(
    event: &NostrEvent,
    zaps_cfg: &NostrZapsConfig,
    fallback_target_pubkey: &str,
) -> std::result::Result<VerifiedZapAlert, String> {
    if event.kind != 9735 {
        return Err(format!("Expected Kind 9735 Zap Receipt, got Kind {}", event.kind));
    }

    // Stage 2: Outer Kind 9735 Schnorr Signature & Provider Allowlist
    if !verify_nostr_event_signature(event) {
        return Err("Outer Kind 9735 Zap Receipt failed BIP-340 Schnorr signature verification".to_string());
    }
    if !zaps_cfg.is_provider_authorized(&event.pubkey) {
        return Err(format!(
            "Outer Kind 9735 signer '{}' is not in trusted_provider_pubkeys",
            event.pubkey
        ));
    }

    // Stage 3: Inner Kind 9734 Zap Request Extraction & Signature Verification
    let Some(description_json) = event
        .tags
        .iter()
        .find(|t| t.len() >= 2 && t[0] == "description")
        .map(|t| t[1].as_str())
    else {
        return Err("Kind 9735 receipt missing required 'description' tag".to_string());
    };

    let inner_req: NostrEvent = serde_json::from_str(description_json)
        .map_err(|e| format!("Kind 9735 'description' tag is not a valid NostrEvent JSON: {}", e))?;

    if inner_req.kind != 9734 {
        return Err(format!(
            "Inner Zap Request in 'description' tag must be Kind 9734 (got Kind {})",
            inner_req.kind
        ));
    }
    if !verify_nostr_event_signature(&inner_req) {
        return Err("Inner Kind 9734 Zap Request failed BIP-340 Schnorr signature verification".to_string());
    }

    // Stage 4: Target Recipient Public Key Match (`p` tag on both Kind 9735 and Kind 9734)
    let target_pubkey = zaps_cfg.resolved_target_pubkey(fallback_target_pubkey);
    let outer_p_matches = event
        .tags
        .iter()
        .any(|t| t.len() >= 2 && t[0] == "p" && t[1].trim().eq_ignore_ascii_case(&target_pubkey));
    if !outer_p_matches {
        return Err(format!(
            "Kind 9735 receipt 'p' tag does not match target pubkey '{}'",
            target_pubkey
        ));
    }

    let inner_p_matches = inner_req
        .tags
        .iter()
        .any(|t| t.len() >= 2 && t[0] == "p" && t[1].trim().eq_ignore_ascii_case(&target_pubkey));
    if !inner_p_matches {
        return Err(format!(
            "Inner Kind 9734 request 'p' tag does not match target pubkey '{}'",
            target_pubkey
        ));
    }

    // Stage 5: BOLT-11 Invoice Amount & description_hash Verification
    let Some(bolt11_str) = event
        .tags
        .iter()
        .find(|t| t.len() >= 2 && t[0] == "bolt11")
        .map(|t| t[1].as_str())
    else {
        return Err("Kind 9735 receipt missing required 'bolt11' tag".to_string());
    };

    let bolt11 = parse_bolt11_invoice(bolt11_str)?;
    let Some(invoice_desc_hash) = bolt11.description_hash else {
        return Err("BOLT-11 invoice missing required 'h' (description_hash) tag".to_string());
    };

    let expected_desc_hash: [u8; 32] = Sha256::digest(description_json.as_bytes()).into();
    let hash_matches: bool = invoice_desc_hash.ct_eq(&expected_desc_hash).into();
    if !hash_matches {
        return Err("BOLT-11 'description_hash' ('h' tag) does not match SHA-256 of Kind 9734 description JSON".to_string());
    }

    // Optional NIP-57 consistency check: if Kind 9734 specifies ["amount", "<msats>"], ensure BOLT-11 amount >= requested amount
    if let Some(req_msats) = inner_req
        .tags
        .iter()
        .find(|t| t.len() >= 2 && t[0] == "amount")
        .and_then(|t| t[1].trim().parse::<u64>().ok())
        && bolt11.amount_msats < req_msats
    {
        return Err(format!(
            "BOLT-11 invoice amount ({} msats) is less than Kind 9734 requested amount ({} msats)",
            bolt11.amount_msats, req_msats
        ));
    }

    // Stage 6: Tiered Satoshi Anti-Spam & Severity Escalation
    let Some(severity) = zaps_cfg.classify_severity(bolt11.amount_sats) else {
        return Err(format!(
            "Zap amount ({} sats) is below minimum anti-spam threshold ({} sats)",
            bolt11.amount_sats, zaps_cfg.min_sats_warning
        ));
    };

    let custom_recipient_hex = inner_req
        .tags
        .iter()
        .find(|t| t.len() >= 2 && t[0] == "recipient_npub")
        .and_then(|t| NostrZapsConfig::normalize_pubkey_hex(&t[1]));

    let clean_msg = inner_req.content.trim();
    let message = if clean_msg.is_empty() {
        format!("⚡ Verified Lightning Zap ({} sats)", bolt11.amount_sats)
    } else {
        clean_msg.to_string()
    };

    Ok(VerifiedZapAlert {
        receipt_id: event.id.clone(),
        zap_request_id: inner_req.id,
        sender_pubkey: inner_req.pubkey,
        provider_pubkey: event.pubkey.clone(),
        amount_sats: bolt11.amount_sats,
        amount_msats: bolt11.amount_msats,
        severity,
        message,
        custom_recipient_hex,
    })
}

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
                subscriber.listen_relay_loop(relay_url, false).await;
            });
        }

        if self.config.zaps.enabled {
            for pub_zap_relay in ["wss://nos.lol", "wss://relay.primal.net"] {
                if !self.config.relays.iter().any(|r| r == pub_zap_relay) {
                    let relay_url = pub_zap_relay.to_string();
                    let subscriber = self.clone();
                    tokio::spawn(async move {
                        subscriber.listen_relay_loop(relay_url, true).await;
                    });
                }
            }
        }

        Ok(())
    }

    /// Continuous connection management loop with exponential/jittered backoff reconnection and ping/pong heartbeats.
    async fn listen_relay_loop(&self, relay_url: String, zaps_only: bool) {
        let mut reconnect_attempt: u32 = 0;

        loop {
            info!("Connecting Nostr subscriber to [{}]...", relay_url);

            match connect_async(&relay_url).await {
                Ok((ws_stream, _)) => {
                    info!("✅ Subscribed to Nostr relay: {}", relay_url);
                    let (mut write, mut read) = ws_stream.split();

                    let now = chrono::Utc::now().timestamp() as u64;
                    let since_timestamp =
                        now.saturating_sub(self.config.subscription_lookback_seconds);

                    let mut req_array = vec![
                        serde_json::Value::String("REQ".to_string()),
                        serde_json::Value::String("openalert-ingress-sub".to_string()),
                    ];

                    if !zaps_only {
                        let mut kinds: Vec<u64> = self
                            .config
                            .subscription_filter_kinds
                            .iter()
                            .copied()
                            .filter(|&k| k != 9735)
                            .collect();
                        if kinds.is_empty() && !self.config.zaps.enabled {
                            kinds.push(self.config.kind);
                        }
                        if self.config.oxchat.enabled {
                            if !kinds.contains(&4) {
                                kinds.push(4);
                            }
                            if !kinds.contains(&1) {
                                kinds.push(1);
                            }
                            if !kinds.contains(&1059) {
                                kinds.push(1059);
                            }
                        }
                        if !kinds.is_empty() {
                            let filter = serde_json::json!({
                                "kinds": kinds,
                                "since": since_timestamp,
                                "limit": 50,
                            });
                            req_array.push(filter);
                        }
                    }

                    // NIP-59 Gift Wraps require dedicated filter without narrow 'since' due to intentional timestamp perturbation
                    if !zaps_only && self.config.oxchat.enabled {
                        let my_pubkey = self.engine.nostr_publisher().public_key();
                        let gift_wrap_filter = serde_json::json!({
                            "kinds": [1059],
                            "#p": [my_pubkey],
                            "limit": 50,
                        });
                        req_array.push(gift_wrap_filter);
                    }

                    // NIP-57 Zap Receipts targeted to this node's pubkey
                    if self.config.zaps.enabled {
                        let my_pubkey = self.engine.nostr_publisher().public_key();
                        let target_pk = self.config.zaps.resolved_target_pubkey(my_pubkey);
                        let zap_filter = serde_json::json!({
                            "kinds": [9735],
                            "#p": [target_pk],
                            "since": since_timestamp,
                            "limit": 50,
                        });
                        req_array.push(zap_filter);
                    }

                    let sub_msg = serde_json::Value::Array(req_array);
                    if let Err(e) = write.send(Message::Text(sub_msg.to_string().into())).await {
                        warn!("Failed to send subscription filter to {}: {}", relay_url, e);
                    } else {
                        // Connection established and subscribed: reset reconnect backoff
                        reconnect_attempt = 0;

                        let mut ping_interval = tokio::time::interval(Duration::from_secs(30));
                        ping_interval
                            .set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);

                        loop {
                            tokio::select! {
                                _ = ping_interval.tick() => {
                                    if let Err(e) = write.send(Message::Ping(vec![0x4f, 0x41].into())).await {
                                        warn!("Heartbeat ping failed to Nostr relay {}: {}", relay_url, e);
                                        break;
                                    }
                                }
                                maybe_msg = read.next() => {
                                    match maybe_msg {
                                        Some(Ok(Message::Text(text))) => {
                                            self.handle_relay_message(&text).await;
                                        }
                                        Some(Ok(Message::Ping(payload))) => {
                                            let _ = write.send(Message::Pong(payload)).await;
                                        }
                                        Some(Ok(Message::Pong(_))) => {
                                            // Heartbeat acknowledged by relay
                                        }
                                        Some(Ok(Message::Close(_))) => {
                                            warn!("Nostr relay {} closed connection", relay_url);
                                            break;
                                        }
                                        Some(Err(e)) => {
                                            warn!("Error reading from Nostr relay {}: {}", relay_url, e);
                                            break;
                                        }
                                        None => {
                                            warn!("Nostr relay {} connection stream closed", relay_url);
                                            break;
                                        }
                                        _ => {}
                                    }
                                }
                            }
                        }
                    }
                }
                Err(e) => {
                    warn!("Failed to connect to Nostr relay {}: {}", relay_url, e);
                }
            }

            // Exponential backoff with random jitter (2s, 4s, 8s, 16s, ... up to 60s max)
            let base_delay = std::cmp::min(60, 2u64.saturating_pow(reconnect_attempt.min(6)));
            let jitter: u64 = if base_delay > 2 {
                rand::rng().random_range(0..=(base_delay / 5).max(1))
            } else {
                0
            };
            let sleep_secs = base_delay + jitter;
            warn!(
                "Reconnecting to Nostr relay {} in {}s (attempt {})...",
                relay_url,
                sleep_secs,
                reconnect_attempt + 1
            );
            reconnect_attempt = reconnect_attempt.saturating_add(1);
            tokio::time::sleep(Duration::from_secs(sleep_secs)).await;
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
    pub async fn process_nostr_event(&self, event: NostrEvent) {
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
            if tag.len() >= 2
                && tag[0] == "expiration"
                && let Ok(exp) = tag[1].parse::<i64>()
                && exp <= now
            {
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
        // NIP-59 Gift Wrap events deliberately randomize created_at up to 2 days into the past to prevent timing analysis
        if event.kind != 1059 && self.config.alert_ttl_seconds > 0 {
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

        // 2b. Handle NIP-57 Lightning Zap Receipts (Kind 9735)
        // Strictly isolated to Nostr / Embedded Relay / 0xChat egress (NEVER routes to telephony, SMS, BLE, or LoRa).
        if event.kind == 9735 {
            if !self.config.zaps.enabled {
                debug!("Ignoring Kind 9735 Zap Receipt because [nostr.zaps] is disabled");
                return;
            }

            // Stage 1: Deduplication
            if self
                .engine
                .is_duplicate_and_record(&format!("nostr-zap:{}", event.id))
                .await
            {
                debug!(
                    "🔄 Dropping duplicate NIP-57 Zap Receipt [{}]",
                    &event.id[..8.min(event.id.len())]
                );
                return;
            }

            // Stages 2–6: Cryptographic verification & threshold classification
            let verified = match verify_and_extract_nip57_zap(&event, &self.config.zaps, my_pubkey) {
                Ok(v) => v,
                Err(reason) => {
                    warn!(
                        "🛑 Rejected NIP-57 Kind 9735 Zap Receipt [{}]: {}",
                        &event.id[..8.min(event.id.len())],
                        reason
                    );
                    return;
                }
            };

            info!(
                "⚡ [NIP-57 Zap Verified] Receipt [{}] ({} sats -> {:?}) from [{}]: \"{}\"",
                &verified.receipt_id[..8.min(verified.receipt_id.len())],
                verified.amount_sats,
                verified.severity,
                &verified.sender_pubkey[..12.min(verified.sender_pubkey.len())],
                verified.message
            );

            // Record the inner Kind 9734 zap_request_id so /api/v1/sos/zap-status/{id} turns green
            let _ = self
                .engine
                .is_duplicate_and_record(&format!("zap-req:{}", verified.zap_request_id))
                .await;

            // Mirror raw Kind 9735 receipt to the local Embedded Nostr Relay if enabled
            if self.config.zaps.mirror_to_embedded_relay
                && let Some(relay) = self.engine.embedded_relay().await
            {
                let _ = relay.save_event(event.clone()).await;
            }

            // Build Nostr/0xChat-only Alert representation for 0xChat subscriber notification
            let zap_alert_id = format!(
                "zap-{}",
                &verified.receipt_id[..12.min(verified.receipt_id.len())]
            );
            let zap_summary = format!(
                "⚡ [{} sats] {}",
                verified.amount_sats, verified.message
            );
            let zap_alert = Alert {
                alert_id: zap_alert_id,
                severity: verified.severity,
                summary: zap_summary.clone(),
                description: Some(format!(
                    "Verified NIP-57 Lightning Zap: {} sats ({} msats)\nSender Pubkey: {}\nLNURL Provider Pubkey: {}\nReceipt ID: {}\nRequest ID: {}\nMessage: {}",
                    verified.amount_sats,
                    verified.amount_msats,
                    verified.sender_pubkey,
                    verified.provider_pubkey,
                    verified.receipt_id,
                    verified.zap_request_id,
                    verified.message
                )),
                source: AlertSource::Nostr,
                sender: Some(verified.sender_pubkey.clone()),
                node: Some(self.engine.config().daemon.name.clone()),
                starts_at: chrono::DateTime::from_timestamp(event.created_at as i64, 0)
                    .unwrap_or_else(chrono::Utc::now),
                destinations: vec!["oxchat".to_string()],
                origin_peer: None,
                hop: 0,
            };

            if self.config.zaps.notify_oxchat_subscribers {
                let count = self
                    .engine
                    .nostr_publisher()
                    .dispatch_oxchat_to_all_subscribers(&zap_alert)
                    .await;
                if count > 0 {
                    self.engine
                        .metrics()
                        .alerts_dispatched_total
                        .with_label_values(&["oxchat", "success"])
                        .inc();
                }
            }

            if let Some(ref custom_rec) = verified.custom_recipient_hex {
                let _ = self
                    .engine
                    .nostr_publisher()
                    .register_oxchat_subscriber(custom_rec)
                    .await;
                let _ = self
                    .engine
                    .nostr_publisher()
                    .dispatch_direct_oxchat_alert(custom_rec, &zap_alert)
                    .await;
            }

            // Also publish a signed Kind 30000 NIP-ALERT event to Nostr relays so public Nostr feeds see the Zap-verified alert
            if let Ok(nip_alert_ev) = self.engine.nostr_publisher().sign_alert(&zap_alert) {
                let _ = self.engine.nostr_publisher().publish_to_relays(&nip_alert_ev).await;
            }

            // STRICT ISOLATION: Return immediately so `engine.route_alert` is NEVER called.
            return;
        }

        // 3. Handle 0xChat / Nostr NIP-04 Direct Messages (Kind 4)
        if event.kind == 4 {
            let is_addressed_to_me = event
                .tags
                .iter()
                .any(|t| t.len() >= 2 && t[0] == "p" && t[1].eq_ignore_ascii_case(my_pubkey));

            if !is_addressed_to_me {
                return;
            }

            if !self.config.oxchat.enabled {
                info!("Received Kind 4 DM, but [nostr.oxchat] is disabled; ignoring");
                return;
            }

            let _ = self
                .engine
                .nostr_publisher()
                .register_oxchat_subscriber(&event.pubkey)
                .await;

            if !self.config.oxchat.c2_enabled {
                info!("Received Kind 4 DM from subscriber [{}]; 0xChat C2 is disabled", &event.pubkey[..12.min(event.pubkey.len())]);
                return;
            }

            let max_c2_age = self.config.subscription_lookback_seconds.max(300) as i64;
            if event.created_at > 0 && now.saturating_sub(event.created_at as i64) > max_c2_age {
                debug!(
                    "⏳ Ignoring historical 0xChat Kind 4 C2 command [{}] from [{}] (created {}s ago > {}s lookback)",
                    &event.id[..8.min(event.id.len())],
                    &event.pubkey[..12.min(event.pubkey.len())],
                    now.saturating_sub(event.created_at as i64),
                    max_c2_age
                );
                return;
            }

            if self
                .engine
                .is_duplicate_and_record(&format!("c2-ev:{}", event.id))
                .await
            {
                return;
            }

            if !self.config.oxchat.is_operator_authorized(&event.pubkey) {
                warn!(
                    "🔒 Received 0xChat Kind 4 direct message from unauthorized operator [{}]; rejecting C2 command",
                    &event.pubkey
                );
                return;
            }

            let Ok(sender_bytes) = hex::decode(event.pubkey.trim()) else {
                warn!("Invalid hex in operator pubkey: {}", event.pubkey);
                return;
            };
            if sender_bytes.len() != 32 {
                warn!("Operator pubkey is not 32 bytes: {}", event.pubkey);
                return;
            }
            let Ok(sender_xonly) = secp256k1::XOnlyPublicKey::from_slice(&sender_bytes) else {
                return;
            };
            let Ok(sender_pk) = crate::crypto::nip04::xonly_to_full_pubkey(&sender_xonly) else {
                return;
            };

            let secp = secp256k1::Secp256k1::new();
            let shared = match crate::crypto::nip04::derive_shared_secret(
                &secp,
                &self.engine.nostr_publisher().secret_key(),
                &sender_pk,
            ) {
                Ok(s) => s,
                Err(e) => {
                    warn!(
                        "Failed to derive NIP-04 shared secret from operator {}: {}",
                        &event.pubkey, e
                    );
                    return;
                }
            };

            let decrypted_cmd = match crate::crypto::nip04::nip04_decrypt(&shared, &event.content) {
                Ok(cmd) => cmd,
                Err(e) => {
                    warn!(
                        "Failed to decrypt NIP-04 C2 payload from operator {}: {}",
                        &event.pubkey, e
                    );
                    return;
                }
            };

            info!(
                "📥 [0xChat C2] Received authenticated command from operator [{}]: \"{}\"",
                &event.pubkey[..12.min(event.pubkey.len())],
                decrypted_cmd.trim()
            );

            let response_text = match self.execute_c2_command(&decrypted_cmd, Some(&event.tags)).await {
                Ok(resp) => resp,
                Err(err) => format!("❌ Command Error: {}", err),
            };

            if let Err(e) = self
                .engine
                .nostr_publisher()
                .send_oxchat_c2_response(&event.pubkey, &response_text)
                .await
            {
                warn!(
                    "Failed to send 0xChat C2 response to {}: {}",
                    event.pubkey, e
                );
            } else {
                info!(
                    "📤 Dispatched encrypted 0xChat C2 reply to operator [{}]",
                    &event.pubkey[..12.min(event.pubkey.len())]
                );
            }

            return;
        }

        // 4. Handle 0xChat / Nostr NIP-17 / NIP-59 Gift Wrap Direct Messages (Kind 1059)
        if event.kind == 1059 {
            let is_addressed_to_me = event
                .tags
                .iter()
                .any(|t| t.len() >= 2 && t[0] == "p" && t[1].eq_ignore_ascii_case(my_pubkey));

            if !is_addressed_to_me {
                return;
            }

            if !self.config.oxchat.enabled {
                info!("Received Kind 1059 Gift Wrap, but [nostr.oxchat] is disabled; ignoring");
                return;
            }

            let unwrapped = match crate::crypto::nip44::unwrap_nip59_gift_wrap(
                &self.engine.nostr_publisher().secret_key(),
                &event.pubkey,
                &event.content,
            ) {
                Ok(u) => u,
                Err(e) => {
                    warn!("Failed to unwrap NIP-59 Gift Wrap: {}", e);
                    return;
                }
            };

            let _ = self
                .engine
                .nostr_publisher()
                .register_oxchat_subscriber(&unwrapped.sender_pubkey)
                .await;

            if !self.config.oxchat.c2_enabled {
                info!(
                    "📲 Registered 0xChat subscriber [{}] from Kind 1059 Gift Wrap (C2 is disabled)",
                    &unwrapped.sender_pubkey[..12.min(unwrapped.sender_pubkey.len())]
                );
                return;
            }

            // Guard against replaying historical NIP-17 C2 commands on daemon restart or reconnect:
            // while outer Kind 1059 created_at is intentionally randomized up to 2 days into the past,
            // the decrypted inner Kind 14 rumor preserves the true authoring timestamp (`unwrapped.created_at`).
            let max_c2_age = self.config.subscription_lookback_seconds.max(300) as i64;
            if unwrapped.created_at > 0 && now.saturating_sub(unwrapped.created_at as i64) > max_c2_age {
                debug!(
                    "⏳ Ignoring historical 0xChat NIP-17 C2 command [{}] from [{}] (inner rumor created {}s ago > {}s lookback)",
                    &event.id[..8.min(event.id.len())],
                    &unwrapped.sender_pubkey[..12.min(unwrapped.sender_pubkey.len())],
                    now.saturating_sub(unwrapped.created_at as i64),
                    max_c2_age
                );
                return;
            }

            if self
                .engine
                .is_duplicate_and_record(&format!("c2-ev:{}", event.id))
                .await
            {
                return;
            }

            if !self.config.oxchat.is_operator_authorized(&unwrapped.sender_pubkey) {
                warn!(
                    "🔒 Received 0xChat Kind 1059 direct message from unauthorized operator [{}]; rejecting C2 command",
                    &unwrapped.sender_pubkey
                );
                return;
            }

            info!(
                "📥 [0xChat C2 (NIP-17)] Received authenticated command from operator [{}]: {}",
                &unwrapped.sender_pubkey[..12.min(unwrapped.sender_pubkey.len())],
                unwrapped.content.trim()
            );

            let response_text = match self.execute_c2_command(&unwrapped.content, Some(&unwrapped.tags)).await {
                Ok(resp) => resp,
                Err(err) => format!("❌ Command Error: {}", err),
            };

            if let Err(e) = self
                .engine
                .nostr_publisher()
                .send_oxchat_c2_response(&unwrapped.sender_pubkey, &response_text)
                .await
            {
                warn!(
                    "Failed to send 0xChat C2 response to {}: {}",
                    unwrapped.sender_pubkey, e
                );
            } else {
                info!(
                    "📤 Dispatched encrypted 0xChat C2 reply to operator [{}]",
                    &unwrapped.sender_pubkey[..12.min(unwrapped.sender_pubkey.len())]
                );
            }

            return;
        }


        // 5. Handle 0xChat Public Timeline Note C2 Commands (Kind 1 tagged with #openalert or mentioning bot)
        if event.kind == 1 && self.config.oxchat.enabled && self.config.oxchat.c2_enabled {
            let is_bot_mentioned = event
                .tags
                .iter()
                .any(|t| t.len() >= 2 && t[0] == "p" && t[1].eq_ignore_ascii_case(my_pubkey));
            let has_openalert_tag = event
                .tags
                .iter()
                .any(|t| t.len() >= 2 && t[0] == "t" && t[1].eq_ignore_ascii_case("openalert"));

            let starts_with_c2 = event.content.trim().starts_with("!")
                || event.content.trim().to_lowercase().starts_with("ping")
                || event.content.trim().to_lowercase().starts_with("status")
                || event.content.trim().to_lowercase().starts_with("help")
                || event.content.trim().to_lowercase().starts_with("ack ");

            if (is_bot_mentioned || has_openalert_tag || self.config.oxchat.mode == crate::config::OxChatMode::Public) && starts_with_c2 {
                if self
                    .engine
                    .is_duplicate_and_record(&format!("c2-ev:{}", event.id))
                    .await
                {
                    return;
                }

                if !self.config.oxchat.is_operator_authorized(&event.pubkey) {
                    warn!(
                        "🔒 Received public timeline C2 command from unauthorized operator [{}]; ignoring",
                        &event.pubkey
                    );
                    return;
                }

                let clean_cmd = event.content.trim().trim_start_matches("!");
                info!(
                    "📥 [0xChat Public C2 (Kind 1)] Received command from operator [{}]: {}",
                    &event.pubkey[..12.min(event.pubkey.len())],
                    clean_cmd
                );

                let response_text = match self.execute_c2_command(clean_cmd, Some(&event.tags)).await {
                    Ok(resp) => resp,
                    Err(err) => format!("❌ Command Error: {}", err),
                };

                if let Err(e) = self
                    .engine
                    .nostr_publisher()
                    .send_oxchat_public_reply(&event.id, &event.pubkey, &response_text)
                    .await
                {
                    warn!("Failed to send public C2 reply to {}: {}", event.pubkey, e);
                } else {
                    info!(
                        "📤 Dispatched public threaded C2 reply to event [{}] for operator [{}]",
                        &event.id[..8.min(event.id.len())],
                        &event.pubkey[..12.min(event.pubkey.len())]
                    );
                }
                return;
            }
        }

        // 5b. Ignore NIP-51 Categorized People List events from 0xChat (e.g. Kind 30000 d="Chat-Friends")
        // while registering the author as an active 0xChat subscriber.
        let is_encrypted = event.tags.iter().any(|t| {
            t.len() >= 2
                && t[0] == "enc"
                && (t[1] == "xchacha20poly1305" || t[1] == "chacha20poly1305")
        });
        let has_openalert_marker = is_encrypted
            || event.tags.iter().any(|t| {
                t.len() >= 2
                    && ((t[0] == "t" && (t[1].eq_ignore_ascii_case("alert") || t[1].eq_ignore_ascii_case("openalert")))
                        || t[0] == "severity")
            });
        let is_nip51_people_list = event.kind == 30000
            && event.tags.iter().any(|t| {
                t.len() >= 2
                    && t[0] == "d"
                    && (t[1].starts_with("Chat-") || t[1].eq_ignore_ascii_case("friends") || t[1].eq_ignore_ascii_case("contacts"))
            });

        if is_nip51_people_list || (event.kind == 30000 && !has_openalert_marker && self.config.oxchat.enabled) {
            let _ = self
                .engine
                .nostr_publisher()
                .register_oxchat_subscriber(&event.pubkey)
                .await;
            info!(
                "📲 Ignored non-alert NIP-51 list event [{}] and registered 0xChat subscriber [{}]",
                &event.id[..8.min(event.id.len())],
                &event.pubkey[..12.min(event.pubkey.len())]
            );
            return;
        }

        let alert = if is_encrypted {
            // Check whitelist if configured
            if !self.config.privacy.authorized_senders.is_empty() {
                let authorized = self
                    .config
                    .privacy
                    .authorized_senders
                    .iter()
                    .any(|p| p.eq_ignore_ascii_case(&event.pubkey));
                if !authorized {
                    warn!(
                        "Dropping encrypted Nostr alert [{}] from unauthorized sender pubkey: {}",
                        &event.id[..8.min(event.id.len())],
                        &event.pubkey
                    );
                    return;
                }
            }

            let Some(key) = self.config.privacy.get_key_bytes() else {
                warn!(
                    "Received encrypted Nostr alert [{}] but no valid nostr.privacy.shared_key configured; dropping",
                    &event.id[..8.min(event.id.len())]
                );
                return;
            };

            use base64::Engine;
            let Ok(datagram) =
                base64::engine::general_purpose::STANDARD.decode(event.content.trim())
            else {
                warn!(
                    "Encrypted Nostr alert [{}] contains malformed base64 content",
                    &event.id[..8.min(event.id.len())]
                );
                return;
            };

            let decrypted = match crate::peering::crypto::decrypt_datagram(&key, &datagram) {
                Ok(d) => d,
                Err(e) => {
                    warn!(
                        "Failed to decrypt Nostr alert [{}] (corrupt, tampered, or wrong key): {}",
                        &event.id[..8.min(event.id.len())],
                        e
                    );
                    return;
                }
            };

            let mut inner_alert: Alert = match serde_json::from_slice(&decrypted) {
                Ok(a) => a,
                Err(e) => {
                    warn!(
                        "Decrypted Nostr alert [{}] contains invalid Alert JSON: {}",
                        &event.id[..8.min(event.id.len())],
                        e
                    );
                    return;
                }
            };
            inner_alert.source = AlertSource::Nostr;
            inner_alert.sender = Some(event.pubkey.clone());
            inner_alert
        } else {
            if self.config.privacy.mode == crate::config::NostrPrivacyMode::Encrypted
                && !self.config.privacy.allow_unencrypted_fallback
            {
                info!(
                    "Dropping cleartext Nostr alert [{}] because nostr.privacy.mode is encrypted and allow_unencrypted_fallback is false",
                    &event.id[..8.min(event.id.len())]
                );
                return;
            }

            let mut alert_id = event.id[..12.min(event.id.len())].to_string();
            let mut severity = AlertSeverity::Critical;
            let mut sender = event.pubkey.clone();
            let mut node: Option<String> = None;

            for tag in &event.tags {
                if tag.len() >= 2 {
                    match tag[0].as_str() {
                        "d" => alert_id = tag[1].clone(),
                        "severity" => {
                            severity = AlertSeverity::parse_str(&tag[1]);
                        }
                        "sender" => sender = tag[1].clone(),
                        "node" => node = Some(tag[1].clone()),
                        _ => {}
                    }
                }
            }

            Alert {
                alert_id,
                severity,
                summary: event.content.clone(),
                description: Some(event.content),
                source: AlertSource::Nostr,
                sender: Some(sender),
                node,
                starts_at: chrono::DateTime::from_timestamp(event.created_at as i64, 0)
                    .unwrap_or_else(chrono::Utc::now),
                destinations: vec!["webhook".to_string()],
                origin_peer: None,
                hop: 5,
            }
        };

        if let Err(err) = self.engine.route_alert(alert).await {
            error!("Failed to route alert from Nostr: {}", err);
        }
    }

    /// Executes authenticated C2 commands received from an authorized operator over 0xChat.
    pub async fn execute_c2_command(&self, cmd_line: &str, tags: Option<&[Vec<String>]>) -> std::result::Result<String, String> {
        let trimmed = cmd_line.trim();
        let mut parts = trimmed.split_whitespace();
        let Some(raw_verb) = parts.next() else {
            return Ok("❓ Empty command. Type 'help' for available commands.".to_string());
        };

        let verb = raw_verb.trim_start_matches('!').trim_start_matches('/');

        match verb.to_lowercase().as_str() {
            "ping" => {
                let now = chrono::Utc::now().format("%Y-%m-%d %H:%M:%S UTC");
                Ok(format!(
                    "🏓 PONG [OpenAlert Daemon]\nTime: {}\nStatus: Operational",
                    now
                ))
            }
            "status" => {
                let status = self.engine.get_status().await;
                Ok(format!(
                    "🛡️ [OpenAlert Status Report]\nNode: {}\nVersion: {}\nUptime: {}s\nPeering: {} active peer(s)\nNostr Relays: {}\nStorage Spool: {} pending",
                    status.node_name,
                    status.version,
                    status.uptime_seconds,
                    status.peering.as_ref().map(|p| p.peers.len()).unwrap_or(0),
                    status.nostr.relays_count,
                    status
                        .storage
                        .spool
                        .as_ref()
                        .map(|s| s.spooled)
                        .unwrap_or(0),
                ))
            }
            "ack" | "ok" => {
                let mut target_alert_id = parts.next().map(String::from);

                // If no alert_id was explicitly provided, attempt NIP-10 thread-aware parent resolution
                if target_alert_id.is_none()
                    && let Some(tags_slice) = tags
                    && let Some(parent_id) = tags_slice.iter().find_map(|t| {
                        if t.len() >= 2 && t[0] == "e" {
                            Some(t[1].clone())
                        } else {
                            None
                        }
                    })
                    && let Some(storage) = self.engine.storage()
                    && let Ok(events) = storage.query_nostr_events(None, None, None, None, None, None, 50).await
                    && let Some(parent_ev) = events.into_iter().find(|e| e.id.eq_ignore_ascii_case(&parent_id))
                    && let Some(d_tag) = parent_ev.tags.iter().find(|t| t.len() >= 2 && t[0] == "d")
                {
                    target_alert_id = Some(d_tag[1].clone());
                }

                // If still unresolved, fallback to acknowledging the most recent pending alert
                if target_alert_id.is_none()
                    && let Some(storage) = self.engine.storage()
                    && let Ok(pending) = storage.get_pending_alerts(3600).await
                    && let Some(latest) = pending.last()
                {
                    target_alert_id = Some(latest.alert_id.clone());
                }

                let Some(alert_id) = target_alert_id else {
                    return Ok("⚠️ Usage: ack <alert_id> (or reply 'ack' directly to an alert card)".to_string());
                };

                if let Some(storage) = self.engine.storage() {
                    match storage.mark_dispatched(&alert_id).await {
                        Ok(()) => Ok(format!(
                            "✅ Alert [{}] acknowledged and marked dispatched.",
                            alert_id
                        )),
                        Err(e) => Ok(format!(
                            "❌ Failed to acknowledge alert [{}]: {}",
                            alert_id, e
                        )),
                    }
                } else {
                    Ok(format!(
                        "⚠️ In-memory ACK acknowledged for alert [{}].",
                        alert_id
                    ))
                }
            }
            "mesh" | "bitchat" => {
                let remaining: Vec<&str> = parts.collect();
                let msg = remaining.join(" ");
                if msg.is_empty() {
                    return Ok("⚠️ Usage: mesh <message>".to_string());
                }
                if let Some(_bitchat) = self.engine.bitchat_service().await {
                    let alert = Alert {
                        alert_id: format!("c2-mesh-{}", chrono::Utc::now().timestamp_millis()),
                        severity: AlertSeverity::Warning,
                        summary: msg.clone(),
                        description: Some("Dispatched via 0xChat C2 bridge".to_string()),
                        source: AlertSource::Nostr,
                        sender: Some("0xchat-c2".to_string()),
                        node: Some(self.engine.config().daemon.name.clone()),
                        starts_at: chrono::Utc::now(),
                        destinations: vec!["bitchat".to_string()],
                        origin_peer: None,
                        hop: 5,
                    };
                    if let Err(e) = self.engine.route_alert(alert).await {
                        Ok(format!("❌ Failed to route mesh message: {}", e))
                    } else {
                        Ok(format!("📡 Broadcasted to BitChat BLE mesh: \"{}\"", msg))
                    }
                } else {
                    Ok(
                        "⚠️ BitChat BLE service is not currently active on this daemon."
                            .to_string(),
                    )
                }
            }
            "sms" => {
                let Some(number) = parts.next() else {
                    return Ok("⚠️ Usage: sms <recipient_phone_number> <message>".to_string());
                };
                let remaining: Vec<&str> = parts.collect();
                let msg = remaining.join(" ");
                if msg.is_empty() {
                    return Ok("⚠️ Usage: sms <recipient_phone_number> <message>".to_string());
                }
                if let Some(sms_svc) = self.engine.sms_service().await {
                    match sms_svc.send_manual_sms(number, &msg).await {
                        Ok(()) => Ok(format!("📱 Dispatched SMS to {}", number)),
                        Err(e) => Ok(format!("❌ Failed to dispatch SMS to {}: {}", number, e)),
                    }
                } else {
                    Ok("⚠️ Cellular SMS gateway service is not active on this daemon.".to_string())
                }
            }
            "help" => Ok("📋 [OpenAlert 0xChat C2 Commands]\n                    - ping : Test latency and daemon heartbeat\n                    - status : Show daemon health and subsystem metrics\n                    - ack <alert_id> : Acknowledge and resolve an active alert\n                    - mesh <message> (or bitchat) : Broadcast message over BitChat BLE mesh\n                    - sms <number> <msg> : Send SMS via cellular gateway\n                    - help : Display this command manual"
                .to_string()),
            unknown => Ok(format!(
                "❓ Unknown command '{}'. Type 'help' for available commands.",
                unknown
            )),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use secp256k1::{Keypair, Secp256k1};

    fn sign_test_event(kp: &Keypair, kind: u64, tags: Vec<Vec<String>>, content: &str) -> NostrEvent {
        let secp = Secp256k1::new();
        let (xonly, _) = kp.x_only_public_key();
        let pubkey = hex::encode(xonly.serialize());
        let created_at = crate::time_sync::now_utc_secs().max(0) as u64;
        let serialized = serde_json::to_string(&serde_json::json!([
            0,
            pubkey,
            created_at,
            kind,
            tags,
            content
        ]))
        .unwrap();
        let id_bytes = Sha256::digest(serialized.as_bytes());
        let id = hex::encode(id_bytes);
        let sig = secp.sign_schnorr(id_bytes.as_slice(), kp);
        NostrEvent {
            id,
            pubkey,
            created_at,
            kind,
            tags,
            content: content.to_string(),
            sig: hex::encode(sig.as_ref()),
        }
    }

    #[test]
    fn test_bolt11_roundtrip_and_nip57_six_stage_verification() {
        let secp = Secp256k1::new();
        let mut rng = secp256k1::rand::rngs::OsRng;

        let target_kp = Keypair::new(&secp, &mut rng);
        let target_pk = hex::encode(target_kp.x_only_public_key().0.serialize());

        let sender_kp = Keypair::new(&secp, &mut rng);
        let provider_kp = Keypair::new(&secp, &mut rng);
        let provider_pk = hex::encode(provider_kp.x_only_public_key().0.serialize());

        // 1. Construct a valid signed Kind 9734 Zap Request for 1,500 sats (Critical tier)
        let req_9734 = sign_test_event(
            &sender_kp,
            9734,
            vec![
                vec!["p".to_string(), target_pk.clone()],
                vec!["amount".to_string(), "1500000".to_string()],
                vec!["relays".to_string(), "ws://127.0.0.1:8088".to_string()],
            ],
            "Substation B transformer overheating",
        );
        let desc_json = serde_json::to_string(&req_9734).unwrap();
        let desc_hash: [u8; 32] = Sha256::digest(desc_json.as_bytes()).into();

        // 2. Encode a valid BOLT-11 invoice for 1,500 sats committing to desc_hash
        let bolt11 = encode_bolt11_with_description_hash(1500, &desc_hash);
        let parsed = parse_bolt11_invoice(&bolt11).expect("Valid BOLT-11");
        assert_eq!(parsed.amount_sats, 1500);
        assert_eq!(parsed.amount_msats, 1_500_000);
        assert_eq!(parsed.description_hash, Some(desc_hash));

        // 3. Construct outer Kind 9735 Zap Receipt signed by LNURL provider
        let receipt_9735 = sign_test_event(
            &provider_kp,
            9735,
            vec![
                vec!["p".to_string(), target_pk.clone()],
                vec!["bolt11".to_string(), bolt11.clone()],
                vec!["description".to_string(), desc_json.clone()],
            ],
            "",
        );

        let mut zaps_cfg = NostrZapsConfig {
            enabled: true,
            trusted_provider_pubkeys: vec![provider_pk.clone()],
            ..Default::default()
        };

        let verified = verify_and_extract_nip57_zap(&receipt_9735, &zaps_cfg, &target_pk)
            .expect("Valid Kind 9735 receipt should pass all 6 stages");
        assert_eq!(verified.amount_sats, 1500);
        assert_eq!(verified.severity, AlertSeverity::Critical);
        assert_eq!(verified.zap_request_id, req_9734.id);
        assert_eq!(verified.message, "Substation B transformer overheating");

        // 4. Reject if provider is not in trusted_provider_pubkeys
        zaps_cfg.trusted_provider_pubkeys = vec!["00".repeat(32)];
        assert!(verify_and_extract_nip57_zap(&receipt_9735, &zaps_cfg, &target_pk).is_err());
        zaps_cfg.trusted_provider_pubkeys = vec![provider_pk];

        // 5. Reject if description_hash does not match Kind 9734 JSON
        let wrong_hash = [0xabu8; 32];
        let bad_bolt11 = encode_bolt11_with_description_hash(1500, &wrong_hash);
        let bad_receipt = sign_test_event(
            &provider_kp,
            9735,
            vec![
                vec!["p".to_string(), target_pk.clone()],
                vec!["bolt11".to_string(), bad_bolt11],
                vec!["description".to_string(), desc_json.clone()],
            ],
            "",
        );
        let err = verify_and_extract_nip57_zap(&bad_receipt, &zaps_cfg, &target_pk).unwrap_err();
        assert!(err.contains("description_hash"));

        // 6. Reject if amount is below min_sats_warning (e.g., 10 sats < 21 sats)
        let dust_req = sign_test_event(
            &sender_kp,
            9734,
            vec![vec!["p".to_string(), target_pk.clone()]],
            "Dust spam",
        );
        let dust_json = serde_json::to_string(&dust_req).unwrap();
        let dust_hash: [u8; 32] = Sha256::digest(dust_json.as_bytes()).into();
        let dust_bolt11 = encode_bolt11_with_description_hash(10, &dust_hash);
        let dust_receipt = sign_test_event(
            &provider_kp,
            9735,
            vec![
                vec!["p".to_string(), target_pk.clone()],
                vec!["bolt11".to_string(), dust_bolt11],
                vec!["description".to_string(), dust_json],
            ],
            "",
        );
        let dust_err = verify_and_extract_nip57_zap(&dust_receipt, &zaps_cfg, &target_pk).unwrap_err();
        assert!(dust_err.contains("below minimum anti-spam threshold"));
    }
}
