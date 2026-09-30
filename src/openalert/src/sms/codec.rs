//! # UTF-8 and UCS-2 / GSM Encoding for Cellular SMS
//!
//! Provides transparent conversion between Rust UTF-8 strings and modem AT
//! UCS-2 / GSM7 representations, ensuring multi-byte unicode characters, emojis,
//! and international diacritics are faithfully transmitted and received.

/// Returns true if all characters in the string are safe 7-bit ASCII/GSM basic characters.
pub fn is_pure_ascii(s: &str) -> bool {
    s.chars()
        .all(|c| c.is_ascii() && (c == '\r' || c == '\n' || (' '..='~').contains(&c)))
}

/// Encodes a UTF-8 string into big-endian UTF-16 (UCS-2) hexadecimal format.
pub fn to_ucs2_hex(s: &str) -> String {
    s.encode_utf16().map(|v| format!("{:04X}", v)).collect()
}

/// Decodes a big-endian UTF-16 (UCS-2) hexadecimal string back into a UTF-8 string.
pub fn from_ucs2_hex(hex: &str) -> Result<String, String> {
    let clean = hex.trim();
    if !clean.len().is_multiple_of(4) {
        return Err(format!(
            "Invalid UCS-2 hex length {} (must be multiple of 4)",
            clean.len()
        ));
    }
    let mut u16_chars = Vec::with_capacity(clean.len() / 4);
    for i in (0..clean.len()).step_by(4) {
        let chunk = &clean[i..i + 4];
        let val = u16::from_str_radix(chunk, 16)
            .map_err(|e| format!("Invalid hex chunk '{}': {}", chunk, e))?;
        u16_chars.push(val);
    }
    String::from_utf16(&u16_chars).map_err(|e| format!("Invalid UTF-16 sequence: {}", e))
}

/// Heuristically determines if a string is encoded as UCS-2 hexadecimal.
/// Useful when reading raw SMS messages from modems whose character set might vary.
pub fn is_likely_ucs2_hex(s: &str) -> bool {
    let clean = s.trim();
    if clean.len() < 4 || !clean.len().is_multiple_of(4) {
        return false;
    }
    clean.chars().all(|c| c.is_ascii_hexdigit())
}

/// Normalizes an incoming SMS text, automatically decoding UCS-2 hex if detected.
pub fn normalize_inbound_text(text: &str) -> String {
    let clean = text.trim();
    if is_likely_ucs2_hex(clean)
        && let Ok(decoded) = from_ucs2_hex(clean)
    {
        return decoded;
    }
    clean.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_pure_ascii() {
        assert!(is_pure_ascii("Hello World 123!"));
        assert!(is_pure_ascii("CR\r and LF\n allowed"));
        assert!(!is_pure_ascii("Attenzione gravità"));
        assert!(!is_pure_ascii("Alert 🚨"));
    }

    #[test]
    fn test_ucs2_hex_roundtrip() {
        let original = "Allarme critico: 🚨 temperatura alta! Gravità elevata.";
        let hex = to_ucs2_hex(original);
        assert!(!hex.is_empty());
        assert_eq!(hex.len() % 4, 0);

        let decoded = from_ucs2_hex(&hex).expect("Failed to decode UCS-2 hex");
        assert_eq!(decoded, original);
    }

    #[test]
    fn test_phone_number_ucs2() {
        let number = "+393349246425";
        let hex = to_ucs2_hex(number);
        let decoded = from_ucs2_hex(&hex).expect("Failed to decode number hex");
        assert_eq!(decoded, number);
    }

    #[test]
    fn test_invalid_ucs2_hex() {
        assert!(from_ucs2_hex("004").is_err());
        assert!(from_ucs2_hex("ZZZZ").is_err());
    }

    #[test]
    fn test_normalize_inbound() {
        let original = "Router rebooted ⚡";
        let hex = to_ucs2_hex(original);
        assert_eq!(normalize_inbound_text(&hex), original);
        assert_eq!(
            normalize_inbound_text("Simple ASCII alert"),
            "Simple ASCII alert"
        );
    }
}
