//! # UTF-8 and UCS-2 / GSM Encoding for Cellular SMS
//!
//! Provides transparent conversion between Rust UTF-8 strings and modem AT
//! UCS-2 / GSM7 representations, ensuring multi-byte unicode characters, emojis,
//! and international diacritics are faithfully transmitted and received.

/// Maximum UTF-16 code units in a single GSM UCS-2 SMS segment.
pub const MAX_UCS2_UNITS_PER_SMS: usize = 70;

/// Returns true if all characters in the string are safe 7-bit ASCII/GSM basic characters.
pub fn is_pure_ascii(s: &str) -> bool {
    s.chars()
        .all(|c| c.is_ascii() && (c == '\r' || c == '\n' || (' '..='~').contains(&c)))
}

/// Encodes a UTF-8 string into big-endian UTF-16 (UCS-2) hexadecimal format.
pub fn to_ucs2_hex(s: &str) -> String {
    s.encode_utf16().map(|v| format!("{:04X}", v)).collect()
}

/// Splits a UTF-8 message into segments that each fit within `max_units` UTF-16
/// code units (70 for a single UCS-2 SMS), never splitting surrogate pairs and
/// prefixing multipart messages with `(i/n) `.
pub fn split_ucs2_chunks(message: &str, max_units: usize) -> Vec<String> {
    if message.is_empty() || message.encode_utf16().count() <= max_units {
        return vec![message.to_string()];
    }

    let split_with_budget = |text: &str, budget: usize| -> Vec<String> {
        let mut parts = Vec::new();
        let mut remaining = text;
        while !remaining.is_empty() {
            let mut units = 0usize;
            let mut cut_byte = 0usize;
            let mut last_space_byte = None;

            for (idx, ch) in remaining.char_indices() {
                let ch_units = ch.len_utf16();
                if units + ch_units > budget {
                    break;
                }
                units += ch_units;
                cut_byte = idx + ch.len_utf8();
                if ch.is_whitespace() && units >= budget / 2 {
                    last_space_byte = Some(idx);
                }
            }

            if cut_byte == 0 {
                if let Some(ch) = remaining.chars().next() {
                    cut_byte = ch.len_utf8();
                } else {
                    break;
                }
            }

            if cut_byte < remaining.len()
                && let Some(sp) = last_space_byte
                && sp > 0
            {
                let piece = remaining[..sp].trim_end();
                if !piece.is_empty() {
                    parts.push(piece.to_string());
                    remaining = remaining[sp..].trim_start();
                    continue;
                }
            }

            parts.push(remaining[..cut_byte].to_string());
            remaining = &remaining[cut_byte..];
            if !remaining.is_empty() {
                remaining = remaining.trim_start();
            }
        }
        parts
    };

    let mut prefix_budget = 6usize;
    let mut raw_parts = split_with_budget(message, max_units.saturating_sub(prefix_budget).max(1));
    if raw_parts.len() >= 10 {
        prefix_budget = format!("({}/{}) ", raw_parts.len(), raw_parts.len())
            .encode_utf16()
            .count();
        raw_parts = split_with_budget(message, max_units.saturating_sub(prefix_budget).max(1));
    }

    let total = raw_parts.len();
    if total <= 1 {
        return raw_parts;
    }

    raw_parts
        .into_iter()
        .enumerate()
        .map(|(i, part)| format!("({}/{}) {}", i + 1, total, part))
        .collect()
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
