//! # NIP-04 Cryptographic Implementation (Secp256k1 ECDH + AES-256-CBC)
//!
//! Provides End-to-End Encrypted (E2EE) messaging compatible with 0xChat and Nostr clients.

use crate::error::{OpenAlertError, Result};
use aes::cipher::{BlockDecryptMut, BlockEncryptMut, KeyIvInit, block_padding::Pkcs7};
use base64::prelude::*;
use secp256k1::{PublicKey, Scalar, Secp256k1, SecretKey, XOnlyPublicKey};

type Aes256CbcEnc = cbc::Encryptor<aes::Aes256>;
type Aes256CbcDec = cbc::Decryptor<aes::Aes256>;

/// Derives the 32-byte shared secret (X coordinate of the ECDH point P = sk * PK) for NIP-04.
pub fn derive_shared_secret(
    secp: &Secp256k1<secp256k1::All>,
    sk: &SecretKey,
    pk: &PublicKey,
) -> Result<[u8; 32]> {
    let scalar = Scalar::from_be_bytes(sk.secret_bytes())
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid scalar from secret key: {:?}", e)))?;
    let point = pk.mul_tweak(secp, &scalar).map_err(|e| {
        OpenAlertError::Crypto(format!("ECDH point multiplication failed: {:?}", e))
    })?;
    let serialized = point.serialize(); // Compressed format: 02/03 || X (33 bytes)
    let mut x_coord = [0u8; 32];
    x_coord.copy_from_slice(&serialized[1..33]);
    Ok(x_coord)
}

/// Helper to convert a 32-byte BIP-340 XOnlyPublicKey (as used across Nostr tags) into a full Secp256k1 PublicKey.
pub fn xonly_to_full_pubkey(xonly: &XOnlyPublicKey) -> Result<PublicKey> {
    let mut compressed = [0u8; 33];
    compressed[0] = 0x02; // Default even Y in BIP-340 / NIP-04 convention
    compressed[1..33].copy_from_slice(&xonly.serialize());
    PublicKey::from_slice(&compressed)
        .map_err(|e| OpenAlertError::Crypto(format!("Failed to parse compressed pubkey: {:?}", e)))
}

/// Encrypts plaintext using NIP-04 standard (AES-256-CBC with PKCS#7 padding) returning `<ciphertext_b64>?iv=<iv_b64>`.
pub fn nip04_encrypt(shared_secret: &[u8; 32], plaintext: &str) -> Result<String> {
    use rand::RngCore;
    let mut iv = [0u8; 16];
    rand::rng().fill_bytes(&mut iv);

    let pt_bytes = plaintext.as_bytes();
    let pt_len = pt_bytes.len();
    let mut buf = vec![0u8; pt_len + 16];
    buf[..pt_len].copy_from_slice(pt_bytes);

    let cipher = Aes256CbcEnc::new(shared_secret.into(), &iv.into());
    let ct = cipher
        .encrypt_padded_mut::<Pkcs7>(&mut buf, pt_len)
        .map_err(|e| OpenAlertError::Crypto(format!("AES encryption failed: {:?}", e)))?;

    let ct_b64 = BASE64_STANDARD.encode(ct);
    let iv_b64 = BASE64_STANDARD.encode(iv);
    Ok(format!("{}?iv={}", ct_b64, iv_b64))
}

/// Decrypts a NIP-04 formatted ciphertext `<ciphertext_b64>?iv=<iv_b64>`.
pub fn nip04_decrypt(shared_secret: &[u8; 32], payload: &str) -> Result<String> {
    let mut parts = payload.split("?iv=");
    let ct_b64 = parts.next().ok_or_else(|| {
        OpenAlertError::Crypto("Malformed NIP-04 payload (missing ciphertext)".to_string())
    })?;
    let iv_b64 = parts.next().ok_or_else(|| {
        OpenAlertError::Crypto("Malformed NIP-04 payload (missing '?iv=')".to_string())
    })?;

    let ct = BASE64_STANDARD
        .decode(ct_b64.trim())
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid base64 ciphertext: {:?}", e)))?;
    let iv = BASE64_STANDARD
        .decode(iv_b64.trim())
        .map_err(|e| OpenAlertError::Crypto(format!("Invalid base64 IV: {:?}", e)))?;

    if iv.len() != 16 {
        return Err(OpenAlertError::Crypto(
            "Invalid IV length for AES-CBC (must be 16 bytes)".to_string(),
        ));
    }

    let mut buf = ct;
    let cipher = Aes256CbcDec::new(shared_secret.into(), iv.as_slice().into());
    let pt = cipher
        .decrypt_padded_mut::<Pkcs7>(&mut buf)
        .map_err(|e| OpenAlertError::Crypto(format!("AES decryption failed: {:?}", e)))?;

    String::from_utf8(pt.to_vec()).map_err(|e| {
        OpenAlertError::Crypto(format!("Decrypted bytes are not valid UTF-8: {:?}", e))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_nip04_encrypt_decrypt_roundtrip() {
        let secp = Secp256k1::new();

        // Alice (OpenAlert Bot)
        let sk_alice = SecretKey::from_slice(&[0x11u8; 32]).unwrap();
        let pk_alice = PublicKey::from_secret_key(&secp, &sk_alice);

        // Bob (0xChat Mobile Operator)
        let sk_bob = SecretKey::from_slice(&[0x22u8; 32]).unwrap();
        let pk_bob = PublicKey::from_secret_key(&secp, &sk_bob);

        // Alice derives shared secret with Bob's public key
        let shared_alice = derive_shared_secret(&secp, &sk_alice, &pk_bob).unwrap();

        // Bob derives shared secret with Alice's public key
        let shared_bob = derive_shared_secret(&secp, &sk_bob, &pk_alice).unwrap();

        // Must be identical!
        assert_eq!(shared_alice, shared_bob, "ECDH shared secrets MUST match!");

        let alert_text = "🚨 CRITICAL: Transformer Overheating at Substation 4! Temp: 98C";
        let encrypted = nip04_encrypt(&shared_alice, alert_text).unwrap();
        assert!(encrypted.contains("?iv="));

        let decrypted = nip04_decrypt(&shared_bob, &encrypted).unwrap();
        assert_eq!(decrypted, alert_text);
    }

    #[test]
    fn test_nip04_cross_python_compatibility() {
        let secp = Secp256k1::new();

        // Matching secret keys tested in Python:
        let sk_alice = SecretKey::from_slice(&[0x11u8; 32]).unwrap();
        let sk_bob = SecretKey::from_slice(&[0x22u8; 32]).unwrap();
        let pk_alice = PublicKey::from_secret_key(&secp, &sk_alice);

        // Derive shared secret
        let shared_bob = derive_shared_secret(&secp, &sk_bob, &pk_alice).unwrap();
        let expected_shared =
            hex::decode("77e0510d5042e2f5e9e59c977b81eeed590cf7d20c1c51da451a8eaa9fdc45ff")
                .unwrap();
        assert_eq!(
            &shared_bob[..],
            &expected_shared[..],
            "Derived shared secret matches Python exact hex!"
        );

        // Decrypt ciphertext generated by Python
        let python_ciphertext =
            "0K192oMhtNbmcBexzGl5loqsPg5GZwm5G8E+601m6AQ=?iv=e7gaapRNTgUydCM7F4r6TA==";
        let decrypted = nip04_decrypt(&shared_bob, python_ciphertext).unwrap();
        assert_eq!(decrypted, "Test Alert for Substation");
    }
}
