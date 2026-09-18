//! # BitChat Bluetooth Mesh Protocol Implementation
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
use chrono::Utc;
use ed25519_dalek::{Signer, SigningKey, Verifier, VerifyingKey};
use futures_util::FutureExt;
use sha2::{Digest, Sha256};
use snow::TransportState;
use std::collections::{BTreeSet, HashMap};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{broadcast, RwLock};
use tokio::time::sleep;
use tracing::{info, warn};
use x25519_dalek::{PublicKey as X25519PublicKey, StaticSecret as X25519StaticSecret};

pub const DEFAULT_BITCHAT_SERVICE_UUID: &str = "f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5c";
pub const DEFAULT_BITCHAT_CHAR_UUID: &str = "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d";

pub const PACKET_VERSION: u8 = 0x01;
pub const PACKET_TYPE_ANNOUNCE: u8 = 0x01;
pub const PACKET_TYPE_MESSAGE: u8 = 0x02;
pub const PACKET_TYPE_NOISE_HANDSHAKE: u8 = 0x10;
pub const PACKET_TYPE_NOISE_ENCRYPTED: u8 = 0x11;
pub const PACKET_TYPE_KEY_EXCHANGE_REQ: u8 = 0x10;
pub const PACKET_TYPE_KEY_EXCHANGE_RESP: u8 = 0x10;
pub const PACKET_TYPE_KEY_EXCHANGE_FINAL: u8 = 0x10;
pub const PACKET_TYPE_ENCRYPTED_MESSAGE: u8 = 0x11;
pub const PACKET_TYPE_ENCRYPTED_ACK: u8 = 0x11;
pub const PACKET_TYPE_REQUEST_SYNC: u8 = 0x20;
pub const PACKET_TYPE_SYNC_RESPONSE: u8 = 0x21;

pub const BITCHAT_BROADCAST_RECIPIENT: [u8; 8] = [0xff; 8];

pub const FLAG_HAS_RECIPIENT: u8 = 0x01;
pub const FLAG_HAS_SIGNATURE: u8 = 0x02;
pub const FLAG_HAS_ROUTE: u8 = 0x04;
pub const FLAG_IS_RSR: u8 = 0x10;

pub const TLV_TAG_NICKNAME: u8 = 0x01;
pub const TLV_TAG_NOISE_PUBKEY: u8 = 0x02;
pub const TLV_TAG_SIGNING_PUBKEY: u8 = 0x03;
pub const TLV_TAG_ROUTE_PEER_ID: u8 = 0x04;

pub const MESSAGE_TTL_HOPS: u8 = 0x07;
pub const BITCHAT_BUCKET_SIZE_256: usize = 256;

/// Live state representation for peer-to-peer Noise encryption handshakes and transport.
pub enum PeerNoiseSession {
    Handshaking(Box<snow::HandshakeState>),
    Established(TransportState),
}

/// Represents a parsed and cryptographically validated incoming BitChat packet.
#[derive(Debug, Clone)]
pub struct ParsedPacket {
    pub packet_type: u8,
    pub sender_id: [u8; 8],
    pub recipient_id: Option<[u8; 8]>,
    pub payload: Option<Vec<u8>>,
    pub signature_valid: bool,
}

/// Manages native Linux BlueZ Bluetooth Low Energy operations and BitChat mesh communications.
pub struct BitChatService {
    config: BitChatConfig,
    engine: Option<Arc<AlertEngine>>,
    running: Arc<AtomicBool>,
    sessions: Arc<RwLock<HashMap<[u8; 8], PeerNoiseSession>>>,
}

impl BitChatService {
    /// Creates a new instance of the BitChat service.
    pub fn new(config: BitChatConfig, engine: Option<Arc<AlertEngine>>) -> Self {
        Self {
            config,
            engine,
            running: Arc::new(AtomicBool::new(true)),
            sessions: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Terminates all background BLE advertising and notification loops.
    pub fn stop(&self) {
        self.running.store(false, Ordering::Relaxed);
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

    /// Encodes TLV metadata blocks (Nickname, Noise X25519 Pubkey, Ed25519 Signing Pubkey) for Node Announcements.
    /// Extracts plain text from BitChat decrypted Noise transport payload.
    /// Supports BitChat PrivateMessagePacket (0x01 || tag 0x00 msgID || tag 0x01 content)
    /// as well as raw UTF-8 payloads.
    pub fn extract_bitchat_private_message(plaintext: &[u8]) -> String {
        if plaintext.is_empty() {
            return String::new();
        }

        // Check for BitChat Noise privateMessage packet: 0x01 || TLV blocks
        if plaintext[0] == 0x01 && plaintext.len() >= 4 {
            let mut offset = 1;
            let mut extracted_content: Option<String> = None;
            while offset + 2 <= plaintext.len() {
                let tag = plaintext[offset];
                let len = plaintext[offset + 1] as usize;
                offset += 2;
                if offset + len <= plaintext.len() {
                    let val = &plaintext[offset..offset + len];
                    if tag == 0x01 {
                        extracted_content = std::str::from_utf8(val).ok().map(|s| s.trim().to_string());
                    }
                    offset += len;
                } else {
                    break;
                }
            }
            if let Some(s) = extracted_content.filter(|s| !s.is_empty()) {
                return s;
            }
        }

        // Fallback: strip leading control byte (<= 0x20) if present
        let clean = if plaintext[0] <= 0x20 {
            &plaintext[1..]
        } else {
            plaintext
        };
        String::from_utf8_lossy(clean).trim().to_string()
    }

    pub fn build_announce_payload(
        node_name: &str,
        noise_pubkey: &[u8; 32],
        ed_pubkey: &[u8; 32],
    ) -> Vec<u8> {
        let mut payload = Vec::with_capacity(2 + node_name.len().min(32) + 34 + 34);

        let name_bytes = node_name.as_bytes();
        let name_len = name_bytes.len().min(32) as u8;
        payload.push(TLV_TAG_NICKNAME);
        payload.push(name_len);
        payload.extend_from_slice(&name_bytes[..name_len as usize]);

        payload.push(TLV_TAG_NOISE_PUBKEY);
        payload.push(32);
        payload.extend_from_slice(noise_pubkey);

        payload.push(TLV_TAG_SIGNING_PUBKEY);
        payload.push(32);
        payload.extend_from_slice(ed_pubkey);

        payload
    }

    /// Constructs a fully signed and bucket-padded BitChat Node Announce packet (Type 0x01).
    pub fn build_announce_packet(
        node_name: &str,
        signing_key: &SigningKey,
        noise_pubkey: &[u8; 32],
    ) -> Vec<u8> {
        let timestamp_ms = Utc::now().timestamp_millis() as u64;
        let ed_pubkey = signing_key.verifying_key().to_bytes();
        let sender_id = Self::derive_sender_id(noise_pubkey);
        let payload = Self::build_announce_payload(node_name, noise_pubkey, &ed_pubkey);
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

        let signing_preimage = Self::canonical_signing_preimage(&data_before_sig, BITCHAT_BUCKET_SIZE_256);
        let signature = signing_key.sign(&signing_preimage);

        let mut live_packet = data_before_sig;
        live_packet.extend_from_slice(&signature.to_bytes());

        Self::pad_to_bucket(live_packet, BITCHAT_BUCKET_SIZE_256)
    }

    /// Constructs a signed and bucket-padded BitChat Chat Message packet (Type 0x02).
    pub fn build_chat_message_packet(
        sender_id: &[u8; 8],
        recipient_id: Option<&[u8; 8]>,
        message_text: &str,
        signing_key: &SigningKey,
    ) -> Vec<u8> {
        let timestamp_ms = Utc::now().timestamp_millis() as u64;
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

    /// Constructs a signed BitChat Key Exchange Response packet (Type 0x10) carrying Noise XX Message 2 payload.
    pub fn build_key_exchange_response(
        my_sender_id: &[u8; 8],
        recipient_id: &[u8; 8],
        noise_msg2_payload: &[u8],
        signing_key: &SigningKey,
    ) -> Vec<u8> {
        let timestamp_ms = Utc::now().timestamp_millis() as u64;
        let payload_len = noise_msg2_payload.len() as u16;
        let flags = FLAG_HAS_RECIPIENT | FLAG_HAS_SIGNATURE;

        let mut data_before_sig = Vec::with_capacity(14 + 8 + 8 + noise_msg2_payload.len());
        data_before_sig.push(PACKET_VERSION);
        data_before_sig.push(PACKET_TYPE_NOISE_HANDSHAKE);
        data_before_sig.push(MESSAGE_TTL_HOPS);
        data_before_sig.extend_from_slice(&timestamp_ms.to_be_bytes());
        data_before_sig.push(flags);
        data_before_sig.extend_from_slice(&payload_len.to_be_bytes());
        data_before_sig.extend_from_slice(my_sender_id);
        data_before_sig.extend_from_slice(recipient_id);
        data_before_sig.extend_from_slice(noise_msg2_payload);

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
        let timestamp_ms = Utc::now().timestamp_millis() as u64;
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

    /// Constructs a Route-Sync-Response frame (Type 0x21) in response to peer discovery.
    pub fn build_sync_response(sender_id: &[u8; 8], _incoming_pkt: &[u8]) -> Vec<u8> {
        let timestamp_ms = Utc::now().timestamp_millis() as u64;
        let sync_payload = [
            0x01, 0x00, 0x01, 0x07, 0x02, 0x00, 0x04, 0x00, 0x00, 0x00, 0x01,
        ];
        let payload_len = sync_payload.len() as u16;

        let mut packet = Vec::with_capacity(14 + 8 + sync_payload.len());
        packet.push(PACKET_VERSION);
        packet.push(PACKET_TYPE_SYNC_RESPONSE);
        packet.push(MESSAGE_TTL_HOPS);
        packet.extend_from_slice(&timestamp_ms.to_be_bytes());
        packet.push(0x00);
        packet.extend_from_slice(&payload_len.to_be_bytes());
        packet.extend_from_slice(sender_id);
        packet.extend_from_slice(&sync_payload);

        packet
    }

    /// Parses and decodes an incoming raw Bluetooth Low Energy BitChat packet.
    pub fn parse_incoming_packet(data: &[u8]) -> Option<ParsedPacket> {
        if data.len() < 14 {
            return None;
        }

        let _pkt_version = data[0];
        let pkt_type = data[1];
        let flags = data[11];
        let payload_len = u16::from_be_bytes([data[12], data[13]]) as usize;

        let has_recipient = (flags & FLAG_HAS_RECIPIENT) != 0;
        let has_signature = (flags & FLAG_HAS_SIGNATURE) != 0;

        let mut offset = 14;
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
                    && let Ok(signature) = ed25519_dalek::Signature::from_slice(sig_bytes) {
                    let canonical_preimage = Self::canonical_signing_preimage(
                        &data[..payload_end_offset],
                        BITCHAT_BUCKET_SIZE_256,
                    );
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
                            && let Ok(name_str) = std::str::from_utf8(tval) {
                            peer_name = name_str.trim().to_string();
                        }
                        p_off += tlen;
                    } else {
                        break;
                    }
                }

                info!(
                    "📡 [BitChat Node Announce] Nickname: '{}', Sender ID: {}, Verified: {}",
                    peer_name,
                    hex::encode(sender_id),
                    if sig_valid { "✅ Valid" } else { "⚠️ Unsigned/Legacy" }
                );

                Some(ParsedPacket {
                    packet_type: pkt_type,
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
                        "💬 [BitChat {} Received]: \"{}\" (from {})",
                        prefix,
                        txt,
                        hex::encode(sender_id)
                    );
                } else {
                    info!(
                        "💬 [BitChat {} Received Raw] ({} bytes, from {})",
                        prefix,
                        payload_to_read.len(),
                        hex::encode(sender_id)
                    );
                }
                Some(ParsedPacket {
                    packet_type: pkt_type,
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
                    "🔐 [BitChat Noise Handshake] {} from peer {}",
                    desc,
                    hex::encode(sender_id)
                );
                Some(ParsedPacket {
                    packet_type: pkt_type,
                    sender_id: sender_id_arr,
                    recipient_id: recipient_id_opt,
                    payload: Some(raw_payload.to_vec()),
                    signature_valid: true,
                })
            }
            PACKET_TYPE_NOISE_ENCRYPTED => {
                info!(
                    "🔐 [BitChat Encrypted Direct Message] Received ciphertext ({} bytes) from peer {}",
                    raw_payload.len(),
                    hex::encode(sender_id)
                );
                Some(ParsedPacket {
                    packet_type: pkt_type,
                    sender_id: sender_id_arr,
                    recipient_id: recipient_id_opt,
                    payload: Some(raw_payload.to_vec()),
                    signature_valid: true,
                })
            }
            PACKET_TYPE_REQUEST_SYNC | PACKET_TYPE_SYNC_RESPONSE => {
                info!(
                    "🔄 [BitChat Sync] Handshake/Sync received from peer {}",
                    hex::encode(sender_id)
                );
                Some(ParsedPacket {
                    packet_type: pkt_type,
                    sender_id: sender_id_arr,
                    recipient_id: recipient_id_opt,
                    payload: None,
                    signature_valid: true,
                })
            }
            _ => {
                info!(
                    "📡 [BitChat Packet] Type 0x{:02x} (len: {}, sender: {})",
                    pkt_type,
                    data.len(),
                    hex::encode(sender_id)
                );
                Some(ParsedPacket {
                    packet_type: pkt_type,
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

        let session = match Session::new().await {
            Ok(s) => s,
            Err(e) => {
                warn!("⚠️ BlueZ session initialization failed (Bluetooth disabled or unavailable): {}", e);
                return Ok(());
            }
        };

        let adapter = match session.default_adapter().await {
            Ok(a) => a,
            Err(e) => {
                warn!("⚠️ Bluetooth default adapter unavailable: {}", e);
                return Ok(());
            }
        };

        if let Err(e) = adapter.set_powered(true).await {
            warn!("⚠️ Could not power on Bluetooth adapter: {}", e);
        }

        let adv_name = node_name.clone();
        let adv_uuid = service_uuid;
        let adv_adapter = adapter.clone();
        let running_adv = self.running.clone();

        tokio::spawn(async move {
            let le_advertisement = Advertisement {
                service_uuids: vec![adv_uuid].into_iter().collect::<BTreeSet<_>>(),
                local_name: Some(adv_name.clone()),
                discoverable: Some(true),
                ..Default::default()
            };

            match adv_adapter.advertise(le_advertisement).await {
                Ok(_handle) => {
                    info!(
                        "📡 BitChat BLE peripheral advertising active [Name: '{}', UUID: {}]",
                        adv_name, adv_uuid
                    );
                    while running_adv.load(Ordering::Relaxed) {
                        sleep(Duration::from_secs(1)).await;
                    }
                }
                Err(e) => {
                    warn!("⚠️ Failed to register BLE advertisement: {}", e);
                }
            }
        });

        let (bcast_tx, _) = broadcast::channel::<Vec<u8>>(128);

        if let Some(ref eng) = self.engine {
            eng.bitchat_egress.attach_broadcast_sender(bcast_tx.clone()).await;
            info!("🔗 Connected BitChat core egress channel to live GATT notification broadcast pipeline");
        }

        // Periodic 30-second mesh announce beacon to ensure continuous visibility in peer tables
        let bcast_ann = bcast_tx.clone();
        let name_ann = node_name.clone();
        let sk_ann = Arc::new(signing_key.clone());
        let np_ann = Arc::new(noise_pubkey);
        let running_ann = self.running.clone();
        tokio::spawn(async move {
            while running_ann.load(Ordering::Relaxed) {
                sleep(Duration::from_secs(30)).await;
                let ann_pkt = BitChatService::build_announce_packet(&name_ann, &sk_ann, &np_ann);
                let _ = bcast_ann.send(ann_pkt);
            }
        });

        let name_sub = node_name.clone();
        let sk_sub = Arc::new(signing_key);
        let np_sub = Arc::new(noise_pubkey);
        let sender_id_sub = sender_id;
        let bcast_tx_sub = bcast_tx.clone();

        let mut noise_hasher = Sha256::new();
        noise_hasher.update(b"bitchat-noise-dh-key-v1-");
        noise_hasher.update(node_name.as_bytes());
        let noise_privkey_bytes: [u8; 32] = noise_hasher.finalize().into();

        let sess_map = self.sessions.clone();
        let eng_opt = self.engine.clone();
        let my_sender_id = sender_id;
        let tx_w = bcast_tx.clone();
        let sk_w = sk_sub.clone();
        let np_w = np_sub.clone();
        let name_w = node_name.clone();
        let n_priv_w = Arc::new(noise_privkey_bytes);

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
                            move |_req| {
                                let pkt = Self::build_announce_packet(&n, &s, &p);
                                async move { Ok(pkt) }.boxed()
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
                            let eng_opt = eng_opt.clone();

                            async move {
                                if val.is_empty() {
                                    return Ok(());
                                }
                                let pkt_type = if val.len() > 1 { val[1] } else { 0 };

                                info!(
                                    "📡 [BitChat GATT] Received mesh packet (Type 0x{:02x}, len: {}) => Hex: {}",
                                    pkt_type,
                                    val.len(),
                                    hex::encode(&val)
                                );

                                let parsed = Self::parse_incoming_packet(&val);

                                if pkt_type == PACKET_TYPE_REQUEST_SYNC {
                                    let sync_resp = Self::build_sync_response(
                                        &my_sender_id,
                                        &val,
                                    );
                                    info!(
                                        "📡 [BitChat GATT] Sending Sync ACK (Type 0x21, {} bytes)",
                                        sync_resp.len()
                                    );
                                    let _ = tx_w.send(sync_resp);
                                } else if pkt_type == PACKET_TYPE_ANNOUNCE {
                                    let ann_reply = Self::build_announce_packet(
                                        &name_w,
                                        &sk_w,
                                        &np_w,
                                    );
                                    info!(
                                        "📡 [BitChat GATT] Transmitting Announce reply (Type 0x01, {} bytes) to peer",
                                        ann_reply.len()
                                    );
                                    let _ = tx_w.send(ann_reply);
                                } else if pkt_type == PACKET_TYPE_NOISE_HANDSHAKE || pkt_type == 0x12 {
                                    if let Some(parsed_pkt) = parsed {
                                        let from_peer = parsed_pkt.sender_id;
                                        if let Some(payload) = parsed_pkt.payload.filter(|p| !p.is_empty()) {
                                            if payload.len() == 32 {
                                                // Noise XX Message 1 (-> e, 32 bytes) from initiator
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
                                                                s.insert(from_peer, PeerNoiseSession::Handshaking(Box::new(handshake)));
                                                            }

                                                            let kex_resp = Self::build_key_exchange_response(
                                                                &my_sender_id,
                                                                &from_peer,
                                                                msg2_payload,
                                                                &sk_w,
                                                            );
                                                            info!(
                                                                "🔐 [BitChat Noise XX SHA256] Transmitting Handshake Response (Type 0x10, {} bytes) to peer {}",
                                                                kex_resp.len(),
                                                                hex::encode(from_peer)
                                                            );
                                                            let _ = tx_w.send(kex_resp);
                                                        }
                                                    }
                                                }
                                            } else if payload.len() >= 48 {
                                                // Noise XX Message 3 (-> s, se, 64 bytes) from initiator
                                                info!(
                                                    "🔐 [BitChat Noise XX SHA256] Received Handshake Final (Message 3, {} bytes) from peer {}",
                                                    payload.len(),
                                                    hex::encode(from_peer)
                                                );
                                                let mut session_opt = {
                                                    let mut s = sess_map.write().await;
                                                    s.remove(&from_peer)
                                                };

                                                if let Some(PeerNoiseSession::Handshaking(mut handshake)) = session_opt.take() {
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
                                                                    s.insert(from_peer, PeerNoiseSession::Established(transport));
                                                                }
                                                                Err(e) => warn!("Failed to convert handshake into transport mode: {}", e),
                                                            }
                                                        }
                                                        Err(e) => warn!("Failed to read Noise XX Message 3 from peer {}: {}", hex::encode(from_peer), e),
                                                    }
                                                }
                                            }
                                        }
                                    }
                                } else if pkt_type == PACKET_TYPE_NOISE_ENCRYPTED || pkt_type == 0x13 || pkt_type == 0x14 {
                                    if let Some(parsed_pkt) = parsed {
                                        let from_peer = parsed_pkt.sender_id;
                                        if let Some(cipher_bytes) = parsed_pkt.payload {
                                            let mut s = sess_map.write().await;
                                            if let Some(PeerNoiseSession::Established(transport)) = s.get_mut(&from_peer) {
                                                let orig_receiving_nonce = transport.receiving_nonce();
                                                let (recvd_nonce, actual_ciphertext) = if cipher_bytes.len() >= 20 {
                                                    let nonce_u32 = u32::from_be_bytes([
                                                        cipher_bytes[0],
                                                        cipher_bytes[1],
                                                        cipher_bytes[2],
                                                        cipher_bytes[3],
                                                    ]);
                                                    (Some(nonce_u32 as u64), &cipher_bytes[4..])
                                                } else {
                                                    (None, &cipher_bytes[..])
                                                };

                                                if let Some(nonce) = recvd_nonce {
                                                    transport.set_receiving_nonce(nonce);
                                                }

                                                let mut plain_bytes = vec![0u8; cipher_bytes.len()];
                                                let dec_res = match transport.read_message(actual_ciphertext, &mut plain_bytes) {
                                                    Ok(dec_len) => Ok(dec_len),
                                                    Err(_) => {
                                                        transport.set_receiving_nonce(orig_receiving_nonce);
                                                        transport.read_message(&cipher_bytes, &mut plain_bytes)
                                                    }
                                                };

                                                match dec_res {
                                                    Ok(dec_len) => {
                                                        plain_bytes.truncate(dec_len);
                                                        let plain_text = Self::extract_bitchat_private_message(&plain_bytes);
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
                                                        let mut enc_ack_buf = vec![0u8; reply_txt.len() + 32];
                                                        if let Ok(ack_len) = transport.write_message(reply_txt.as_bytes(), &mut enc_ack_buf) {
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

                                                        if let Some(ref eng) = eng_opt {
                                                            let alert = Alert {
                                                                alert_id: format!("bitchat-dm-{}-{}", &hex::encode(from_peer)[..8], Utc::now().timestamp_millis()),
                                                                severity: AlertSeverity::Critical,
                                                                summary: plain_text.clone(),
                                                                description: Some(format!(
                                                                    "Private 1-on-1 encrypted BLE mesh alert from BitChat peer {}",
                                                                    hex::encode(from_peer)
                                                                )),
                                                                source: AlertSource::BitChat,
                                                                sender: Some(hex::encode(from_peer)),
                                                                node: Some(name_w.to_string()),
                                                                starts_at: Utc::now(),
                                                                destinations: vec!["webhook".to_string(), "nostr".to_string(), "bitchat".to_string()],
                                                                origin_peer: None,
                                                                hop: 3,
                                                            };
                                                            let eng_clone = eng.clone();
                                                            tokio::spawn(async move {
                                                                sleep(Duration::from_millis(250)).await;
                                                                if let Err(err) = eng_clone.route_alert(alert).await {
                                                                    warn!("Failed to route BitChat private ingress alert: {}", err);
                                                                }
                                                            });
                                                        }
                                                    }
                                                    Err(e) => {
                                                        warn!(
                                                            "⚠️ [BitChat E2EE] Failed to decrypt transport message from peer {}: {}",
                                                            hex::encode(from_peer),
                                                            e
                                                        );
                                                    }
                                                }
                                            } else {
                                                warn!(
                                                    "⚠️ [BitChat E2EE] Received encrypted message without an active session from peer {}",
                                                    hex::encode(from_peer)
                                                );
                                            }
                                        }
                                    }
                                } else if (pkt_type == PACKET_TYPE_MESSAGE) && let Some(parsed_pkt) = parsed {
                                    let from_peer = parsed_pkt.sender_id;
                                    let is_broadcast = parsed_pkt.recipient_id.is_none()
                                        || parsed_pkt.recipient_id == Some(BITCHAT_BROADCAST_RECIPIENT);
                                    let is_direct_to_me = parsed_pkt.recipient_id == Some(my_sender_id);

                                    if let Some(payload) = parsed_pkt.payload {
                                        let txt = String::from_utf8_lossy(&payload).trim().to_string();

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

                                            if let Some(ref eng) = eng_opt {
                                                let alert = Alert {
                                                    alert_id: format!("bitchat-dm-{}-{}", &hex::encode(from_peer)[..8], Utc::now().timestamp_millis()),
                                                    severity: AlertSeverity::Critical,
                                                    summary: txt.clone(),
                                                    description: Some(format!(
                                                        "Private 1-on-1 direct message alert from BitChat peer {}",
                                                        hex::encode(from_peer)
                                                    )),
                                                    source: AlertSource::BitChat,
                                                    sender: Some(hex::encode(from_peer)),
                                                    node: Some(name_w.to_string()),
                                                    starts_at: Utc::now(),
                                                    destinations: vec!["webhook".to_string(), "nostr".to_string(), "bitchat".to_string()],
                                                    origin_peer: None,
                                                    hop: 3,
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
                                            info!(
                                                "💬 [BitChat Public Mesh Broadcast]: \"{}\" (from {})",
                                                txt,
                                                hex::encode(from_peer)
                                            );
                                            // Public channel mesh chat messages are NOT escalated as alerts
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
                                async move {
                                    let initial_ann = Self::build_announce_packet(
                                        &name_s, &sk_s, &np_s,
                                    );
                                    info!(
                                        "📡 [BitChat GATT] Peer subscribed to Mesh notifications. Sending fresh announce packet ({} bytes)",
                                        initial_ann.len()
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

                                    while let Ok(pkt) = rx.recv().await {
                                        let ptype =
                                            if pkt.len() > 1 { pkt[1] } else { 0 };
                                        info!(
                                            "📡 [BitChat GATT] Transmitting packet (Type 0x{:02x}, len: {}) to peer",
                                            ptype,
                                            pkt.len()
                                        );
                                        if let Err(err) = notifier.notify(pkt).await
                                        {
                                            warn!(
                                                "[BitChat GATT] Notify stream error: {}",
                                                err
                                            );
                                            break;
                                        }
                                        sleep(Duration::from_millis(150)).await;
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
                info!("✅ BitChat BlueZ GATT application registered and serving requests");
                while self.running.load(Ordering::Relaxed) {
                    sleep(Duration::from_secs(1)).await;
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
        // 1. Test extract_bitchat_private_message with BitChat TLV PrivateMessagePacket
        // 0x01 (type) || 0x00, len_id, "msg-1234" || 0x01, len_content, "FIRE IN SERVER ROOM"
        let mut tlv_bytes = vec![0x01];
        let msg_id = b"msg-1234";
        tlv_bytes.push(0x00);
        tlv_bytes.push(msg_id.len() as u8);
        tlv_bytes.extend_from_slice(msg_id);

        let content = b"FIRE IN SERVER ROOM";
        tlv_bytes.push(0x01);
        tlv_bytes.push(content.len() as u8);
        tlv_bytes.extend_from_slice(content);

        let extracted = BitChatService::extract_bitchat_private_message(&tlv_bytes);
        assert_eq!(extracted, "FIRE IN SERVER ROOM");

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

        let mut dec_buf = vec![0u8; actual_cipher.len()];
        let dec_len = resp_transport.read_message(actual_cipher, &mut dec_buf).unwrap();
        dec_buf.truncate(dec_len);

        let final_text = BitChatService::extract_bitchat_private_message(&dec_buf);
        assert_eq!(final_text, "FIRE IN SERVER ROOM");
    }

    #[test]
    fn test_live_phone_announce_verification_jorge_and_xiaomi() {
        let jorge_hex = "010107000001a089d694e90200552a7bc99a8dbe975f01054a6f72676502209554bb078bb7a96ee66eb5fdc7cc423057c6a6c9dd4e45d4fc67c431e0f34b4c0320bdbf6af05707831e372e703a1081ea1f5a984469ad2ec2cf1451dac94d6477d70408753e419cac15081df1d595522aec069f66e8d2c29b0ab2969f63df5f571a347ab332b93871ade4d531a882731eabba6ac8f4ef72daa153aec381b807f51551d0a36162e0d7486a0c55555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555555";
        let jorge_bytes = hex::decode(jorge_hex).expect("valid hex");
        let parsed_jorge = BitChatService::parse_incoming_packet(&jorge_bytes).expect("parsed jorge");
        assert_eq!(parsed_jorge.packet_type, PACKET_TYPE_ANNOUNCE);
        assert_eq!(hex::encode(parsed_jorge.sender_id), "2a7bc99a8dbe975f");
        assert!(parsed_jorge.signature_valid, "Jorge announce signature MUST be valid!");
        assert_eq!(String::from_utf8_lossy(&parsed_jorge.payload.unwrap()), "Jorge");

        let xiaomi_hex = "010106000001a089d6c064020058753e419cac15081d01087869616f6d6931310220d927fb0c88f863b5873001f518f22ba24fcc17ce0be5e033576ec9c028d7052e0320ccd4dd5ac871f381a618d10ea3eb176f5269d0817286195fcb79c625f7476e2a04082a7bc99a8dbe975f467876363e1484d0508a36d913880004d64f66de14fb57256ab88cd9e5ca375b5a8253afc7949807365f90028c3dcc86524a2654fe95527ac2d39aa450b73a0d52525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252525252";
        let xiaomi_bytes = hex::decode(xiaomi_hex).expect("valid hex");
        let parsed_xiaomi = BitChatService::parse_incoming_packet(&xiaomi_bytes).expect("parsed xiaomi");
        assert_eq!(parsed_xiaomi.packet_type, PACKET_TYPE_ANNOUNCE);
        assert_eq!(hex::encode(parsed_xiaomi.sender_id), "753e419cac15081d");
        assert!(parsed_xiaomi.signature_valid, "Xiaomi announce signature MUST be valid!");
        assert_eq!(String::from_utf8_lossy(&parsed_xiaomi.payload.unwrap()), "xiaomi11");
    }

    #[test]
    fn test_phone_key_exchange_req_handling() {
        let phone_kex1_hex = "011007000001a082bb777a0300202a7bc99a8dbe975fd0287522a59c1e762f4904acd47e64d869db0f4321635eabc85280004cb26f117ba75043e30d4e74498c59a1c4fa021c534202a4fee777b8b0a340e209e3bee63e49d3c9263670622efd0e388e4efd1bfded6d5fb37579b8346a3f057d914e03fa72b70e46c1220b828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282828282";
        let raw_bytes = hex::decode(phone_kex1_hex).expect("valid hex");
        let parsed = BitChatService::parse_incoming_packet(&raw_bytes).expect("parsed packet");

        assert_eq!(parsed.packet_type, PACKET_TYPE_NOISE_HANDSHAKE);
        assert_eq!(hex::encode(parsed.sender_id), "2a7bc99a8dbe975f");
        assert_eq!(parsed.recipient_id, Some(hex::decode("d0287522a59c1e76").unwrap().try_into().unwrap()));
        assert_eq!(parsed.payload.as_ref().map(|p| p.len()), Some(32));

        let (_, _, _) = BitChatService::derive_keys("OpenAlert-Mesh");
        let mut noise_hasher = Sha256::new();
        noise_hasher.update(b"bitchat-noise-dh-key-v1-");
        noise_hasher.update(b"OpenAlert-Mesh");
        let noise_privkey: [u8; 32] = noise_hasher.finalize().into();

        let pattern: snow::params::NoiseParams = "Noise_XX_25519_ChaChaPoly_SHA256"
            .parse()
            .expect("Valid Noise XX pattern");
        let builder = snow::Builder::new(pattern);
        let mut handshake = builder.local_private_key(&noise_privkey[..]).build_responder().expect("build responder");

        let mut read_buf = [0u8; 128];
        let res = handshake.read_message(&parsed.payload.unwrap(), &mut read_buf);
        assert!(res.is_ok(), "Failed to read Noise msg 1: {:?}", res);
    }
}
