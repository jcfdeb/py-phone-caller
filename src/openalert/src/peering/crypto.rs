//! # XChaCha20-Poly1305 Authenticated Encryption for Peering Datagrams
//!
//! Provides zero-handshake, stateless AEAD security using 24-byte random nonces and 256-bit
//! pre-shared symmetric keys (PSK).

use crate::error::{OpenAlertError, Result};
use chacha20poly1305::aead::{Aead, KeyInit};
use chacha20poly1305::{Key, XChaCha20Poly1305, XNonce};
use rand::RngCore;
use std::collections::HashMap;

/// Length of the XChaCha20 nonce in bytes (192 bits).
pub const NONCE_LEN: usize = 24;

/// Length of the Poly1305 authentication tag in bytes (128 bits).
pub const TAG_LEN: usize = 16;

/// Minimum valid datagram length (Nonce + MAC Tag with 0-byte payload).
pub const MIN_DATAGRAM_LEN: usize = NONCE_LEN + TAG_LEN;

/// Encrypts plaintext bytes using XChaCha20-Poly1305 with a freshly generated random 192-bit nonce.
///
/// Output format: `[ 24-byte Nonce ] || [ Ciphertext with appended 16-byte Poly1305 MAC ]`
pub fn encrypt_datagram(key: &[u8; 32], plaintext: &[u8]) -> Result<Vec<u8>> {
    let mut nonce_bytes = [0u8; NONCE_LEN];
    rand::rng().fill_bytes(&mut nonce_bytes);
    let nonce = XNonce::from_slice(&nonce_bytes);

    let cipher = XChaCha20Poly1305::new(Key::from_slice(key));
    let ciphertext = cipher
        .encrypt(nonce, plaintext)
        .map_err(|e| OpenAlertError::Crypto(format!("AEAD encryption failed: {}", e)))?;

    let mut datagram = Vec::with_capacity(NONCE_LEN + ciphertext.len());
    datagram.extend_from_slice(&nonce_bytes);
    datagram.extend_from_slice(&ciphertext);

    Ok(datagram)
}

/// Decrypts an inbound UDP datagram using XChaCha20-Poly1305.
///
/// Discards corrupt or unauthenticated datagrams in 0ms without evaluating contents.
pub fn decrypt_datagram(key: &[u8; 32], datagram: &[u8]) -> Result<Vec<u8>> {
    if datagram.len() < MIN_DATAGRAM_LEN {
        return Err(OpenAlertError::Crypto(format!(
            "Datagram length ({} bytes) is shorter than minimum required ({} bytes)",
            datagram.len(),
            MIN_DATAGRAM_LEN
        )));
    }

    let (nonce_bytes, ciphertext) = datagram.split_at(NONCE_LEN);
    let nonce = XNonce::from_slice(nonce_bytes);

    let cipher = XChaCha20Poly1305::new(Key::from_slice(key));
    let plaintext = cipher
        .decrypt(nonce, ciphertext)
        .map_err(|_| OpenAlertError::Crypto("AEAD authentication/decryption failed".to_string()))?;

    Ok(plaintext)
}

/// Parses a 64-character hexadecimal string into a 32-byte pre-shared key.
pub fn parse_psk(hex_str: &str) -> Result<[u8; 32]> {
    let clean = hex_str.trim();
    if clean.len() != 64 {
        return Err(OpenAlertError::Config(format!(
            "Invalid PSK length: expected 64 hex characters (32 bytes), got {}",
            clean.len()
        )));
    }

    let bytes = hex::decode(clean)
        .map_err(|e| OpenAlertError::Config(format!("Invalid PSK hex encoding: {}", e)))?;

    let mut key = [0u8; 32];
    key.copy_from_slice(&bytes);
    Ok(key)
}

/// Cryptographic key registry resolving global and per-peer PSKs for physical isolation.
#[derive(Debug, Clone)]
pub struct KeyRegistry {
    default_key: Option<[u8; 32]>,
    peer_keys: HashMap<String, [u8; 32]>,
}

impl KeyRegistry {
    /// Creates a key registry from global and per-peer configuration.
    pub fn new(global_key_hex: &str, peer_overrides: &[(String, Option<String>)]) -> Result<Self> {
        let default_key = if !global_key_hex.trim().is_empty() {
            Some(parse_psk(global_key_hex)?)
        } else {
            None
        };

        let mut peer_keys = HashMap::new();
        for (name, override_hex) in peer_overrides {
            if let Some(hex_key) = override_hex
                && !hex_key.trim().is_empty()
            {
                peer_keys.insert(name.clone(), parse_psk(hex_key)?);
            }
        }

        Ok(Self {
            default_key,
            peer_keys,
        })
    }

    /// Resolves the active 32-byte key for a named peer.
    pub fn get_key_for_peer(&self, peer_name: &str) -> Option<&[u8; 32]> {
        if let Some(k) = self.peer_keys.get(peer_name) {
            Some(k)
        } else {
            self.default_key.as_ref()
        }
    }

    /// Attempts to decrypt an inbound datagram against all configured keys (per-peer and default).
    pub fn try_decrypt_any(&self, datagram: &[u8]) -> Option<(Vec<u8>, Option<String>)> {
        // Try per-peer keys first
        for (peer_name, key) in &self.peer_keys {
            if let Ok(plaintext) = decrypt_datagram(key, datagram) {
                return Some((plaintext, Some(peer_name.clone())));
            }
        }

        // Fall back to global default key
        if let Some(ref key) = self.default_key
            && let Ok(plaintext) = decrypt_datagram(key, datagram)
        {
            return Some((plaintext, None));
        }

        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_xchacha20_encrypt_decrypt_roundtrip() {
        let key = [0x42u8; 32];
        let payload = b"critical-peering-alert-payload";

        let encrypted = encrypt_datagram(&key, payload).expect("Encryption failed");
        // Nonce (24B) + Payload (30B) + Poly1305 Tag (16B) = 70B
        assert_eq!(encrypted.len(), NONCE_LEN + payload.len() + TAG_LEN);

        let decrypted = decrypt_datagram(&key, &encrypted).expect("Decryption failed");
        assert_eq!(decrypted, payload);
    }

    #[test]
    fn test_wrong_key_rejected() {
        let key1 = [0x42u8; 32];
        let key2 = [0x99u8; 32];
        let payload = b"secret-alert";

        let encrypted = encrypt_datagram(&key1, payload).expect("Encryption failed");
        let res = decrypt_datagram(&key2, &encrypted);
        assert!(res.is_err());
    }

    #[test]
    fn test_short_datagram_rejected() {
        let key = [0x42u8; 32];
        let res = decrypt_datagram(&key, &[0u8; 10]);
        assert!(res.is_err());
    }
}
