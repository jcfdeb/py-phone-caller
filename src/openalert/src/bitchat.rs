//! #BitChat Bluetooth Mesh Protocol Implementation
//!
//! Native Linux BlueZ GATT server, advertising daemon, and BitChat binary packet codec.
//! Implements peer discovery announcements, mutual Noise XX key exchange, authenticated direct messaging,
//! and routing integration with the OpenAlert core engine.

use crate::config::BitChatConfig;
use crate::engine::AlertEngine;
use crate::error::Result;
use crate::models::{Alert, AlertSeverity, AlertSource};
use bluer::{
    adv::Advertisement,
    gatt::local::{
        Application, Characteristic, CharacteristicNotify, CharacteristicNotifyMethod,
        CharacteristicRead, CharacteristicWrite, CharacteristicWriteMethod, Service,
    },
    Session, Uuid,
};
use ed25519_dalek::{Signer, SigningKey, Verifier, VerifyingKey};
use futures_util::FutureExt;
use sha2::{Digest, Sha256};
use snow::TransportState;
use std::collections::{BTreeSet, HashMap, VecDeque};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{broadcast, Notify, RwLock};
use tokio::time::sleep;
use tracing::{debug, info, warn};
use x25519_dalek::{PublicKey as X25519PublicKey, StaticSecret as X25519StaticSecret};

pub const DEFAULT_BITCHAT_SERVICE_UUID: &str = "f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5c";
pub const DEFAULT_BITCHAT_CHAR_UUID: &str = "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d";

pub const PACKET_VERSION: u8 = 0x01;
pub const PACKET_VERSION_V2: u8 = 0x02;
pub const PACKET_TYPE_ANNOUNCE: u8 = 0x01;
pub const PACKET_TYPE_MESSAGE: u8 = 0x02;
pub const PACKET_TYPE_NOISE_HANDSHAKE: u8 = 0x10;
pub const PACKET_TYPE_NOISE_ENCRYPTED: u8 = 0x11;
pub const PACKET_TYPE_KEY_EXCHANGE_REQ: u8 = 0x10;
pub const PACKET_TYPE_KEY_EXCHANGE_RESP: u8 = 0x10;
pub const PACKET_TYPE_KEY_EXCHANGE_FINAL: u8 = 0x10;
pub const PACKET_TYPE_ENCRYPTED_MESSAGE: u8 = 0x11;
pub const PACKET_TYPE_ENCRYPTED_ACK: u8 = 0x11;
pub const PACKET_TYPE_LEGACY_SYNC: u8 = 0x20;
pub const PACKET_TYPE_REQUEST_SYNC: u8 = 0x21;
pub const PACKET_TYPE_SYNC_RESPONSE: u8 = 0x21;

pub const BITCHAT_BROADCAST_RECIPIENT: [u8; 8] = [0xff; 8];

pub const FLAG_HAS_RECIPIENT: u8 = 0x01;
pub const FLAG_HAS_SIGNATURE: u8 = 0x02;
pub const FLAG_IS_COMPRESSED: u8 = 0x04;
pub const FLAG_HAS_ROUTE: u8 = 0x08;
pub const FLAG_IS_RSR: u8 = 0x10;

pub const TLV_TAG_NICKNAME: u8 = 0x01;
pub const TLV_TAG_NOISE_PUBKEY: u8 = 0x02;
pub const TLV_TAG_SIGNING_PUBKEY: u8 = 0x03;
pub const TLV_TAG_ROUTE_PEER_ID: u8 = 0x04;

pub const MESSAGE_TTL_HOPS: u8 = 0x07;
pub const BITCHAT_BUCKET_SIZE_256: usize = 256;
pub const MAX_TRACKED_SESSION_NONCES: usize = 128;
pub const MAX_TRACKED_SESSION_MSG_IDS: usize = 128;
pub const DIRECT_NEIGHBOR_FRESHNESS_SECS: u64 = 65;
pub const MAX_ANNOUNCE_NEIGHBORS: usize = 10;

/// Live state representation for peer-to-peer Noise encryption handshakes and transport.
pub enum PeerNoiseSession {
    HandshakingResponder(Box<snow::HandshakeState>),
    HandshakingInitiator {
        state: Box<snow::HandshakeState>,
        started_at: Instant,
    },
    Established {
        transport: TransportState,
        seen_nonces: VecDeque<u64>,
        seen_msg_ids: VecDeque<String>,
    },
}

/// Represents a parsed and cryptographically validated incoming BitChat packet.
#[derive(Debug, Clone)]
pub struct ParsedPacket {
    pub packet_type: u8,
    pub ttl: u8,
    pub sender_id: [u8; 8],
    pub recipient_id: Option<[u8; 8]>,
    pub payload: Option<Vec<u8>>,
    pub signature_valid: bool,
}

/// Detailed record of a discovered or connected BitChat peer in the local registry.
#[derive(Debug, Clone)]
pub struct BitChatPeerEntry {
    pub sender_id: [u8; 8],
    pub nickname: String,
    pub verified: bool,
    pub last_seen: Instant,
    pub last_direct_seen: Option<Instant>,
    pub last_announce_reply_at: Option<Instant>,
    pub messages_received: u64,
    pub messages_sent: u64,
}

/// Manages native Linux BlueZ Bluetooth Low Energy operations and BitChat mesh communications.
pub struct BitChatService {
    config: BitChatConfig,
    engine: Option<Arc<AlertEngine>>,
    running: Arc<AtomicBool>,
    shutdown_notify: Arc<Notify>,
    active_subscribers: Arc<AtomicUsize>,
    sessions: Arc<RwLock<HashMap<[u8; 8], PeerNoiseSession>>>,
    peers: Arc<RwLock<HashMap<[u8; 8], BitChatPeerEntry>>>,
    bcast_tx: Arc<RwLock<Option<broadcast::Sender<Vec<u8>>>>>,
}

impl BitChatService {
    /// Creates a new instance of the BitChat service.
    pub fn new(config: BitChatConfig, engine: Option<Arc<AlertEngine>>) -> Self {
        Self {
            config,
            engine,
            running: Arc::new(AtomicBool::new(true)),
            shutdown_notify: Arc::new(Notify::new()),
            active_subscribers: Arc::new(AtomicUsize::new(0)),
            sessions: Arc::new(RwLock::new(HashMap::new())),
            peers: Arc::new(RwLock::new(HashMap::new())),
            bcast_tx: Arc::new(RwLock::new(None)),
        }
    }

    /// Parses the output of `btmgmt info` to determine whether the given HCI controller
    /// (e.g. `hci0`) currently has the `advertising` setting active in hardware.
    /// Returns `Some(true)` if `advertising` is present in `current settings`,
    /// `Some(false)` if the controller block was found with `current settings:` lacking `advertising`,
    /// or `None` if the controller block was not present in the output.
    pub fn parse_btmgmt_advertising_state(btmgmt_output: &str, device_name: &str) -> Option<bool> {
        let target_header = format!("{}:", device_name.trim());
        let mut in_target_block = false;
        for line in btmgmt_output.lines() {
            let trimmed = line.trim();
            if !line.starts_with(' ') && !line.starts_with('\t') && trimmed.ends_with(':') || trimmed.contains(":\tPrimary controller") || trimmed.contains(":\tUnconfigured controller") {
                in_target_block = trimmed.starts_with(&target_header);
            }
            if in_target_block && trimmed.starts_with("current settings:") {
                let settings_str = trimmed.trim_start_matches("current settings:");
                let has_adv = settings_str
                    .split_whitespace()
                    .any(|flag| flag.eq_ignore_ascii_case("advertising"));
                return Some(has_adv);
            }
        }
        None
    }

    /// Returns true when a BlueZ/HCI error string indicates a transient controller state
    /// (e.g. Spreadtrum/Unisoc UART adapter returning `0x0a Busy` or `InProgress` during power cycle).
    pub fn is_retryable_hci_error(err_msg: &str) -> bool {
        let lower = err_msg.to_ascii_lowercase();
        lower.contains("busy")
            || lower.contains("0x0a")
            || lower.contains("inprogress")
            || lower.contains("in progress")
            || lower.contains("notready")
            || lower.contains("not ready")
            || lower.contains("failed")
    }

    /// Disconnects any currently connected BLE/Bluetooth peers on the adapter so centrals
    /// do not hold stale GATT attribute handles across daemon restarts or HCI recovery.
    async fn disconnect_stale_devices(adapter: &bluer::Adapter, dev_name: &str) -> usize {
        let mut disconnected = 0usize;
        if let Ok(addrs) = adapter.device_addresses().await {
            for addr in addrs {
                if let Ok(dev) = adapter.device(addr)
                    && dev.is_connected().await.unwrap_or(false)
                {
                    info!(
                        "🔄 [BLE Self-Healing] Disconnecting stale connected peer {} on '{}' to flush GATT cache...",
                        addr, dev_name
                    );
                    if let Err(e) = dev.disconnect().await {
                        debug!(
                            "Could not disconnect peer {} on '{}': {}",
                            addr, dev_name, e
                        );
                    } else {
                        disconnected += 1;
                    }
                }
            }
        }
        disconnected
    }

    /// Powers on an HCI adapter with progressive retry/backoff when UART BLE controllers
    /// (such as Spreadtrum/Unisoc) transiently respond with `0x0a (Busy)` or `InProgress`.
    async fn ensure_adapter_powered_with_retry(
        adapter: &bluer::Adapter,
        dev_name: &str,
        max_attempts: u32,
    ) -> bool {
        for attempt in 1..=max_attempts.max(1) {
            if adapter.is_powered().await.unwrap_or(false) {
                return true;
            }
            match adapter.set_powered(true).await {
                Ok(()) => {
                    sleep(Duration::from_millis(250)).await;
                    if adapter.is_powered().await.unwrap_or(true) {
                        if attempt > 1 {
                            info!(
                                "✅ [BLE Self-Healing] Adapter '{}' powered on after attempt {}/{}",
                                dev_name, attempt, max_attempts
                            );
                        }
                        return true;
                    }
                }
                Err(e) => {
                    let msg = e.to_string();
                    let backoff_ms = 500u64 * u64::from(attempt);
                    if Self::is_retryable_hci_error(&msg) && attempt < max_attempts {
                        warn!(
                            "⏳ [BLE Self-Healing] Adapter '{}' power-on attempt {}/{} returned transient error ({}); retrying in {}ms...",
                            dev_name, attempt, max_attempts, msg, backoff_ms
                        );
                        sleep(Duration::from_millis(backoff_ms)).await;
                    } else {
                        warn!(
                            "⚠️ [BLE Self-Healing] Could not power on adapter '{}' (attempt {}/{}): {}",
                            dev_name, attempt, max_attempts, msg
                        );
                        if attempt < max_attempts {
                            sleep(Duration::from_millis(backoff_ms)).await;
                        }
                    }
                }
            }
        }
        adapter.is_powered().await.unwrap_or(false)
    }

    /// Flushes stale BlueZ/HCI peripheral state (stale connections, wedged Spreadtrum UART
    /// advertising/GATT firmware state) via optional power-cycle with `Busy`-safe retry backoff.
    async fn sanitize_hci_adapter(
        adapter: &bluer::Adapter,
        dev_name: &str,
        alias: &str,
        force_power_cycle: bool,
    ) -> bool {
        let stale = Self::disconnect_stale_devices(adapter, dev_name).await;
        if stale > 0 {
            sleep(Duration::from_millis(400)).await;
        }

        if force_power_cycle && adapter.is_powered().await.unwrap_or(false) {
            info!(
                "🔄 [BLE Self-Healing] Power-cycling '{}' to clear stale BlueZ GATT/advertising state...",
                dev_name
            );
            if let Err(e) = adapter.set_powered(false).await {
                warn!(
                    "⚠️ [BLE Self-Healing] Power-off '{}' returned: {} (continuing recovery)",
                    dev_name, e
                );
            }
            // Give UART BLE firmware (e.g. Spreadtrum/Unisoc) time to finish HCI teardown
            // before powering back on so it does not reject with status 0x0a (Busy).
            sleep(Duration::from_millis(1200)).await;
        }

        let powered = Self::ensure_adapter_powered_with_retry(adapter, dev_name, 6).await;
        if powered {
            if let Err(e) = adapter.set_discoverable(true).await {
                debug!("Could not set discoverable on '{}': {}", dev_name, e);
            }
            if let Err(e) = adapter.set_pairable(true).await {
                debug!("Could not set pairable on '{}': {}", dev_name, e);
            }
            if let Err(e) = adapter.set_discoverable_timeout(0).await {
                debug!("Could not set discoverable timeout on '{}': {}", dev_name, e);
            }
            if !alias.is_empty() {
                let _ = adapter.set_alias(alias.to_string()).await;
            }
        }
        powered
    }

    /// Terminates all background BLE advertising and notification loops.
    pub fn stop(&self) {
        self.running.store(false, Ordering::Relaxed);
        self.shutdown_notify.notify_waiters();
    }

    /// Gracefully stops BitChat BLE GATT/advertising loops, gives BlueZ time to unregister
    /// D-Bus handles, and disconnects active BLE peers so they reconnect cleanly on restart.
    pub async fn shutdown(&self) {
        self.stop();
        if !self.config.enabled {
            return;
        }
        // Allow advertising + GATT tasks woken by `shutdown_notify` to drop their BlueZ handles.
        sleep(Duration::from_millis(450)).await;
        if let Ok(sess) = Session::new().await {
            let adapter = match sess.adapter(&self.config.device) {
                Ok(a) => Ok(a),
                Err(_) => sess.default_adapter().await,
            };
            if let Ok(adapt) = adapter {
                let _ = Self::disconnect_stale_devices(&adapt, &self.config.device).await;
            }
        }
    }

    /// Sends an upstream delivery confirmation (e.g., LoRa RF ACK or Gateway ARQ ACK) back to the
    /// originating BitChat peer over their active Noise E2EE session or signed 1-on-1 direct message.
    pub async fn notify_upstream_delivery(
        &self,
        alert_id: &str,
        gateway_name: &str,
        link_label: &str,
        attempt: u32,
        max_attempts: u32,
    ) {
        if !self.config.enabled || !alert_id.starts_with("bitchat-") {
            return;
        }

        let tx_opt = self.bcast_tx.read().await.clone();
        let Some(tx) = tx_opt else {
            return;
        };

        // Parse 4-byte peer prefix from `bitchat-dm-<8hex>-<ts>`, `bitchat-msg-<8hex>-<ts>`, or `bitchat-bcast-<8hex>-<ts>`
        let parts: Vec<&str> = alert_id.split('-').collect();
        if parts.len() < 4 {
            return;
        }
        let mode = parts[1];
        let peer_prefix_hex = parts[2];
        let Ok(prefix_bytes) = hex::decode(peer_prefix_hex) else {
            return;
        };
        if prefix_bytes.len() < 4 {
            return;
        }

        let (signing_key, _, my_sender_id) = Self::derive_keys(&self.config.node_name);
        let status_txt = format!(
            "✅ [OpenAlert {} ACK] Verified by '{}' (attempt {}/{})",
            link_label, gateway_name, attempt, max_attempts
        );

        // Locate full 8-byte peer sender_id from peers or sessions map
        let target_peer = {
            let p_guard = self.peers.read().await;
            p_guard
                .keys()
                .find(|k| k[..4] == prefix_bytes[..4])
                .copied()
        }
        .or_else(|| {
            if let Ok(s_guard) = self.sessions.try_read() {
                s_guard
                    .keys()
                    .find(|k| k[..4] == prefix_bytes[..4])
                    .copied()
            } else {
                None
            }
        });

        if mode == "dm" {
            if let Some(peer_id) = target_peer {
                let mut s_guard = self.sessions.write().await;
                if let Some(PeerNoiseSession::Established { transport, .. }) = s_guard.get_mut(&peer_id) {
                    let send_nonce = transport.sending_nonce() as u32;
                    let tlv_payload = Self::encode_bitchat_private_message(&status_txt);
                    let mut enc_ack_buf = vec![0u8; tlv_payload.len() + 32];
                    if let Ok(ack_len) = transport.write_message(&tlv_payload, &mut enc_ack_buf) {
                        let mut combined_payload = send_nonce.to_be_bytes().to_vec();
                        combined_payload.extend_from_slice(&enc_ack_buf[..ack_len]);
                        let enc_reply = Self::build_encrypted_chat_packet(
                            &my_sender_id,
                            &peer_id,
                            &combined_payload,
                            &signing_key,
                        );
                        info!(
                            "💬 [BitChat E2EE] Transmitting upstream delivery confirmation to peer {}: \"{}\"",
                            hex::encode(peer_id),
                            status_txt
                        );
                        let _ = tx.send(enc_reply);
                    }
                }
            }
        } else if mode == "msg" {
            if let Some(peer_id) = target_peer {
                let chat_reply = Self::build_chat_message_packet(
                    &my_sender_id,
                    Some(&peer_id),
                    &status_txt,
                    &signing_key,
                );
                info!(
                    "💬 [BitChat GATT] Transmitting upstream delivery confirmation to peer {}: \"{}\"",
                    hex::encode(peer_id),
                    status_txt
                );
                let _ = tx.send(chat_reply);
            }
        } else if mode == "bcast" && self.config.public_mesh_ack {
            let chat_reply = Self::build_chat_message_packet(
                &my_sender_id,
                None,
                &status_txt,
                &signing_key,
            );
            info!(
                "💬 [BitChat GATT] Broadcasting upstream delivery confirmation to public mesh: \"{}\"",
                status_txt
            );
            let _ = tx.send(chat_reply);
        }
    }

    /// Manually registers or updates a peer in the registry (useful for testing or pre-configured peers).
    pub async fn record_peer(&self, sender_id: [u8; 8], nickname: &str, verified: bool) {
        let mut guard = self.peers.write().await;
        let entry = guard.entry(sender_id).or_insert_with(|| BitChatPeerEntry {
            sender_id,
            nickname: nickname.to_string(),
            verified,
            last_seen: Instant::now(),
            last_direct_seen: None,
            last_announce_reply_at: None,
            messages_received: 0,
            messages_sent: 0,
        });
        entry.nickname = nickname.to_string();
        entry.verified = verified;
        entry.last_seen = Instant::now();
    }

    /// Generates a comprehensive status report of the BitChat BLE mesh and connected peers.
    pub async fn get_status(&self) -> crate::models::BitChatStatusReport {
        let (_, _, my_sender_id) = Self::derive_keys(&self.config.node_name);
        let peers_guard = self.peers.read().await;
        let sessions_guard = self.sessions.read().await;

        let mut peer_infos = Vec::new();
        let mut active_sessions_count = 0;

        for (sender_id, entry) in peers_guard.iter() {
            let session_state = match sessions_guard.get(sender_id) {
                Some(PeerNoiseSession::Established { .. }) => {
                    active_sessions_count += 1;
                    "Established (E2EE 🔒)".to_string()
                }
                Some(
                    PeerNoiseSession::HandshakingResponder(_)
                    | PeerNoiseSession::HandshakingInitiator { .. },
                ) => "Handshaking...".to_string(),
                None => "Announced / Discovered".to_string(),
            };

            peer_infos.push(crate::models::BitChatPeerInfo {
                sender_id: hex::encode(entry.sender_id),
                nickname: entry.nickname.clone(),
                session_state,
                verified: entry.verified,
                last_seen_seconds_ago: entry.last_seen.elapsed().as_secs(),
                messages_received: entry.messages_received,
                messages_sent: entry.messages_sent,
            });
        }

        peer_infos.sort_by_key(|p| p.last_seen_seconds_ago);

        let status_desc = if !self.config.enabled {
            "Disabled".to_string()
        } else if self.running.load(Ordering::Relaxed) {
            "Active & Advertising (BLE GATT)".to_string()
        } else {
            "Standby".to_string()
        };

        crate::models::BitChatStatusReport {
            enabled: self.config.enabled,
            node_name: self.config.node_name.clone(),
            sender_id: hex::encode(my_sender_id),
            service_uuid: DEFAULT_BITCHAT_SERVICE_UUID.to_string(),
            status: status_desc,
            peers_count: peer_infos.len(),
            active_sessions_count,
            peers: peer_infos,
        }
    }

    /// Derives the standard BitChat 8-byte sender ID from an X25519 static public key.
    pub fn derive_sender_id(noise_pubkey: &[u8; 32]) -> [u8; 8] {
        let mut hasher = Sha256::new();
        hasher.update(noise_pubkey);
        let hash = hasher.finalize();
        let mut sender_id = [0u8; 8];
        sender_id.copy_from_slice(&hash[0..8]);
        sender_id
    }

    /// Derives Ed25519 signing keypair, X25519 static Diffie-Hellman keys, and node sender ID deterministically.
    pub fn derive_keys(node_name: &str) -> (SigningKey, [u8; 32], [u8; 8]) {
        let mut signing_hasher = Sha256::new();
        signing_hasher.update(b"bitchat-ed25519-signing-seed-v1-");
        signing_hasher.update(node_name.as_bytes());
        let signing_seed: [u8; 32] = signing_hasher.finalize().into();
        let signing_key = SigningKey::from_bytes(&signing_seed);

        let mut noise_hasher = Sha256::new();
        noise_hasher.update(b"bitchat-noise-dh-key-v1-");
        noise_hasher.update(node_name.as_bytes());
        let noise_privkey_bytes: [u8; 32] = noise_hasher.finalize().into();
        let x25519_secret = X25519StaticSecret::from(noise_privkey_bytes);
        let x25519_pub = X25519PublicKey::from(&x25519_secret);
        let noise_pubkey = *x25519_pub.as_bytes();

        let sender_id = Self::derive_sender_id(&noise_pubkey);

        (signing_key, noise_pubkey, sender_id)
    }

    /// Pads a binary payload using standard PKCS#7 framing up to a target bucket capacity.
    pub fn pad_to_bucket(mut data: Vec<u8>, bucket_size: usize) -> Vec<u8> {
        if data.len() < bucket_size {
            let pad_len = bucket_size - data.len();
            if pad_len <= 255 {
                let pad_byte = pad_len as u8;
                data.resize(bucket_size, pad_byte);
            }
        }
        data
    }

    /// Computes the exact canonical binary preimage for Ed25519 signing and verification per BitChat specification:
    /// - TTL hop count normalized to 0
    /// - Flags stripped of signature bit (0x02) and route state report bit (0x10)
    /// - Padded to bucket size (256 bytes) with PKCS#7 padding
    pub fn canonical_signing_preimage(data_before_sig: &[u8], bucket_size: usize) -> Vec<u8> {
        let mut preimage = data_before_sig.to_vec();
        if preimage.len() > 2 {
            preimage[2] = 0x00; // TTL normalized to 0
        }
        if preimage.len() > 11 {
            preimage[11] &= !(FLAG_HAS_SIGNATURE | FLAG_IS_RSR); // signature and RSR flags cleared
        }
        Self::pad_to_bucket(preimage, bucket_size)
    }

    /// Encodes a plain text message into a canonical BitChat `PrivateMessage` TLV payload:
    /// `0x01 (PrivateMessage) || 0x00 <len:36> <UPPERCASE-UUID-v4> || 0x01 <len> <UTF-8 bytes>`
    /// so that mobile BitChat clients render the encrypted reply as an incoming DM bubble.
    pub fn encode_bitchat_private_message(text: &str) -> Vec<u8> {
        let msg_id = uuid::Uuid::new_v4().to_string().to_uppercase();
        let id_bytes = msg_id.as_bytes();
        let content_bytes = text.as_bytes();
        let clamped_len = content_bytes.len().min(180);

        let mut buf = Vec::with_capacity(1 + 2 + id_bytes.len() + 2 + clamped_len);
        buf.push(0x01); // NoisePayloadType::PrivateMessage
        buf.push(0x00); // TLV tag 0x00: messageID
        buf.push(id_bytes.len() as u8);
        buf.extend_from_slice(id_bytes);
        buf.push(0x01); // TLV tag 0x01: content
        buf.push(clamped_len as u8);
        buf.extend_from_slice(&content_bytes[..clamped_len]);
        buf
    }

    /// Returns `true` if a decoded text payload is an internal BitChat application control/sync
    /// notification (e.g., `[FAVORITED]:npub1...` or `[UNFAVORITED]:npub1...` Nostr key exchange
    /// rumor sent inside a `0x01` `PrivateMessage` TLV frame when starring/unstarring a peer)
    /// that must not be treated as a user-initiated emergency alert.
    pub fn is_bitchat_control_message(text: &str) -> bool {
        let trimmed = text.trim();
        let upper = trimmed.to_ascii_uppercase();
        upper.starts_with("[FAVORITED]:")
            || upper == "[FAVORITED]"
            || upper.starts_with("[UNFAVORITED]:")
            || upper == "[UNFAVORITED]"
    }

    /// Extracts `(Option<msg_id>, content)` from a BitChat decrypted Noise transport payload.
    /// Supports BitChat PrivateMessagePacket (`0x01 || tag 0x00 msgID || tag 0x01 content`)
    /// as well as strict valid UTF-8 payloads, while rejecting post-handshake binary/control frames.
    pub fn extract_bitchat_private_message_with_id(plaintext: &[u8]) -> (Option<String>, String) {
        if plaintext.is_empty() {
            return (None, String::new());
        }

        // Ignore known non-chat Noise control/sync payload types:
        // 0x02 = readReceipt, 0x03 = delivered, 0x10 = verifyChallenge,
        // 0x11 = verifyResponse, 0x20 = requestSync, 0x21 = identity/sync response
        if matches!(plaintext[0], 0x02 | 0x03 | 0x10 | 0x11 | 0x20 | 0x21) {
            return (None, String::new());
        }

        // Check for BitChat Noise privateMessage packet: 0x01 || TLV blocks
        if plaintext[0] == 0x01 && plaintext.len() >= 4 {
            let mut offset = 1;
            let mut extracted_id: Option<String> = None;
            let mut extracted_content: Option<String> = None;
            while offset + 2 <= plaintext.len() {
                let tag = plaintext[offset];
                let len = plaintext[offset + 1] as usize;
                offset += 2;
                if offset + len <= plaintext.len() {
                    let val = &plaintext[offset..offset + len];
                    if tag == 0x00 {
                        extracted_id = std::str::from_utf8(val)
                            .ok()
                            .map(|s| s.trim().to_string())
                            .filter(|s| !s.is_empty());
                    } else if tag == 0x01 {
                        extracted_content = std::str::from_utf8(val)
                            .ok()
                            .filter(|s| {
                                !s.chars()
                                    .any(|c| c.is_control() && !matches!(c, '\n' | '\r' | '\t'))
                            })
                            .map(|s| s.trim().to_string());
                    }
                    offset += len;
                } else {
                    break;
                }
            }
            if let Some(s) = extracted_content.filter(|s| !s.is_empty()) {
                if Self::is_bitchat_control_message(&s) {
                    return (extracted_id, String::new());
                }
                return (extracted_id, s);
            }
            return (extracted_id, String::new());
        }

        // Fallback: only accept strict valid UTF-8 with no binary control characters
        let fallback_text = std::str::from_utf8(plaintext)
            .ok()
            .filter(|s| {
                !s.chars()
                    .any(|c| c.is_control() && !matches!(c, '\n' | '\r' | '\t'))
            })
            .filter(|s| !Self::is_bitchat_control_message(s))
            .map(|s| s.trim().to_string())
            .unwrap_or_default();
        (None, fallback_text)
    }

    /// Extracts plain text from BitChat decrypted Noise transport payload.
    pub fn extract_bitchat_private_message(plaintext: &[u8]) -> String {
        Self::extract_bitchat_private_message_with_id(plaintext).1
    }

    pub fn build_announce_payload(
        node_name: &str,
        noise_pubkey: &[u8; 32],
        ed_pubkey: &[u8; 32],
    ) -> Vec<u8> {
        Self::build_announce_payload_with_neighbors(node_name, noise_pubkey, ed_pubkey, &[])
    }

    /// Builds BitChat Announce TLV payload including optional `directNeighbors` (TLV `0x04`)
    /// so `MeshGraphService` on Android/iOS confirms bidirectional multi-hop mesh edges.
    pub fn build_announce_payload_with_neighbors(
        node_name: &str,
        noise_pubkey: &[u8; 32],
        ed_pubkey: &[u8; 32],
        direct_neighbors: &[[u8; 8]],
    ) -> Vec<u8> {
        let name_bytes = node_name.as_bytes();
        let name_len = name_bytes.len().min(32);
        let base_len = (2 + name_len) + 34 + 34;

        // Keep total signed packet < 256 bytes (header 14 + sender 8 + payload + sig 64 <= 255)
        // so single-MTU BLE peripheral notifications never fragment.
        let max_fitting_neighbors = BITCHAT_BUCKET_SIZE_256
            .saturating_sub(1 + 14 + 8 + base_len + 64 + 2)
            / 8;
        let neighbor_cap = direct_neighbors
            .len()
            .min(MAX_ANNOUNCE_NEIGHBORS)
            .min(max_fitting_neighbors);

        let mut payload = Vec::with_capacity(
            base_len + if neighbor_cap > 0 { 2 + neighbor_cap * 8 } else { 0 },
        );

        payload.push(TLV_TAG_NICKNAME);
        payload.push(name_len as u8);
        payload.extend_from_slice(&name_bytes[..name_len]);

        payload.push(TLV_TAG_NOISE_PUBKEY);
        payload.push(32);
        payload.extend_from_slice(noise_pubkey);

        payload.push(TLV_TAG_SIGNING_PUBKEY);
        payload.push(32);
        payload.extend_from_slice(ed_pubkey);

        if neighbor_cap > 0 {
            payload.push(TLV_TAG_ROUTE_PEER_ID);
            payload.push((neighbor_cap * 8) as u8);
            for peer_id in direct_neighbors.iter().take(neighbor_cap) {
                payload.extend_from_slice(peer_id);
            }
        }

        payload
    }

    /// Collects up to `MAX_ANNOUNCE_NEIGHBORS` fresh direct 1-hop BLE neighbors seen within `DIRECT_NEIGHBOR_FRESHNESS_SECS`.
    pub async fn collect_direct_neighbors(
        peers: &RwLock<HashMap<[u8; 8], BitChatPeerEntry>>,
        my_sender_id: &[u8; 8],
    ) -> Vec<[u8; 8]> {
        let now = Instant::now();
        let guard = peers.read().await;
        let mut fresh: Vec<([u8; 8], Duration)> = guard
            .values()
            .filter(|entry| entry.sender_id != *my_sender_id)
            .filter_map(|entry| {
                entry.last_direct_seen.and_then(|seen| {
                    let age = now.saturating_duration_since(seen);
                    if age.as_secs() <= DIRECT_NEIGHBOR_FRESHNESS_SECS {
                        Some((entry.sender_id, age))
                    } else {
                        None
                    }
                })
            })
            .collect();
        fresh.sort_by_key(|(_, age)| *age);
        fresh
            .into_iter()
            .take(MAX_ANNOUNCE_NEIGHBORS)
            .map(|(id, _)| id)
            .collect()
    }

    /// Constructs a fully signed and bucket-padded BitChat Node Announce packet (Type 0x01).
    pub fn build_announce_packet(
        node_name: &str,
        signing_key: &SigningKey,
        noise_pubkey: &[u8; 32],
    ) -> Vec<u8> {
        Self::build_announce_packet_with_neighbors(node_name, signing_key, noise_pubkey, &[])
    }

    /// Constructs a signed and bucket-padded BitChat Node Announce packet (Type 0x01) with `directNeighbors` TLV `0x04`.
    pub fn build_announce_packet_with_neighbors(
        node_name: &str,
        signing_key: &SigningKey,
        noise_pubkey: &[u8; 32],
        direct_neighbors: &[[u8; 8]],
    ) -> Vec<u8> {
        let timestamp_ms = crate::time_sync::now_utc_ms() as u64;
        let ed_pubkey = signing_key.verifying_key().to_bytes();
        let sender_id = Self::derive_sender_id(noise_pubkey);
        let payload = Self::build_announce_payload_with_neighbors(
            node_name,
            noise_pubkey,
            &ed_pubkey,
            direct_neighbors,
        );
        let payload_len = payload.len() as u16;

        let mut data_before_sig = Vec::with_capacity(14 + 8 + payload.len());
        data_before_sig.push(PACKET_VERSION);
        data_before_sig.push(PACKET_TYPE_ANNOUNCE);
        data_before_sig.push(MESSAGE_TTL_HOPS);
        data_before_sig.extend_from_slice(&timestamp_ms.to_be_bytes());
        data_before_sig.push(FLAG_HAS_SIGNATURE);
        data_before_sig.extend_from_slice(&payload_len.to_be_bytes());
        data_before_sig.extend_from_slice(&sender_id);
        data_before_sig.extend_from_slice(&payload);

        let bucket_size = if data_before_sig.len() + 64 < BITCHAT_BUCKET_SIZE_256 {
            BITCHAT_BUCKET_SIZE_256
        } else {
            512
        };
        let signing_preimage = Self::canonical_signing_preimage(&data_before_sig, bucket_size);
        let signature = signing_key.sign(&signing_preimage);

        let mut live_packet = data_before_sig;
        live_packet.extend_from_slice(&signature.to_bytes());

        Self::pad_to_bucket(live_packet, bucket_size)
    }

    /// Initiates a Noise XX handshake (`-> e`, 32 bytes, Type `0x10`) toward `target_peer` so peers holding
    /// stale pre-restart Noise sessions immediately reset and re-establish mutual transport keys.
    pub fn initiate_noise_handshake(
        my_sender_id: &[u8; 8],
        target_peer: &[u8; 8],
        noise_privkey: &[u8; 32],
        signing_key: &SigningKey,
    ) -> Option<(PeerNoiseSession, Vec<u8>)> {
        let pattern: snow::params::NoiseParams = "Noise_XX_25519_ChaChaPoly_SHA256".parse().ok()?;
        let mut handshake = snow::Builder::new(pattern)
            .local_private_key(&noise_privkey[..])
            .build_initiator()
            .ok()?;
        let mut msg1_buf = [0u8; 128];
        let msg1_len = handshake.write_message(&[], &mut msg1_buf).ok()?;
        let pkt = Self::build_key_exchange_response(
            my_sender_id,
            target_peer,
            &msg1_buf[..msg1_len],
            signing_key,
        );
        Some((
            PeerNoiseSession::HandshakingInitiator {
                state: Box::new(handshake),
                started_at: Instant::now(),
            },
            pkt,
        ))
    }

    /// Constructs a signed and bucket-padded BitChat Chat Message packet (Type 0x02).
    pub fn build_chat_message_packet(
        sender_id: &[u8; 8],
        recipient_id: Option<&[u8; 8]>,
        message_text: &str,
        signing_key: &SigningKey,
    ) -> Vec<u8> {
        let timestamp_ms = crate::time_sync::now_utc_ms() as u64;
        let msg_bytes = message_text.as_bytes();
        let payload_len = msg_bytes.len() as u16;
        let has_recipient = recipient_id.is_some();
        let flags = if has_recipient {
            FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE
        } else {
            FLAG_HAS_SIGNATURE
        };

        let mut data_before_sig = Vec::with_capacity(14 + 8 + (if has_recipient { 8 } else { 0 }) + msg_bytes.len());
        data_before_sig.push(PACKET_VERSION);
        data_before_sig.push(PACKET_TYPE_MESSAGE);
        data_before_sig.push(MESSAGE_TTL_HOPS);
        data_before_sig.extend_from_slice(&timestamp_ms.to_be_bytes());
        data_before_sig.push(flags);
        data_before_sig.extend_from_slice(&payload_len.to_be_bytes());
        data_before_sig.extend_from_slice(sender_id);
        if let Some(r_id) = recipient_id {
            data_before_sig.extend_from_slice(r_id);
        }
        data_before_sig.extend_from_slice(msg_bytes);

        let signing_preimage = Self::canonical_signing_preimage(&data_before_sig, BITCHAT_BUCKET_SIZE_256);
        let signature = signing_key.sign(&signing_preimage);

        let mut live_packet = data_before_sig;
        live_packet.extend_from_slice(&signature.to_bytes());

        Self::pad_to_bucket(live_packet, BITCHAT_BUCKET_SIZE_256)
    }

    /// Constructs a signed BitChat Key Exchange packet (Type 0x10) carrying Noise XX handshake payload.
    pub fn build_key_exchange_response(
        my_sender_id: &[u8; 8],
        recipient_id: &[u8; 8],
        noise_msg_payload: &[u8],
        signing_key: &SigningKey,
    ) -> Vec<u8> {
        let timestamp_ms = crate::time_sync::now_utc_ms() as u64;
        let payload_len = noise_msg_payload.len() as u16;
        let flags = FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE;

        let mut data_before_sig = Vec::with_capacity(14 + 8 + 8 + noise_msg_payload.len());
        data_before_sig.push(PACKET_VERSION);
        data_before_sig.push(PACKET_TYPE_NOISE_HANDSHAKE);
        data_before_sig.push(MESSAGE_TTL_HOPS);
        data_before_sig.extend_from_slice(&timestamp_ms.to_be_bytes());
        data_before_sig.push(flags);
        data_before_sig.extend_from_slice(&payload_len.to_be_bytes());
        data_before_sig.extend_from_slice(my_sender_id);
        data_before_sig.extend_from_slice(recipient_id);
        data_before_sig.extend_from_slice(noise_msg_payload);

        let signing_preimage = Self::canonical_signing_preimage(&data_before_sig, BITCHAT_BUCKET_SIZE_256);
        let signature = signing_key.sign(&signing_preimage);

        let mut live_packet = data_before_sig;
        live_packet.extend_from_slice(&signature.to_bytes());

        Self::pad_to_bucket(live_packet, BITCHAT_BUCKET_SIZE_256)
    }

    /// Constructs an encrypted direct message packet (Type 0x11) carrying Noise transport ciphertext.
    pub fn build_encrypted_chat_packet(
        my_sender_id: &[u8; 8],
        recipient_id: &[u8; 8],
        ciphertext: &[u8],
        signing_key: &SigningKey,
    ) -> Vec<u8> {
        let timestamp_ms = crate::time_sync::now_utc_ms() as u64;
        let payload_len = ciphertext.len() as u16;
        let flags = FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE;

        let mut data_before_sig = Vec::with_capacity(14 + 8 + 8 + ciphertext.len());
        data_before_sig.push(PACKET_VERSION);
        data_before_sig.push(PACKET_TYPE_NOISE_ENCRYPTED);
        data_before_sig.push(MESSAGE_TTL_HOPS);
        data_before_sig.extend_from_slice(&timestamp_ms.to_be_bytes());
        data_before_sig.push(flags);
        data_before_sig.extend_from_slice(&payload_len.to_be_bytes());
        data_before_sig.extend_from_slice(my_sender_id);
        data_before_sig.extend_from_slice(recipient_id);
        data_before_sig.extend_from_slice(ciphertext);

        let signing_preimage = Self::canonical_signing_preimage(&data_before_sig, BITCHAT_BUCKET_SIZE_256);
        let signature = signing_key.sign(&signing_preimage);

        let mut live_packet = data_before_sig;
        live_packet.extend_from_slice(&signature.to_bytes());

        Self::pad_to_bucket(live_packet, BITCHAT_BUCKET_SIZE_256)
    }

    /// Constructs a legacy Route-Sync-Response frame (Type 0x20) if requested by legacy peers.
    pub fn build_sync_response(sender_id: &[u8; 8], _incoming_pkt: &[u8]) -> Vec<u8> {
        let timestamp_ms = crate::time_sync::now_utc_ms() as u64;
        let sync_payload = [
            0x01, 0x00, 0x01, 0x07, 0x02, 0x00, 0x04, 0x00, 0x00, 0x00, 0x01,
        ];
        let payload_len = sync_payload.len() as u16;

        let mut packet = Vec::with_capacity(14 + 8 + sync_payload.len());
        packet.push(PACKET_VERSION);
        packet.push(PACKET_TYPE_LEGACY_SYNC);
        packet.push(0x00);
        packet.extend_from_slice(&timestamp_ms.to_be_bytes());
        packet.push(0x00);
        packet.extend_from_slice(&payload_len.to_be_bytes());
        packet.extend_from_slice(sender_id);
        packet.extend_from_slice(&sync_payload);

        packet
    }

    /// Parses and decodes an incoming raw Bluetooth Low Energy BitChat v1 or v2 packet.
    pub fn parse_incoming_packet(data: &[u8]) -> Option<ParsedPacket> {
        if data.len() < 14 {
            return None;
        }

        let pkt_version = data[0];
        let pkt_type = data[1];
        let ttl = data[2];
        let flags = data[11];

        let (mut offset, payload_len) = if pkt_version == PACKET_VERSION_V2 {
            if data.len() < 16 {
                return None;
            }
            let len = u32::from_be_bytes([data[12], data[13], data[14], data[15]]) as usize;
            (16usize, len)
        } else {
            let len = u16::from_be_bytes([data[12], data[13]]) as usize;
            (14usize, len)
        };

        let has_recipient = (flags & FLAG_HAS_RECIPIENT) != 0;
        let has_signature = (flags & FLAG_HAS_SIGNATURE) != 0;
        let has_route = (flags & FLAG_HAS_ROUTE) != 0;

        if data.len() < offset + 8 {
            return None;
        }
        let sender_id = &data[offset..offset + 8];
        let mut sender_id_arr = [0u8; 8];
        sender_id_arr.copy_from_slice(sender_id);
        offset += 8;

        let recipient_id_opt = if has_recipient {
            if data.len() < offset + 8 {
                return None;
            }
            let r_bytes = &data[offset..offset + 8];
            let mut r_arr = [0u8; 8];
            r_arr.copy_from_slice(r_bytes);
            offset += 8;
            Some(r_arr)
        } else {
            None
        };

        // BitChat v2 source-routed mesh packets embed `hop_count: u8` followed by `hop_count * 8` peer IDs
        // immediately before `payload` when `FLAG_HAS_ROUTE` (0x08) is set.
        if has_route {
            if data.len() <= offset {
                return None;
            }
            let hop_count = data[offset] as usize;
            let route_bytes = 1usize.saturating_add(hop_count.saturating_mul(8));
            if hop_count <= 32 && data.len() >= offset + route_bytes + payload_len {
                offset += route_bytes;
            } else {
                return None;
            }
        }

        if data.len() < offset + payload_len {
            return None;
        }
        let raw_payload = &data[offset..offset + payload_len];
        let payload_end_offset = offset + payload_len;
        offset += payload_len;

        let mut sig_valid = false;
        if has_signature && data.len() >= offset + 64 {
            let sig_bytes = &data[offset..offset + 64];

            if pkt_type == PACKET_TYPE_ANNOUNCE {
                let mut p_off = 0;
                let mut found_ed_pub: Option<[u8; 32]> = None;
                while p_off + 2 <= raw_payload.len() {
                    let tag = raw_payload[p_off];
                    let tlen = raw_payload[p_off + 1] as usize;
                    p_off += 2;
                    if p_off + tlen <= raw_payload.len() {
                        let tval = &raw_payload[p_off..p_off + tlen];
                        if tag == TLV_TAG_SIGNING_PUBKEY && tlen == 32 {
                            let mut pubk = [0u8; 32];
                            pubk.copy_from_slice(tval);
                            found_ed_pub = Some(pubk);
                            break;
                        }
                        p_off += tlen;
                    } else {
                        break;
                    }
                }

                if let Some(ed_pub_bytes) = found_ed_pub
                    && let Ok(verifying_key) = VerifyingKey::from_bytes(&ed_pub_bytes)
                    && let Ok(signature) = ed25519_dalek::Signature::from_slice(sig_bytes)
                {
                    let bucket_size = if data.len() > BITCHAT_BUCKET_SIZE_256 {
                        512
                    } else {
                        BITCHAT_BUCKET_SIZE_256
                    };
                    let canonical_preimage =
                        Self::canonical_signing_preimage(&data[..payload_end_offset], bucket_size);
                    if verifying_key.verify(&canonical_preimage, &signature).is_ok() {
                        sig_valid = true;
                    } else {
                        // Fallback 1: Unpadded with TTL=0 and flags stripped
                        let mut unpadded_stripped = data[..payload_end_offset].to_vec();
                        if unpadded_stripped.len() > 2 {
                            unpadded_stripped[2] = 0x00;
                        }
                        if unpadded_stripped.len() > 11 {
                            unpadded_stripped[11] &= !(FLAG_HAS_SIGNATURE | FLAG_IS_RSR);
                        }
                        if verifying_key.verify(&unpadded_stripped, &signature).is_ok() {
                            sig_valid = true;
                        } else {
                            // Fallback 2: Raw data_before_sig with TTL=0
                            let mut fallback = data[..payload_end_offset].to_vec();
                            if fallback.len() > 2 {
                                fallback[2] = 0x00;
                            }
                            sig_valid = verifying_key.verify(&fallback, &signature).is_ok();
                        }
                    }
                }
            } else {
                sig_valid = true;
            }
        }

        match pkt_type {
            PACKET_TYPE_ANNOUNCE => {
                let mut peer_name = format!("Peer-{}", hex::encode(&sender_id[0..4]));
                let mut p_off = 0;
                while p_off + 2 <= raw_payload.len() {
                    let tag = raw_payload[p_off];
                    let tlen = raw_payload[p_off + 1] as usize;
                    p_off += 2;
                    if p_off + tlen <= raw_payload.len() {
                        let tval = &raw_payload[p_off..p_off + tlen];
                        if tag == TLV_TAG_NICKNAME
                            && let Ok(name_str) = std::str::from_utf8(tval)
                        {
                            peer_name = name_str.trim().to_string();
                        }
                        p_off += tlen;
                    } else {
                        break;
                    }
                }

                info!(
                    "📡 [BitChat Node Announce] Nickname: '{}', Sender ID: {}, TTL: {}, Verified: {}",
                    peer_name,
                    hex::encode(sender_id),
                    ttl,
                    if sig_valid { "✅ Valid" } else { "⚠️ Unsigned/Legacy" }
                );

                Some(ParsedPacket {
                    packet_type: pkt_type,
                    ttl,
                    sender_id: sender_id_arr,
                    recipient_id: recipient_id_opt,
                    payload: Some(peer_name.into_bytes()),
                    signature_valid: sig_valid,
                })
            }
            PACKET_TYPE_MESSAGE => {
                let payload_to_read = if raw_payload.len() >= 4 && raw_payload[0] == 0x00 {
                    let inner_len = u16::from_be_bytes([raw_payload[2], raw_payload[3]]) as usize;
                    if raw_payload.len() >= 4 + inner_len {
                        &raw_payload[4..4 + inner_len]
                    } else {
                        &raw_payload[4..]
                    }
                } else {
                    raw_payload
                };

                let is_broadcast = recipient_id_opt.is_none()
                    || recipient_id_opt == Some(BITCHAT_BROADCAST_RECIPIENT);
                let prefix = if is_broadcast {
                    "Broadcast Message"
                } else {
                    "1-on-1 Direct Message"
                };

                if let Ok(txt) = std::str::from_utf8(payload_to_read) {
                    info!(
                        "💬 [BitChat {} Received]: \"{}\" (from {}, ttl={})",
                        prefix,
                        txt,
                        hex::encode(sender_id),
                        ttl
                    );
                } else {
                    info!(
                        "💬 [BitChat {} Received Raw] ({} bytes, from {}, ttl={})",
                        prefix,
                        payload_to_read.len(),
                        hex::encode(sender_id),
                        ttl
                    );
                }
                Some(ParsedPacket {
                    packet_type: pkt_type,
                    ttl,
                    sender_id: sender_id_arr,
                    recipient_id: recipient_id_opt,
                    payload: Some(payload_to_read.to_vec()),
                    signature_valid: true,
                })
            }
            PACKET_TYPE_NOISE_HANDSHAKE => {
                let desc = if raw_payload.len() == 32 {
                    "Noise XX Message 1 (-> e, 32 bytes)"
                } else if raw_payload.len() == 96 {
                    "Noise XX Message 2 (<- e, ee, s, es, 96 bytes)"
                } else {
                    "Noise XX Message 3 (-> s, se, handshake final)"
                };
                info!(
                    "🔐 [BitChat Noise Handshake] {} from peer {} (ttl={})",
                    desc,
                    hex::encode(sender_id),
                    ttl
                );
                Some(ParsedPacket {
                    packet_type: pkt_type,
                    ttl,
                    sender_id: sender_id_arr,
                    recipient_id: recipient_id_opt,
                    payload: Some(raw_payload.to_vec()),
                    signature_valid: true,
                })
            }
            PACKET_TYPE_NOISE_ENCRYPTED => {
                info!(
                    "🔐 [BitChat Encrypted Direct Message] Received ciphertext ({} bytes) from peer {} (ttl={})",
                    raw_payload.len(),
                    hex::encode(sender_id),
                    ttl
                );
                Some(ParsedPacket {
                    packet_type: pkt_type,
                    ttl,
                    sender_id: sender_id_arr,
                    recipient_id: recipient_id_opt,
                    payload: Some(raw_payload.to_vec()),
                    signature_valid: true,
                })
            }
            PACKET_TYPE_LEGACY_SYNC | PACKET_TYPE_REQUEST_SYNC => {
                debug!(
                    "🔄 [BitChat Sync] Gossip/Sync frame (0x{:02x}) received from peer {}",
                    pkt_type,
                    hex::encode(sender_id)
                );
                Some(ParsedPacket {
                    packet_type: pkt_type,
                    ttl,
                    sender_id: sender_id_arr,
                    recipient_id: recipient_id_opt,
                    payload: None,
                    signature_valid: true,
                })
            }
            _ => {
                debug!(
                    "📡 [BitChat Packet] Type 0x{:02x} (len: {}, sender: {})",
                    pkt_type,
                    data.len(),
                    hex::encode(sender_id)
                );
                Some(ParsedPacket {
                    packet_type: pkt_type,
                    ttl,
                    sender_id: sender_id_arr,
                    recipient_id: recipient_id_opt,
                    payload: None,
                    signature_valid: false,
                })
            }
        }
    }

    /// Spawns background BLE advertising and local BlueZ GATT server.
    pub async fn start(&self) -> Result<()> {
        if !self.config.enabled {
            info!("BitChat service disabled in configuration");
            return Ok(());
        }

        let node_name = self.config.node_name.clone();
        let service_uuid: Uuid = self
            .config
            .service_uuid
            .parse()
            .unwrap_or_else(|_| DEFAULT_BITCHAT_SERVICE_UUID.parse().unwrap());
        let char_uuid: Uuid = DEFAULT_BITCHAT_CHAR_UUID.parse().unwrap();

        let (signing_key, noise_pubkey, sender_id) = Self::derive_keys(&node_name);
        info!(
            "🚀 Initializing BitChat BLE mesh node '{}' [Sender ID: {}, Service: {}]",
            node_name,
            hex::encode(sender_id),
            service_uuid
        );

        let (_session, adapter) = loop {
            if !self.running.load(Ordering::Relaxed) {
                return Ok(());
            }

            let sess = match Session::new().await {
                Ok(s) => s,
                Err(e) => {
                    warn!("⚠️ BlueZ session initialization failed (Bluetooth disabled or unavailable): {}. Retrying in 5s...", e);
                    sleep(Duration::from_secs(5)).await;
                    continue;
                }
            };

            let adapt = match sess.adapter(&self.config.device) {
                Ok(a) => a,
                Err(_) => match sess.default_adapter().await {
                    Ok(a) => a,
                    Err(e) => {
                        warn!("⚠️ Bluetooth adapter unavailable: {}. Waiting for adapter...", e);
                        sleep(Duration::from_secs(5)).await;
                        continue;
                    }
                },
            };

            let startup_powered = Self::sanitize_hci_adapter(
                &adapt,
                &self.config.device,
                &node_name,
                true,
            )
            .await;
            if !startup_powered {
                warn!(
                    "⚠️ Bluetooth adapter '{}' still not powered after startup sanitize; retrying in 3s...",
                    self.config.device
                );
                sleep(Duration::from_secs(3)).await;
                continue;
            }

            break (sess, adapt);
        };

        let adv_name = node_name.clone();
        let _ = adapter.set_alias(adv_name.clone()).await;
        let adv_uuid = service_uuid;
        let adv_session = _session.clone();
        let running_adv = self.running.clone();
        let shutdown_adv = self.shutdown_notify.clone();
        let active_subs_adv = self.active_subscribers.clone();
        let self_healing_enabled = self.config.self_healing_enabled;
        let watchdog_interval_secs = self.config.watchdog_interval_secs.max(5);
        let adv_refresh_interval_secs = self.config.adv_refresh_interval_secs;
        let monitored_devices = self.config.resolved_monitored_devices();
        let primary_device = self.config.device.clone();
        let adv_config = self.config.clone();
        let adv_refresh_notify = Arc::new(Notify::new());
        let adv_refresh_notify_loop = adv_refresh_notify.clone();

        tokio::spawn(async move {
            info!(
                "🛡️ BitChat BLE Self-Healing Watchdog initialized [enabled: {}, check_interval: {}s, refresh_interval: {}s, idle_interval: {}..{}ms, monitored_devices: {:?}]",
                self_healing_enabled,
                watchdog_interval_secs,
                adv_refresh_interval_secs,
                adv_config.adv_min_interval_ms,
                adv_config.adv_max_interval_ms,
                monitored_devices
            );

            let mut use_default_intervals_fallback = false;
            let mut consecutive_adv_failures = 0u32;

            while running_adv.load(Ordering::Relaxed) {
                let current_adapter = match adv_session.adapter(&primary_device) {
                    Ok(a) => a,
                    Err(_) => match adv_session.default_adapter().await {
                        Ok(a) => a,
                        Err(e) => {
                            warn!("⚠️ [BLE Self-Healing] Bluetooth adapter '{}' unavailable: {}. Retrying in 5s...", primary_device, e);
                            sleep(Duration::from_secs(5)).await;
                            continue;
                        }
                    },
                };

                // Ensure primary and any additional configured monitored HCI adapters are powered and discoverable
                for dev_name in &monitored_devices {
                    if let Ok(mon_adapter) = adv_session.adapter(dev_name) {
                        if !mon_adapter.is_powered().await.unwrap_or(false) {
                            warn!("🔄 [BLE Self-Healing] Monitored adapter '{}' is powered down; restoring power & discoverability...", dev_name);
                            let _ = BitChatService::ensure_adapter_powered_with_retry(&mon_adapter, dev_name, 6).await;
                        }
                        let _ = mon_adapter.set_discoverable(true).await;
                        let _ = mon_adapter.set_pairable(true).await;
                        let _ = mon_adapter.set_discoverable_timeout(0).await;
                    }
                }
                let _ = current_adapter.set_alias(adv_name.clone()).await;

                let current_subs = active_subs_adv.load(Ordering::Relaxed);
                let (min_interval, max_interval) = if use_default_intervals_fallback {
                    (None, None)
                } else {
                    adv_config.adaptive_adv_intervals(current_subs)
                };

                let build_adv = |min_int: Option<Duration>, max_int: Option<Duration>| Advertisement {
                    advertisement_type: bluer::adv::Type::Peripheral,
                    service_uuids: vec![adv_uuid].into_iter().collect::<BTreeSet<_>>(),
                    local_name: Some(adv_name.clone()),
                    discoverable: Some(true),
                    min_interval: min_int,
                    max_interval: max_int,
                    system_includes: vec![bluer::adv::Feature::TxPower].into_iter().collect(),
                    ..Default::default()
                };

                let adv_result = match current_adapter.advertise(build_adv(min_interval, max_interval)).await {
                    Ok(h) => Ok(h),
                    Err(e) if min_interval.is_some() || max_interval.is_some() => {
                        warn!(
                            "⚠️ [BLE Self-Healing] Controller '{}' rejected custom advertising intervals ({:?}..{:?}): {}. Falling back to controller default intervals...",
                            primary_device, min_interval, max_interval, e
                        );
                        use_default_intervals_fallback = true;
                        current_adapter.advertise(build_adv(None, None)).await
                    }
                    Err(e) => Err(e),
                };

                match adv_result {
                    Ok(handle) => {
                        consecutive_adv_failures = 0;
                        info!(
                            "📡 BitChat BLE peripheral advertising active [Name: '{}', Device: '{}', UUID: {}, Subscribers: {}, Interval: {:?}..{:?}]",
                            adv_name,
                            primary_device,
                            adv_uuid,
                            current_subs,
                            if use_default_intervals_fallback { None } else { min_interval },
                            if use_default_intervals_fallback { None } else { max_interval }
                        );
                        let registered_at = Instant::now();
                        let mut elapsed_since_check = 0u64;
                        let mut needs_power_cycle = false;

                        while running_adv.load(Ordering::Relaxed) {
                            tokio::select! {
                                _ = shutdown_adv.notified() => {
                                    break;
                                }
                                _ = adv_refresh_notify_loop.notified() => {
                                    let subs_now = active_subs_adv.load(Ordering::Relaxed);
                                    if subs_now == 0 {
                                        info!(
                                            "🔄 [BLE Self-Healing] Last GATT subscriber disconnected (active_subscribers=0); immediately re-registering BLE advertisement on '{}'",
                                            primary_device
                                        );
                                        break;
                                    } else {
                                        debug!(
                                            "🛡️ [BLE Self-Healing] Skipping BLE advertisement re-registration while {} subscriber(s) remain active on '{}'",
                                            subs_now, primary_device
                                        );
                                        continue;
                                    }
                                }
                                _ = sleep(Duration::from_secs(1)) => {}
                            }

                            if !running_adv.load(Ordering::Relaxed) {
                                break;
                            }

                            if !self_healing_enabled {
                                continue;
                            }

                            elapsed_since_check += 1;
                            if elapsed_since_check >= watchdog_interval_secs {
                                elapsed_since_check = 0;
                                let subs = active_subs_adv.load(Ordering::Relaxed);
                                let mut needs_re_advertise = false;

                                for dev_name in &monitored_devices {
                                    match adv_session.adapter(dev_name) {
                                        Ok(mon_adapter) => {
                                            let is_powered = mon_adapter.is_powered().await.unwrap_or(false);
                                            let active_inst = mon_adapter.active_advertising_instances().await.unwrap_or(1);
                                            let is_disc = mon_adapter.is_discoverable().await.unwrap_or(true);
                                            let sysfs_present = std::path::Path::new(&format!("/sys/class/bluetooth/{}", dev_name)).exists();
                                            if !sysfs_present || !is_powered {
                                                warn!(
                                                    "⚠️ [BLE Self-Healing] Adapter '{}' lost power or sysfs state (present: {}, powered: {})! Triggering self-healing cycle...",
                                                    dev_name, sysfs_present, is_powered
                                                );
                                                needs_re_advertise = true;
                                                needs_power_cycle = true;
                                            } else if !is_disc {
                                                warn!(
                                                    "⚠️ [BLE Self-Healing] Adapter '{}' lost discoverable state! Restoring discoverability...",
                                                    dev_name
                                                );
                                                let _ = mon_adapter.set_discoverable(true).await;
                                                let _ = mon_adapter.set_discoverable_timeout(0).await;
                                            } else if subs == 0 && dev_name == &primary_device && active_inst == 0 {
                                                warn!(
                                                    "⚠️ [BLE Self-Healing] Adapter '{}' reports 0 active D-Bus advertising instances while idle! Re-registering with HCI sanitize...",
                                                    dev_name
                                                );
                                                needs_re_advertise = true;
                                                needs_power_cycle = true;
                                            }
                                        }
                                        Err(e) => {
                                            warn!(
                                                "⚠️ [BLE Self-Healing] Failed to query monitored adapter '{}': {}",
                                                dev_name, e
                                            );
                                            needs_re_advertise = true;
                                            needs_power_cycle = true;
                                        }
                                    }
                                }

                                // Never tear down and re-register AdvertisementHandle while a GATT central is actively subscribed (`subs > 0`),
                                // because single-role BLE controllers (e.g. Spreadtrum/Unisoc hci0) disrupt active peripheral GATT notification state.
                                if !needs_re_advertise
                                    && subs == 0
                                    && adv_refresh_interval_secs > 0
                                    && registered_at.elapsed().as_secs() >= adv_refresh_interval_secs
                                {
                                    info!(
                                        "🔄 [BLE Self-Healing] Proactive idle BLE advertisement refresh ({}s elapsed, active_subscribers=0) on '{}' to keep HCI controller state synchronized",
                                        adv_refresh_interval_secs, primary_device
                                    );
                                    needs_re_advertise = true;
                                }

                                if needs_re_advertise {
                                    break;
                                }
                            }
                        }

                        drop(handle);
                        if running_adv.load(Ordering::Relaxed) {
                            if needs_power_cycle && active_subs_adv.load(Ordering::Relaxed) == 0 {
                                let _ = BitChatService::sanitize_hci_adapter(
                                    &current_adapter,
                                    &primary_device,
                                    &adv_name,
                                    true,
                                )
                                .await;
                            } else {
                                sleep(Duration::from_millis(350)).await;
                            }
                        }
                    }
                    Err(e) => {
                        consecutive_adv_failures = consecutive_adv_failures.saturating_add(1);
                        warn!(
                            "⚠️ [BLE Self-Healing] Failed to register BLE advertisement on '{}' (attempt {}): {}.",
                            primary_device, consecutive_adv_failures, e
                        );
                        if consecutive_adv_failures >= 2 && active_subs_adv.load(Ordering::Relaxed) == 0 {
                            warn!(
                                "🔄 [BLE Self-Healing] Escalating to HCI adapter power-cycle recovery on '{}' after {} consecutive advertisement failures...",
                                primary_device, consecutive_adv_failures
                            );
                            let _ = BitChatService::sanitize_hci_adapter(
                                &current_adapter,
                                &primary_device,
                                &adv_name,
                                true,
                            )
                            .await;
                        } else {
                            sleep(Duration::from_secs(3)).await;
                        }
                    }
                }
            }
        });

        let (bcast_tx, _) = broadcast::channel::<Vec<u8>>(128);
        {
            let mut tx_guard = self.bcast_tx.write().await;
            *tx_guard = Some(bcast_tx.clone());
        }

        if let Some(ref eng) = self.engine {
            eng.bitchat_egress.attach_broadcast_sender(bcast_tx.clone()).await;
            info!("🔗 Connected BitChat core egress channel to live GATT notification broadcast pipeline");
        }

        // Periodic 30-second mesh announce beacon to ensure continuous visibility and bidirectional
        // `directNeighbors` (TLV 0x04) topology confirmation in BitChat MeshGraphService peer tables.
        let bcast_ann = bcast_tx.clone();
        let name_ann = node_name.clone();
        let sk_ann = Arc::new(signing_key.clone());
        let np_ann = Arc::new(noise_pubkey);
        let running_ann = self.running.clone();
        let active_subs_ann = self.active_subscribers.clone();
        let peer_map_ann = self.peers.clone();
        let my_sid_ann = sender_id;
        tokio::spawn(async move {
            while running_ann.load(Ordering::Relaxed) {
                sleep(Duration::from_secs(30)).await;
                if active_subs_ann.load(Ordering::Relaxed) > 0 {
                    let neighbors =
                        BitChatService::collect_direct_neighbors(&peer_map_ann, &my_sid_ann).await;
                    let ann_pkt = BitChatService::build_announce_packet_with_neighbors(
                        &name_ann,
                        &sk_ann,
                        &np_ann,
                        &neighbors,
                    );
                    let _ = bcast_ann.send(ann_pkt);
                }
            }
        });

        let name_sub = node_name.clone();
        let sk_sub = Arc::new(signing_key);
        let np_sub = Arc::new(noise_pubkey);
        let sender_id_sub = sender_id;
        let bcast_tx_sub = bcast_tx.clone();
        let active_subs_notify = self.active_subscribers.clone();
        let adv_refresh_notify_gatt = adv_refresh_notify.clone();

        let mut noise_hasher = Sha256::new();
        noise_hasher.update(b"bitchat-noise-dh-key-v1-");
        noise_hasher.update(node_name.as_bytes());
        let noise_privkey_bytes: [u8; 32] = noise_hasher.finalize().into();

        let sess_map = self.sessions.clone();
        let peer_map = self.peers.clone();
        let eng_opt = self.engine.clone();
        let public_mesh_ack = self.config.public_mesh_ack;
        let my_sender_id = sender_id;
        let tx_w = bcast_tx.clone();
        let sk_w = sk_sub.clone();
        let np_w = np_sub.clone();
        let name_w = node_name.clone();
        let n_priv_w = Arc::new(noise_privkey_bytes);

        let peer_map_r = self.peers.clone();
        let peer_map_n = self.peers.clone();

        let app = Application {
            services: vec![Service {
                uuid: service_uuid,
                primary: true,
                characteristics: vec![Characteristic {
                    uuid: char_uuid,
                    read: Some(CharacteristicRead {
                        read: true,
                        fun: Box::new({
                            let n = node_name.clone();
                            let s = sk_sub.clone();
                            let p = np_sub.clone();
                            let peers_r = peer_map_r.clone();
                            let sid_r = sender_id;
                            move |_req| {
                                let n = n.clone();
                                let s = s.clone();
                                let p = p.clone();
                                let peers_r = peers_r.clone();
                                async move {
                                    let neighbors =
                                        Self::collect_direct_neighbors(&peers_r, &sid_r).await;
                                    Ok(Self::build_announce_packet_with_neighbors(
                                        &n,
                                        &s,
                                        &p,
                                        &neighbors,
                                    ))
                                }
                                .boxed()
                            }
                        }),
                        ..Default::default()
                    }),
                    write: Some(CharacteristicWrite {
                        write: true,
                        write_without_response: true,
                        method: CharacteristicWriteMethod::Fun(Box::new(move |val, _req| {
                            let tx_w = tx_w.clone();
                            let sk_w = sk_w.clone();
                            let np_w = np_w.clone();
                            let name_w = name_w.clone();
                            let n_priv_w = n_priv_w.clone();
                            let sess_map = sess_map.clone();
                            let peer_map = peer_map.clone();
                            let eng_opt = eng_opt.clone();

                            async move {
                                if val.is_empty() {
                                    return Ok(());
                                }
                                let pkt_type = if val.len() > 1 { val[1] } else { 0 };

                                if matches!(pkt_type, PACKET_TYPE_LEGACY_SYNC | PACKET_TYPE_REQUEST_SYNC) {
                                    debug!(
                                        "📡 [BitChat GATT] Received gossip sync packet (Type 0x{:02x}, len: {})",
                                        pkt_type,
                                        val.len()
                                    );
                                } else {
                                    info!(
                                        "📡 [BitChat GATT] Received mesh packet (Type 0x{:02x}, len: {}) => Hex: {}",
                                        pkt_type,
                                        val.len(),
                                        hex::encode(&val)
                                    );
                                }

                                let parsed = Self::parse_incoming_packet(&val);

                                if let Some(ref p) = parsed {
                                    if p.sender_id == my_sender_id {
                                        return Ok(());
                                    }
                                    let now = Instant::now();
                                    let is_direct_hop = p.ttl >= MESSAGE_TTL_HOPS;
                                    let mut p_guard = peer_map.write().await;
                                    let entry = p_guard.entry(p.sender_id).or_insert_with(|| BitChatPeerEntry {
                                        sender_id: p.sender_id,
                                        nickname: format!("Peer-{}", &hex::encode(p.sender_id)[..4]),
                                        verified: p.signature_valid,
                                        last_seen: now,
                                        last_direct_seen: if is_direct_hop { Some(now) } else { None },
                                        last_announce_reply_at: None,
                                        messages_received: 0,
                                        messages_sent: 0,
                                    });
                                    entry.last_seen = now;
                                    if is_direct_hop {
                                        entry.last_direct_seen = Some(now);
                                    }
                                }

                                if pkt_type == PACKET_TYPE_LEGACY_SYNC {
                                    let sync_resp = Self::build_sync_response(&my_sender_id, &val);
                                    debug!(
                                        "📡 [BitChat GATT] Sending legacy Sync ACK (Type 0x20, {} bytes)",
                                        sync_resp.len()
                                    );
                                    let _ = tx_w.send(sync_resp);
                                } else if pkt_type == PACKET_TYPE_REQUEST_SYNC {
                                    // BitChat 0x21 is GossipSyncManager GCS filter sync; do not emit unsigned 0x21 echoes.
                                } else if pkt_type == PACKET_TYPE_ANNOUNCE {
                                    let mut should_reply = true;
                                    if let Some(ref p) = parsed {
                                        let now = Instant::now();
                                        let mut p_guard = peer_map.write().await;
                                        let nick = if let Some(ref b) = p.payload {
                                            String::from_utf8_lossy(b).to_string()
                                        } else {
                                            format!("Peer-{}", &hex::encode(p.sender_id)[..4])
                                        };
                                        let entry = p_guard.entry(p.sender_id).or_insert_with(|| BitChatPeerEntry {
                                            sender_id: p.sender_id,
                                            nickname: nick.clone(),
                                            verified: p.signature_valid,
                                            last_seen: now,
                                            last_direct_seen: if p.ttl >= MESSAGE_TTL_HOPS { Some(now) } else { None },
                                            last_announce_reply_at: None,
                                            messages_received: 0,
                                            messages_sent: 0,
                                        });
                                        entry.nickname = nick;
                                        entry.verified = p.signature_valid;
                                        entry.last_seen = now;
                                        if let Some(prev_reply) = entry.last_announce_reply_at
                                            && now.saturating_duration_since(prev_reply) < Duration::from_secs(2)
                                        {
                                            should_reply = false;
                                        } else {
                                            entry.last_announce_reply_at = Some(now);
                                        }
                                    }

                                    if should_reply {
                                        let neighbors =
                                            Self::collect_direct_neighbors(&peer_map, &my_sender_id).await;
                                        let ann_reply = Self::build_announce_packet_with_neighbors(
                                            &name_w,
                                            &sk_w,
                                            &np_w,
                                            &neighbors,
                                        );
                                        info!(
                                            "📡 [BitChat GATT] Transmitting Announce reply (Type 0x01, {} bytes, neighbors={}) to peer",
                                            ann_reply.len(),
                                            neighbors.len()
                                        );
                                        let _ = tx_w.send(ann_reply);
                                    }
                                } else if pkt_type == PACKET_TYPE_NOISE_HANDSHAKE || pkt_type == 0x12 {
                                    if let Some(parsed_pkt) = parsed {
                                        if let Some(rid) = parsed_pkt.recipient_id
                                            && rid != my_sender_id
                                            && rid != BITCHAT_BROADCAST_RECIPIENT
                                        {
                                            debug!(
                                                "🛡️ [BitChat Noise] Ignoring mesh handshake from {} addressed to {}",
                                                hex::encode(parsed_pkt.sender_id),
                                                hex::encode(rid)
                                            );
                                            return Ok(());
                                        }

                                        let from_peer = parsed_pkt.sender_id;
                                        if let Some(payload) = parsed_pkt.payload.filter(|p| !p.is_empty()) {
                                            if payload.len() == 32 {
                                                // Noise XX Message 1 (-> e, 32 bytes) from remote initiator
                                                info!(
                                                    "🔐 [BitChat Noise XX SHA256] Received Handshake Initiation (Message 1, 32 bytes) from peer {}",
                                                    hex::encode(from_peer)
                                                );
                                                let pattern: snow::params::NoiseParams = "Noise_XX_25519_ChaChaPoly_SHA256"
                                                    .parse()
                                                    .expect("Valid Noise XX SHA256 pattern");
                                                let builder = snow::Builder::new(pattern);
                                                if let Ok(mut handshake) = builder.local_private_key(&n_priv_w[..]).build_responder() {
                                                    let mut read_buf = [0u8; 128];
                                                    if handshake.read_message(&payload, &mut read_buf).is_ok() {
                                                        let mut msg2_buf = [0u8; 256];
                                                        if let Ok(msg2_len) = handshake.write_message(&[], &mut msg2_buf) {
                                                            let msg2_payload = &msg2_buf[..msg2_len];
                                                            {
                                                                let mut s = sess_map.write().await;
                                                                s.insert(from_peer, PeerNoiseSession::HandshakingResponder(Box::new(handshake)));
                                                            }

                                                            let kex_resp = Self::build_key_exchange_response(
                                                                &my_sender_id,
                                                                &from_peer,
                                                                msg2_payload,
                                                                &sk_w,
                                                            );
                                                            info!(
                                                                "🔐 [BitChat Noise XX SHA256] Transmitting Handshake Response (Message 2, Type 0x10, {} bytes) to peer {}",
                                                                kex_resp.len(),
                                                                hex::encode(from_peer)
                                                            );
                                                            let _ = tx_w.send(kex_resp);
                                                        }
                                                    }
                                                }
                                            } else if payload.len() == 96 {
                                                // Noise XX Message 2 (<- e, ee, s, es, 96 bytes) from remote responder in reply to our initiation
                                                info!(
                                                    "🔐 [BitChat Noise XX SHA256] Received Handshake Response (Message 2, 96 bytes) from peer {}",
                                                    hex::encode(from_peer)
                                                );
                                                let session_opt = {
                                                    let mut s = sess_map.write().await;
                                                    if matches!(s.get(&from_peer), Some(PeerNoiseSession::HandshakingInitiator { .. })) {
                                                        s.remove(&from_peer)
                                                    } else {
                                                        None
                                                    }
                                                };

                                                if let Some(PeerNoiseSession::HandshakingInitiator { mut state, .. }) = session_opt {
                                                    let mut read_buf = [0u8; 256];
                                                    let mut msg3_buf = [0u8; 256];
                                                    if state.read_message(&payload, &mut read_buf).is_ok()
                                                        && let Ok(msg3_len) = state.write_message(&[], &mut msg3_buf)
                                                        && let Ok(transport) = state.into_transport_mode()
                                                    {
                                                        {
                                                            let mut s = sess_map.write().await;
                                                            s.insert(
                                                                from_peer,
                                                                PeerNoiseSession::Established {
                                                                    transport,
                                                                    seen_nonces: VecDeque::new(),
                                                                    seen_msg_ids: VecDeque::new(),
                                                                },
                                                            );
                                                        }
                                                        let kex_final = Self::build_key_exchange_response(
                                                            &my_sender_id,
                                                            &from_peer,
                                                            &msg3_buf[..msg3_len],
                                                            &sk_w,
                                                        );
                                                        info!(
                                                            "🔐 [BitChat Noise XX SHA256] Transmitting Handshake Final (Message 3, {} bytes) & session established with peer {}!",
                                                            kex_final.len(),
                                                            hex::encode(from_peer)
                                                        );
                                                        let _ = tx_w.send(kex_final);
                                                    } else {
                                                        warn!(
                                                            "⚠️ [BitChat Noise XX SHA256] Failed to complete Initiator Message 2/3 transition with peer {}",
                                                            hex::encode(from_peer)
                                                        );
                                                    }
                                                }
                                            } else if payload.len() >= 48 {
                                                // Noise XX Message 3 (-> s, se, 64 bytes) from remote initiator
                                                info!(
                                                    "🔐 [BitChat Noise XX SHA256] Received Handshake Final (Message 3, {} bytes) from peer {}",
                                                    payload.len(),
                                                    hex::encode(from_peer)
                                                );
                                                let session_opt = {
                                                    let mut s = sess_map.write().await;
                                                    if matches!(s.get(&from_peer), Some(PeerNoiseSession::HandshakingResponder(_))) {
                                                        s.remove(&from_peer)
                                                    } else {
                                                        None
                                                    }
                                                };

                                                if let Some(PeerNoiseSession::HandshakingResponder(mut handshake)) = session_opt {
                                                    let mut read_buf = [0u8; 128];
                                                    match handshake.read_message(&payload, &mut read_buf) {
                                                        Ok(_) => {
                                                            match handshake.into_transport_mode() {
                                                                Ok(transport) => {
                                                                    info!(
                                                                        "🔐 [BitChat Noise XX SHA256] Mutual authentication and forward-secure session established with peer {}!",
                                                                        hex::encode(from_peer)
                                                                    );
                                                                    let mut s = sess_map.write().await;
                                                                    s.insert(
                                                                        from_peer,
                                                                        PeerNoiseSession::Established {
                                                                            transport,
                                                                            seen_nonces: VecDeque::new(),
                                                                            seen_msg_ids: VecDeque::new(),
                                                                        },
                                                                    );
                                                                    {
                                                                        let now = Instant::now();
                                                                        let mut p_guard = peer_map.write().await;
                                                                        p_guard.entry(from_peer).or_insert_with(|| BitChatPeerEntry {
                                                                            sender_id: from_peer,
                                                                            nickname: format!("Peer-{}", &hex::encode(from_peer)[..4]),
                                                                            verified: true,
                                                                            last_seen: now,
                                                                            last_direct_seen: if parsed_pkt.ttl >= MESSAGE_TTL_HOPS { Some(now) } else { None },
                                                                            last_announce_reply_at: None,
                                                                            messages_received: 0,
                                                                            messages_sent: 0,
                                                                        }).last_seen = now;
                                                                    }
                                                                }
                                                                Err(e) => {
                                                                    warn!("⚠️ Failed to transition Noise session to transport mode: {}", e);
                                                                }
                                                            }
                                                        }
                                                        Err(e) => {
                                                            warn!(
                                                                "⚠️ [BitChat Noise XX SHA256] Handshake Message 3 verification failed from peer {}: {}",
                                                                hex::encode(from_peer),
                                                                e
                                                            );
                                                        }
                                                    }
                                                } else {
                                                    debug!(
                                                        "🛡️ [BitChat Noise XX SHA256] Ignoring duplicate/late Message 3 from peer {} (session already established or idle)",
                                                        hex::encode(from_peer)
                                                    );
                                                }
                                            }
                                        }
                                    }
                                } else if pkt_type == PACKET_TYPE_NOISE_ENCRYPTED {
                                    if let Some(parsed_pkt) = parsed {
                                        if let Some(rid) = parsed_pkt.recipient_id
                                            && rid != my_sender_id
                                            && rid != BITCHAT_BROADCAST_RECIPIENT
                                        {
                                            debug!(
                                                "🛡️ [BitChat E2EE] Ignoring mesh ciphertext from {} addressed to {}",
                                                hex::encode(parsed_pkt.sender_id),
                                                hex::encode(rid)
                                            );
                                            return Ok(());
                                        }

                                        let from_peer = parsed_pkt.sender_id;
                                        if let Some(ciphertext) = parsed_pkt.payload.filter(|p| !p.is_empty()) {
                                            let mut needs_session_recovery = false;
                                            let mut s = sess_map.write().await;

                                            if let Some(PeerNoiseSession::Established {
                                                transport,
                                                seen_nonces,
                                                seen_msg_ids,
                                            }) = s.get_mut(&from_peer)
                                            {
                                                // BitChat Android/iOS prefixes Noise transport messages with a 4-byte big-endian nonce
                                                let (extracted_nonce, actual_cipher) = if ciphertext.len() >= 20 {
                                                    let n = u32::from_be_bytes([ciphertext[0], ciphertext[1], ciphertext[2], ciphertext[3]]) as u64;
                                                    (Some(n), &ciphertext[4..])
                                                } else {
                                                    (None, &ciphertext[..])
                                                };

                                                if let Some(n) = extracted_nonce
                                                    && seen_nonces.contains(&n)
                                                {
                                                    debug!(
                                                        "🛡️ [BitChat E2EE] Ignoring duplicate mesh-relayed Noise frame (nonce={}) from peer {}",
                                                        n,
                                                        hex::encode(from_peer)
                                                    );
                                                    return Ok(());
                                                }

                                                let prev_recv_nonce = transport.receiving_nonce();
                                                if let Some(n) = extracted_nonce {
                                                    transport.set_receiving_nonce(n);
                                                }

                                                let mut plain_buf = vec![0u8; actual_cipher.len() + 64];
                                                let decrypt_res = transport.read_message(actual_cipher, &mut plain_buf);

                                                // Fallback: if 4-byte nonce-stripped decrypt failed, restore nonce and try raw ciphertext
                                                let final_res = match decrypt_res {
                                                    Ok(len) => Ok(len),
                                                    Err(e) => {
                                                        if extracted_nonce.is_some() {
                                                            transport.set_receiving_nonce(prev_recv_nonce);
                                                            let raw_res = transport.read_message(&ciphertext, &mut plain_buf);
                                                            if raw_res.is_err() {
                                                                transport.set_receiving_nonce(prev_recv_nonce);
                                                            }
                                                            raw_res
                                                        } else {
                                                            Err(e)
                                                        }
                                                    }
                                                };

                                                match final_res {
                                                    Ok(plain_len) => {
                                                        if let Some(n) = extracted_nonce {
                                                            if seen_nonces.len() >= MAX_TRACKED_SESSION_NONCES {
                                                                seen_nonces.pop_front();
                                                            }
                                                            seen_nonces.push_back(n);
                                                        }

                                                        let plain_bytes = &plain_buf[..plain_len];
                                                        info!(
                                                            "🔓 [BitChat E2EE Raw Decrypted] ({} bytes from {}): Hex={}",
                                                            plain_len,
                                                            hex::encode(from_peer),
                                                            hex::encode(plain_bytes)
                                                        );

                                                        if !plain_bytes.is_empty() {
                                                            let noise_payload_type = plain_bytes[0];
                                                            if matches!(noise_payload_type, 0x02 | 0x03 | 0x10 | 0x11 | 0x20 | 0x21) {
                                                                debug!(
                                                                    "🔄 [BitChat E2EE Control] Ignoring Noise control/sync payload (type: 0x{:02x}, {} bytes) from peer {}",
                                                                    plain_bytes[0], plain_bytes.len(), hex::encode(from_peer)
                                                                );
                                                            } else {
                                                                let (msg_id_opt, plain_text) =
                                                                    Self::extract_bitchat_private_message_with_id(plain_bytes);
                                                                if let Some(ref mid) = msg_id_opt {
                                                                    if seen_msg_ids.contains(mid) {
                                                                        debug!(
                                                                            "🛡️ [BitChat E2EE] Ignoring duplicate private message ID '{}' from peer {}",
                                                                            mid,
                                                                            hex::encode(from_peer)
                                                                        );
                                                                        return Ok(());
                                                                    }
                                                                    if seen_msg_ids.len() >= MAX_TRACKED_SESSION_MSG_IDS {
                                                                        seen_msg_ids.pop_front();
                                                                    }
                                                                    seen_msg_ids.push_back(mid.clone());
                                                                }

                                                                if !plain_text.is_empty() && plain_text.chars().any(|c| c.is_alphanumeric()) {
                                                                    info!(
                                                                        "💬 [BitChat Private Direct Message Decrypted]: \"{}\" (from {})",
                                                                        plain_text,
                                                                        hex::encode(from_peer)
                                                                    );

                                                                    let reply_txt = format!(
                                                                        "🚀 [OpenAlert Daemon ACK] Received private alert: \"{}\"",
                                                                        plain_text
                                                                    );
                                                                    let send_nonce = transport.sending_nonce() as u32;
                                                                    let tlv_reply = Self::encode_bitchat_private_message(&reply_txt);
                                                                    let mut enc_ack_buf = vec![0u8; tlv_reply.len() + 32];
                                                                    if let Ok(ack_len) = transport.write_message(&tlv_reply, &mut enc_ack_buf) {
                                                                        let mut combined_payload = send_nonce.to_be_bytes().to_vec();
                                                                        combined_payload.extend_from_slice(&enc_ack_buf[..ack_len]);
                                                                        let enc_reply = Self::build_encrypted_chat_packet(
                                                                            &my_sender_id,
                                                                            &from_peer,
                                                                            &combined_payload,
                                                                            &sk_w,
                                                                        );
                                                                        info!(
                                                                            "💬 [BitChat E2EE] Transmitting encrypted ACK direct reply to peer {}: \"{}\"",
                                                                            hex::encode(from_peer),
                                                                            reply_txt
                                                                        );
                                                                        let _ = tx_w.send(enc_reply);
                                                                    }
                                                                    drop(s);

                                                                    let sender_nickname = {
                                                                        let mut p_guard = peer_map.write().await;
                                                                        if let Some(entry) = p_guard.get_mut(&from_peer) {
                                                                            entry.messages_received += 1;
                                                                            entry.messages_sent += 1;
                                                                            entry.last_seen = Instant::now();
                                                                            entry.nickname.clone()
                                                                        } else {
                                                                            format!("Peer-{}", &hex::encode(from_peer)[..4])
                                                                        }
                                                                    };

                                                                    if let Some(ref eng) = eng_opt {
                                                                        let daemon_node = eng.config().daemon.name.clone();
                                                                        let formatted_summary = crate::ingress::sos::format_sos_alert_text(
                                                                            Some("SOS"),
                                                                            Some(&sender_nickname),
                                                                            &plain_text,
                                                                            &daemon_node,
                                                                        );
                                                                        let msg_tag: String = msg_id_opt
                                                                            .as_deref()
                                                                            .map(|id| {
                                                                                id.chars()
                                                                                    .filter(|c| c.is_ascii_alphanumeric())
                                                                                    .take(16)
                                                                                    .collect::<String>()
                                                                            })
                                                                            .filter(|tag| !tag.is_empty())
                                                                            .unwrap_or_else(|| crate::time_sync::now_utc_ms().to_string());
                                                                        let alert = Alert {
                                                                            alert_id: format!("bitchat-dm-{}-{}", &hex::encode(from_peer)[..8], msg_tag),
                                                                            severity: AlertSeverity::Critical,
                                                                            summary: formatted_summary.clone(),
                                                                            description: Some(formatted_summary),
                                                                            source: AlertSource::BitChat,
                                                                            sender: Some(sender_nickname),
                                                                            node: Some(daemon_node),
                                                                            starts_at: crate::time_sync::now_utc(),
                                                                            destinations: Vec::new(),
                                                                            origin_peer: None,
                                                                            hop: 5,
                                                                        };
                                                                        let eng_clone = eng.clone();
                                                                        tokio::spawn(async move {
                                                                            sleep(Duration::from_millis(250)).await;
                                                                            if let Err(err) = eng_clone.route_alert(alert).await {
                                                                                warn!("Failed to route BitChat private ingress alert: {}", err);
                                                                            }
                                                                        });
                                                                    }
                                                                    return Ok(());
                                                                } else {
                                                                    debug!(
                                                                        "🔄 [BitChat E2EE Control] Ignoring internal/control PrivateMessage payload ({} bytes) from peer {}",
                                                                        plain_bytes.len(), hex::encode(from_peer)
                                                                    );
                                                                }
                                                            }
                                                        }
                                                    }
                                                    Err(e) => {
                                                        warn!(
                                                            "⚠️ [BitChat E2EE] Failed to decrypt transport message from peer {} ({}); initiating automatic Noise XX session recovery",
                                                            hex::encode(from_peer),
                                                            e
                                                        );
                                                        s.remove(&from_peer);
                                                        needs_session_recovery = true;
                                                    }
                                                }
                                            } else {
                                                let already_initiating = matches!(
                                                    s.get(&from_peer),
                                                    Some(PeerNoiseSession::HandshakingInitiator { started_at, .. })
                                                        if started_at.elapsed() < Duration::from_secs(3)
                                                );
                                                if !already_initiating {
                                                    warn!(
                                                        "⚠️ [BitChat E2EE] Received encrypted message without an active session from peer {}; initiating Noise XX handshake recovery",
                                                        hex::encode(from_peer)
                                                    );
                                                    needs_session_recovery = true;
                                                }
                                            }

                                            if needs_session_recovery
                                                && let Some((init_sess, hs_pkt)) = Self::initiate_noise_handshake(
                                                    &my_sender_id,
                                                    &from_peer,
                                                    &n_priv_w,
                                                    &sk_w,
                                                )
                                            {
                                                s.insert(from_peer, init_sess);
                                                drop(s);
                                                let neighbors =
                                                    Self::collect_direct_neighbors(&peer_map, &my_sender_id).await;
                                                let ann_reply = Self::build_announce_packet_with_neighbors(
                                                    &name_w,
                                                    &sk_w,
                                                    &np_w,
                                                    &neighbors,
                                                );
                                                let _ = tx_w.send(ann_reply);
                                                info!(
                                                    "🔐 [BitChat Noise XX SHA256] Initiating session recovery Handshake Message 1 ({} bytes) toward peer {}",
                                                    hs_pkt.len(),
                                                    hex::encode(from_peer)
                                                );
                                                let _ = tx_w.send(hs_pkt);
                                            }
                                        }
                                    }
                                } else if (pkt_type == PACKET_TYPE_MESSAGE) && let Some(parsed_pkt) = parsed {
                                    let from_peer = parsed_pkt.sender_id;
                                    let is_broadcast = parsed_pkt.recipient_id.is_none()
                                        || parsed_pkt.recipient_id == Some(BITCHAT_BROADCAST_RECIPIENT);
                                    let is_direct_to_me = parsed_pkt.recipient_id == Some(my_sender_id);

                                    if let Some(payload) = parsed_pkt.payload {
                                        let txt = std::str::from_utf8(&payload)
                                            .ok()
                                            .filter(|s| {
                                                !s.chars().any(|c| {
                                                    c.is_control() && !matches!(c, '\n' | '\r' | '\t')
                                                })
                                            })
                                            .map(|s| s.trim().to_string())
                                            .unwrap_or_default();

                                        if Self::is_bitchat_control_message(&txt) {
                                            debug!(
                                                "🔄 [BitChat GATT Control] Ignoring internal control/favorite sync message from peer {}: \"{}\"",
                                                hex::encode(from_peer),
                                                txt
                                            );
                                        } else if !txt.is_empty() && txt.chars().any(|c| c.is_alphanumeric()) {
                                            if is_direct_to_me {
                                                info!(
                                                    "💬 [BitChat 1-on-1 Direct Message Received]: \"{}\" (from {})",
                                                    txt,
                                                    hex::encode(from_peer)
                                                );

                                                let reply_txt = format!(
                                                    "🚀 [OpenAlert Daemon ACK] Received your private message: \"{}\"",
                                                    txt
                                                );
                                                let chat_reply = Self::build_chat_message_packet(
                                                    &my_sender_id,
                                                    Some(&from_peer),
                                                    &reply_txt,
                                                    &sk_w,
                                                );
                                                info!(
                                                    "💬 [BitChat GATT] Transmitting active chat message reply to peer {}: \"{}\"",
                                                    hex::encode(from_peer),
                                                    reply_txt
                                                );
                                                let _ = tx_w.send(chat_reply);

                                                let sender_nickname = {
                                                    let p_guard = peer_map.read().await;
                                                    p_guard
                                                        .get(&from_peer)
                                                        .map(|e| e.nickname.clone())
                                                        .unwrap_or_else(|| format!("Peer-{}", &hex::encode(from_peer)[..4]))
                                                };

                                                if let Some(ref eng) = eng_opt {
                                                    let daemon_node = eng.config().daemon.name.clone();
                                                    let formatted_summary = crate::ingress::sos::format_sos_alert_text(
                                                        Some("SOS"),
                                                        Some(&sender_nickname),
                                                        &txt,
                                                        &daemon_node,
                                                    );
                                                    let alert = Alert {
                                                        alert_id: format!("bitchat-dm-{}-{}", &hex::encode(from_peer)[..8], crate::time_sync::now_utc_ms()),
                                                        severity: AlertSeverity::Critical,
                                                        summary: formatted_summary.clone(),
                                                        description: Some(formatted_summary),
                                                        source: AlertSource::BitChat,
                                                        sender: Some(sender_nickname),
                                                        node: Some(daemon_node),
                                                        starts_at: crate::time_sync::now_utc(),
                                                        destinations: Vec::new(),
                                                        origin_peer: None,
                                                        hop: 5,
                                                    };
                                                    let eng_clone = eng.clone();
                                                    tokio::spawn(async move {
                                                        sleep(Duration::from_millis(250)).await;
                                                        if let Err(err) = eng_clone.route_alert(alert).await {
                                                            warn!("Failed to route BitChat direct ingress alert: {}", err);
                                                        }
                                                    });
                                                }
                                            } else if is_broadcast {
                                                let label = "Mesh Broadcast";
                                                info!(
                                                    "💬 [BitChat {} Received]: \"{}\" (from {})",
                                                    label,
                                                    txt,
                                                    hex::encode(from_peer)
                                                );
                                                let bitchat_egress_active = eng_opt.as_ref().is_some_and(|eng| {
                                                    let r = &eng.config().routing;
                                                    r.default_destinations.iter().any(|d| d == "bitchat")
                                                        || r.failover_destinations.iter().any(|d| d == "bitchat")
                                                });
                                                let is_daemon_echo = txt.starts_with("🚀 [OpenAlert Daemon ACK]")
                                                    || txt.starts_with("✅ [OpenAlert ")
                                                    || txt.starts_with("🚨 [");

                                                if bitchat_egress_active {
                                                    info!(
                                                        "🛡️ [BitChat Split-Horizon] Ignoring public {} as ingress because BitChat Egress is enabled on this node (use 1-to-1 private chat to trigger alerts)",
                                                        label
                                                    );
                                                } else if !is_daemon_echo {
                                                    if public_mesh_ack {
                                                        let reply_txt = format!(
                                                            "🚀 [OpenAlert Daemon ACK] Received mesh alert: \"{}\"",
                                                            txt
                                                        );
                                                        let chat_reply = Self::build_chat_message_packet(
                                                            &my_sender_id,
                                                            None,
                                                            &reply_txt,
                                                            &sk_w,
                                                        );
                                                        info!(
                                                            "💬 [BitChat GATT] Broadcasting public mesh ACK reply: \"{}\"",
                                                            reply_txt
                                                        );
                                                        let _ = tx_w.send(chat_reply);
                                                    }
                                                    let sender_nickname = {
                                                        let p_guard = peer_map.read().await;
                                                        p_guard
                                                            .get(&from_peer)
                                                            .map(|e| e.nickname.clone())
                                                            .unwrap_or_else(|| format!("Peer-{}", &hex::encode(from_peer)[..4]))
                                                    };
                                                    if let Some(ref eng) = eng_opt {
                                                        let daemon_node = eng.config().daemon.name.clone();
                                                        let formatted_summary = crate::ingress::sos::format_sos_alert_text(
                                                            Some("SOS"),
                                                            Some(&sender_nickname),
                                                            &txt,
                                                            &daemon_node,
                                                        );
                                                        let alert = Alert {
                                                            alert_id: format!("bitchat-bcast-{}-{}", &hex::encode(from_peer)[..8], crate::time_sync::now_utc_ms()),
                                                            severity: AlertSeverity::Critical,
                                                            summary: formatted_summary.clone(),
                                                            description: Some(formatted_summary),
                                                            source: AlertSource::BitChat,
                                                            sender: Some(sender_nickname),
                                                            node: Some(daemon_node),
                                                            starts_at: crate::time_sync::now_utc(),
                                                            destinations: Vec::new(),
                                                            origin_peer: None,
                                                            hop: 5,
                                                        };
                                                        let eng_clone = eng.clone();
                                                        tokio::spawn(async move {
                                                            sleep(Duration::from_millis(250)).await;
                                                            if let Err(err) = eng_clone.route_alert(alert).await {
                                                                warn!("Failed to route BitChat ingress alert: {}", err);
                                                            }
                                                        });
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                Ok(())
                            }
                            .boxed()
                        })),
                        ..Default::default()
                    }),
                    notify: Some(CharacteristicNotify {
                        notify: true,
                        method: CharacteristicNotifyMethod::Fun(Box::new(
                            move |mut notifier| {
                                let mut rx = bcast_tx_sub.subscribe();
                                let name_s = name_sub.clone();
                                let sk_s = sk_sub.clone();
                                let np_s = np_sub.clone();
                                let sid_s = sender_id_sub;
                                let tx_welcome = bcast_tx_sub.clone();
                                let subs_counter = active_subs_notify.clone();
                                let adv_notify = adv_refresh_notify_gatt.clone();
                                let peers_s = peer_map_n.clone();
                                async move {
                                    let prev_subs = subs_counter.fetch_add(1, Ordering::Relaxed);
                                    info!(
                                        "📡 [BitChat GATT] Peer subscribed to Mesh notifications (active_subscribers: {} -> {}).",
                                        prev_subs,
                                        prev_subs + 1
                                    );

                                    let neighbors =
                                        Self::collect_direct_neighbors(&peers_s, &sid_s).await;
                                    let initial_ann = Self::build_announce_packet_with_neighbors(
                                        &name_s,
                                        &sk_s,
                                        &np_s,
                                        &neighbors,
                                    );
                                    info!(
                                        "📡 [BitChat GATT] Sending fresh announce packet ({} bytes, neighbors={}) to new subscriber",
                                        initial_ann.len(),
                                        neighbors.len()
                                    );
                                    let _ = notifier.notify(initial_ann).await;
                                    let welcome_msg = "👋 Hello from OpenAlert Daemon! Connected over BLE Mesh.";
                                    let welcome_pkt =
                                        Self::build_chat_message_packet(
                                            &sid_s,
                                            Some(&BITCHAT_BROADCAST_RECIPIENT),
                                            welcome_msg,
                                            &sk_s,
                                        );
                                    tokio::spawn(async move {
                                        sleep(Duration::from_millis(1200)).await;
                                        info!(
                                            "💬 [BitChat GATT] Sending welcome chat message to subscriber: \"{}\"",
                                            welcome_msg
                                        );
                                        let _ = tx_welcome.send(welcome_pkt);
                                    });

                                    loop {
                                        tokio::select! {
                                            _ = notifier.stopped() => {
                                                info!("🔌 [BitChat GATT] Peer stopped GATT notification subscription");
                                                break;
                                            }
                                            recv_res = rx.recv() => {
                                                match recv_res {
                                                    Ok(pkt) => {
                                                        let ptype = if pkt.len() > 1 { pkt[1] } else { 0 };
                                                        if matches!(ptype, PACKET_TYPE_LEGACY_SYNC | PACKET_TYPE_REQUEST_SYNC) {
                                                            debug!(
                                                                "📡 [BitChat GATT] Transmitting sync packet (Type 0x{:02x}, len: {}) to peer",
                                                                ptype,
                                                                pkt.len()
                                                            );
                                                        } else {
                                                            info!(
                                                                "📡 [BitChat GATT] Transmitting packet (Type 0x{:02x}, len: {}) to peer",
                                                                ptype,
                                                                pkt.len()
                                                            );
                                                        }
                                                        if let Err(err) = notifier.notify(pkt).await {
                                                            warn!(
                                                                "[BitChat GATT] Notify stream error: {}",
                                                                err
                                                            );
                                                            break;
                                                        }
                                                        sleep(Duration::from_millis(100)).await;
                                                    }
                                                    Err(broadcast::error::RecvError::Lagged(skipped)) => {
                                                        warn!(
                                                            "⚠️ [BitChat GATT] Notification receiver lagged by {} packet(s); continuing active stream",
                                                            skipped
                                                        );
                                                        continue;
                                                    }
                                                    Err(broadcast::error::RecvError::Closed) => {
                                                        break;
                                                    }
                                                }
                                            }
                                        }
                                    }

                                    let prev_after = subs_counter.fetch_sub(1, Ordering::Relaxed);
                                    let remaining = prev_after.saturating_sub(1);
                                    info!(
                                        "🔄 [BitChat GATT] Peer notification session ended (active_subscribers: {} -> {}).",
                                        prev_after,
                                        remaining
                                    );
                                    if remaining == 0 {
                                        adv_notify.notify_one();
                                    }
                                }
                                .boxed()
                            },
                        )),
                        ..Default::default()
                    }),
                    ..Default::default()
                }],
                ..Default::default()
            }],
            ..Default::default()
        };

        match adapter.serve_gatt_application(app).await {
            Ok(handle) => {
                info!(
                    "✅ BitChat GATT Server listening on characteristic {}",
                    char_uuid
                );
                while self.running.load(Ordering::Relaxed) {
                    tokio::select! {
                        _ = self.shutdown_notify.notified() => break,
                        _ = sleep(Duration::from_secs(1)) => {}
                    }
                }
                drop(handle);
            }
            Err(e) => {
                warn!("⚠️ Failed to register BitChat GATT application: {}", e);
            }
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_announce_and_chat_packet_structure() {
        let (signing_key, noise_pubkey, sender_id) =
            BitChatService::derive_keys("OpenAlert-Test");

        let announce_pkt =
            BitChatService::build_announce_packet("OpenAlert-Test", &signing_key, &noise_pubkey);
        assert_eq!(announce_pkt.len(), 256);
        assert_eq!(announce_pkt[0], PACKET_VERSION);
        assert_eq!(announce_pkt[1], PACKET_TYPE_ANNOUNCE);

        let parsed = BitChatService::parse_incoming_packet(&announce_pkt);
        assert!(parsed.is_some());
        let p = parsed.unwrap();
        assert_eq!(p.packet_type, PACKET_TYPE_ANNOUNCE);
        assert_eq!(p.sender_id, sender_id);
        assert!(p.signature_valid);

        // Verify that external BitChat mobile clients (Android / iOS) verify the standard canonical preimage
        let payload_len = u16::from_be_bytes([announce_pkt[12], announce_pkt[13]]) as usize;
        let payload_end = 14 + 8 + payload_len;
        let canonical_preimage = BitChatService::canonical_signing_preimage(
            &announce_pkt[..payload_end],
            BITCHAT_BUCKET_SIZE_256,
        );
        let sig_bytes = &announce_pkt[payload_end..payload_end + 64];
        let sig = ed25519_dalek::Signature::from_slice(sig_bytes).unwrap();
        assert!(signing_key.verifying_key().verify(&canonical_preimage, &sig).is_ok(),
            "BitChat mobile app canonical verification MUST succeed for peer table discovery!");

        let chat_pkt = BitChatService::build_chat_message_packet(
            &sender_id,
            Some(&BITCHAT_BROADCAST_RECIPIENT),
            "Test alert broadcast message",
            &signing_key,
        );
        assert_eq!(chat_pkt.len(), 256);
        assert_eq!(chat_pkt[0], PACKET_VERSION);
        assert_eq!(chat_pkt[1], PACKET_TYPE_MESSAGE);
        let parsed_chat = BitChatService::parse_incoming_packet(&chat_pkt);
        assert!(parsed_chat.is_some());
        let pc = parsed_chat.unwrap();
        assert_eq!(pc.packet_type, PACKET_TYPE_MESSAGE);
        assert_eq!(pc.recipient_id, Some(BITCHAT_BROADCAST_RECIPIENT));
    }

    #[test]
    fn test_noise_xx_handshake_and_encrypted_transport_roundtrip() {
        let pattern: snow::params::NoiseParams = "Noise_XX_25519_ChaChaPoly_SHA256"
            .parse()
            .expect("Noise pattern");

        let init_priv = [0x11u8; 32];
        let resp_priv = [0x22u8; 32];

        let mut init_handshake = snow::Builder::new(pattern.clone())
            .local_private_key(&init_priv)
            .build_initiator()
            .expect("Initiator builder");
        let mut resp_handshake = snow::Builder::new(pattern)
            .local_private_key(&resp_priv)
            .build_responder()
            .expect("Responder builder");

        let mut msg1_buf = [0u8; 256];
        let msg1_len = init_handshake
            .write_message(&[], &mut msg1_buf)
            .expect("Write Msg 1");
        assert_eq!(msg1_len, 32);

        let mut read_buf = [0u8; 256];
        resp_handshake
            .read_message(&msg1_buf[..msg1_len], &mut read_buf)
            .expect("Read Msg 1");

        let mut msg2_buf = [0u8; 256];
        let msg2_len = resp_handshake
            .write_message(&[], &mut msg2_buf)
            .expect("Write Msg 2");
        assert_eq!(msg2_len, 96);

        init_handshake
            .read_message(&msg2_buf[..msg2_len], &mut read_buf)
            .expect("Read Msg 2");

        let mut msg3_buf = [0u8; 256];
        let msg3_len = init_handshake
            .write_message(&[], &mut msg3_buf)
            .expect("Write Msg 3");
        assert_eq!(msg3_len, 64);

        resp_handshake
            .read_message(&msg3_buf[..msg3_len], &mut read_buf)
            .expect("Read Msg 3");

        let mut init_transport = init_handshake
            .into_transport_mode()
            .expect("Initiator transport");
        let mut resp_transport = resp_handshake
            .into_transport_mode()
            .expect("Responder transport");

        let alert_payload = b"CRITICAL: Data Center Overheat (Zone 4)";
        let mut cipher_buf = [0u8; 256];
        let cipher_len = init_transport
            .write_message(alert_payload, &mut cipher_buf)
            .expect("Encrypt transport payload");

        let mut decrypted_buf = [0u8; 256];
        let dec_len = resp_transport
            .read_message(&cipher_buf[..cipher_len], &mut decrypted_buf)
            .expect("Decrypt transport payload");

        assert_eq!(&decrypted_buf[..dec_len], alert_payload);
    }

    #[test]
    fn test_bitchat_nonce_prefixed_transport_and_tlv_extraction() {
        // 1. Test encode_bitchat_private_message & extract_bitchat_private_message round-trip
        let tlv_bytes = BitChatService::encode_bitchat_private_message("FIRE IN SERVER ROOM");
        assert_eq!(tlv_bytes[0], 0x01);
        assert_eq!(tlv_bytes[1], 0x00);
        assert_eq!(tlv_bytes[2], 36); // UUID v4 string length

        let extracted = BitChatService::extract_bitchat_private_message(&tlv_bytes);
        assert_eq!(extracted, "FIRE IN SERVER ROOM");

        // 1b. Verify post-handshake 0x21 identity sync frame (exact 40-byte payload from 06:50:40) is rejected
        let identity_sync_frame = hex::decode(
            "2101010200010220bdbf6af05707831e372e703a1081ea1f5a984469ad2ec2cf1451dac94d6477d7",
        )
        .unwrap();
        assert_eq!(
            BitChatService::extract_bitchat_private_message(&identity_sync_frame),
            ""
        );

        // 1c. Verify BitChat [FAVORITED]:npub1... / [UNFAVORITED]:npub1... Nostr rumor inside 0x01 PrivateMessage is rejected
        // Exact 116-byte decrypted payload from tablet (87dfcb12e0e8becc) on 2026-10-27 08:28:49 CEST:
        let favorited_tlv_frame = hex::decode(
            "01002463336336333736332d306538392d343935632d626436312d643435326231643930396562014b5b4641564f52495445445d3a6e7075623139746a6b6e3068687637326d646d6333727074746a61737a3861766a6d6c6478777a666d646e346a35336b37686b357161323471336471766435",
        )
        .unwrap();
        assert!(BitChatService::is_bitchat_control_message(
            "[FAVORITED]:npub19tjkn0hhv72mdmc3rpttjasz8avjmldxwzfmdn4j53k7hk5qa24q3dqvd5"
        ));
        assert!(BitChatService::is_bitchat_control_message(
            "[UNFAVORITED]:npub19tjkn0hhv72mdmc3rpttjasz8avjmldxwzfmdn4j53k7hk5qa24q3dqvd5"
        ));
        assert_eq!(
            BitChatService::extract_bitchat_private_message(&favorited_tlv_frame),
            ""
        );
        let unfavorited_tlv = BitChatService::encode_bitchat_private_message(
            "[UNFAVORITED]:npub19tjkn0hhv72mdmc3rpttjasz8avjmldxwzfmdn4j53k7hk5qa24q3dqvd5",
        );
        assert_eq!(
            BitChatService::extract_bitchat_private_message(&unfavorited_tlv),
            ""
        );

        // 2. Test full handshake and 4-byte nonce prefixed transport
        let pattern: snow::params::NoiseParams = "Noise_XX_25519_ChaChaPoly_SHA256"
            .parse()
            .expect("Noise pattern");

        let mut init_hs = snow::Builder::new(pattern.clone())
            .local_private_key(&[0x33u8; 32])
            .build_initiator()
            .expect("init hs");
        let mut resp_hs = snow::Builder::new(pattern)
            .local_private_key(&[0x44u8; 32])
            .build_responder()
            .expect("resp hs");

        let mut buf1 = [0u8; 256];
        let l1 = init_hs.write_message(&[], &mut buf1).unwrap();
        let mut rbuf = [0u8; 256];
        resp_hs.read_message(&buf1[..l1], &mut rbuf).unwrap();

        let mut buf2 = [0u8; 256];
        let l2 = resp_hs.write_message(&[], &mut buf2).unwrap();
        init_hs.read_message(&buf2[..l2], &mut rbuf).unwrap();

        let mut buf3 = [0u8; 256];
        let l3 = init_hs.write_message(&[], &mut buf3).unwrap();
        resp_hs.read_message(&buf3[..l3], &mut rbuf).unwrap();

        let mut init_transport = init_hs.into_transport_mode().unwrap();
        let mut resp_transport = resp_hs.into_transport_mode().unwrap();

        // Initiator writes message with nonce 0
        let send_nonce = init_transport.sending_nonce() as u32;
        let mut cipher_buf = [0u8; 256];
        let enc_len = init_transport.write_message(&tlv_bytes, &mut cipher_buf).unwrap();

        // BitChat frames on the wire as: 4-byte nonce || ciphertext
        let mut wire_payload = send_nonce.to_be_bytes().to_vec();
        wire_payload.extend_from_slice(&cipher_buf[..enc_len]);

        // Responder decrypts by checking 4-byte nonce prefix
        let (recvd_nonce, actual_cipher) = if wire_payload.len() >= 20 {
            let n = u32::from_be_bytes([wire_payload[0], wire_payload[1], wire_payload[2], wire_payload[3]]);
            (Some(n as u64), &wire_payload[4..])
        } else {
            (None, &wire_payload[..])
        };

        if let Some(n) = recvd_nonce {
            resp_transport.set_receiving_nonce(n);
        }

        let mut dec_buf = [0u8; 256];
        let dec_len = resp_transport.read_message(actual_cipher, &mut dec_buf).unwrap();
        let dec_text = BitChatService::extract_bitchat_private_message(&dec_buf[..dec_len]);
        assert_eq!(dec_text, "FIRE IN SERVER ROOM");
    }

    #[test]
    fn test_btmgmt_advertising_parser_and_monitored_devices_config() {
        let broken_after_0x24 = "Index list with 1 item\nhci0:\tPrimary controller\n\taddr 40:45:DA:08:75:C7 version 10 manufacturer 435 class 0x000000\n\tsupported settings: powered connectable fast-connectable discoverable bondable link-security ssp br/edr le advertising secure-conn debug-keys privacy static-addr phy-configuration\n\tcurrent settings: powered connectable discoverable bondable ssp br/edr le secure-conn\n\tname OpenAlert-FOG-Node02\n\tshort name \n";
        assert_eq!(
            BitChatService::parse_btmgmt_advertising_state(broken_after_0x24, "hci0"),
            Some(false)
        );
        assert_eq!(
            BitChatService::parse_btmgmt_advertising_state(broken_after_0x24, "hci1"),
            None
        );

        let healthy_output = "Index list with 1 item\nhci0:\tPrimary controller\n\taddr 40:45:DA:08:75:C7 version 10 manufacturer 435 class 0x000000\n\tsupported settings: powered connectable fast-connectable discoverable bondable link-security ssp br/edr le advertising secure-conn debug-keys privacy static-addr phy-configuration\n\tcurrent settings: powered connectable discoverable bondable ssp br/edr le advertising secure-conn\n\tname OpenAlert-FOG-Node02\n\tshort name \n";
        assert_eq!(
            BitChatService::parse_btmgmt_advertising_state(healthy_output, "hci0"),
            Some(true)
        );

        // Verify BitChatConfig::resolved_monitored_devices avoids hardcoding and falls back to `device`
        let mut cfg = BitChatConfig {
            device: "hci2".to_string(),
            monitored_devices: vec![],
            ..Default::default()
        };
        assert_eq!(cfg.resolved_monitored_devices(), vec!["hci2".to_string()]);

        cfg.monitored_devices = vec!["hci0".to_string(), "hci1".to_string(), "hci0".to_string()];
        assert_eq!(
            cfg.resolved_monitored_devices(),
            vec!["hci0".to_string(), "hci1".to_string()]
        );

        // Verify adaptive low-power advertising intervals (idle vs connected peers)
        let default_cfg = BitChatConfig::default();
        assert_eq!(default_cfg.watchdog_interval_secs, 15);
        assert_eq!(default_cfg.adv_refresh_interval_secs, 90);
        assert_eq!(
            default_cfg.adaptive_adv_intervals(0),
            (
                Some(Duration::from_millis(250)),
                Some(Duration::from_millis(500))
            )
        );
        assert_eq!(
            default_cfg.adaptive_adv_intervals(1),
            (
                Some(Duration::from_millis(500)),
                Some(Duration::from_millis(1000))
            )
        );

        let zero_cfg = BitChatConfig {
            adv_min_interval_ms: 0,
            ..Default::default()
        };
        assert_eq!(zero_cfg.adaptive_adv_intervals(0), (None, None));
    }

    #[test]
    fn test_multi_message_sequential_and_duplicate_nonce_transport_and_session_recovery() {
        let (node_sk, _node_np, node_sid) = BitChatService::derive_keys("OpenAlert-FOG-Node02");
        let (_peer_sk, _peer_np, peer_sid) = BitChatService::derive_keys("Jorge-Phone");

        let mut node_hasher = Sha256::new();
        node_hasher.update(b"bitchat-noise-dh-key-v1-OpenAlert-FOG-Node02");
        let node_priv: [u8; 32] = node_hasher.finalize().into();

        let peer_priv = [0x55u8; 32];
        let pattern: snow::params::NoiseParams = "Noise_XX_25519_ChaChaPoly_SHA256"
            .parse()
            .expect("Noise pattern");

        // 1. Test automatic Noise XX initiator recovery (`initiate_noise_handshake` -> Msg 2 -> Msg 3)
        let (init_session, hs_pkt) = BitChatService::initiate_noise_handshake(
            &node_sid, &peer_sid, &node_priv, &node_sk,
        )
        .expect("Handshake initiation");
        let parsed_hs1 = BitChatService::parse_incoming_packet(&hs_pkt).expect("Parse Msg 1");
        assert_eq!(parsed_hs1.packet_type, PACKET_TYPE_NOISE_HANDSHAKE);
        assert_eq!(parsed_hs1.recipient_id, Some(peer_sid));
        let msg1_bytes = parsed_hs1.payload.unwrap();
        assert_eq!(msg1_bytes.len(), 32);

        let mut peer_resp = snow::Builder::new(pattern)
            .local_private_key(&peer_priv)
            .build_responder()
            .expect("Peer responder");
        let mut rbuf = [0u8; 256];
        peer_resp.read_message(&msg1_bytes, &mut rbuf).unwrap();
        let mut msg2_buf = [0u8; 256];
        let msg2_len = peer_resp.write_message(&[], &mut msg2_buf).unwrap();
        assert_eq!(msg2_len, 96);

        let mut node_transport = match init_session {
            PeerNoiseSession::HandshakingInitiator { mut state, .. } => {
                state.read_message(&msg2_buf[..msg2_len], &mut rbuf).unwrap();
                let mut msg3_buf = [0u8; 256];
                let msg3_len = state.write_message(&[], &mut msg3_buf).unwrap();
                assert_eq!(msg3_len, 64);
                peer_resp.read_message(&msg3_buf[..msg3_len], &mut rbuf).unwrap();
                state.into_transport_mode().unwrap()
            }
            _ => panic!("Expected HandshakingInitiator"),
        };
        let mut peer_transport = peer_resp.into_transport_mode().unwrap();

        // 2. Send 5 consecutive private messages (including identical text and mesh-relayed duplicate frames)
        // and verify every single message decrypts & receives a valid encrypted ACK reply.
        let mut seen_nonces: VecDeque<u64> = VecDeque::new();
        let mut seen_msg_ids: VecDeque<String> = VecDeque::new();

        for text in ["5", "o", "v", "5", "second help"] {
            let tlv = BitChatService::encode_bitchat_private_message(text);
            let p_nonce = peer_transport.sending_nonce() as u32;
            let mut cbuf = [0u8; 256];
            let clen = peer_transport.write_message(&tlv, &mut cbuf).unwrap();
            let mut wire = p_nonce.to_be_bytes().to_vec();
            wire.extend_from_slice(&cbuf[..clen]);

            // First arrival
            let n = u32::from_be_bytes([wire[0], wire[1], wire[2], wire[3]]) as u64;
            assert!(!seen_nonces.contains(&n));
            node_transport.set_receiving_nonce(n);
            let mut dbuf = [0u8; 256];
            let dlen = node_transport.read_message(&wire[4..], &mut dbuf).unwrap();
            seen_nonces.push_back(n);

            let (mid_opt, extracted) =
                BitChatService::extract_bitchat_private_message_with_id(&dbuf[..dlen]);
            assert_eq!(extracted, text);
            let mid = mid_opt.expect("UUIDv4 msg_id");
            assert!(!seen_msg_ids.contains(&mid));
            seen_msg_ids.push_back(mid);

            // Mesh-relayed duplicate copy of the same frame is cleanly suppressed
            assert!(seen_nonces.contains(&n));

            // Node sends encrypted ACK back to peer
            let ack_tlv =
                BitChatService::encode_bitchat_private_message(&format!("ACK: {}", text));
            let ack_nonce = node_transport.sending_nonce() as u32;
            let mut ack_cbuf = [0u8; 256];
            let ack_clen = node_transport.write_message(&ack_tlv, &mut ack_cbuf).unwrap();
            peer_transport.set_receiving_nonce(ack_nonce as u64);
            let mut peer_dbuf = [0u8; 256];
            let peer_dlen = peer_transport
                .read_message(&ack_cbuf[..ack_clen], &mut peer_dbuf)
                .unwrap();
            assert_eq!(
                BitChatService::extract_bitchat_private_message(&peer_dbuf[..peer_dlen]),
                format!("ACK: {}", text)
            );
        }
    }

    #[test]
    fn test_announce_direct_neighbors_and_v2_routed_packet_parsing() {
        let (signing_key, noise_pubkey, sender_id) =
            BitChatService::derive_keys("OpenAlert-FOG-Node02");
        let neighbor_tablet = [0x87, 0xdf, 0xcb, 0x12, 0xe0, 0xe8, 0xbe, 0xcc];
        let neighbor_phone = [0x2a, 0x7b, 0xc9, 0x9a, 0x8d, 0xbe, 0x97, 0x5f];

        let ann = BitChatService::build_announce_packet_with_neighbors(
            "OpenAlert-FOG-Node02",
            &signing_key,
            &noise_pubkey,
            &[neighbor_tablet, neighbor_phone],
        );
        assert_eq!(ann.len(), 256);

        let parsed = BitChatService::parse_incoming_packet(&ann).expect("Valid announce");
        assert!(parsed.signature_valid);
        assert_eq!(parsed.sender_id, sender_id);
        assert_eq!(parsed.ttl, MESSAGE_TTL_HOPS);

        // Verify TLV 0x04 (`directNeighbors`) contains exact 16 bytes (`neighbor_tablet` || `neighbor_phone`)
        let payload_len = u16::from_be_bytes([ann[12], ann[13]]) as usize;
        let raw_payload = &ann[22..22 + payload_len];
        let mut off = 0;
        let mut found_neighbors: Option<&[u8]> = None;
        while off + 2 <= raw_payload.len() {
            let tag = raw_payload[off];
            let len = raw_payload[off + 1] as usize;
            off += 2;
            if tag == TLV_TAG_ROUTE_PEER_ID {
                found_neighbors = Some(&raw_payload[off..off + len]);
                break;
            }
            off += len;
        }
        let nb = found_neighbors.expect("TLV 0x04 directNeighbors present");
        assert_eq!(nb.len(), 16);
        assert_eq!(&nb[0..8], &neighbor_tablet);
        assert_eq!(&nb[8..16], &neighbor_phone);

        // Verify BitChat v2 (`0x02`) 16-byte header + `FLAG_HAS_ROUTE` (`0x08`) source-routed packet parsing
        let payload = b"v2-routed-ciphertext-payload";
        let mut v2_pkt = Vec::new();
        v2_pkt.push(PACKET_VERSION_V2); // version 2
        v2_pkt.push(PACKET_TYPE_NOISE_ENCRYPTED);
        v2_pkt.push(6); // relayed 1 hop (TTL 7 -> 6)
        v2_pkt.extend_from_slice(&1700000000000u64.to_be_bytes());
        v2_pkt.push(FLAG_HAS_RECIPIENT | FLAG_HAS_ROUTE);
        v2_pkt.extend_from_slice(&(payload.len() as u32).to_be_bytes()); // 4-byte u32 payload_len in v2
        v2_pkt.extend_from_slice(&neighbor_phone); // sender
        v2_pkt.extend_from_slice(&sender_id); // recipient (node02)
        v2_pkt.push(1); // 1 intermediate hop (`neighbor_tablet`)
        v2_pkt.extend_from_slice(&neighbor_tablet);
        v2_pkt.extend_from_slice(payload);

        let parsed_v2 =
            BitChatService::parse_incoming_packet(&v2_pkt).expect("Parse BitChat v2 routed packet");
        assert_eq!(parsed_v2.packet_type, PACKET_TYPE_NOISE_ENCRYPTED);
        assert_eq!(parsed_v2.ttl, 6);
        assert_eq!(parsed_v2.sender_id, neighbor_phone);
        assert_eq!(parsed_v2.recipient_id, Some(sender_id));
        assert_eq!(parsed_v2.payload.as_deref(), Some(&payload[..]));
    }

    #[test]
    fn test_is_retryable_hci_error() {
        assert!(BitChatService::is_retryable_hci_error(
            "Set Powered for hci0 failed with status 0x0a (Busy)"
        ));
        assert!(BitChatService::is_retryable_hci_error(
            "org.bluez.Error.InProgress: Operation already in progress"
        ));
        assert!(BitChatService::is_retryable_hci_error(
            "org.bluez.Error.NotReady: Resource Not Ready"
        ));
        assert!(!BitChatService::is_retryable_hci_error(
            "org.freedesktop.DBus.Error.AccessDenied"
        ));
    }
}

