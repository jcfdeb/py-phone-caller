//! # Application Configuration
//!
//! Strongly-typed configuration structures mapped to the TOML configuration schema
//! loaded at daemon startup.

use crate::error::{OpenAlertError, Result};
use serde::{Deserialize, Serialize};
use std::path::Path;

/// Root configuration holding all daemon subsystem settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    /// General daemon settings (naming, log levels).
    pub daemon: DaemonConfig,
    /// HTTP REST API ingress server configuration.
    pub rest: RestConfig,
    /// Alert template directory and default template settings.
    pub templates: TemplateConfig,
    /// Nostr relay connection and subscription parameters.
    pub nostr: NostrConfig,
    /// BitChat Bluetooth Low Energy mesh configuration.
    pub bitchat: BitChatConfig,
    /// Routing rules, destinations, and deduplication cache parameters.
    pub routing: RoutingConfig,
    /// Target `py-phone-caller` Prometheus webhook endpoint settings.
    pub py_phone_caller: PyPhoneCallerConfig,
}

/// Daemon process metadata and logging configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DaemonConfig {
    /// Symbolic daemon instance name.
    pub name: String,
    /// Tracing log filter directive.
    pub log_level: String,
}

/// HTTP REST ingress server configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RestConfig {
    /// IP address or hostname to bind the REST listener to.
    pub listen_host: String,
    /// TCP port number for the REST listener.
    pub listen_port: u16,
    /// Whether to permit cross-origin resource sharing.
    pub enable_cors: bool,
}

/// Template engine configuration for alert rendering.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TemplateConfig {
    /// Directory containing `.tera` template files.
    pub template_dir: String,
    /// Default template name used when no specific override is requested.
    pub default_template: String,
}

/// Nostr decentralized pub/sub relay configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NostrConfig {
    /// List of WebSocket Nostr relay URLs.
    pub relays: Vec<String>,
    /// Nostr event kind used for outbound alert publishing.
    pub kind: u64,
    /// Whether the background ingress subscriber should actively connect.
    pub enable_subscriber: bool,
    /// Array of event kinds to subscribe to on connected relays.
    pub subscription_filter_kinds: Vec<u64>,
}

/// BitChat Bluetooth Low Energy mesh configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BitChatConfig {
    /// Whether the BitChat BLE service is activated.
    pub enabled: bool,
    /// Legacy/bridge TCP listen host.
    pub listen_host: String,
    /// Legacy/bridge TCP listen port.
    pub listen_port: u16,
    /// Bluetooth adapter identifier (e.g. "hci0").
    pub device: String,
    /// Advertised node name in BLE beacons and mesh announces.
    #[serde(default = "default_node_name")]
    pub node_name: String,
    /// Primary 128-bit GATT Service UUID.
    #[serde(default = "default_service_uuid")]
    pub service_uuid: String,
    /// Path to the fallback python BLE advertiser script.
    #[serde(default = "default_advertiser_script")]
    pub advertiser_script: String,
}

fn default_node_name() -> String {
    "OpenAlert-Mesh".to_string()
}

fn default_service_uuid() -> String {
    "f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5c".to_string()
}

fn default_advertiser_script() -> String {
    "docs/openalert/dist/bitchat-gateway/bitchat_ble_advertiser.py".to_string()
}

/// Alert routing and deduplication settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoutingConfig {
    /// Default egress destinations applied if an alert specifies none.
    pub default_destinations: Vec<String>,
    /// Maximum number of alert fingerprints held in the deduplication cache.
    pub dedup_cache_size: usize,
    /// Deduplication window duration in seconds.
    pub dedup_ttl_seconds: u64,
}

/// Egress connection parameters for the `py-phone-caller` Prometheus webhook.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PyPhoneCallerConfig {
    /// Target webhook URL.
    pub webhook_url: String,
    /// HTTP request timeout in seconds.
    pub timeout_seconds: f64,
    /// Maximum retry attempts on network or HTTP 5xx errors.
    pub max_retries: u32,
}

impl AppConfig {
    /// Loads and parses an [`AppConfig`] from a TOML file on disk.
    pub fn load<P: AsRef<Path>>(path: P) -> Result<Self> {
        let content = std::fs::read_to_string(path.as_ref()).map_err(|e| {
            OpenAlertError::Config(format!("Failed to read configuration file: {}", e))
        })?;

        toml::from_str(&content).map_err(|e| {
            OpenAlertError::Config(format!("Failed to parse TOML configuration: {}", e))
        })
    }
}
