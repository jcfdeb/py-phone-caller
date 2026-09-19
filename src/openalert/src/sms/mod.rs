//! # Cellular GSM/LTE SMS Gateway Subsystem
//!
//! Provides bidirectional SMS communication via standard serial AT cellular modems:
//! - **Egress**: Dispatches alerts as UTF-8 / UCS-2 SMS to preconfigured recipient numbers.
//! - **Ingress**: Periodically polls incoming SMS messages from the SIM card, verifies sender
//!   authorization, ingests them into the OpenAlert routing engine, and prunes processed SIM storage.
//! - **Resilience**: Absolute zero-crash tolerance for unplugged cables, missing `/dev/ttyUSB*` devices,
//!   or unresponsive baseband firmware.
//! - **SQLite Persistence**: Stores all inbound and outbound SMS messages with configurable TTL retention.
//! - **Hot-Reload**: Allows dynamic updating of `recipients` and `authorized_senders` via REST API / Web UI.

pub mod codec;
pub mod modem;

use crate::config::SmsConfig;
use crate::engine::AlertEngine;
use crate::models::{Alert, AlertSeverity, AlertSource, SmsRecord, SmsStatusResponse};
use crate::storage::Storage;
use chrono::Utc;
use modem::ModemDriver;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Weak};
use std::time::Duration;
use tokio::sync::{Mutex, RwLock};
use tokio::time::sleep;
use tracing::{debug, error, info, warn};

/// Thread-safe status of the modem hardware link.
#[derive(Debug, Clone)]
pub struct ModemState {
    pub status: String,
    pub last_error: Option<String>,
}

/// Central cellular SMS service coordinating modem driver, background ingress, and persistence.
pub struct SmsService {
    config: Arc<RwLock<SmsConfig>>,
    storage: Arc<Storage>,
    engine: Weak<AlertEngine>,
    driver: ModemDriver,
    serial_lock: Arc<Mutex<()>>,
    modem_state: Arc<RwLock<ModemState>>,
    running: Arc<AtomicBool>,
}

impl SmsService {
    /// Initializes a new SMS service instance.
    /// Dynamic recipients and authorized senders are restored from SQLite if previously saved.
    pub async fn new(
        mut config: SmsConfig,
        storage: Arc<Storage>,
        engine: Weak<AlertEngine>,
    ) -> Self {
        // Restore dynamic settings from SQLite if present
        if let Ok(Some(recipients_json)) = storage.get_sms_setting("recipients").await
            && let Ok(loaded) = serde_json::from_str::<Vec<String>>(&recipients_json) {
            config.recipients = loaded;
        }
        if let Ok(Some(senders_json)) = storage.get_sms_setting("authorized_senders").await
            && let Ok(loaded) = serde_json::from_str::<Vec<String>>(&senders_json) {
            config.authorized_senders = loaded;
        }

        let driver = ModemDriver::new(&config.port, config.baud_rate);
        let initial_status = if config.enabled {
            "Initializing...".to_string()
        } else {
            "Disabled".to_string()
        };

        Self {
            config: Arc::new(RwLock::new(config)),
            storage,
            engine,
            driver,
            serial_lock: Arc::new(Mutex::new(())),
            modem_state: Arc::new(RwLock::new(ModemState {
                status: initial_status,
                last_error: None,
            })),
            running: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Spawns the background ingress poller and TTL pruning loop.
    pub fn start_worker(self: Arc<Self>) {
        if self.running.swap(true, Ordering::SeqCst) {
            return; // already started
        }

        let service = self.clone();
        tokio::spawn(async move {
            service.run_worker_loop().await;
        });
    }

    /// Continuous background loop executing modem polling and SQLite TTL cleanup.
    async fn run_worker_loop(&self) {
        let is_enabled = self.config.read().await.enabled;
        if !is_enabled {
            info!("Cellular GSM/LTE SMS subsystem is disabled ([sms] enabled = false)");
        } else {
            let active_port = self.driver.resolve_port();
            if active_port != self.driver.port_path {
                info!(
                    "📡 Starting cellular SMS worker on '{}' (resolved to active port '{}', poll interval: {}s)",
                    self.driver.port_path,
                    active_port,
                    self.config.read().await.poll_interval_seconds
                );
            } else {
                info!(
                    "📡 Starting cellular SMS worker on '{}' (poll interval: {}s)",
                    self.driver.port_path,
                    self.config.read().await.poll_interval_seconds
                );
            }
        }

        let mut last_probe_log = tokio::time::Instant::now() - Duration::from_secs(300);

        loop {
            let (enabled, poll_secs, ttl_minutes, authorized_senders) = {
                let cfg = self.config.read().await;
                (
                    cfg.enabled,
                    cfg.poll_interval_seconds,
                    cfg.ttl_minutes,
                    cfg.authorized_senders.clone(),
                )
            };

            if enabled {
                // Safely lock the serial port to avoid collisions with concurrent outgoing dispatches
                let lock_res = self.serial_lock.try_lock();
                if let Ok(_guard) = lock_res {
                    // Check modem status and read inbound messages
                    match self.driver.check_status().await {
                        Ok(status_desc) => {
                            {
                                let mut st = self.modem_state.write().await;
                                st.status = status_desc;
                                st.last_error = None;
                            }

                            // Fetch unread inbound messages
                            match self.driver.read_and_delete_inbound().await {
                                Ok(inbound_msgs) => {
                                    for msg in inbound_msgs {
                                        self.process_inbound_sms(&msg, &authorized_senders).await;
                                    }
                                }
                                Err(err) => {
                                    debug!("Inbound SMS read query failed: {}", err);
                                }
                            }
                        }
                        Err(err) => {
                            let mut st = self.modem_state.write().await;
                            st.status = "Device Unavailable".to_string();
                            st.last_error = Some(err.clone());

                            // Throttled warning log every 60s
                            if last_probe_log.elapsed() > Duration::from_secs(60) {
                                warn!(
                                    "⚠️ SMS modem device '{}' unreachable: {}. Subsystem remains resilient.",
                                    self.driver.resolve_port(), err
                                );
                                last_probe_log = tokio::time::Instant::now();
                            }
                        }
                    }
                }

                // Periodic TTL pruning of SQLite SMS records
                if ttl_minutes > 0
                    && let Ok(pruned) = self.storage.prune_sms(ttl_minutes).await
                    && pruned > 0 {
                    debug!("🧹 Pruned {} expired SMS records older than {}m", pruned, ttl_minutes);
                }
            }

            sleep(Duration::from_secs(poll_secs.max(2))).await;
        }
    }

    /// Handles an individual incoming SMS from the modem, applying authorization rules
    /// and injecting canonical alerts into the routing engine.
    async fn process_inbound_sms(&self, msg: &modem::InboundSms, authorized_senders: &[String]) {
        let clean_sender = msg.sender.trim();
        let clean_body = msg.body.trim();

        // Sender authorization check (if authorized_senders is not empty)
        let is_authorized = authorized_senders.is_empty()
            || authorized_senders.iter().any(|auth| {
                fn norm(s: &str) -> String {
                    let d: String = s.chars().filter(|c| c.is_ascii_digit()).collect();
                    if let Some(stripped) = d.strip_prefix("00") {
                        stripped.to_string()
                    } else {
                        d
                    }
                }
                let norm_auth = norm(auth);
                let norm_sender = norm(clean_sender);
                if norm_auth == norm_sender {
                    return true;
                }
                if norm_auth.len() >= 8 && norm_sender.len() >= 8 {
                    return norm_sender.ends_with(&norm_auth) || norm_auth.ends_with(&norm_sender);
                }
                auth.trim().eq_ignore_ascii_case(clean_sender)
            });

        if !is_authorized {
            warn!(
                "⛔ Ignored inbound SMS from unauthorized sender '{}' (Body: '{}')",
                clean_sender, clean_body
            );
            let _ = self
                .storage
                .record_sms(
                    "inbound",
                    clean_sender,
                    clean_body,
                    "rejected",
                    Some("Unauthorized sender"),
                )
                .await;
            return;
        }

        info!(
            "📥 Received authorized inbound SMS from '{}': \"{}\"",
            clean_sender, clean_body
        );

        // Record in SQLite
        let _ = self
            .storage
            .record_sms("inbound", clean_sender, clean_body, "received", None)
            .await;

        // Ingest into OpenAlert engine
        if let Some(engine) = self.engine.upgrade() {
            let alert_id = format!("sms-{}", &uuid::Uuid::new_v4().to_string()[..8]);
            let alert = Alert {
                alert_id,
                severity: AlertSeverity::Warning,
                summary: format!("Cellular SMS notification from {}", clean_sender),
                description: Some(clean_body.to_string()),
                source: AlertSource::Sms,
                sender: Some(clean_sender.to_string()),
                node: None,
                starts_at: Utc::now(),
                destinations: Vec::new(),
                origin_peer: None,
                hop: 3,
            };

            if let Err(e) = engine.route_alert(alert).await {
                error!("Failed to route inbound SMS alert into engine: {}", e);
            }
        }
    }

    /// Dispatches an alert as outbound SMS to all preconfigured recipients.
    /// Returns count of successfully delivered SMS messages.
    pub async fn dispatch_alert(&self, alert: &Alert) -> Result<usize, String> {
        let (enabled, recipients) = {
            let cfg = self.config.read().await;
            (cfg.enabled, cfg.recipients.clone())
        };

        if !enabled {
            debug!("SMS dispatch skipped: SMS subsystem is disabled");
            return Ok(0);
        }

        if recipients.is_empty() {
            warn!(
                "⚠️ SMS dispatch requested for alert [{}] but no recipients are configured",
                alert.alert_id
            );
            return Ok(0);
        }

        let desc_part = alert
            .description
            .as_deref()
            .unwrap_or(alert.summary.as_str());
        let message_payload = format!(
            "[{}] {}: {}",
            format!("{:?}", alert.severity).to_uppercase(),
            alert.alert_id,
            desc_part
        );

        let _guard = self.serial_lock.lock().await;
        let mut delivered_count = 0;

        for recipient in &recipients {
            match self.driver.send_sms(recipient, &message_payload).await {
                Ok(()) => {
                    info!(
                        "✅ Outbound SMS delivered to {} for alert [{}]",
                        recipient, alert.alert_id
                    );
                    let _ = self
                        .storage
                        .record_sms("outbound", recipient, &message_payload, "sent", None)
                        .await;
                    delivered_count += 1;
                }
                Err(err) => {
                    warn!(
                        "⚠️ Outbound SMS failed to {} for alert [{}]: {}",
                        recipient, alert.alert_id, err
                    );
                    let _ = self
                        .storage
                        .record_sms("outbound", recipient, &message_payload, "failed", Some(&err))
                        .await;
                }
            }
        }

        Ok(delivered_count)
    }

    /// Sends an ad-hoc SMS directly (e.g. from Web UI test button or REST API).
    pub async fn send_manual_sms(&self, phone: &str, message: &str) -> Result<(), String> {
        let _guard = self.serial_lock.lock().await;
        match self.driver.send_sms(phone, message).await {
            Ok(()) => {
                let _ = self
                    .storage
                    .record_sms("outbound", phone, message, "sent", None)
                    .await;
                Ok(())
            }
            Err(err) => {
                {
                    let mut st = self.modem_state.write().await;
                    st.status = "Device Unavailable".to_string();
                    st.last_error = Some(err.clone());
                }
                let _ = self
                    .storage
                    .record_sms("outbound", phone, message, "failed", Some(&err))
                    .await;
                Err(err)
            }
        }
    }

    /// Updates dynamic recipients and authorized senders, persisting changes to SQLite for hot-reload.
    pub async fn update_config(
        &self,
        new_recipients: Option<Vec<String>>,
        new_senders: Option<Vec<String>>,
    ) -> Result<SmsStatusResponse, String> {
        let mut cfg = self.config.write().await;

        if let Some(r) = new_recipients {
            let json = serde_json::to_string(&r).unwrap_or_else(|_| "[]".to_string());
            self.storage
                .set_sms_setting("recipients", &json)
                .await
                .map_err(|e| e.to_string())?;
            cfg.recipients = r;
        }

        if let Some(s) = new_senders {
            let json = serde_json::to_string(&s).unwrap_or_else(|_| "[]".to_string());
            self.storage
                .set_sms_setting("authorized_senders", &json)
                .await
                .map_err(|e| e.to_string())?;
            cfg.authorized_senders = s;
        }

        let state = self.modem_state.read().await.clone();
        Ok(SmsStatusResponse {
            enabled: cfg.enabled,
            port: cfg.port.clone(),
            baud_rate: cfg.baud_rate,
            poll_interval_seconds: cfg.poll_interval_seconds,
            ttl_minutes: cfg.ttl_minutes,
            recipients: cfg.recipients.clone(),
            authorized_senders: cfg.authorized_senders.clone(),
            modem_status: state.status,
            last_error: state.last_error,
        })
    }

    /// Returns the active status, modem state, and configured recipients.
    pub async fn get_status(&self) -> SmsStatusResponse {
        let cfg = self.config.read().await;
        let state = self.modem_state.read().await;

        let active_port = self.driver.resolve_port();
        SmsStatusResponse {
            enabled: cfg.enabled,
            port: active_port,
            baud_rate: cfg.baud_rate,
            poll_interval_seconds: cfg.poll_interval_seconds,
            ttl_minutes: cfg.ttl_minutes,
            recipients: cfg.recipients.clone(),
            authorized_senders: cfg.authorized_senders.clone(),
            modem_status: state.status.clone(),
            last_error: state.last_error.clone(),
        }
    }

    /// Returns historical SMS records from SQLite.
    pub async fn get_history(&self, limit: u32) -> Result<Vec<SmsRecord>, String> {
        self.storage
            .get_recent_sms(limit)
            .await
            .map_err(|e| e.to_string())
    }
}
