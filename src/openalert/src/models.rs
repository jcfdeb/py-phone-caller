//! # Internal Data Models & Wire Formats
//!
//! Defines the canonical [`Alert`] struct used within the routing engine alongside
//! serializable wire formats for Nostr events (NIP-01), Prometheus Alertmanager webhooks,
//! HTTP REST requests, and federated peer datagrams.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::HashMap;

/// Severity levels for incoming and routed alerts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AlertSeverity {
    /// Informational notifications without operational urgency.
    Info,
    /// Non-critical anomalies or early warning thresholds.
    Warning,
    /// Urgent operational failures requiring prompt intervention.
    Critical,
    /// Highest urgency catastrophe or safety threat.
    Emergency,
}

impl AlertSeverity {
    /// Parses a string slice into an [`AlertSeverity`], defaulting to `Critical` if unrecognized.
    pub fn parse_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "info" | "informational" => Self::Info,
            "warning" | "warn" => Self::Warning,
            "critical" | "crit" => Self::Critical,
            "emergency" | "emerg" => Self::Emergency,
            _ => Self::Critical,
        }
    }
}

/// Identifies the protocol or channel where an alert originated.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AlertSource {
    /// Ingested via direct HTTP REST call (`/api/v1/alerts`).
    Rest,
    /// Ingested via Prometheus Alertmanager webhook (`/api/v1/webhook/prometheus`).
    Prometheus,
    /// Received from a Nostr relay subscriber (NIP-01 / Kind 30000).
    Nostr,
    /// Decoded from a local Bluetooth Low Energy mesh packet.
    BitChat,
    /// Ingested from a federated peer node via encrypted UDP datagram.
    Peering,
    /// Ingested from a cellular GSM modem via inbound SMS.
    Sms,
}

impl std::fmt::Display for AlertSource {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Rest => write!(f, "rest"),
            Self::Prometheus => write!(f, "prometheus"),
            Self::Nostr => write!(f, "nostr"),
            Self::BitChat => write!(f, "bitchat"),
            Self::Peering => write!(f, "peering"),
            Self::Sms => write!(f, "sms"),
        }
    }
}

fn default_hop_count() -> u8 {
    3
}

/// Canonical internal representation of an alert routed through OpenAlert.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Alert {
    /// Unique identifier for this alert instance.
    pub alert_id: String,
    /// Urgency level of the alert.
    pub severity: AlertSeverity,
    /// Short summary of the alerting condition.
    pub summary: String,
    /// Extended technical description or diagnostic details.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    /// Source interface where the alert was ingested.
    pub source: AlertSource,
    /// Identifier of the originator (e.g. pubkey, peer ID, or job name).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sender: Option<String>,
    /// Node or host where the alert was generated.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node: Option<String>,
    /// UTC timestamp marking when the alert condition began.
    pub starts_at: DateTime<Utc>,
    /// List of target egress channels (e.g., `"nostr"`, `"webhook"`, `"bitchat"`, `"peering"`, `"sms"`).
    #[serde(default)]
    pub destinations: Vec<String>,
    /// Originating peer identifier if received via peering (used for split-horizon suppression).
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub origin_peer: Option<String>,
    /// Remaining mesh hop count (decremented on forwarding, dropped when 0).
    #[serde(default = "default_hop_count")]
    pub hop: u8,
}

impl Alert {
    /// Computes a stable SHA-256 fingerprint from the alert ID and summary.
    pub fn fingerprint(&self) -> String {
        let mut hasher = Sha256::new();
        hasher.update(self.alert_id.as_bytes());
        hasher.update(self.summary.as_bytes());
        hex::encode(hasher.finalize())
    }

    /// Computes a 64-bit integer fingerprint for high-density peering datagrams.
    pub fn fingerprint_u64(&self) -> u64 {
        let mut hasher = Sha256::new();
        hasher.update(self.alert_id.as_bytes());
        hasher.update(self.summary.as_bytes());
        let hash = hasher.finalize();
        u64::from_be_bytes(hash[0..8].try_into().unwrap_or([0u8; 8]))
    }

    /// Computes a normalized content key for deduplication across slight ID changes.
    pub fn content_key(&self) -> String {
        let mut hasher = Sha256::new();
        hasher.update(self.summary.trim().to_lowercase().as_bytes());
        hasher.update(format!("{:?}", self.severity).as_bytes());
        if let Some(ref s) = self.sender {
            hasher.update(s.trim().as_bytes());
        }
        hex::encode(hasher.finalize())
    }

    /// Checks if a given destination is active for this alert.
    pub fn has_destination(&self, dest: &str) -> bool {
        self.destinations
            .iter()
            .any(|d| d.eq_ignore_ascii_case(dest))
    }
}

/// Incoming JSON payload structure for the `/api/v1/alerts` REST endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RestAlertRequest {
    /// Unique alert identifier.
    pub alert_id: String,
    /// Alert urgency level.
    pub severity: AlertSeverity,
    /// Brief synopsis of the alert.
    pub summary: String,
    /// Optional expanded details.
    #[serde(default)]
    pub description: Option<String>,
    /// Originating sender name or identifier.
    #[serde(default)]
    pub sender: Option<String>,
    /// Host or cluster node name.
    #[serde(default)]
    pub node: Option<String>,
    /// Explicit destination channels for this alert.
    #[serde(default)]
    pub destinations: Vec<String>,
}

/// Response returned to clients after successful alert ingestion via REST.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RestAlertResponse {
    /// Processing status string (`"accepted"`).
    pub status: String,
    /// Echo of the submitted alert identifier.
    pub alert_id: String,
    /// Computed fingerprint used for deduplication tracking.
    pub fingerprint: String,
    /// Ingestion timestamp.
    pub timestamp: DateTime<Utc>,
}

/// Standard Prometheus Alertmanager webhook payload model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PrometheusAlertmanagerPayload {
    /// Webhook format version.
    #[serde(default)]
    pub version: Option<String>,
    /// Group alert status ("firing" or "resolved").
    #[serde(default)]
    pub status: Option<String>,
    /// Receiver identifier configured in Alertmanager.
    #[serde(default)]
    pub receiver: Option<String>,
    /// List of individual alert items in this notification batch.
    #[serde(default)]
    pub alerts: Vec<PrometheusAlertItem>,
    /// Key-value pairs common across all alerts in the batch.
    #[serde(default)]
    pub common_labels: HashMap<String, String>,
    /// Annotation key-value pairs common across all alerts in the batch.
    #[serde(default)]
    pub common_annotations: HashMap<String, String>,
    /// External URL backlink to the Alertmanager web UI.
    #[serde(default)]
    pub external_url: Option<String>,
}

impl PrometheusAlertmanagerPayload {
    /// Converts all firing alert items into canonical [`Alert`] structures.
    pub fn into_canonical_alerts(self) -> Vec<Alert> {
        self.alerts
            .into_iter()
            .filter(|item| item.status == "firing")
            .map(|item| item.into_canonical_alert())
            .collect()
    }
}

/// Individual alert item within a Prometheus Alertmanager notification batch.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PrometheusAlertItem {
    /// Status of this specific alert ("firing" or "resolved").
    #[serde(default = "default_firing_status")]
    pub status: String,
    /// Prometheus labels identifying the target and alert dimensions.
    #[serde(default)]
    pub labels: HashMap<String, String>,
    /// Prometheus annotations holding human-readable summary and description.
    #[serde(default)]
    pub annotations: HashMap<String, String>,
    /// Timestamp when the alert started firing.
    #[serde(rename = "startsAt", default = "Utc::now")]
    pub starts_at: DateTime<Utc>,
    /// Timestamp when the alert was resolved (if applicable).
    #[serde(rename = "endsAt", default)]
    pub ends_at: Option<DateTime<Utc>>,
    /// Backlink URL to Prometheus query generator.
    #[serde(rename = "generatorURL", default)]
    pub generator_url: Option<String>,
}

fn default_firing_status() -> String {
    "firing".to_string()
}

impl PrometheusAlertItem {
    /// Converts a Prometheus alert item into a canonical [`Alert`].
    pub fn into_canonical_alert(self) -> Alert {
        let alert_id = self
            .labels
            .get("alertname")
            .cloned()
            .unwrap_or_else(|| "prometheus_alert".to_string());

        let severity = self
            .labels
            .get("severity")
            .map(|s| AlertSeverity::parse_str(s))
            .unwrap_or(AlertSeverity::Critical);

        let description = self.annotations.get("description").cloned();
        let summary = self
            .annotations
            .get("summary")
            .cloned()
            .or_else(|| description.clone())
            .unwrap_or_else(|| alert_id.clone());

        let sender = self
            .labels
            .get("sender")
            .cloned()
            .or_else(|| self.labels.get("job").cloned());

        let node = self.labels.get("instance").cloned();

        Alert {
            alert_id,
            severity,
            summary,
            description,
            source: AlertSource::Prometheus,
            sender,
            node,
            starts_at: self.starts_at,
            destinations: Vec::new(),
            origin_peer: None,
            hop: default_hop_count(),
        }
    }
}

/// Response returned by the Prometheus webhook ingress endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PrometheusWebhookResponse {
    /// Processing status string.
    pub status: String,
    /// Total count of alerts ingested from the payload.
    pub ingested_count: usize,
    /// Identifiers of all ingested alerts.
    pub alert_ids: Vec<String>,
    /// Ingestion timestamp.
    pub timestamp: DateTime<Utc>,
}

/// Canonical Nostr event structure following NIP-01 specifications.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NostrEvent {
    /// Unique 32-byte hex event ID derived from SHA-256 hash of serialized event data.
    pub id: String,
    /// 32-byte hex public key of the event creator.
    pub pubkey: String,
    /// Unix timestamp in seconds marking event creation.
    pub created_at: u64,
    /// Event kind integer defining semantic type (e.g., 30000 for parameter-replaceable alerts).
    pub kind: u64,
    /// Arbitrary structured tag arrays (e.g. `["d", "identifier"]`, `["severity", "critical"]`).
    pub tags: Vec<Vec<String>>,
    /// Stringified payload content, typically JSON-serialized alert data.
    pub content: String,
    /// 64-byte hex Schnorr signature over the event ID.
    pub sig: String,
}

/// Lightweight liveness health response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthResponse {
    pub status: String,
    pub uptime_seconds: u64,
    pub version: String,
}

/// Comprehensive daemon status diagnostics response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeStatusResponse {
    pub status: String,
    pub node_name: String,
    pub version: String,
    pub pubkey: String,
    pub uptime_seconds: u64,
    pub storage: StorageStatusReport,
    pub peering: Option<PeeringStatusReport>,
    pub webhook: WebhookStatusReport,
    pub nostr: NostrStatusReport,
    pub bitchat: BitChatStatusReport,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sms: Option<SmsStatusResponse>,
}

/// Storage status and spool backlog report.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageStatusReport {
    pub enabled: bool,
    pub is_in_memory: bool,
    pub spool: Option<SpoolStats>,
}

/// Peering spool metrics summary.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpoolStats {
    pub spooled: usize,
    pub delivered: usize,
    pub total: usize,
}

/// Peering subsystem diagnostics report.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeeringStatusReport {
    pub enabled: bool,
    pub listen_addr: String,
    pub peers: Vec<PeerDiagnostics>,
}

/// Diagnostics for an individual peer node.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PeerDiagnostics {
    pub name: String,
    pub addr: String,
    pub link_type: String,
    pub circuit_state: crate::peering::circuit_breaker::CircuitState,
    pub consecutive_failures: u32,
    pub spooled_count: usize,
}

/// Webhook egress status report.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WebhookStatusReport {
    pub strategy: String,
    pub targets_count: usize,
}

/// Nostr transport status report.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NostrStatusReport {
    pub enabled: bool,
    pub relays_count: usize,
    pub pubkey: String,
    #[serde(default)]
    pub oxchat_enabled: bool,
    #[serde(default)]
    pub oxchat_mode: String,
    #[serde(default)]
    pub oxchat_recipients_count: usize,
}

/// Detailed BitChat peer node information.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BitChatPeerInfo {
    pub sender_id: String,
    pub nickname: String,
    pub session_state: String,
    pub verified: bool,
    pub last_seen_seconds_ago: u64,
    pub messages_received: u64,
    pub messages_sent: u64,
}

/// BitChat BLE mesh status report.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BitChatStatusReport {
    pub enabled: bool,
    pub node_name: String,
    pub sender_id: String,
    pub service_uuid: String,
    pub status: String,
    pub peers_count: usize,
    pub active_sessions_count: usize,
    pub peers: Vec<BitChatPeerInfo>,
}

/// Historical record of an SMS transaction in SQLite.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SmsRecord {
    pub id: i64,
    pub direction: String,
    pub phone_number: String,
    pub message: String,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_detail: Option<String>,
    pub created_at: i64,
}

/// Request payload to update SMS configuration dynamically.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SmsConfigUpdateRequest {
    #[serde(default)]
    pub recipients: Option<Vec<String>>,
    #[serde(default)]
    pub authorized_senders: Option<Vec<String>>,
}

/// Request payload to send an ad-hoc SMS via REST / Web UI.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SmsSendRequest {
    #[serde(alias = "phone")]
    pub phone_number: String,
    pub message: String,
}

/// Status and configuration of the cellular SMS subsystem.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SmsStatusResponse {
    pub enabled: bool,
    pub port: String,
    pub baud_rate: u32,
    pub poll_interval_seconds: u64,
    pub ttl_minutes: u64,
    pub recipients: Vec<String>,
    pub authorized_senders: Vec<String>,
    pub modem_status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_error: Option<String>,
}

/// Request payload to convert a Nostr key or derive public keys.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolConvertKeyRequest {
    pub key: String,
}

/// Request payload to convert between UTF-8 text and SMS UCS-2 hex.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolConvertSmsRequest {
    pub payload: String,
}

/// Request payload to hash a password.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolHashPasswordRequest {
    pub password: String,
}

/// Response payload for raw configuration operations.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigResponse {
    pub config_path: String,
    pub toml_content: String,
    pub config: crate::config::AppConfig,
}

/// Request payload to validate or save raw configuration TOML.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConfigUpdateRequest {
    pub toml_content: String,
    #[serde(default)]
    pub reload: bool,
}

/// Request payload to update Nostr 0xChat operators & recipients specifically.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct NostrOxchatUpdateRequest {
    #[serde(default)]
    pub recipients: Option<Vec<String>>,
    #[serde(default)]
    pub c2_authorized_operators: Option<Vec<String>>,
    #[serde(default)]
    pub mode: Option<String>,
}
