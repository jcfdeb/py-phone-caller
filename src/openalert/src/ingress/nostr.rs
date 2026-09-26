//! # Nostr Ingress Subscriber
//!
//! Subscribes to configured Nostr relays via WebSockets to ingest decentralized alerts.
//! Enforces NIP-40 expiration tags, alert TTL filtering, and prevents self-echo loops.
//! Implements periodic heartbeat pings and exponential backoff with jitter for network resilience.

use crate::config::NostrConfig;
use crate::engine::AlertEngine;
use crate::error::Result;
use crate::models::{Alert, AlertSeverity, AlertSource, NostrEvent};
use futures_util::{SinkExt, StreamExt};
use rand::Rng;
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

    /// Continuous connection management loop with exponential/jittered backoff reconnection and ping/pong heartbeats.
    async fn listen_relay_loop(&self, relay_url: String) {
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

                    let mut kinds = self.config.subscription_filter_kinds.clone();
                    if kinds.is_empty() {
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

                    let filter = serde_json::json!({
                        "kinds": kinds,
                        "since": since_timestamp,
                        "limit": 50,
                    });

                    let mut req_array = vec![
                        serde_json::Value::String("REQ".to_string()),
                        serde_json::Value::String("openalert-ingress-sub".to_string()),
                        filter,
                    ];

                    // NIP-59 Gift Wraps require dedicated filter without narrow 'since' due to intentional timestamp perturbation
                    if self.config.oxchat.enabled {
                        let my_pubkey = self.engine.nostr_publisher().public_key();
                        let gift_wrap_filter = serde_json::json!({
                            "kinds": [1059],
                            "#p": [my_pubkey],
                            "limit": 50,
                        });
                        req_array.push(gift_wrap_filter);
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

            if !self.config.oxchat.c2_enabled {
                info!("Received Kind 4 DM, but 0xChat C2 is disabled; ignoring");
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

            if !self.config.oxchat.c2_enabled {
                info!("Received Kind 1059 Gift Wrap, but 0xChat C2 is disabled; ignoring");
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

        let is_encrypted = event.tags.iter().any(|t| {
            t.len() >= 2
                && t[0] == "enc"
                && (t[1] == "xchacha20poly1305" || t[1] == "chacha20poly1305")
        });

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

            Alert {
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
                    "🏓 PONG [OpenAlert Daemon]
Time: {}
Status: Operational",
                    now
                ))
            }
            "status" => {
                let status = self.engine.get_status().await;
                Ok(format!(
                    "🛡️ [OpenAlert Status Report]
Node: {}
Version: {}
Uptime: {}s
Peering: {} active peer(s)
Nostr Relays: {}
Storage Spool: {} pending",
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
                        hop: 3,
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
            "help" => Ok("📋 [OpenAlert 0xChat C2 Commands]
                    - ping : Test latency and daemon heartbeat
                    - status : Show daemon health and subsystem metrics
                    - ack <alert_id> : Acknowledge and resolve an active alert
                    - mesh <message> (or bitchat) : Broadcast message over BitChat BLE mesh
                    - sms <number> <msg> : Send SMS via cellular gateway
                    - help : Display this command manual"
                .to_string()),
            unknown => Ok(format!(
                "❓ Unknown command '{}'. Type 'help' for available commands.",
                unknown
            )),
        }
    }
}
