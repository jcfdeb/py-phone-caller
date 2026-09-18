//! # Alert Routing Engine
//!
//! Central routing core responsible for alert ingestion, deduplication, destination resolution,
//! persistent sliding-window storage, Prometheus/OpenTelemetry metrics, and asynchronous
//! dispatch across registered egress drivers.

use crate::config::AppConfig;
use crate::egress::{BitChatEgress, NostrPublisher, PrometheusWebhookDispatcher};
use crate::error::Result;
use crate::metrics::{MetricsHandle, OpenAlertMetrics};
use crate::models::{Alert, AlertSource};
use crate::storage::Storage;
use crate::templates::TemplateEngine;
use std::collections::HashMap;
use crate::peering::PeeringService;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::{Mutex, RwLock};
use tracing::{info, warn};

/// Coordinates alert processing, deduplication windows, persistent storage, and egress routing.
pub struct AlertEngine {
    config: AppConfig,
    nostr_publisher: Arc<NostrPublisher>,
    webhook_dispatcher: Arc<PrometheusWebhookDispatcher>,
    pub bitchat_egress: Arc<BitChatEgress>,
    storage: Option<Arc<Storage>>,
    dedup_cache: Arc<Mutex<HashMap<String, Instant>>>,
    metrics: MetricsHandle,
    peering_service: Arc<RwLock<Option<Arc<PeeringService>>>>,
}

impl AlertEngine {
    /// Creates and initializes the alert engine, storage layer, metrics registry, and all associated egress drivers.
    pub fn new(config: AppConfig) -> Result<Self> {
        let metrics = Arc::new(OpenAlertMetrics::new()?);

        let template_engine = Arc::new(TemplateEngine::new(
            &config.templates.template_dir,
            config.templates.default_template.clone(),
        )?);

        let nostr_publisher = Arc::new(NostrPublisher::new(
            config.nostr.relays.clone(),
            config.nostr.kind,
            config.nostr.alert_ttl_seconds,
        ));

        let webhook_dispatcher = Arc::new(PrometheusWebhookDispatcher::new(
            config.py_phone_caller.clone(),
            template_engine,
            Some(metrics.clone()),
        ));

        let bitchat_egress = Arc::new(BitChatEgress::new(config.bitchat.clone()));

        let storage = if config.storage.enabled {
            Some(Arc::new(Storage::new(config.storage.clone())?))
        } else {
            None
        };

        info!(
            "Initialized OpenAlert Engine [Pubkey: {}] (Storage: {})",
            nostr_publisher.public_key(),
            if let Some(ref s) = storage {
                if s.is_in_memory() { "in-memory SQLite (:memory:)" } else { "persistent SQLite (disk)" }
            } else {
                "disabled"
            }
        );

        Ok(Self {
            config,
            nostr_publisher,
            webhook_dispatcher,
            bitchat_egress,
            storage,
            dedup_cache: Arc::new(Mutex::new(HashMap::new())),
            metrics,
            peering_service: Arc::new(RwLock::new(None)),
        })
    }

    /// Returns a reference to the active Nostr event publisher.
    pub fn nostr_publisher(&self) -> &NostrPublisher {
        &self.nostr_publisher
    }

    /// Returns a reference to the active Prometheus webhook dispatcher.
    pub fn webhook_dispatcher(&self) -> &PrometheusWebhookDispatcher {
        &self.webhook_dispatcher
    }

    /// Returns a reference to the active BitChat BLE mesh egress driver.
    pub fn bitchat_egress(&self) -> &BitChatEgress {
        &self.bitchat_egress
    }

    /// Returns a reference to the embedded storage layer if enabled.
    pub fn storage(&self) -> Option<&Arc<Storage>> {
        self.storage.as_ref()
    }

    /// Returns a reference to the central daemon metrics registry.
    pub fn metrics(&self) -> &MetricsHandle {
        &self.metrics
    }

    /// Links the PeeringService to this engine.
    pub async fn set_peering_service(&self, peering: Arc<PeeringService>) {
        let mut guard = self.peering_service.write().await;
        *guard = Some(peering);
    }

    /// Returns a reference to the active PeeringService if attached.
    pub async fn peering_service(&self) -> Option<Arc<PeeringService>> {
        self.peering_service.read().await.clone()
    }

    /// Evaluates if an alert is duplicate using a multi-key strategy:
    /// 1. `id:<alert_id>` (explicit identifier)
    /// 2. `fp:<alert_id|summary>` (fingerprint hash)
    /// 3. `content:<summary:severity:sender>` (normalized content key to drop rapid identical spam)
    pub async fn is_duplicate_alert(&self, alert: &Alert) -> (bool, String) {
        let dedup_window = Duration::from_secs(self.config.routing.dedup_ttl_seconds);
        let now = Instant::now();
        let mut cache = self.dedup_cache.lock().await;

        cache.retain(|_, seen_at| now.duration_since(*seen_at) < dedup_window);

        let mut check_keys = Vec::new();

        // Key 1: Primary Alert ID
        let clean_id = alert.alert_id.trim();
        if !clean_id.is_empty() && clean_id != "unspecified" {
            check_keys.push(format!("id:{}", clean_id));
        }

        // Key 2: Canonical fingerprint (alert_id + summary)
        let fp = alert.fingerprint();
        check_keys.push(format!("fp:{}", fp));
        check_keys.push(fp.clone());

        // Key 3: Normalized content key (summary + severity + sender)
        let clean_summary = alert.summary.trim();
        if !clean_summary.is_empty() {
            let sender_str = alert.sender.as_deref().unwrap_or("");
            let content_key = format!("content:{}:{:?}:{}", clean_summary, alert.severity, sender_str);
            check_keys.push(content_key);
        }

        // 1. Fast in-memory check
        for key in &check_keys {
            if cache.contains_key(key) {
                return (true, key.clone());
            }
        }

        // 2. Persistent storage check (survives restarts)
        if let Some(ref storage) = self.storage
            && let Ok((is_dup, Some(matched))) = storage.is_duplicate(&check_keys, self.config.routing.dedup_ttl_seconds).await
            && is_dup {
            cache.insert(matched.clone(), now);
            return (true, matched);
        }

        // Record in fast RAM cache
        for key in &check_keys {
            cache.insert(key.clone(), now);
        }

        // Record in persistent storage
        if let Some(ref storage) = self.storage {
            let _ = storage.record_dedup_keys(&check_keys).await;
        }

        (false, String::new())
    }

    /// Evaluates if an arbitrary key or fingerprint was already processed within the deduplication window.
    pub async fn is_duplicate_and_record(&self, key: &str) -> bool {
        let dedup_window = Duration::from_secs(self.config.routing.dedup_ttl_seconds);
        let now = Instant::now();
        let mut cache = self.dedup_cache.lock().await;

        cache.retain(|_, seen_at| now.duration_since(*seen_at) < dedup_window);

        if cache.contains_key(key) {
            return true;
        }

        if let Some(ref storage) = self.storage {
            if let Ok((is_dup, _)) = storage.is_duplicate(&[key.to_string()], self.config.routing.dedup_ttl_seconds).await
                && is_dup {
                cache.insert(key.to_string(), now);
                return true;
            }
            let _ = storage.record_dedup_keys(&[key.to_string()]).await;
        }

        cache.insert(key.to_string(), now);
        false
    }

    /// Recovers and re-routes pending or unacknowledged alerts from storage after a restart.
    pub async fn recover_pending_alerts(self: &Arc<Self>) -> Result<usize> {
        let Some(ref storage) = self.storage else {
            return Ok(0);
        };

        let pending = storage.get_pending_alerts(self.config.storage.retention_seconds).await?;
        let count = pending.len();

        if count > 0 {
            info!(
                "🔄 Found {} unacknowledged / pending alert(s) within {}s retention window. Re-routing...",
                count, self.config.storage.retention_seconds
            );
            for alert in pending {
                let engine = self.clone();
                tokio::spawn(async move {
                    if let Err(e) = engine.route_alert(alert).await {
                        warn!("Failed to re-route recovered pending alert: {}", e);
                    }
                });
            }
        }

        Ok(count)
    }

    /// Spawns a background worker periodically pruning records older than the sliding window retention.
    pub fn start_background_pruning(self: Arc<Self>) {
        let Some(storage) = self.storage.clone() else {
            return;
        };

        let interval_secs = self.config.storage.prune_interval_seconds;
        let retention_secs = self.config.storage.retention_seconds;

        tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(interval_secs));
            loop {
                interval.tick().await;
                match storage.prune(retention_secs).await {
                    Ok(pruned) if pruned > 0 => {
                        info!("🧹 Storage sliding window: pruned {} expired alert/dedup records", pruned);
                    }
                    Err(e) => {
                        warn!("Failed to prune storage sliding window: {}", e);
                    }
                    _ => {}
                }
            }
        });
    }

    /// Routes an alert to its designated egress targets based on configuration and alert rules.
    pub async fn route_alert(&self, alert: Alert) -> Result<()> {
        let source_name = match alert.source {
            AlertSource::Rest => "rest",
            AlertSource::Nostr => "nostr",
            AlertSource::BitChat => "bitchat",
            AlertSource::Prometheus => "prometheus",
            AlertSource::Peering => "peering",
        };
        self.metrics.alerts_received_total.with_label_values(&[source_name]).inc();

        let (is_dup, matched_key) = self.is_duplicate_alert(&alert).await;
        if is_dup {
            let match_type = if matched_key.starts_with("id:") {
                "id"
            } else if matched_key.starts_with("fp:") {
                "fp"
            } else if matched_key.starts_with("content:") {
                "content"
            } else {
                "hash"
            };
            self.metrics.duplicates_dropped_total.with_label_values(&[match_type]).inc();

            info!(
                "🛑 Dropped duplicate alert [{}] (summary: \"{}\", matched key: {}) within deduplication window",
                alert.alert_id,
                alert.summary,
                matched_key
            );
            return Ok(());
        }

        // Record initial pending state in persistent storage
        if let Some(ref storage) = self.storage {
            let _ = storage.record_alert(&alert, "pending").await;
            self.metrics.storage_alerts_count.with_label_values(&["pending"]).inc();
        }

        info!(
            "🚀 Routing Alert [{}] (Severity: {:?}, Source: {:?})",
            alert.alert_id, alert.severity, alert.source
        );

        let destinations = if alert.destinations.is_empty() {
            &self.config.routing.default_destinations
        } else {
            &alert.destinations
        };

        for destination in destinations {
            match destination.as_str() {
                "nostr" => {
                    if alert.source != AlertSource::Nostr {
                        let publisher = self.nostr_publisher.clone();
                        let outbound_alert = alert.clone();
                        let metrics = self.metrics.clone();
                        tokio::spawn(async move {
                            match publisher.sign_alert(&outbound_alert) {
                                Ok(event) => {
                                    publisher.publish_to_relays(&event).await;
                                    metrics.alerts_dispatched_total.with_label_values(&["nostr", "success"]).inc();
                                }
                                Err(err) => {
                                    warn!(
                                        "Failed to sign Nostr event for alert [{}]: {}",
                                        outbound_alert.alert_id, err
                                    );
                                    metrics.alerts_dispatched_total.with_label_values(&["nostr", "failure"]).inc();
                                }
                            }
                        });
                    }
                }
                "peering" => {
                    let peering_opt = self.peering_service.read().await.clone();
                    if let Some(peering) = peering_opt {
                        let outbound_alert = alert.clone();
                        let metrics = self.metrics.clone();
                        tokio::spawn(async move {
                            match peering.dispatch_alert(&outbound_alert, false).await {
                                Ok(()) => {
                                    metrics.alerts_dispatched_total.with_label_values(&["peering", "success"]).inc();
                                }
                                Err(err) => {
                                    metrics.alerts_dispatched_total.with_label_values(&["peering", "failure"]).inc();
                                    warn!("Peering dispatch failed for alert [{}]: {}", outbound_alert.alert_id, err);
                                }
                            }
                        });
                    }
                }
                "webhook" | "py_phone_caller" => {
                    let dispatcher = self.webhook_dispatcher.clone();
                    let outbound_alert = alert.clone();
                    let storage_opt = self.storage.clone();
                    let metrics = self.metrics.clone();
                    let failover_destinations = self.config.routing.failover_destinations.clone();
                    let peering_opt = self.peering_service.read().await.clone();
                    tokio::spawn(async move {
                        match dispatcher.dispatch(&outbound_alert).await {
                            Ok(()) => {
                                metrics.alerts_dispatched_total.with_label_values(&["webhook", "success"]).inc();
                                if let Some(ref s) = storage_opt {
                                    let _ = s.mark_dispatched(&outbound_alert.alert_id).await;
                                    metrics.storage_alerts_count.with_label_values(&["dispatched"]).inc();
                                }
                            }
                            Err(e) => {
                                metrics.alerts_dispatched_total.with_label_values(&["webhook", "failure"]).inc();
                                warn!("Failed to dispatch webhook for alert [{}]: {}", outbound_alert.alert_id, e);

                                if failover_destinations.contains(&"peering".to_string())
                                    && let Some(peering) = peering_opt {
                                        let failover_alert = outbound_alert.clone();
                                        tokio::spawn(async move {
                                            warn!("🚨 Primary webhook failed! Escalating alert [{}] to failover peering", failover_alert.alert_id);
                                            let _ = peering.dispatch_alert(&failover_alert, true).await;
                                        });
                                }
                            }
                        }
                    });
                }
                "bitchat" => {
                    let should_broadcast = alert.source != AlertSource::BitChat
                        || alert.alert_id.starts_with("bitchat-dm-");
                    if should_broadcast {
                        let egress = self.bitchat_egress.clone();
                        let outbound_alert = alert.clone();
                        let metrics = self.metrics.clone();
                        tokio::spawn(async move {
                            match egress.broadcast(&outbound_alert).await {
                                Ok(()) => {
                                    metrics.alerts_dispatched_total.with_label_values(&["bitchat", "success"]).inc();
                                }
                                Err(err) => {
                                    metrics.alerts_dispatched_total.with_label_values(&["bitchat", "failure"]).inc();
                                    warn!(
                                        "BitChat broadcast failed for alert [{}]: {}",
                                        outbound_alert.alert_id, err
                                    );
                                }
                            }
                        });
                    }
                }
                unknown_dest => {
                    warn!("Unknown alert destination: {}", unknown_dest);
                }
            }
        }

        Ok(())
    }
}
