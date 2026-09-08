//! # Data Models
//!
//! Defines canonical alert representations, network request/response DTOs, and protocol-specific
//! event structures used throughout the daemon.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Severity classifications for routed alerts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum AlertSeverity {
    /// Informational notice; non-urgent status update.
    Info,
    /// Warning condition that may require operator attention.
    Warning,
    /// Critical failure requiring immediate operational response.
    #[default]
    Critical,
    /// Emergency situation demanding immediate voice call dispatch.
    Emergency,
}

impl AlertSeverity {
    /// Parses a string representation into an [`AlertSeverity`] variant.
    pub fn parse_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "info" => Self::Info,
            "warning" | "warn" => Self::Warning,
            "critical" | "crit" => Self::Critical,
            "emergency" | "fatal" => Self::Emergency,
            _ => Self::Critical,
        }
    }
}

/// Identifies the originating network or protocol source of an alert.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum AlertSource {
    /// Ingested via local or remote HTTP REST API endpoint.
    #[default]
    Rest,
    /// Received from a decentralized Nostr relay subscription.
    Nostr,
    /// Received over Bluetooth Low Energy BitChat mesh.
    BitChat,
    /// Native Prometheus or Alertmanager webhook ingestion.
    Prometheus,
    /// Custom integration source with identifier.
    Custom(String),
}

/// Canonical internal alert model routed across `openalertd` components.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Alert {
    /// Unique identifier for this alert instance or correlation key.
    pub alert_id: String,
    /// Severity classification determining dispatch urgency.
    pub severity: AlertSeverity,
    /// Short summary describing the incident.
    pub summary: String,
    /// Detailed incident description, context, or remediation instructions.
    pub description: Option<String>,
    /// Protocol source where the alert originated.
    pub source: AlertSource,
    /// Identity, pubkey, or nickname of the originating entity.
    pub sender: Option<String>,
    /// Hostname or mesh node identifier that dispatched the alert.
    pub node: Option<String>,
    /// Timestamp when the alert event was initiated.
    #[serde(default = "Utc::now")]
    pub starts_at: DateTime<Utc>,
    /// Target dispatch destinations (e.g. "webhook", "nostr", "bitchat").
    #[serde(default)]
    pub destinations: Vec<String>,
}

impl Alert {
    /// Computes a deterministic SHA-256 hexadecimal fingerprint for deduplication.
    pub fn fingerprint(&self) -> String {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(self.alert_id.as_bytes());
        hasher.update(self.summary.as_bytes());
        if let Some(ref desc) = self.description {
            hasher.update(desc.as_bytes());
        }
        format!("{:x}", hasher.finalize())
    }
}

/// Ingest request payload submitted to the generic HTTP REST endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RestAlertRequest {
    /// Unique identifier or alert key.
    pub alert_id: String,
    /// Optional severity; defaults to Critical if omitted.
    #[serde(default)]
    pub severity: AlertSeverity,
    /// Short incident summary.
    pub summary: String,
    /// Detailed description or log snippet.
    pub description: Option<String>,
    /// Originating sender name or identifier.
    pub sender: Option<String>,
    /// Originating node or machine name.
    pub node: Option<String>,
    /// Specific egress destinations to route this alert to.
    #[serde(default)]
    pub destinations: Vec<String>,
}

/// Response returned by the HTTP REST ingress endpoint upon alert ingestion.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RestAlertResponse {
    /// Processing status string (e.g., "accepted").
    pub status: String,
    /// Ingested alert identifier.
    pub alert_id: String,
    /// Computed deduplication fingerprint hash.
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
    /// SHA-256 hexadecimal event hash.
    pub id: String,
    /// Hex-encoded Schnorr public key of the author.
    pub pubkey: String,
    /// Unix timestamp in seconds.
    pub created_at: i64,
    /// Event kind number (e.g., Kind 1 for text, custom kind for alerts).
    pub kind: u64,
    /// Array of NIP-01 tags (e.g., `["d", "<alert_id>"]`, `["severity", "critical"]`).
    pub tags: Vec<Vec<String>>,
    /// Serialized event payload or message text.
    pub content: String,
    /// BIP-340 Schnorr signature over the event ID.
    pub sig: String,
}

/// BitChat mesh packet representation for peer exchange.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BitChatPacket {
    /// Optional associated alert identifier.
    #[serde(default)]
    pub alert_id: Option<String>,
    /// Optional alert severity level.
    #[serde(default)]
    pub severity: Option<AlertSeverity>,
    /// Message text content.
    pub content: String,
    /// Sender nickname or identifier.
    #[serde(default)]
    pub sender: Option<String>,
    /// Mesh node name.
    #[serde(default)]
    pub node: Option<String>,
    /// Unix timestamp in milliseconds.
    #[serde(default)]
    pub timestamp: Option<i64>,
}
