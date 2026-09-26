//! # Nostr NIP-44 v2 & NIP-59 / NIP-17 Direct Messaging Implementation
//!
//! Provides authenticated encryption and decryption according to:
//! - **NIP-44 v2**: ChaCha20 + HMAC-SHA256 authenticated encryption using HKDF-derived keys
//! - **NIP-59 / NIP-17**: Gift Wrap (Kind 1059) -> Seal (Kind 13) -> Rumor (Kind 14) unwrapping

use crate::error::{OpenAlertError, Result};
use base64::prelude::*;
use chacha20::cipher::{KeyIvInit, StreamCipher};
use chacha20::ChaCha20;
use hmac::{Hmac, Mac};
use rand::RngCore;
use secp256k1::{PublicKey, Secp256k1, SecretKey, XOnlyPublicKey};
use sha2::{Digest, Sha256};
use std::sync::LazyLock;

type HmacSha256 = Hmac<Sha256>;

static SECP: LazyLock<Secp256k1<secp256k1::All>> = LazyLock::new(Secp256k1::new);

/// Derives the 32-byte X-coordinate shared secret $P = d \cdot Q$ for NIP-44.
pub fn derive_nip44_shared_secret(sk: &SecretKey, pk: &PublicKey) -> Result<[u8; 32]> {
    let scalar = secp256k1::Scalar::from_be_bytes(sk.secret_bytes())
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid scalar from secret key: {:?}", e)))?;

    let point = pk
        .mul_tweak(&SECP, &scalar)
        .map_err(|e| OpenAlertError::Crypto(format!("ECDH curve multiplication failed: {:?}", e)))?;

    let comp = point.serialize();
    let mut x_coord = [0u8; 32];
    x_coord.copy_from_slice(&comp[1..33]);
    Ok(x_coord)
}

/// Converts a 32-byte X-Only public key (BIP-340) into a full Secp256k1 public key with even Y.
pub fn xonly_to_pubkey(xonly: &XOnlyPublicKey) -> Result<PublicKey> {
    let mut compressed = [0u8; 33];
    compressed[0] = 0x02; // Even Y coordinate
    compressed[1..33].copy_from_slice(&xonly.serialize());
    PublicKey::from_slice(&compressed)
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid public key from xonly: {}", e)))
}

/// Computes the 32-byte conversation key using HKDF-extract with salt "nip44-v2".
pub fn derive_conversation_key(sk: &SecretKey, pk: &PublicKey) -> Result<[u8; 32]> {
    let shared_x = derive_nip44_shared_secret(sk, pk)?;
    let mut mac = HmacSha256::new_from_slice(b"nip44-v2")
        .map_err(|e| OpenAlertError::Crypto(format!("HMAC init failed: {}", e)))?;
    mac.update(&shared_x);
    let prk = mac.finalize().into_bytes();
    let mut conv_key = [0u8; 32];
    conv_key.copy_from_slice(&prk);
    Ok(conv_key)
}

/// Expands the conversation key and 32-byte nonce into ChaCha20 key, nonce, and HMAC key.
fn expand_message_keys(conv_key: &[u8; 32], nonce: &[u8; 32]) -> Result<([u8; 32], [u8; 12], [u8; 32])> {
    let hkdf = hkdf::Hkdf::<Sha256>::from_prk(conv_key)
        .map_err(|e| OpenAlertError::Crypto(format!("HKDF from_prk failed: {:?}", e)))?;

    let mut okm = [0u8; 76];
    hkdf.expand(nonce, &mut okm)
        .map_err(|e| OpenAlertError::Crypto(format!("HKDF expand failed: {:?}", e)))?;

    let mut chacha_key = [0u8; 32];
    let mut chacha_nonce = [0u8; 12];
    let mut hmac_key = [0u8; 32];

    chacha_key.copy_from_slice(&okm[0..32]);
    chacha_nonce.copy_from_slice(&okm[32..44]);
    hmac_key.copy_from_slice(&okm[44..76]);

    Ok((chacha_key, chacha_nonce, hmac_key))
}

/// Calculates the padded length according to NIP-44 v2 padding rules.
pub fn calc_padded_len(unpadded_len: usize) -> usize {
    if unpadded_len <= 32 {
        return 32;
    }
    let next_power = 1usize << ((unpadded_len - 1).ilog2() + 1);
    let chunk = if next_power <= 256 { 32 } else { next_power / 8 };
    if unpadded_len <= chunk {
        chunk
    } else {
        chunk * ((unpadded_len - 1) / chunk + 1)
    }
}

/// Encrypts plaintext using NIP-44 v2 authenticated encryption (base64 output).
pub fn nip44_encrypt(sk: &SecretKey, pk: &PublicKey, plaintext: &str) -> Result<String> {
    let conv_key = derive_conversation_key(sk, pk)?;
    let mut nonce = [0u8; 32];
    rand::rng().fill_bytes(&mut nonce);

    let (chacha_key, chacha_nonce, hmac_key) = expand_message_keys(&conv_key, &nonce)?;

    let unpadded_bytes = plaintext.as_bytes();
    let unpadded_len = unpadded_bytes.len();
    if unpadded_len == 0 || unpadded_len > 65535 {
        return Err(OpenAlertError::Crypto(format!(
            "Plaintext length {} is out of NIP-44 bounds [1, 65535]",
            unpadded_len
        )));
    }

    let padded_len = calc_padded_len(unpadded_len);
    let mut payload = vec![0u8; 2 + padded_len];
    payload[0..2].copy_from_slice(&(unpadded_len as u16).to_be_bytes());
    payload[2..2 + unpadded_len].copy_from_slice(unpadded_bytes);

    let mut cipher = ChaCha20::new(&chacha_key.into(), &chacha_nonce.into());
    cipher.apply_keystream(&mut payload);

    let mut mac = HmacSha256::new_from_slice(&hmac_key)
        .map_err(|e| OpenAlertError::Crypto(format!("HMAC init failed: {}", e)))?;
    mac.update(&nonce);
    mac.update(&payload);
    let computed_mac = mac.finalize().into_bytes();

    let mut result = Vec::with_capacity(1 + 32 + payload.len() + 32);
    result.push(0x02); // Version 2
    result.extend_from_slice(&nonce);
    result.extend_from_slice(&payload);
    result.extend_from_slice(&computed_mac);

    Ok(BASE64_STANDARD.encode(&result))
}

/// Decrypts a NIP-44 v2 base64 payload.
pub fn nip44_decrypt(sk: &SecretKey, pk: &PublicKey, payload_b64: &str) -> Result<String> {
    let clean_b64 = payload_b64.trim();
    let raw = BASE64_STANDARD
        .decode(clean_b64)
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid base64 in NIP-44 payload: {}", e)))?;

    if raw.len() < 1 + 32 + 32 + 2 {
        return Err(OpenAlertError::Crypto(format!(
            "NIP-44 payload too short ({} bytes)",
            raw.len()
        )));
    }

    if raw[0] != 0x02 {
        return Err(OpenAlertError::Crypto(format!(
            "Unsupported NIP-44 version: {}",
            raw[0]
        )));
    }

    let mut nonce = [0u8; 32];
    nonce.copy_from_slice(&raw[1..33]);

    let ciphertext_end = raw.len() - 32;
    let ciphertext = &raw[33..ciphertext_end];
    let provided_mac = &raw[ciphertext_end..];

    let conv_key = derive_conversation_key(sk, pk)?;
    let (chacha_key, chacha_nonce, hmac_key) = expand_message_keys(&conv_key, &nonce)?;

    let mut mac = HmacSha256::new_from_slice(&hmac_key)
        .map_err(|e| OpenAlertError::Crypto(format!("HMAC init failed: {}", e)))?;
    mac.update(&nonce);
    mac.update(ciphertext);
    mac.verify_slice(provided_mac)
        .map_err(|_| OpenAlertError::Crypto("NIP-44 HMAC verification failed (tampered or wrong key)".to_string()))?;

    let mut decrypted = ciphertext.to_vec();
    let mut cipher = ChaCha20::new(&chacha_key.into(), &chacha_nonce.into());
    cipher.apply_keystream(&mut decrypted);

    if decrypted.len() < 2 {
        return Err(OpenAlertError::Crypto("Decrypted payload too short for length header".to_string()));
    }

    let unpadded_len = u16::from_be_bytes([decrypted[0], decrypted[1]]) as usize;
    if unpadded_len > decrypted.len() - 2 {
        return Err(OpenAlertError::Crypto(format!(
            "Unpadded length header {} exceeds decrypted buffer size {}",
            unpadded_len,
            decrypted.len() - 2
        )));
    }

    let plaintext_bytes = &decrypted[2..2 + unpadded_len];
    String::from_utf8(plaintext_bytes.to_vec())
        .map_err(|e| OpenAlertError::Crypto(format!("Decrypted NIP-44 content is not valid UTF-8: {}", e)))
}

/// Unwrapped NIP-17 / NIP-59 message payload containing author and message content.
#[derive(Debug, Clone)]
pub struct UnwrappedGiftWrap {
    /// The real verified author of the message (from Kind 13 Seal).
    pub sender_pubkey: String,
    /// The unencrypted message body (from Kind 14 Rumor).
    pub content: String,
    /// Original rumor creation timestamp.
    pub created_at: u64,
    /// Optional tags from the Kind 14 Rumor (e.g. NIP-10 #e parent event references).
    pub tags: Vec<Vec<String>>,
}

/// Unwraps a NIP-59 Gift Wrap (Kind 1059) envelope addressed to this recipient.
///
/// Flow:
/// 1. Decrypts the Gift Wrap (Kind 1059) payload using recipient secret key + ephemeral wrap pubkey -> produces Kind 13 Seal JSON.
/// 2. Parses Kind 13 Seal and extracts the real author public key.
/// 3. Decrypts the Seal (Kind 13) payload using recipient secret key + author pubkey -> produces Kind 14 Rumor JSON.
/// 4. Parses Kind 14 Rumor and returns the unencrypted command text.
pub fn sign_event(
    keypair: &secp256k1::Keypair,
    kind: u64,
    created_at: u64,
    tags: Vec<Vec<String>>,
    content: String,
) -> Result<crate::models::NostrEvent> {
    let pubkey_hex = hex::encode(keypair.x_only_public_key().0.serialize());
    let serialized = serde_json::to_string(&serde_json::json!([
        0,
        pubkey_hex,
        created_at,
        kind,
        tags,
        content
    ]))?;

    let mut hasher = Sha256::new();
    hasher.update(serialized.as_bytes());
    let id_bytes = hasher.finalize();
    let id_hex = hex::encode(id_bytes);

    let sig = SECP.sign_schnorr(id_bytes.as_slice(), keypair);
    let sig_hex = hex::encode(sig.as_ref());

    Ok(crate::models::NostrEvent {
        id: id_hex,
        pubkey: pubkey_hex,
        created_at,
        kind,
        tags,
        content,
        sig: sig_hex,
    })
}

/// Wraps and signs a message into a NIP-17 / NIP-59 Gift Wrap (Kind 1059) NostrEvent.
pub fn wrap_nip59_gift_wrap(
    sender_keypair: &secp256k1::Keypair,
    recipient_pubkey_hex: &str,
    message: &str,
) -> Result<crate::models::NostrEvent> {
    let now = chrono::Utc::now().timestamp().max(0) as u64;
    let sender_pubkey_hex = hex::encode(sender_keypair.x_only_public_key().0.serialize());

    let rec_bytes = hex::decode(recipient_pubkey_hex.trim())
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid hex in recipient pubkey: {}", e)))?;
    let rec_xonly = XOnlyPublicKey::from_slice(&rec_bytes)
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid xonly recipient pubkey: {}", e)))?;
    let rec_pk = xonly_to_pubkey(&rec_xonly)?;

    // Step 1: Create Kind 14 Rumor (unsigned event)
    let rumor_tags = vec![vec!["p".to_string(), recipient_pubkey_hex.to_string()]];
    let rumor_serialized = serde_json::to_string(&serde_json::json!([
        0,
        sender_pubkey_hex,
        now,
        14,
        rumor_tags,
        message
    ]))?;
    let mut hasher = Sha256::new();
    hasher.update(rumor_serialized.as_bytes());
    let rumor_id = hex::encode(hasher.finalize());

    let rumor_json = serde_json::to_string(&serde_json::json!({
        "id": rumor_id,
        "pubkey": sender_pubkey_hex,
        "created_at": now,
        "kind": 14,
        "tags": rumor_tags,
        "content": message,
        "sig": ""
    }))?;

    // Step 2: Seal (Kind 13) encrypted with sender_sk + recipient_pk
    let seal_ciphertext = nip44_encrypt(&sender_keypair.secret_key(), &rec_pk, &rumor_json)?;
    let seal_event = sign_event(sender_keypair, 13, now, vec![], seal_ciphertext)?;
    let seal_json = serde_json::to_string(&seal_event)?;

    // Step 3: Gift Wrap (Kind 1059) encrypted with ephemeral_sk + recipient_pk
    let ephemeral_keypair = {
        let mut sk_bytes = [0u8; 32];
        rand::rng().fill_bytes(&mut sk_bytes);
        let sk = SecretKey::from_slice(&sk_bytes).unwrap();
        secp256k1::Keypair::from_secret_key(&SECP, &sk)
    };
    let wrap_ciphertext = nip44_encrypt(&ephemeral_keypair.secret_key(), &rec_pk, &seal_json)?;

    // Perturb created_at slightly within recent window (e.g. up to 120s in the past)
    let jitter = (rand::rng().next_u32() % 120) as u64;
    let wrap_created_at = now.saturating_sub(jitter);

    let wrap_tags = vec![vec!["p".to_string(), recipient_pubkey_hex.to_string()]];
    let gift_wrap_event = sign_event(&ephemeral_keypair, 1059, wrap_created_at, wrap_tags, wrap_ciphertext)?;

    Ok(gift_wrap_event)
}

pub fn unwrap_nip59_gift_wrap(
    recipient_sk: &SecretKey,
    gift_wrap_pubkey: &str,
    gift_wrap_content: &str,
) -> Result<UnwrappedGiftWrap> {
    let wrap_bytes = hex::decode(gift_wrap_pubkey.trim())
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid hex in gift wrap pubkey: {}", e)))?;
    let wrap_xonly = XOnlyPublicKey::from_slice(&wrap_bytes)
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid xonly wrap pubkey: {}", e)))?;
    let wrap_pk = xonly_to_pubkey(&wrap_xonly)?;

    // Step 1: Decrypt Gift Wrap -> Seal
    let seal_json = nip44_decrypt(recipient_sk, &wrap_pk, gift_wrap_content)?;
    let seal_val: serde_json::Value = serde_json::from_str(&seal_json)
        .map_err(|e| OpenAlertError::Crypto(format!("Failed to parse seal JSON: {}", e)))?;

    let seal_author = seal_val
        .get("pubkey")
        .and_then(|v| v.as_str())
        .ok_or_else(|| OpenAlertError::Crypto("Seal JSON missing pubkey".to_string()))?;

    let seal_content = seal_val
        .get("content")
        .and_then(|v| v.as_str())
        .ok_or_else(|| OpenAlertError::Crypto("Seal JSON missing content".to_string()))?;

    let author_bytes = hex::decode(seal_author.trim())
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid hex in seal author pubkey: {}", e)))?;
    let author_xonly = XOnlyPublicKey::from_slice(&author_bytes)
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid xonly seal author pubkey: {}", e)))?;
    let author_pk = xonly_to_pubkey(&author_xonly)?;

    // Step 2: Decrypt Seal -> Rumor
    let rumor_json = nip44_decrypt(recipient_sk, &author_pk, seal_content)?;
    let rumor_val: serde_json::Value = serde_json::from_str(&rumor_json)
        .map_err(|e| OpenAlertError::Crypto(format!("Failed to parse rumor JSON: {}", e)))?;

    let content = rumor_val
        .get("content")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();

    let created_at = rumor_val
        .get("created_at")
        .and_then(|v| v.as_u64())
        .unwrap_or(0);

    let tags = rumor_val
        .get("tags")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|item| {
                    item.as_array().map(|sub| {
                        sub.iter()
                            .filter_map(|s| s.as_str().map(String::from))
                            .collect::<Vec<String>>()
                    })
                })
                .collect::<Vec<Vec<String>>>()
        })
        .unwrap_or_default();

    Ok(UnwrappedGiftWrap {
        sender_pubkey: seal_author.to_string(),
        content,
        created_at,
        tags,
    })
}

#[cfg(test)]
mod tests {
    #[test]
    fn test_wrap_and_unwrap_nip59_roundtrip() {
        let sender_keypair = {
        let mut sk_bytes = [0u8; 32];
        rand::rng().fill_bytes(&mut sk_bytes);
        let sk = SecretKey::from_slice(&sk_bytes).unwrap();
        secp256k1::Keypair::from_secret_key(&SECP, &sk)
    };
        let recipient_keypair = {
        let mut sk_bytes = [0u8; 32];
        rand::rng().fill_bytes(&mut sk_bytes);
        let sk = SecretKey::from_slice(&sk_bytes).unwrap();
        secp256k1::Keypair::from_secret_key(&SECP, &sk)
    };
        let recipient_pubkey_hex = hex::encode(recipient_keypair.x_only_public_key().0.serialize());

        let secret_command = "ping";
        let gift_wrap = wrap_nip59_gift_wrap(&sender_keypair, &recipient_pubkey_hex, secret_command)
            .expect("wrap failed");

        assert_eq!(gift_wrap.kind, 1059);
        assert_eq!(gift_wrap.tags[0][0], "p");
        assert_eq!(gift_wrap.tags[0][1], recipient_pubkey_hex);

        let unwrapped = unwrap_nip59_gift_wrap(
            &recipient_keypair.secret_key(),
            &gift_wrap.pubkey,
            &gift_wrap.content,
        ).expect("unwrap failed");

        let expected_sender = hex::encode(sender_keypair.x_only_public_key().0.serialize());
        assert_eq!(unwrapped.sender_pubkey, expected_sender);
        assert_eq!(unwrapped.content, secret_command);
    }

    #[test]
    fn test_unwrap_real_0xchat_gift_wrap() {
        let bot_sk = SecretKey::from_slice(&hex::decode("67c4b156aedd0c6da4459d1c38e63dd4e4dadea2b80535fcec1327412299825b").unwrap()).unwrap();
        let gift_wrap_pubkey = "4b53cfdd7d65276e49f461b9468e77b54e6b1aed649ef20187dd79548b0f7796";
        let gift_wrap_content = "AiTL43EZTXEXKXHH1BXeQGh/TAyNhe2xL0Mdyt+gDW2HWybAEw6u4zqpYFBwXT7PWjORYzBpN/TJRd1mzihh8EFTSpcl2/5/MtLesGHfun4UrDYKVFm7ljMKFnHLvYPi05StPvKMhV+qTJhVteDOClR3N7hi1ic0D7kd7mWltHonhKbsRmts8iO6pOE0SzZBnTvw5lq57LHkxC7lbUrMcPlilbZ2sXmIDQ6wtjlJpbSfwAMjDhX980EtI3Zn4QxI4WO9F5tRFEJJsjkzyKysfwc/3X6RdRUqlfBUCO2ss8BHlJrZlj7X1em5yLuUrHFHwaOEHRyGXmpdNaI5sLmo15KAKSTULtsBywort8Qmyyhhyn0fO1sxoVwL1tF2RGszks/qzXz53WOhDJ9ejUzT07x9MGAEB0e7kfglFuqBlWjMkbpLrDI+FWNI0ynYn5bGWqxIbxrE+ggZuyCnSg/lgv+Hz65Y7J91TaXB8+4Z7zzpIRAFQh9b89P1v6kLvVUgvMyS9GoBbLW0gBYO8KADFH2O1VLFW4q26d6sitese/tlNHkT74aX6Z6yxsP/Dnxfdp7ML7UjN9HTrAFgDSKIhvor7UGTBcjVqk2INW+Lf6jfAHJEmpmFPt6n5i6yTC+Jy2q8ZUoaDEEo+/raHIoBxoHgkOD+ez/MOyrE/uHS2J45QWD6TD5zOJGKAGdXo5XrI8ndQlAPENphhD8wMwC5F7bcSzmzR72O9tuhVQRIZ6vJyVsmMwjG3iTEhMFhqITMhSBqIwjYA2vMfwCKDU2MuM8TgtRUxNi0nOgRiFsuGptMifnhpzO8xJwQUJCUIJZVM+TTGYjbhMXtwAui3L5l8YrGs0T14nlegfRcL58/wgGvvDxmv3Jg0QiWWUBTKlyMfxuH3PiJ0U++LB/6V4zHCPB48yqSy1659Fx4tMLS0SDY/+uNXmN5ARxb3LdEWpaldy3VLA1wAYHyHPjxo1ys4rsoDIU/i0nyQ6KZu1Qw7JdrrIcra1yXXHvAVBnqwLZmhN5qV2OAF0+o31VoT+YUZgrFQPghk/HH0O68kSiqy9C+0GPlMxOWVSM9MkpHhGcZJyO/QdRv2CNtU1kZSngLQD8WJx8B05wPoFXjX1A5G0QFbUaFW+9SQeysRZ9XYyEjaVUlyIrm4qBPOZqDgUz0Gk3qW9Q9jr1PCkhZvMWaBsG270rGtaUj9hhNH6LYpw+d6szKjd/b8+R3AEJiU8j3v4k/Fz6m8215AdlZ9fVR17bDUJRQkxmUwV1GusSCYtuTbhsf";

        let unwrapped = unwrap_nip59_gift_wrap(&bot_sk, gift_wrap_pubkey, gift_wrap_content).expect("unwrapping real 0xChat gift wrap");
        assert_eq!(unwrapped.sender_pubkey, "e3172c8eae9f88a00735c7d806f802f1aa7885770cd19701adc3e26cc225e023");
        assert_eq!(unwrapped.content, "ping");
        println!("✅ Successfully unwrapped real 0xChat NIP-59 / NIP-17 Gift Wrap message: '{}' from {}", unwrapped.content, unwrapped.sender_pubkey);
    }

    use super::*;

    #[test]
    fn test_nip44_encrypt_decrypt_roundtrip() {
        let secp = Secp256k1::new();
        let alice_sk = SecretKey::from_slice(&[0x11u8; 32]).unwrap();
        let alice_pk = PublicKey::from_secret_key(&secp, &alice_sk);

        let bob_sk = SecretKey::from_slice(&[0x22u8; 32]).unwrap();
        let bob_pk = PublicKey::from_secret_key(&secp, &bob_sk);

        let plaintext = "ping - OpenAlert 0xChat Secure Channel";
        let encrypted = nip44_encrypt(&alice_sk, &bob_pk, plaintext).expect("encryption failed");

        let decrypted = nip44_decrypt(&bob_sk, &alice_pk, &encrypted).expect("decryption failed");
        assert_eq!(decrypted, plaintext);
    }
}
