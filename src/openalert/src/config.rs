//! # Configuration Management
//!
//! Loads and validates the `openalertd.toml` runtime configuration file, supplying default
//! values for missing options and parsing nested protocol settings.

use crate::error::Result;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

/// Root daemon configuration encapsulating all subsystem settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    /// General daemon settings (node name, logging).
    pub daemon: DaemonConfig,
    /// Ingress HTTP REST API server settings.
    pub rest: RestConfig,
    /// Nostr relay connection and event handling settings.
    pub nostr: NostrConfig,
    /// BitChat BLE mesh and GATT configuration.
    pub bitchat: BitChatConfig,
    /// Alert routing and deduplication policies.
    pub routing: RoutingConfig,
    /// Egress connection parameters for the `py-phone-caller` Prometheus webhook.
    #[serde(default)]
    pub py_phone_caller: PyPhoneCallerConfig,
    /// Dynamic payload templating settings.
    pub templates: TemplateConfig,
    /// Embedded database storage and sliding window retention settings.
    #[serde(default)]
    pub storage: StorageConfig,
    /// Decentralized UDP peering, emergency escape valve, and radio backhaul settings.
    #[serde(default)]
    pub peering: PeeringConfig,
    /// Optional embedded web dashboard and authentication settings.
    #[serde(default)]
    pub dashboard: DashboardConfig,
    /// Optional cellular GSM/LTE SMS gateway subsystem (ingress & egress).
    #[serde(default)]
    pub sms: SmsConfig,
}

impl AppConfig {
    /// Loads and parses the TOML configuration file from the specified filesystem path.
    pub fn load<P: AsRef<Path>>(path: P) -> Result<Self> {
        let content = fs::read_to_string(path.as_ref())?;
        let config: AppConfig = toml::from_str(&content)?;
        Ok(config)
    }
}

/// General daemon metadata, log level, and systemd journal integration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DaemonConfig {
    /// Human-readable node name used in log traces and mesh identification.
    #[serde(default = "default_node_name")]
    pub name: String,
    /// Active tracing log level (e.g., `trace`, `debug`, `info`, `warn`, `error`).
    #[serde(default = "default_log_level")]
    pub log_level: String,
    /// Logging mode: "default" (with ISO-8601 timestamps for terminal/standalone)
    /// or "systemd" (without timestamps to prevent redundant timestamps in journald).
    #[serde(default = "default_logging_mode")]
    pub logging: String,
}

impl DaemonConfig {
    /// Checks whether logging is configured for systemd / journald.
    pub fn is_systemd_logging(&self) -> bool {
        self.logging.trim().eq_ignore_ascii_case("systemd")
            || self.logging.trim().eq_ignore_ascii_case("journald")
    }
}

fn default_node_name() -> String {
    "openalertd-hub".to_string()
}

fn default_log_level() -> String {
    "info".to_string()
}

fn default_logging_mode() -> String {
    "default".to_string()
}

/// Optional TLS / mTLS configuration for HTTPS server.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TlsConfig {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub cert_path: Option<String>,
    #[serde(default)]
    pub key_path: Option<String>,
    #[serde(default)]
    pub client_ca_path: Option<String>,
    #[serde(default)]
    pub require_client_cert: bool,
}

/// Configuration for the HTTP REST and Prometheus webhook ingress server.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RestConfig {
    /// Interface IP to bind for HTTP listeners.
    pub listen_host: String,
    /// Port number for HTTP REST listeners.
    pub listen_port: u16,
    /// Whether to permit cross-origin requests.
    pub enable_cors: bool,
    /// Optional bearer token for authenticating HTTP REST / API requests.
    #[serde(default)]
    pub auth_token: Option<String>,
    /// Optional shared secret for verifying HMAC-SHA256 signatures on inbound webhooks.
    #[serde(default)]
    pub webhook_secret: Option<String>,
    /// Maximum allowed clock skew in seconds for webhook timestamps (default: 60s).
    #[serde(default = "default_webhook_max_skew_seconds")]
    pub webhook_max_skew_seconds: u64,
    /// Optional TLS and client certificate mutual authentication settings.
    #[serde(default)]
    pub tls: TlsConfig,
}

fn default_webhook_max_skew_seconds() -> u64 {
    60
}

/// Optional dashboard authentication settings.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DashboardConfig {
    /// Dashboard authentication configuration.
    #[serde(default)]
    pub auth: DashboardAuthConfig,
}

/// Dashboard user authentication configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DashboardAuthConfig {
    /// Whether user authentication is required for the dashboard.
    #[serde(default)]
    pub enabled: bool,
    /// Administrator username.
    #[serde(default)]
    pub username: String,
    /// SHA-256 hash of the admin password (in hex).
    #[serde(default)]
    pub password_hash: String,
}

impl DashboardAuthConfig {
    /// Returns true if authentication is active (enabled and password_hash non-empty).
    pub fn is_active(&self) -> bool {
        self.enabled && !self.password_hash.trim().is_empty()
    }
}

/// Operational privacy mode for Nostr transport.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum NostrPrivacyMode {
    #[default]
    Public,
    Encrypted,
}

/// Nostr alert privacy and group encryption parameters.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct NostrPrivacyConfig {
    /// Operational mode: "public" (cleartext) or "encrypted" (XChaCha20-Poly1305).
    #[serde(default)]
    pub mode: NostrPrivacyMode,
    /// 256-bit pre-shared hex key (64 hex characters) required when mode is "encrypted".
    #[serde(default)]
    pub shared_key: Option<String>,
    /// Optional whitelist of authorized sender public keys (hex). If empty, any sender possessing the key is accepted.
    #[serde(default)]
    pub authorized_senders: Vec<String>,
    /// When mode is "encrypted", whether to accept unencrypted public alerts. Default: false.
    #[serde(default)]
    pub allow_unencrypted_fallback: bool,
}

impl NostrPrivacyConfig {
    /// Returns decoded 32-byte shared key if mode is Encrypted and key is valid.
    pub fn get_key_bytes(&self) -> Option<[u8; 32]> {
        if let Some(ref hex_str) = self.shared_key {
            let clean = hex_str.trim();
            if let Ok(bytes) = hex::decode(clean)
                && bytes.len() == 32
            {
                let mut arr = [0u8; 32];
                arr.copy_from_slice(&bytes);
                return Some(arr);
            }
        }
        None
    }
}

/// Nostr relay mesh and subscription parameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NostrConfig {
    /// List of WebSocket URLs pointing to Nostr relays.
    pub relays: Vec<String>,
    /// Default Nostr event kind to publish and subscribe (e.g., 30000).
    pub kind: u64,
    /// Whether to launch the persistent inbound WebSocket subscriber.
    pub enable_subscriber: bool,
    /// Event kinds to subscribe to from configured relays.
    #[serde(default)]
    pub subscription_filter_kinds: Vec<u64>,
    /// Alert validity / time-to-live in seconds for NIP-40 expiration tagging and stale event filtering.
    #[serde(default = "default_alert_ttl_seconds")]
    pub alert_ttl_seconds: u64,
    /// Historical catch-up window in seconds when subscribing on startup.
    #[serde(default = "default_subscription_lookback_seconds")]
    pub subscription_lookback_seconds: u64,
    /// Minimum positive NIP-20 relay confirmations required to achieve delivery quorum.
    #[serde(default = "default_quorum_min_relays")]
    pub quorum_min_relays: usize,
    /// Timeout in seconds to wait for NIP-20 command results from each relay.
    #[serde(default = "default_nip20_timeout_secs")]
    pub nip20_timeout_secs: u64,
    /// Privacy and group encryption settings.
    #[serde(default)]
    pub privacy: NostrPrivacyConfig,
}

fn default_quorum_min_relays() -> usize {
    1
}

fn default_nip20_timeout_secs() -> u64 {
    5
}

fn default_alert_ttl_seconds() -> u64 {
    3600
}

fn default_subscription_lookback_seconds() -> u64 {
    300
}

/// BitChat BLE mesh and Linux BlueZ GATT server parameters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BitChatConfig {
    /// Whether BitChat BLE mesh functionality is enabled.
    pub enabled: bool,
    /// Linux HCI Bluetooth adapter name (e.g. `hci0`).
    #[serde(default = "default_ble_device")]
    pub device: String,
    /// Bluetooth BLE advertised local name.
    #[serde(default = "default_ble_node_name")]
    pub node_name: String,
    /// Custom BitChat GATT primary service UUID.
    #[serde(default = "default_service_uuid")]
    pub service_uuid: String,
    /// Legacy TCP host for mock emulator bridge (deprecated).
    #[serde(default)]
    pub listen_host: Option<String>,
    /// Legacy TCP port for mock emulator bridge (deprecated).
    #[serde(default)]
    pub listen_port: Option<u16>,
    /// Legacy path to external BLE advertiser script (deprecated, native BlueZ advertising is built-in).
    #[serde(default)]
    pub advertiser_script: Option<String>,
}

fn default_ble_device() -> String {
    "hci0".to_string()
}

fn default_ble_node_name() -> String {
    "OpenAlert-Mesh".to_string()
}

fn default_service_uuid() -> String {
    "f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5c".to_string()
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
    /// Last-resort fallback channels triggered when primary destinations fail or trip circuit breakers.
    #[serde(default)]
    pub failover_destinations: Vec<String>,
}

/// Dispatch strategy for multiple py-phone-caller webhook instances.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum WebhookStrategy {
    /// Try webhooks in priority order; on failure, wait delay before next (failover).
    #[default]
    Cascade,
    /// Distribute alerts sequentially across webhooks.
    Roundrobin,
    /// Pick a random webhook instance for each alert.
    Random,
    /// Dispatch concurrently to all configured webhooks.
    Broadcast,
}

fn default_webhook_timeout_seconds() -> f64 {
    5.0
}

fn default_webhook_max_retries() -> u32 {
    3
}

fn default_webhook_delay_seconds() -> u64 {
    30
}

fn default_circuit_breaker_enabled() -> bool {
    true
}

fn default_circuit_breaker_failure_threshold() -> u32 {
    3
}

fn default_circuit_breaker_cooldown_seconds() -> u64 {
    30
}

fn deserialize_priority<'de, D>(deserializer: D) -> std::result::Result<Option<u32>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::de::{self, Visitor};
    use std::fmt;

    struct PriorityVisitor;

    impl<'de> Visitor<'de> for PriorityVisitor {
        type Value = Option<u32>;

        fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
            formatter.write_str("a two-digit integer or string representing priority (e.g. 0, 10, '00')")
        }

        fn visit_i64<E>(self, v: i64) -> std::result::Result<Self::Value, E>
        where
            E: de::Error,
        {
            Ok(Some(v as u32))
        }

        fn visit_u64<E>(self, v: u64) -> std::result::Result<Self::Value, E>
        where
            E: de::Error,
        {
            Ok(Some(v as u32))
        }

        fn visit_str<E>(self, v: &str) -> std::result::Result<Self::Value, E>
        where
            E: de::Error,
        {
            v.parse::<u32>().map(Some).map_err(de::Error::custom)
        }

        fn visit_none<E>(self) -> std::result::Result<Self::Value, E>
        where
            E: de::Error,
        {
            Ok(None)
        }

        fn visit_some<D>(self, deserializer: D) -> std::result::Result<Self::Value, D::Error>
        where
            D: serde::Deserializer<'de>,
        {
            deserializer.deserialize_any(self)
        }
    }

    deserializer.deserialize_option(PriorityVisitor)
}

/// Configuration for a single py-phone-caller Prometheus webhook endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WebhookEndpointConfig {
    /// Target webhook URL.
    pub url: String,
    /// HTTP request timeout in seconds.
    #[serde(default = "default_webhook_timeout_seconds")]
    pub timeout_seconds: f64,
    /// Maximum retry attempts on network or HTTP 5xx errors.
    #[serde(default = "default_webhook_max_retries")]
    pub max_retries: u32,
    /// Delay in seconds to wait before trying the next endpoint in cascade strategy.
    #[serde(default = "default_webhook_delay_seconds")]
    pub delay: u64,
    /// Priority order (e.g. 0, 10, 20). Formatted with 2 digits in logs. Auto-assigned if omitted.
    #[serde(default, deserialize_with = "deserialize_priority")]
    pub priority: Option<u32>,
}

/// Egress connection parameters for the `py-phone-caller` Prometheus webhook.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PyPhoneCallerConfig {
    /// Balancing strategy: "cascade" (default), "roundrobin", "random", or "broadcast".
    #[serde(default)]
    pub strategy: WebhookStrategy,
    /// Legacy single webhook URL for backward compatibility.
    #[serde(default)]
    pub webhook_url: Option<String>,
    /// Fallback HTTP request timeout in seconds.
    #[serde(default = "default_webhook_timeout_seconds")]
    pub timeout_seconds: f64,
    /// Fallback maximum retry attempts.
    #[serde(default = "default_webhook_max_retries")]
    pub max_retries: u32,
    /// Multi-instance webhook endpoints (up to 3 supported).
    #[serde(default)]
    pub webhooks: Vec<WebhookEndpointConfig>,
    /// Whether circuit breaker protection is active (default: true).
    #[serde(default = "default_circuit_breaker_enabled")]
    pub circuit_breaker_enabled: bool,
    /// Number of consecutive failures before opening the circuit (default: 3).
    #[serde(default = "default_circuit_breaker_failure_threshold")]
    pub circuit_breaker_failure_threshold: u32,
    /// Cooldown period in seconds before probing a tripped endpoint (default: 30s).
    #[serde(default = "default_circuit_breaker_cooldown_seconds")]
    pub circuit_breaker_cooldown_seconds: u64,
}

impl Default for PyPhoneCallerConfig {
    fn default() -> Self {
        Self {
            strategy: WebhookStrategy::default(),
            webhook_url: None,
            timeout_seconds: default_webhook_timeout_seconds(),
            max_retries: default_webhook_max_retries(),
            webhooks: Vec::new(),
            circuit_breaker_enabled: default_circuit_breaker_enabled(),
            circuit_breaker_failure_threshold: default_circuit_breaker_failure_threshold(),
            circuit_breaker_cooldown_seconds: default_circuit_breaker_cooldown_seconds(),
        }
    }
}

impl PyPhoneCallerConfig {
    /// Returns the resolved list of webhook endpoints (up to 3), normalized with priorities.
    pub fn resolved_webhooks(&self) -> Vec<WebhookEndpointConfig> {
        let mut list = self.webhooks.clone();
        if list.is_empty()
            && let Some(ref url) = self.webhook_url {
            list.push(WebhookEndpointConfig {
                url: url.clone(),
                timeout_seconds: self.timeout_seconds,
                max_retries: self.max_retries,
                delay: default_webhook_delay_seconds(),
                priority: Some(0),
            });
        }

        if list.len() > 3 {
            tracing::warn!(
                "⚠️ More than 3 webhook instances configured ({}). Capping to maximum of 3.",
                list.len()
            );
            list.truncate(3);
        }

        for (i, endpoint) in list.iter_mut().enumerate() {
            if endpoint.priority.is_none() {
                endpoint.priority = Some((i as u32) * 10);
            }
        }

        if self.strategy == WebhookStrategy::Cascade {
            list.sort_by_key(|e| e.priority.unwrap_or(0));
        }

        list
    }
}

/// Embedded database storage and sliding window retention settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageConfig {
    /// Whether persistent storage is activated.
    #[serde(default = "default_storage_enabled")]
    pub enabled: bool,
    /// Path to SQLite database file on disk, or ":memory:" for RAM-only.
    /// Automatically falls back to in-memory if the filesystem is unwritable or read-only.
    #[serde(default = "default_storage_path")]
    pub path: String,
    /// Sliding window retention in seconds (e.g. 900 = 15 minutes).
    #[serde(default = "default_storage_retention_seconds")]
    pub retention_seconds: u64,
    /// Whether to re-route pending/unacknowledged alerts found on startup.
    #[serde(default = "default_storage_recover_pending")]
    pub recover_pending_on_startup: bool,
    /// Background pruning interval in seconds (default: 60s).
    #[serde(default = "default_storage_prune_interval_seconds")]
    pub prune_interval_seconds: u64,
}

fn default_storage_enabled() -> bool {
    true
}

fn default_storage_path() -> String {
    "data/openalert.db".to_string()
}

fn default_storage_retention_seconds() -> u64 {
    900 // 15 minutes
}

fn default_storage_recover_pending() -> bool {
    true
}

fn default_storage_prune_interval_seconds() -> u64 {
    60
}

impl Default for StorageConfig {
    fn default() -> Self {
        Self {
            enabled: default_storage_enabled(),
            path: default_storage_path(),
            retention_seconds: default_storage_retention_seconds(),
            recover_pending_on_startup: default_storage_recover_pending(),
            prune_interval_seconds: default_storage_prune_interval_seconds(),
        }
    }
}

/// Dynamic payload templating settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TemplateConfig {
    /// Filesystem directory containing `.tera` templates.
    pub template_dir: String,
    /// Default template filename rendered for outbound webhooks.
    pub default_template: String,
}

/// Physical link layer profile for a federated peer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum PeeringLinkType {
    /// High-speed local Ethernet / LAN link.
    #[default]
    Lan,
    /// Encrypted WireGuard or site-to-site IP tunnel.
    Vpn,
    /// Duty-cycle-constrained 868 MHz / 915 MHz LoRa radio interface (via UDP simulation).
    Lora,
    /// Hardware Serial / UART LoRa interface (/dev/ttyUSB*, /dev/ttyS*).
    #[serde(rename = "lora_serial")]
    LoraSerial,
}

/// Global retry configuration for peering nodes.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeeringRetryConfig {
    /// Maximum retry attempts for ARQ on IP links (LAN/VPN).
    #[serde(default = "default_max_ip_retries")]
    pub max_ip_retries: u32,
    /// Initial base timeout in milliseconds for exponential backoff.
    #[serde(default = "default_base_timeout_ms")]
    pub base_timeout_ms: u64,
    /// Maximum backoff ceiling in milliseconds.
    #[serde(default = "default_max_timeout_ms")]
    pub max_timeout_ms: u64,
}

impl Default for PeeringRetryConfig {
    fn default() -> Self {
        Self {
            max_ip_retries: default_max_ip_retries(),
            base_timeout_ms: default_base_timeout_ms(),
            max_timeout_ms: default_max_timeout_ms(),
        }
    }
}

fn default_max_ip_retries() -> u32 {
    4
}

fn default_base_timeout_ms() -> u64 {
    250
}

fn default_max_timeout_ms() -> u64 {
    8000
}

/// Circuit breaker failure thresholds and cooldown settings for peer links.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeeringCircuitBreakerConfig {
    /// Consecutive failed deliveries required to trip the circuit to OPEN.
    #[serde(default = "default_cb_failure_threshold")]
    pub failure_threshold: u32,
    /// Initial cooldown period in seconds before probing a tripped peer link.
    #[serde(default = "default_cb_base_cooldown_secs")]
    pub base_cooldown_secs: u64,
    /// Maximum cooldown backoff ceiling in seconds.
    #[serde(default = "default_cb_max_cooldown_secs")]
    pub max_cooldown_secs: u64,
    /// Timeout in milliseconds for canary probe acknowledgments during HALF-OPEN state.
    #[serde(default = "default_cb_canary_timeout_ms")]
    pub canary_timeout_ms: u64,
}

impl Default for PeeringCircuitBreakerConfig {
    fn default() -> Self {
        Self {
            failure_threshold: default_cb_failure_threshold(),
            base_cooldown_secs: default_cb_base_cooldown_secs(),
            max_cooldown_secs: default_cb_max_cooldown_secs(),
            canary_timeout_ms: default_cb_canary_timeout_ms(),
        }
    }
}

fn default_cb_failure_threshold() -> u32 {
    3
}

fn default_cb_base_cooldown_secs() -> u64 {
    60
}

fn default_cb_max_cooldown_secs() -> u64 {
    1800
}

fn default_cb_canary_timeout_ms() -> u64 {
    3500
}

fn default_peering_addr() -> String {
    "127.0.0.1:0".to_string()
}

/// Definition and connection parameters for an individual federated peer node.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeeringNodeConfig {
    /// Alphanumeric identifier of the remote peer (e.g. "hub-core-lan").
    pub name: String,
    /// Remote UDP socket address (e.g. "192.168.1.10:9876" or "10.10.0.2:9876").
    #[serde(default = "default_peering_addr")]
    pub addr: String,
    /// Hardware serial device path (e.g. "/dev/ttyUSB0") when link_type is lora_serial.
    #[serde(default)]
    pub serial_device: Option<String>,
    /// Serial baud rate (default: 115200).
    #[serde(default)]
    pub baud_rate: Option<u32>,
    /// LoRa spreading factor (7..=12, default: 9).
    #[serde(default)]
    pub spreading_factor: Option<u8>,
    /// LoRa bandwidth in kHz (default: 125).
    #[serde(default)]
    pub bandwidth_khz: Option<u32>,
    /// LoRa duty cycle limit percent (e.g. 1.0 for 1%, default: 1.0).
    #[serde(default)]
    pub duty_cycle_percent: Option<f64>,
    /// Physical link classification (LAN, VPN, or LoRa radio).
    #[serde(default)]
    pub link_type: PeeringLinkType,
    /// Number of jittered burst transmissions for LoRa links (Profile A).
    #[serde(default)]
    pub burst_retries: Option<u32>,
    /// Base interval in milliseconds between burst transmissions.
    #[serde(default)]
    pub burst_interval_ms: Option<u64>,
    /// Maximum random jitter in milliseconds applied to burst intervals.
    #[serde(default)]
    pub burst_jitter_ms: Option<u64>,
    /// Maximum retry attempts for IP links (Profile B ARQ override).
    #[serde(default)]
    pub max_ip_retries: Option<u32>,
    /// Initial base timeout in milliseconds (Profile B ARQ override).
    #[serde(default)]
    pub base_timeout_ms: Option<u64>,
    /// Circuit breaker consecutive failure threshold override.
    #[serde(default)]
    pub failure_threshold: Option<u32>,
    /// Circuit breaker base cooldown seconds override.
    #[serde(default)]
    pub base_cooldown_secs: Option<u64>,
    /// Per-peer 256-bit pre-shared key (64 hex characters) overriding the global key.
    #[serde(default)]
    pub shared_key: Option<String>,
}

/// Configuration for the decentralized UDP peering, edge-backhaul, and emergency failover subsystem.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeeringConfig {
    /// Whether the peering subsystem UDP socket and workers are enabled.
    #[serde(default = "default_peering_enabled")]
    pub enabled: bool,
    /// Local UDP socket bind address (e.g. "0.0.0.0:9876").
    #[serde(default = "default_peering_listen_addr")]
    pub listen_addr: String,
    /// Global 256-bit symmetric pre-shared key (64 hex characters) for XChaCha20-Poly1305.
    #[serde(default)]
    pub shared_key: String,
    /// Sliding-window deduplication cache lifetime in seconds.
    #[serde(default = "default_peering_dedup_ttl")]
    pub dedup_ttl_secs: u64,
    /// Clock skew tolerance in seconds for off-grid edge nodes without NTP.
    #[serde(default = "default_clock_skew_tolerance")]
    pub clock_skew_tolerance_secs: u64,
    /// Global retry defaults.
    #[serde(default)]
    pub retry: PeeringRetryConfig,
    /// Global circuit breaker defaults.
    #[serde(default)]
    pub circuit_breaker: PeeringCircuitBreakerConfig,
    /// Configured remote peer nodes.
    #[serde(default)]
    pub nodes: Vec<PeeringNodeConfig>,
}

fn default_peering_enabled() -> bool {
    false
}

fn default_peering_listen_addr() -> String {
    "0.0.0.0:9876".to_string()
}

fn default_peering_dedup_ttl() -> u64 {
    60
}

fn default_clock_skew_tolerance() -> u64 {
    300
}

impl Default for PeeringConfig {
    fn default() -> Self {
        Self {
            enabled: default_peering_enabled(),
            listen_addr: default_peering_listen_addr(),
            shared_key: String::new(),
            dedup_ttl_secs: default_peering_dedup_ttl(),
            clock_skew_tolerance_secs: default_clock_skew_tolerance(),
            retry: PeeringRetryConfig::default(),
            circuit_breaker: PeeringCircuitBreakerConfig::default(),
            nodes: Vec::new(),
        }
    }
}

impl Default for PeeringNodeConfig {
    fn default() -> Self {
        Self {
            name: "peer".to_string(),
            addr: default_peering_addr(),
            serial_device: None,
            baud_rate: None,
            spreading_factor: None,
            bandwidth_khz: None,
            duty_cycle_percent: None,
            link_type: PeeringLinkType::default(),
            burst_retries: None,
            burst_interval_ms: None,
            burst_jitter_ms: None,
            max_ip_retries: None,
            base_timeout_ms: None,
            failure_threshold: None,
            base_cooldown_secs: None,
            shared_key: None,
        }
    }
}

/// Configuration for the cellular GSM/LTE SMS gateway subsystem.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SmsConfig {
    /// Whether the SMS gateway subsystem is active (default: false).
    #[serde(default = "default_sms_enabled")]
    pub enabled: bool,
    /// Serial AT device path (e.g., "/dev/ttyUSB2").
    #[serde(default = "default_sms_port")]
    pub port: String,
    /// Serial baud rate (default: 115200).
    #[serde(default = "default_sms_baud_rate")]
    pub baud_rate: u32,
    /// Preconfigured recipient phone numbers for outbound alerts.
    #[serde(default)]
    pub recipients: Vec<String>,
    /// Authorized sender phone numbers for inbound alert generation (empty = all allowed).
    #[serde(default)]
    pub authorized_senders: Vec<String>,
    /// Polling interval in seconds to check for incoming SMS messages.
    #[serde(default = "default_sms_poll_interval")]
    pub poll_interval_seconds: u64,
    /// SQLite SMS retention TTL in minutes (0 = never deleted).
    #[serde(default = "default_sms_ttl_minutes")]
    pub ttl_minutes: u64,
}

fn default_sms_enabled() -> bool {
    false
}

fn default_sms_port() -> String {
    "/dev/ttyUSB2".to_string()
}

fn default_sms_baud_rate() -> u32 {
    115200
}

fn default_sms_poll_interval() -> u64 {
    10
}

fn default_sms_ttl_minutes() -> u64 {
    1440 // 24 hours
}

impl Default for SmsConfig {
    fn default() -> Self {
        Self {
            enabled: default_sms_enabled(),
            port: default_sms_port(),
            baud_rate: default_sms_baud_rate(),
            recipients: Vec::new(),
            authorized_senders: Vec::new(),
            poll_interval_seconds: default_sms_poll_interval(),
            ttl_minutes: default_sms_ttl_minutes(),
        }
    }
}
