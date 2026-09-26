//! # Prometheus Webhook Dispatcher
//!
//! Submits rendered alert payloads to the `py-phone-caller` Prometheus Webhook receiver
//! with configurable multi-instance balancing strategies:
//! - **Cascade**: Failover by priority (`00`, `10`, `20`), with configurable delays before next endpoint.
//! - **Roundrobin**: Sequential rotation across instances.
//! - **Random**: Random endpoint selection with failover.
//! - **Broadcast**: Simultaneous parallel delivery to all configured instances.
//!
//! Includes an active **Circuit Breaker** protecting each endpoint against cascading timeouts
//! when downstream services are unreachable.

use crate::config::{PyPhoneCallerConfig, WebhookEndpointConfig, WebhookStrategy};
use crate::error::{OpenAlertError, Result};
use crate::metrics::MetricsHandle;
use crate::models::Alert;
use crate::templates::TemplateEngine;
use reqwest::Client;
use std::collections::HashMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tracing::{error, info, warn};

/// State of an endpoint circuit breaker.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CircuitBreakerState {
    /// Normal operation: requests pass through.
    Closed,
    /// Testing recovery: single probe allowed.
    HalfOpen,
    /// Tripped / cooldown: fast-fail without network request.
    Open,
}

impl CircuitBreakerState {
    /// Converts state to a numerical gauge representation for Prometheus metrics.
    pub fn as_metric_value(&self) -> f64 {
        match self {
            Self::Closed => 0.0,
            Self::HalfOpen => 1.0,
            Self::Open => 2.0,
        }
    }
}

#[derive(Debug)]
struct CircuitBreakerEntry {
    consecutive_failures: u32,
    failure_threshold: u32,
    cooldown: Duration,
    last_failure_time: Option<Instant>,
    state: CircuitBreakerState,
}

impl CircuitBreakerEntry {
    fn new(failure_threshold: u32, cooldown: Duration) -> Self {
        Self {
            consecutive_failures: 0,
            failure_threshold,
            cooldown,
            last_failure_time: None,
            state: CircuitBreakerState::Closed,
        }
    }

    fn can_attempt(&mut self) -> bool {
        match self.state {
            CircuitBreakerState::Closed => true,
            CircuitBreakerState::Open => {
                if let Some(last_time) = self.last_failure_time {
                    if last_time.elapsed() >= self.cooldown {
                        self.state = CircuitBreakerState::HalfOpen;
                        true
                    } else {
                        false
                    }
                } else {
                    self.state = CircuitBreakerState::HalfOpen;
                    true
                }
            }
            CircuitBreakerState::HalfOpen => true,
        }
    }

    fn record_success(&mut self) {
        self.consecutive_failures = 0;
        self.state = CircuitBreakerState::Closed;
    }

    fn record_failure(&mut self) -> CircuitBreakerState {
        self.consecutive_failures += 1;
        self.last_failure_time = Some(Instant::now());
        if self.state == CircuitBreakerState::HalfOpen
            || self.consecutive_failures >= self.failure_threshold
        {
            self.state = CircuitBreakerState::Open;
        }
        self.state
    }
}

/// Dispatches formatted alert JSON payloads to `py-phone-caller` HTTP webhooks.
pub struct PrometheusWebhookDispatcher {
    client: Client,
    config: PyPhoneCallerConfig,
    template_engine: Arc<TemplateEngine>,
    round_robin_counter: AtomicUsize,
    circuit_breakers: Mutex<HashMap<String, CircuitBreakerEntry>>,
    metrics: Option<MetricsHandle>,
}

impl PrometheusWebhookDispatcher {
    /// Constructs a new webhook dispatcher with the specified configuration, template engine, and optional metrics.
    pub fn new(
        config: PyPhoneCallerConfig,
        template_engine: Arc<TemplateEngine>,
        metrics: Option<MetricsHandle>,
    ) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs_f64(config.timeout_seconds))
            .build()
            .unwrap_or_default();

        Self {
            client,
            config,
            template_engine,
            round_robin_counter: AtomicUsize::new(0),
            circuit_breakers: Mutex::new(HashMap::new()),
            metrics,
        }
    }

    /// Checks whether the circuit breaker permits an attempt to the given endpoint URL.
    pub fn can_attempt_endpoint(&self, url: &str) -> bool {
        if !self.config.circuit_breaker_enabled {
            return true;
        }
        let mut breakers = self.circuit_breakers.lock().unwrap();
        let entry = breakers.entry(url.to_string()).or_insert_with(|| {
            CircuitBreakerEntry::new(
                self.config.circuit_breaker_failure_threshold,
                Duration::from_secs(self.config.circuit_breaker_cooldown_seconds),
            )
        });
        let allowed = entry.can_attempt();
        if let Some(ref m) = self.metrics {
            m.webhook_circuit_breaker_state
                .with_label_values(&[url])
                .set(entry.state.as_metric_value());
        }
        allowed
    }

    /// Records a successful HTTP dispatch, closing or resetting the circuit breaker.
    pub fn record_endpoint_success(&self, url: &str) {
        if !self.config.circuit_breaker_enabled {
            return;
        }
        let mut breakers = self.circuit_breakers.lock().unwrap();
        if let Some(entry) = breakers.get_mut(url) {
            let was_open = entry.state != CircuitBreakerState::Closed;
            entry.record_success();
            if was_open {
                info!("⚡ [Circuit Breaker] Webhook [{}] recovered to CLOSED", url);
            }
            if let Some(ref m) = self.metrics {
                m.webhook_circuit_breaker_state
                    .with_label_values(&[url])
                    .set(entry.state.as_metric_value());
            }
        }
    }

    /// Records a failed HTTP dispatch or timeout, incrementing consecutive failures and potentially opening the circuit.
    pub fn record_endpoint_failure(&self, url: &str) {
        if !self.config.circuit_breaker_enabled {
            return;
        }
        let mut breakers = self.circuit_breakers.lock().unwrap();
        let cooldown = Duration::from_secs(self.config.circuit_breaker_cooldown_seconds);
        let entry = breakers.entry(url.to_string()).or_insert_with(|| {
            CircuitBreakerEntry::new(self.config.circuit_breaker_failure_threshold, cooldown)
        });
        let prev_state = entry.state;
        let new_state = entry.record_failure();
        if new_state == CircuitBreakerState::Open && prev_state != CircuitBreakerState::Open {
            warn!(
                "⚡ [Circuit Breaker] Webhook [{}] tripped to OPEN (consecutive failures: {}, cooldown: {:?})",
                url, entry.consecutive_failures, entry.cooldown
            );
        }
        if let Some(ref m) = self.metrics {
            m.webhook_circuit_breaker_state
                .with_label_values(&[url])
                .set(entry.state.as_metric_value());
        }
    }

    /// Helper to transmit an alert payload to a single webhook endpoint with exponential backoff retries and circuit breaker protection.
    async fn send_to_endpoint(
        &self,
        endpoint: &WebhookEndpointConfig,
        alert_id: &str,
        payload_json: &str,
    ) -> Result<()> {
        let priority_val = endpoint.priority.unwrap_or(0);

        if !self.can_attempt_endpoint(&endpoint.url) {
            warn!(
                "⚡ [Circuit Breaker] Webhook [priority: {:02}] [{}] is OPEN (cooling down). Fast-skipping alert [{}]",
                priority_val, endpoint.url, alert_id
            );
            return Err(OpenAlertError::Routing(format!(
                "Circuit breaker OPEN for {}",
                endpoint.url
            )));
        }

        let auth_hdr = endpoint.auth.as_ref().and_then(|a| a.resolve_authorization_header());
        if auth_hdr.is_some() {
            let auth_type = endpoint.auth.as_ref().and_then(|a| a.auth_type.as_deref()).unwrap_or("unknown");
            info!(
                "Dispatching alert [{}] to py-phone-caller webhook [priority: {:02}] at [{}] (auth: {})",
                alert_id, priority_val, endpoint.url, auth_type
            );
        } else {
            info!(
                "Dispatching alert [{}] to py-phone-caller webhook [priority: {:02}] at [{}]",
                alert_id, priority_val, endpoint.url
            );
        }

        let mut attempts = 0;
        let mut last_error = None;
        let max_attempts = endpoint.max_retries.max(1);

        while attempts < max_attempts {
            attempts += 1;
            if let Some(ref m) = self.metrics {
                m.webhook_requests_total
                    .with_label_values(&[&endpoint.url, "attempt"])
                    .inc();
            }

            let mut req = self
                .client
                .post(&endpoint.url)
                .timeout(Duration::from_secs_f64(endpoint.timeout_seconds))
                .header("Content-Type", "application/json")
                .header("User-Agent", "openalertd/0.1.0");

            if let Some(ref h) = auth_hdr {
                req = req.header("Authorization", h);
            }

            match req
                .body(payload_json.to_string())
                .send()
                .await
            {
                Ok(resp) if resp.status().is_success() => {
                    info!(
                        "✅ Webhook [priority: {:02}] [{}] dispatch succeeded for alert [{}] (status {})",
                        priority_val,
                        endpoint.url,
                        alert_id,
                        resp.status()
                    );
                    self.record_endpoint_success(&endpoint.url);
                    if let Some(ref m) = self.metrics {
                        m.webhook_requests_total
                            .with_label_values(&[&endpoint.url, "success"])
                            .inc();
                    }
                    return Ok(());
                }
                Ok(resp) => {
                    warn!(
                        "⚠️ Webhook [priority: {:02}] [{}] returned HTTP status {} (attempt {}/{})",
                        priority_val,
                        endpoint.url,
                        resp.status(),
                        attempts,
                        max_attempts
                    );
                    last_error = Some(OpenAlertError::Routing(format!(
                        "Webhook returned HTTP {}",
                        resp.status()
                    )));
                }
                Err(err) => {
                    warn!(
                        "⚠️ Webhook [priority: {:02}] [{}] connection error: {} (attempt {}/{})",
                        priority_val, endpoint.url, err, attempts, max_attempts
                    );
                    last_error = Some(OpenAlertError::HttpClient(err));
                }
            }

            if attempts < max_attempts {
                tokio::time::sleep(Duration::from_millis(300 * attempts as u64)).await;
            }
        }

        warn!(
            "⚠️ Webhook [priority: {:02}] [{}] exhausted all {} attempt(s) for alert [{}]",
            priority_val, endpoint.url, max_attempts, alert_id
        );

        self.record_endpoint_failure(&endpoint.url);
        if let Some(ref m) = self.metrics {
            m.webhook_requests_total
                .with_label_values(&[&endpoint.url, "failure"])
                .inc();
        }

        Err(last_error
            .unwrap_or_else(|| OpenAlertError::Routing("Webhook dispatch failed".to_string())))
    }

    /// Renders the alert payload and transmits it according to the configured balancing strategy.
    pub async fn dispatch(&self, alert: &Alert) -> Result<()> {
        let endpoints = self.config.resolved_webhooks();
        if endpoints.is_empty() {
            warn!(
                "⚠️ No py-phone-caller webhook endpoints configured. Skipping webhook egress for alert [{}]",
                alert.alert_id
            );
            return Ok(());
        }

        let payload_json = self.template_engine.render_alert(alert, None)?;

        match self.config.strategy {
            WebhookStrategy::Cascade => {
                let total = endpoints.len();
                let mut last_err = None;

                for (idx, endpoint) in endpoints.iter().enumerate() {
                    let priority_val = endpoint.priority.unwrap_or(0);
                    info!(
                        "Cascade strategy: Attempting webhook [priority: {:02}] [{}] for alert [{}]",
                        priority_val, endpoint.url, alert.alert_id
                    );

                    match self
                        .send_to_endpoint(endpoint, &alert.alert_id, &payload_json)
                        .await
                    {
                        Ok(()) => {
                            // Primary/active webhook succeeded, complete dispatch to avoid duplicate calls
                            return Ok(());
                        }
                        Err(err) => {
                            warn!(
                                "⚠️ Webhook [priority: {:02}] [{}] failed or open: {}. Continuity active.",
                                priority_val, endpoint.url, err
                            );
                            last_err = Some(err);

                            // If another webhook instance is available in cascade, wait configured delay (unless fast-failed by circuit breaker)
                            if idx + 1 < total {
                                let next_priority = endpoints[idx + 1].priority.unwrap_or(0);
                                if self.can_attempt_endpoint(&endpoints[idx + 1].url) {
                                    info!(
                                        "Waiting {}s delay before cascading to next webhook [priority: {:02}]...",
                                        endpoint.delay, next_priority
                                    );
                                    tokio::time::sleep(Duration::from_secs(endpoint.delay)).await;
                                } else {
                                    info!(
                                        "Next webhook [priority: {:02}] is also cooling down. Fast-forwarding...",
                                        next_priority
                                    );
                                }
                            }
                        }
                    }
                }

                error!(
                    "❌ All {} cascade webhook instances exhausted for alert [{}]",
                    total, alert.alert_id
                );
                Err(last_err.unwrap_or_else(|| {
                    OpenAlertError::Routing("All cascade webhooks failed".to_string())
                }))
            }

            WebhookStrategy::Roundrobin => {
                let total = endpoints.len();
                let start_idx = self.round_robin_counter.fetch_add(1, Ordering::Relaxed) % total;
                let mut last_err = None;

                for step in 0..total {
                    let idx = (start_idx + step) % total;
                    let endpoint = &endpoints[idx];
                    match self
                        .send_to_endpoint(endpoint, &alert.alert_id, &payload_json)
                        .await
                    {
                        Ok(()) => return Ok(()),
                        Err(err) => {
                            warn!(
                                "Roundrobin: Endpoint [{}] failed for alert [{}], trying next available...",
                                endpoint.url, alert.alert_id
                            );
                            last_err = Some(err);
                        }
                    }
                }

                error!(
                    "❌ All {} roundrobin webhook instances failed for alert [{}]",
                    total, alert.alert_id
                );
                Err(last_err.unwrap_or_else(|| {
                    OpenAlertError::Routing("All roundrobin webhooks failed".to_string())
                }))
            }

            WebhookStrategy::Random => {
                let total = endpoints.len();
                let start_idx = (rand::random::<u32>() as usize) % total;
                let mut last_err = None;

                for step in 0..total {
                    let idx = (start_idx + step) % total;
                    let endpoint = &endpoints[idx];
                    match self
                        .send_to_endpoint(endpoint, &alert.alert_id, &payload_json)
                        .await
                    {
                        Ok(()) => return Ok(()),
                        Err(err) => {
                            warn!(
                                "Random strategy: Endpoint [{}] failed for alert [{}], trying fallback...",
                                endpoint.url, alert.alert_id
                            );
                            last_err = Some(err);
                        }
                    }
                }

                error!(
                    "❌ All {} webhook instances failed in random strategy for alert [{}]",
                    total, alert.alert_id
                );
                Err(last_err.unwrap_or_else(|| {
                    OpenAlertError::Routing("All random webhooks failed".to_string())
                }))
            }

            WebhookStrategy::Broadcast => {
                let mut futures = Vec::new();
                for endpoint in &endpoints {
                    let ep = endpoint.clone();
                    let a_id = alert.alert_id.clone();
                    let payload = payload_json.clone();
                    futures.push(async move { self.send_to_endpoint(&ep, &a_id, &payload).await });
                }

                let results = futures_util::future::join_all(futures).await;
                let mut any_success = false;
                let mut last_err = None;

                for (idx, res) in results.into_iter().enumerate() {
                    let endpoint = &endpoints[idx];
                    match res {
                        Ok(()) => any_success = true,
                        Err(e) => {
                            warn!(
                                "⚠️ Broadcast delivery failed for webhook [{}]: {}",
                                endpoint.url, e
                            );
                            last_err = Some(e);
                        }
                    }
                }

                if any_success {
                    Ok(())
                } else {
                    error!(
                        "❌ Broadcast delivery failed for all {} webhook instances for alert [{}]",
                        endpoints.len(),
                        alert.alert_id
                    );
                    Err(last_err.unwrap_or_else(|| {
                        OpenAlertError::Routing("Broadcast webhook delivery failed".to_string())
                    }))
                }
            }
        }
    }
}
