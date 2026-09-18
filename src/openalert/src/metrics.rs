//! # Metrics & Observability Subsystem
//!
//! Provides native Prometheus and OpenTelemetry-aligned metrics exposition
//! covering alert ingestion, deduplication, storage depth, webhook circuit breakers,
//! BitChat peers, and runtime process telemetry.

use crate::error::{OpenAlertError, Result};
use prometheus::{
    opts, register_counter_vec_with_registry, register_gauge_vec_with_registry, CounterVec,
    Encoder, GaugeVec, Registry, TextEncoder,
};
use std::sync::Arc;

/// Central metrics registry for openalertd daemon.
#[derive(Clone)]
pub struct OpenAlertMetrics {
    registry: Registry,
    /// Total alerts received across all ingress transports: Rest, Nostr, BitChat, Prometheus.
    pub alerts_received_total: CounterVec,
    /// Total alert dispatches attempted across egress destinations.
    pub alerts_dispatched_total: CounterVec,
    /// Total duplicate alerts suppressed by multi-key deduplication.
    pub duplicates_dropped_total: CounterVec,
    /// Total HTTP requests dispatched to py-phone-caller webhook instances.
    pub webhook_requests_total: CounterVec,
    /// Current circuit breaker state per webhook URL (0 = Closed, 1 = HalfOpen, 2 = Open).
    pub webhook_circuit_breaker_state: GaugeVec,
    /// Current count of alerts stored in SQLite database.
    pub storage_alerts_count: GaugeVec,
    /// Number of active BitChat BLE mesh peers currently known.
    pub bitchat_peers_connected: GaugeVec,
}

impl OpenAlertMetrics {
    /// Initializes all metric vectors and registers them with a dedicated registry.
    pub fn new() -> Result<Self> {
        let registry = Registry::new_custom(Some("openalert".to_string()), None)
            .map_err(|e| OpenAlertError::Config(format!("Failed to create metrics registry: {}", e)))?;

        // Ingress alerts counter
        let alerts_received_total = register_counter_vec_with_registry!(
            opts!(
                "alerts_received_total",
                "Total number of alerts received by openalertd by ingress transport"
            ),
            &["source"],
            registry
        )
        .map_err(|e| OpenAlertError::Config(format!("Metric registration error: {}", e)))?;

        // Egress alerts counter
        let alerts_dispatched_total = register_counter_vec_with_registry!(
            opts!(
                "alerts_dispatched_total",
                "Total number of alert dispatches attempted by destination and status"
            ),
            &["destination", "status"],
            registry
        )
        .map_err(|e| OpenAlertError::Config(format!("Metric registration error: {}", e)))?;

        // Deduplication drops counter
        let duplicates_dropped_total = register_counter_vec_with_registry!(
            opts!(
                "duplicates_dropped_total",
                "Total duplicate alerts dropped by matching key type"
            ),
            &["match_type"],
            registry
        )
        .map_err(|e| OpenAlertError::Config(format!("Metric registration error: {}", e)))?;

        // Webhook requests counter
        let webhook_requests_total = register_counter_vec_with_registry!(
            opts!(
                "webhook_requests_total",
                "Total HTTP requests dispatched to py-phone-caller webhook endpoints"
            ),
            &["url", "status"],
            registry
        )
        .map_err(|e| OpenAlertError::Config(format!("Metric registration error: {}", e)))?;

        // Circuit breaker gauge (0 = Closed, 1 = HalfOpen, 2 = Open)
        let webhook_circuit_breaker_state = register_gauge_vec_with_registry!(
            opts!(
                "webhook_circuit_breaker_state",
                "Current state of webhook circuit breaker (0=Closed, 1=HalfOpen, 2=Open)"
            ),
            &["url"],
            registry
        )
        .map_err(|e| OpenAlertError::Config(format!("Metric registration error: {}", e)))?;

        // Storage depth gauge
        let storage_alerts_count = register_gauge_vec_with_registry!(
            opts!(
                "storage_alerts_count",
                "Current count of stored alerts in embedded SQLite persistence layer"
            ),
            &["status"],
            registry
        )
        .map_err(|e| OpenAlertError::Config(format!("Metric registration error: {}", e)))?;

        // BitChat peers gauge
        let bitchat_peers_connected = register_gauge_vec_with_registry!(
            opts!(
                "bitchat_peers_connected",
                "Number of active BitChat BLE mesh peers currently known"
            ),
            &["node"],
            registry
        )
        .map_err(|e| OpenAlertError::Config(format!("Metric registration error: {}", e)))?;

        Ok(Self {
            registry,
            alerts_received_total,
            alerts_dispatched_total,
            duplicates_dropped_total,
            webhook_requests_total,
            webhook_circuit_breaker_state,
            storage_alerts_count,
            bitchat_peers_connected,
        })
    }

    /// Exports all metric families encoded in standard Prometheus text format.
    pub fn render(&self) -> Result<String> {
        let encoder = TextEncoder::new();
        let metric_families = self.registry.gather();
        let mut buffer = Vec::new();
        encoder
            .encode(&metric_families, &mut buffer)
            .map_err(|e| OpenAlertError::Config(format!("Failed to encode metrics: {}", e)))?;

        String::from_utf8(buffer)
            .map_err(|e| OpenAlertError::Config(format!("Invalid UTF-8 in metrics output: {}", e)))
    }
}

/// Global shared handle for daemon metrics.
pub type MetricsHandle = Arc<OpenAlertMetrics>;
