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
    let config = AppConfig::load(path).map_err(|e| format!("Failed to parse TOML configuration: {}", e))?;

    let mut checks = Vec::new();
    checks.push(format!("Node Name:        {}", config.daemon.name));
    checks.push(format!("Logging:          {} (level: {})", config.daemon.logging, config.daemon.log_level));
    checks.push(format!("REST Ingress:     http://{}:{}", config.rest.listen_host, config.rest.listen_port));

    // Templates check
    let tpl_path = Path::new(&config.templates.template_dir);
    if tpl_path.exists() {
        checks.push(format!("Templates:        {} (valid directory)", config.templates.template_dir));
    } else {
        checks.push(format!("Templates:        ⚠️ Directory '{}' does not exist (will create or fallback)", config.templates.template_dir));
    }

    // Storage check
    if config.storage.enabled {
        checks.push(format!("Storage:          {} (retention: {}s)", config.storage.path, config.storage.retention_seconds));
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
    checks.push(format!(
        "Nostr:            {} relay(s), Subscriber: {}",
        config.nostr.relays.len(),
        if config.nostr.enable_subscriber { "enabled" } else { "disabled" }
    ));

    // BitChat check
    checks.push(format!(
        "BitChat BLE:      {}",
        if config.bitchat.enabled { format!("enabled (device: {}, node: {})", config.bitchat.device, config.bitchat.node_name) } else { "disabled".to_string() }
    ));

    // Dashboard Auth check
    if config.dashboard.auth.is_active() {
        checks.push(format!(
            "Dashboard Auth:   enabled (user: '{}', hash: {}...)",
            config.dashboard.auth.username,
            &config.dashboard.auth.password_hash[..8.min(config.dashboard.auth.password_hash.len())]
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
        format!("Failed to connect to daemon at '{}': {}. Is openalertd running?", url, e)
    })?;

    if !resp.status().is_success() {
        return Err(format!("Daemon returned HTTP status {}", resp.status()));
    }

    resp.json::<NodeStatusResponse>().await.map_err(|e| {
        format!("Failed to parse daemon status response: {}", e)
    })
}

/// Queries daemon `/api/v1/peers`.
pub async fn query_peers(base_url: &str) -> Result<PeeringStatusReport, String> {
    let url = format!("{}/api/v1/peers", base_url.trim_end_matches('/'));
    let client = create_client();
    let resp = client.get(&url).send().await.map_err(|e| {
        format!("Failed to connect to daemon at '{}': {}. Is openalertd running?", url, e)
    })?;

    if !resp.status().is_success() {
        return Err(format!("Daemon returned HTTP status {}", resp.status()));
    }

    resp.json::<PeeringStatusReport>().await.map_err(|e| {
        format!("Failed to parse daemon peers response: {}", e)
    })
}

/// Queries daemon `/api/v1/spool`.
pub async fn query_spool(base_url: &str) -> Result<SpoolStats, String> {
    let url = format!("{}/api/v1/spool", base_url.trim_end_matches('/'));
    let client = create_client();
    let resp = client.get(&url).send().await.map_err(|e| {
        format!("Failed to connect to daemon at '{}': {}. Is openalertd running?", url, e)
    })?;

    if !resp.status().is_success() {
        return Err(format!("Daemon returned HTTP status {}", resp.status()));
    }

    resp.json::<SpoolStats>().await.map_err(|e| {
        format!("Failed to parse daemon spool response: {}", e)
    })
}

/// Pretty prints the status report to stdout.
pub fn print_status(status: &NodeStatusResponse) {
    println!("============================================================");
    println!(" 🛰️ OpenAlert Daemon Status: {}", status.node_name);
    println!("============================================================");
    println!("Status:           {}", status.status);
    println!("Version:          {}", status.version);
    println!("Uptime:           {}s ({:.2}h)", status.uptime_seconds, status.uptime_seconds as f64 / 3600.0);
    println!("Nostr Pubkey:     {}", status.pubkey);
    println!("------------------------------------------------------------");
    println!("Storage:          enabled={}, RAM-only={}", status.storage.enabled, status.storage.is_in_memory);
    if let Some(ref spool) = status.storage.spool {
        println!("Peering Spool:    {} pending, {} delivered, {} total", spool.spooled, spool.delivered, spool.total);
    }
    println!("Telephony:        strategy={}, targets={}", status.webhook.strategy, status.webhook.targets_count);
    println!("Nostr Relays:     {} relays configured (subscriber: {})", status.nostr.relays_count, status.nostr.enabled);
    println!("BitChat BLE:      enabled={}, node_name='{}'", status.bitchat.enabled, status.bitchat.node_name);
    println!("------------------------------------------------------------");
    if let Some(ref peering) = status.peering {
        println!("Peering Listen:   {} ({} configured peer(s))", peering.listen_addr, peering.peers.len());
        for p in &peering.peers {
            println!(
                "  • {:<16} {:<21} {:<5} state={:<9} fails={} spooled={}",
                p.name, p.addr, p.link_type, format!("{:?}", p.circuit_state), p.consecutive_failures, p.spooled_count
            );
        }
    } else {
        println!("Peering:          disabled");
    }
    println!("============================================================");
}

/// Pretty prints the peer table to stdout.
pub fn print_peers(peering: &PeeringStatusReport) {
    println!("=========================================================================================");
    println!(" 🛰️ OpenAlert Peering Link Status (UDP: {})", peering.listen_addr);
    println!("=========================================================================================");
    if peering.peers.is_empty() {
        println!("No peer nodes configured.");
    } else {
        println!("{:<18} {:<24} {:<8} {:<12} {:<10} {:<8}", "PEER NAME", "REMOTE ADDRESS", "LINK", "STATE", "FAILURES", "SPOOLED");
        println!("-----------------------------------------------------------------------------------------");
        for p in &peering.peers {
            let state_str = format!("{:?}", p.circuit_state).to_lowercase();
            println!(
                "{:<18} {:<24} {:<8} {:<12} {:<10} {:<8}",
                p.name, p.addr, p.link_type, state_str, p.consecutive_failures, p.spooled_count
            );
        }
    }
    println!("=========================================================================================");
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
