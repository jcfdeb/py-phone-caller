//! # Management CLI & Operational Diagnostics Commands
//!
//! Provides operational diagnostics, configuration linting/dry-run checks,
//! live node status inspection, peer circuit breaker monitors, and spool backlog queries.

use crate::config::AppConfig;
use crate::models::{NodeStatusResponse, PeeringStatusReport, SpoolStats};
use std::path::Path;
use std::time::Duration;

/// Validates configuration and template files without starting network listeners.
pub fn validate_config(path: &str) -> Result<String, String> {
    let config =
        AppConfig::load(path).map_err(|e| format!("Failed to parse TOML configuration: {}", e))?;

    let mut checks = Vec::new();
    checks.push(format!("Node Name:        {}", config.daemon.name));
    checks.push(format!(
        "Logging:          {} (level: {})",
        config.daemon.logging, config.daemon.log_level
    ));
    checks.push(format!(
        "REST Ingress:     http://{}:{}",
        config.rest.listen_host, config.rest.listen_port
    ));

    // Templates check
    let tpl_path = Path::new(&config.templates.template_dir);
    if tpl_path.exists() {
        checks.push(format!(
            "Templates:        {} (valid directory)",
            config.templates.template_dir
        ));
    } else {
        checks.push(format!(
            "Templates:        ⚠️ Directory '{}' does not exist (will create or fallback)",
            config.templates.template_dir
        ));
    }

    // Storage check
    if config.storage.enabled {
        checks.push(format!(
            "Storage:          {} (retention: {}s)",
            config.storage.path, config.storage.retention_seconds
        ));
    } else {
        checks.push("Storage:          Disabled".to_string());
    }

    // Peering check
    if config.peering.enabled {
        checks.push(format!(
            "Peering:          UDP {} ({} configured peer nodes)",
            config.peering.listen_addr,
            config.peering.nodes.len()
        ));
    } else {
        checks.push("Peering:          Disabled".to_string());
    }

    // Webhooks check
    let targets_count = if !config.py_phone_caller.webhooks.is_empty() {
        config.py_phone_caller.webhooks.len()
    } else if config.py_phone_caller.webhook_url.is_some() {
        1
    } else {
        0
    };
    checks.push(format!(
        "Telephony Egress: Strategy '{:?}', {} target endpoint(s)",
        config.py_phone_caller.strategy, targets_count
    ));

    // Nostr check
    let privacy_str = if config.nostr.privacy.mode == crate::config::NostrPrivacyMode::Encrypted {
        match config.nostr.privacy.get_key_bytes() {
            Some(_) => {
                let key_preview = &config.nostr.privacy.shared_key.as_deref().unwrap_or("")[..8];
                format!("Encrypted (XChaCha20-Poly1305, key: {}...)", key_preview)
            }
            None => {
                return Err(
                    "nostr.privacy.mode is 'encrypted' but nostr.privacy.shared_key is missing or not a valid 64-character (32-byte) hex string".to_string()
                );
            }
        }
    } else {
        "Public (cleartext broadcast)".to_string()
    };
    checks.push(format!(
        "Nostr:            {} relay(s), Subscriber: {}, Privacy: {}",
        config.nostr.relays.len(),
        if config.nostr.enable_subscriber {
            "enabled"
        } else {
            "disabled"
        },
        privacy_str
    ));

    // BitChat check
    checks.push(format!(
        "BitChat BLE:      {}",
        if config.bitchat.enabled {
            format!(
                "enabled (device: {}, node: {})",
                config.bitchat.device, config.bitchat.node_name
            )
        } else {
            "disabled".to_string()
        }
    ));

    // Dashboard Auth check
    if config.dashboard.auth.is_active() {
        checks.push(format!(
            "Dashboard Auth:   enabled (user: '{}', hash: {}...)",
            config.dashboard.auth.username,
            &config.dashboard.auth.password_hash
                [..8.min(config.dashboard.auth.password_hash.len())]
        ));
    } else {
        checks.push("Dashboard Auth:   disabled (open access)".to_string());
    }

    Ok(checks.join("\n"))
}

fn create_client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .unwrap_or_default()
}

/// Queries daemon `/api/v1/status`.
pub async fn query_status(base_url: &str) -> Result<NodeStatusResponse, String> {
    let url = format!("{}/api/v1/status", base_url.trim_end_matches('/'));
    let client = create_client();
    let resp = client.get(&url).send().await.map_err(|e| {
        format!(
            "Failed to connect to daemon at '{}': {}. Is openalertd running?",
            url, e
        )
    })?;

    if !resp.status().is_success() {
        return Err(format!("Daemon returned HTTP status {}", resp.status()));
    }

    resp.json::<NodeStatusResponse>()
        .await
        .map_err(|e| format!("Failed to parse daemon status response: {}", e))
}

/// Queries daemon `/api/v1/peers`.
pub async fn query_peers(base_url: &str) -> Result<PeeringStatusReport, String> {
    let url = format!("{}/api/v1/peers", base_url.trim_end_matches('/'));
    let client = create_client();
    let resp = client.get(&url).send().await.map_err(|e| {
        format!(
            "Failed to connect to daemon at '{}': {}. Is openalertd running?",
            url, e
        )
    })?;

    if !resp.status().is_success() {
        return Err(format!("Daemon returned HTTP status {}", resp.status()));
    }

    resp.json::<PeeringStatusReport>()
        .await
        .map_err(|e| format!("Failed to parse daemon peers response: {}", e))
}

/// Queries daemon `/api/v1/spool`.
pub async fn query_spool(base_url: &str) -> Result<SpoolStats, String> {
    let url = format!("{}/api/v1/spool", base_url.trim_end_matches('/'));
    let client = create_client();
    let resp = client.get(&url).send().await.map_err(|e| {
        format!(
            "Failed to connect to daemon at '{}': {}. Is openalertd running?",
            url, e
        )
    })?;

    if !resp.status().is_success() {
        return Err(format!("Daemon returned HTTP status {}", resp.status()));
    }

    resp.json::<SpoolStats>()
        .await
        .map_err(|e| format!("Failed to parse daemon spool response: {}", e))
}

/// Pretty prints the status report to stdout.
pub fn print_status(status: &NodeStatusResponse) {
    println!("============================================================");
    println!(" 🛰️ OpenAlert Daemon Status: {}", status.node_name);
    println!("============================================================");
    println!("Status:           {}", status.status);
    println!("Version:          {}", status.version);
    println!(
        "Uptime:           {}s ({:.2}h)",
        status.uptime_seconds,
        status.uptime_seconds as f64 / 3600.0
    );
    println!("Nostr Pubkey:     {}", status.pubkey);
    println!("------------------------------------------------------------");
    println!(
        "Storage:          enabled={}, RAM-only={}",
        status.storage.enabled, status.storage.is_in_memory
    );
    if let Some(ref spool) = status.storage.spool {
        println!(
            "Peering Spool:    {} pending, {} delivered, {} total",
            spool.spooled, spool.delivered, spool.total
        );
    }
    println!(
        "Telephony:        strategy={}, targets={}",
        status.webhook.strategy, status.webhook.targets_count
    );
    println!(
        "Nostr Relays:     {} relays configured (subscriber: {})",
        status.nostr.relays_count, status.nostr.enabled
    );
    println!(
        "BitChat BLE:      enabled={}, node_name='{}'",
        status.bitchat.enabled, status.bitchat.node_name
    );
    println!("------------------------------------------------------------");
    if let Some(ref peering) = status.peering {
        println!(
            "Peering Listen:   {} ({} configured peer(s))",
            peering.listen_addr,
            peering.peers.len()
        );
        for p in &peering.peers {
            println!(
                "  • {:<16} {:<21} {:<5} state={:<9} fails={} spooled={}",
                p.name,
                p.addr,
                p.link_type,
                format!("{:?}", p.circuit_state),
                p.consecutive_failures,
                p.spooled_count
            );
        }
    } else {
        println!("Peering:          disabled");
    }
    println!("============================================================");
}

/// Pretty prints the peer table to stdout.
pub fn print_peers(peering: &PeeringStatusReport) {
    println!(
        "========================================================================================="
    );
    println!(
        " 🛰️ OpenAlert Peering Link Status (UDP: {})",
        peering.listen_addr
    );
    println!(
        "========================================================================================="
    );
    if peering.peers.is_empty() {
        println!("No peer nodes configured.");
    } else {
        println!(
            "{:<18} {:<24} {:<8} {:<12} {:<10} {:<8}",
            "PEER NAME", "REMOTE ADDRESS", "LINK", "STATE", "FAILURES", "SPOOLED"
        );
        println!(
            "-----------------------------------------------------------------------------------------"
        );
        for p in &peering.peers {
            let state_str = format!("{:?}", p.circuit_state).to_lowercase();
            println!(
                "{:<18} {:<24} {:<8} {:<12} {:<10} {:<8}",
                p.name, p.addr, p.link_type, state_str, p.consecutive_failures, p.spooled_count
            );
        }
    }
    println!(
        "========================================================================================="
    );
}

/// Pretty prints spool statistics to stdout.
pub fn print_spool(spool: &SpoolStats) {
    println!("============================================================");
    println!(" 💾 OpenAlert Peering Spool Backlog");
    println!("============================================================");
    println!("Spooled (Pending):    {}", spool.spooled);
    println!("Delivered (Archived): {}", spool.delivered);
    println!("Total Records in DB:  {}", spool.total);
    println!("============================================================");
}

/// Computes a SHA-256 hex-encoded hash of the password for dashboard configuration.
pub fn hash_password(password: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(password.as_bytes());
    hex::encode(hasher.finalize())
}

/// Generates a cryptographically secure 256-bit (32-byte) random hex key for peering or Nostr group privacy.
pub fn generate_key() -> String {
    use rand::RngCore;
    let mut key_bytes = [0u8; 32];
    rand::rng().fill_bytes(&mut key_bytes);
    hex::encode(key_bytes)
}

/// A generated Nostr identity containing both private and public keys.
#[derive(Debug, Clone)]
pub struct NostrIdentity {
    pub priv_hex: String,
    pub nsec: String,
    pub pub_hex: String,
    pub npub: String,
}

/// Result of converting a key between Bech32 and Hex formats.
#[derive(Debug, Clone)]
pub struct KeyConversionResult {
    pub input_format: String,
    pub hex_value: String,
    pub bech32_value: String,
    /// If the input was a private key, holds the derived public key (hex, npub)
    pub derived_public: Option<(String, String)>,
}

/// Generates a complete cryptographic Nostr Secp256k1 keypair (nsec / npub / hex).
pub fn generate_keypair() -> NostrIdentity {
    use rand::RngCore;
    use secp256k1::{Keypair, Secp256k1, SecretKey};

    let secp = Secp256k1::new();
    let mut rng = rand::rng();
    let mut seed = [0u8; 32];
    loop {
        rng.fill_bytes(&mut seed);
        if let Ok(sk) = SecretKey::from_slice(&seed) {
            let keypair = Keypair::from_secret_key(&secp, &sk);
            let (xonly, _) = keypair.x_only_public_key();

            let priv_bytes = sk.secret_bytes();
            let pub_bytes = xonly.serialize();

            let priv_hex = hex::encode(priv_bytes);
            let pub_hex = hex::encode(pub_bytes);

            let nsec_hrp = bech32::Hrp::parse("nsec").expect("valid hrp");
            let npub_hrp = bech32::Hrp::parse("npub").expect("valid hrp");

            let nsec = bech32::encode::<bech32::Bech32>(nsec_hrp, &priv_bytes).expect("encode nsec");
            let npub = bech32::encode::<bech32::Bech32>(npub_hrp, &pub_bytes).expect("encode npub");

            return NostrIdentity {
                priv_hex,
                nsec,
                pub_hex,
                npub,
            };
        }
    }
}

/// Decodes any Bech32 string (npub / nsec) to hex and vice versa,
/// automatically deriving public keys when private keys are provided.
pub fn convert_key(input: &str) -> Result<KeyConversionResult, String> {
    let clean = input.trim().strip_prefix("nostr:").unwrap_or(input.trim());
    let secp = secp256k1::Secp256k1::new();

    if clean.starts_with("npub1") {
        let (hrp, data) = bech32::decode(clean)
            .map_err(|e| format!("Invalid npub Bech32 string: {}", e))?;
        if hrp.as_str() != "npub" {
            return Err(format!("Expected 'npub' prefix, found '{}'", hrp));
        }
        if data.len() != 32 {
            return Err(format!("Expected 32-byte payload, found {} bytes", data.len()));
        }
        let hex_val = hex::encode(&data);
        Ok(KeyConversionResult {
            input_format: "npub (Public Key)".to_string(),
            hex_value: hex_val,
            bech32_value: clean.to_string(),
            derived_public: None,
        })
    } else if clean.starts_with("nsec1") {
        let (hrp, data) = bech32::decode(clean)
            .map_err(|e| format!("Invalid nsec Bech32 string: {}", e))?;
        if hrp.as_str() != "nsec" {
            return Err(format!("Expected 'nsec' prefix, found '{}'", hrp));
        }
        if data.len() != 32 {
            return Err(format!("Expected 32-byte payload, found {} bytes", data.len()));
        }
        let priv_hex = hex::encode(&data);
        let sk = secp256k1::SecretKey::from_slice(&data)
            .map_err(|e| format!("Invalid Secp256k1 secret key: {}", e))?;
        let keypair = secp256k1::Keypair::from_secret_key(&secp, &sk);
        let (xonly, _) = keypair.x_only_public_key();
        let pub_bytes = xonly.serialize();
        let pub_hex = hex::encode(pub_bytes);
        let npub_hrp = bech32::Hrp::parse("npub").map_err(|e| e.to_string())?;
        let npub = bech32::encode::<bech32::Bech32>(npub_hrp, &pub_bytes)
            .map_err(|e| format!("Failed to encode npub: {}", e))?;

        Ok(KeyConversionResult {
            input_format: "nsec (Private Key)".to_string(),
            hex_value: priv_hex,
            bech32_value: clean.to_string(),
            derived_public: Some((pub_hex, npub)),
        })
    } else {
        // Hex representation (either private or public key)
        let hex_clean = clean.strip_prefix("0x").unwrap_or(clean);
        let bytes = hex::decode(hex_clean)
            .map_err(|e| format!("Invalid hex string: {}", e))?;
        if bytes.len() != 32 {
            return Err(format!("Expected 32-byte (64 hex characters) key, found {} bytes", bytes.len()));
        }

        let npub_hrp = bech32::Hrp::parse("npub").map_err(|e| e.to_string())?;
        let as_npub = bech32::encode::<bech32::Bech32>(npub_hrp, &bytes)
            .map_err(|e| format!("Failed to encode npub: {}", e))?;

        // If it is also a valid secret key, derive its public key
        let derived = if let Ok(sk) = secp256k1::SecretKey::from_slice(&bytes) {
            let keypair = secp256k1::Keypair::from_secret_key(&secp, &sk);
            let (xonly, _) = keypair.x_only_public_key();
            let pub_bytes = xonly.serialize();
            let pub_hex = hex::encode(pub_bytes);
            let npub = bech32::encode::<bech32::Bech32>(npub_hrp, &pub_bytes)
                .map_err(|e| format!("Failed to encode npub: {}", e))?;
            Some((pub_hex, npub))
        } else {
            None
        };

        Ok(KeyConversionResult {
            input_format: "64-Hex Key".to_string(),
            hex_value: hex_clean.to_string(),
            bech32_value: as_npub,
            derived_public: derived,
        })
    }
}

/// Converts between UTF-8 text and Cellular SMS UCS-2 hex.
pub fn convert_sms_codec(input: &str) -> Result<(String, String), String> {
    use crate::sms::codec::{from_ucs2_hex, is_likely_ucs2_hex, to_ucs2_hex};
    let clean = input.trim();
    if is_likely_ucs2_hex(clean) {
        let decoded = from_ucs2_hex(clean)?;
        Ok(("Decoded UCS-2 Hex -> UTF-8 Text".to_string(), decoded))
    } else {
        let encoded = to_ucs2_hex(clean);
        Ok(("Encoded UTF-8 Text -> UCS-2 Hex".to_string(), encoded))
    }
}

#[cfg(test)]
mod tests_convert {
    use super::*;

    #[test]
    fn test_cli_convert_key() {
        let npub = "npub1uvtjer4wn7y2qpe4clvqd7qz7x483pthpngewqddc03xes39uq3sw9p5u6";
        let expected_hex = "e3172c8eae9f88a00735c7d806f802f1aa7885770cd19701adc3e26cc225e023";
        let res = convert_key(npub).unwrap();
        assert_eq!(res.hex_value, expected_hex);
        assert_eq!(res.bech32_value, npub);

        let res2 = convert_key(expected_hex).unwrap();
        assert_eq!(res2.hex_value, expected_hex);
        assert_eq!(res2.bech32_value, npub);
    }

    #[test]
    fn test_cli_generate_keypair() {
        let id = generate_keypair();
        assert!(id.nsec.starts_with("nsec1"));
        assert!(id.npub.starts_with("npub1"));
        assert_eq!(id.priv_hex.len(), 64);
        assert_eq!(id.pub_hex.len(), 64);

        // Converting nsec should derive the exact same npub!
        let conv = convert_key(&id.nsec).unwrap();
        let (pub_hex, npub) = conv.derived_public.unwrap();
        assert_eq!(pub_hex, id.pub_hex);
        assert_eq!(npub, id.npub);
    }

    #[test]
    fn test_cli_convert_sms_codec() {
        let text = "Emergency Alert ⚠️";
        let (dir1, hex) = convert_sms_codec(text).unwrap();
        assert!(dir1.contains("Encoded"));

        let (dir2, decoded) = convert_sms_codec(&hex).unwrap();
        assert!(dir2.contains("Decoded"));
        assert_eq!(decoded, text);
    }
}
