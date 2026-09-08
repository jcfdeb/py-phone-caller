//! # Alert Routing Engine
//!
//! Central routing core responsible for alert ingestion, deduplication, destination resolution,
//! and asynchronous dispatch across registered egress drivers.

use crate::config::AppConfig;
use crate::egress::{BitChatEgress, NostrPublisher, PrometheusWebhookDispatcher};
use crate::error::Result;
use crate::models::{Alert, AlertSource};
use crate::templates::TemplateEngine;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;
use tracing::{debug, info, warn};

/// Coordinates alert processing, deduplication windows, and egress routing.
pub struct AlertEngine {
    config: AppConfig,
    nostr_publisher: Arc<NostrPublisher>,
    webhook_dispatcher: Arc<PrometheusWebhookDispatcher>,
    pub bitchat_egress: Arc<BitChatEgress>,
    dedup_cache: Arc<Mutex<HashMap<String, Instant>>>,
}

impl AlertEngine {
    /// Creates and initializes the alert engine and all associated egress drivers.
    pub fn new(config: AppConfig) -> Result<Self> {
        let template_engine = Arc::new(TemplateEngine::new(
            &config.templates.template_dir,
            config.templates.default_template.clone(),
        )?);

        let nostr_publisher = Arc::new(NostrPublisher::new(
            config.nostr.relays.clone(),
            config.nostr.kind,
        ));

        let webhook_dispatcher = Arc::new(PrometheusWebhookDispatcher::new(
            config.py_phone_caller.clone(),
            template_engine,
        ));

        let bitchat_egress = Arc::new(BitChatEgress::new(config.bitchat.clone()));

        info!(
            "Initialized OpenAlert Engine [Pubkey: {}]",
            nostr_publisher.public_key()
        );

        Ok(Self {
            config,
            nostr_publisher,
            webhook_dispatcher,
            bitchat_egress,
            dedup_cache: Arc::new(Mutex::new(HashMap::new())),
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

    /// Evaluates if an alert fingerprint was already processed within the deduplication window.
    pub async fn is_duplicate_and_record(&self, fingerprint: &str) -> bool {
        let dedup_window = Duration::from_secs(self.config.routing.dedup_ttl_seconds);
        let now = Instant::now();
        let mut cache = self.dedup_cache.lock().await;

        cache.retain(|_, seen_at| now.duration_since(*seen_at) < dedup_window);

        if cache.contains_key(fingerprint) {
            return true;
        }

        cache.insert(fingerprint.to_string(), now);
        false
    }

    /// Routes an alert to its designated egress targets based on configuration and alert rules.
    pub async fn route_alert(&self, alert: Alert) -> Result<()> {
        let fingerprint = alert.fingerprint();
        if self.is_duplicate_and_record(&fingerprint).await {
            debug!(
                "Dropped duplicate alert [{}] (fp: {})",
                alert.alert_id,
                &fingerprint[..8]
            );
            return Ok(());
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
                        tokio::spawn(async move {
                            match publisher.sign_alert(&outbound_alert) {
                                Ok(event) => {
                                    publisher.publish_to_relays(&event).await;
                                }
                                Err(err) => {
                                    warn!(
                                        "Failed to sign Nostr event for alert [{}]: {}",
                                        outbound_alert.alert_id, err
                                    );
                                }
                            }
                        });
                    }
                }
                "webhook" | "py_phone_caller" => {
                    let dispatcher = self.webhook_dispatcher.clone();
                    let outbound_alert = alert.clone();
                    tokio::spawn(async move {
                        if let Err(err) = dispatcher.dispatch(&outbound_alert).await {
                            warn!(
                                "Webhook dispatch failed for alert [{}]: {}",
                                outbound_alert.alert_id, err
                            );
                        }
                    });
                }
                "bitchat" => {
                    let should_broadcast = alert.source != AlertSource::BitChat
                        || alert.alert_id.starts_with("bitchat-dm-");
                    if should_broadcast {
                        let egress = self.bitchat_egress.clone();
                        let outbound_alert = alert.clone();
                        tokio::spawn(async move {
                            if let Err(err) = egress.broadcast(&outbound_alert).await {
                                warn!(
                                    "BitChat egress failed for alert [{}]: {}",
                                    outbound_alert.alert_id, err
                                );
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
