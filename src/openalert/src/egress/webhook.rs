//! # Prometheus Webhook Dispatcher
//!
//! Submits rendered alert payloads to the `py-phone-caller` Prometheus Webhook receiver
//! with configurable exponential backoff and retry policies.

use crate::config::PyPhoneCallerConfig;
use crate::error::{OpenAlertError, Result};
use crate::models::Alert;
use crate::templates::TemplateEngine;
use reqwest::Client;
use std::sync::Arc;
use std::time::Duration;
use tracing::{error, info, warn};

/// Dispatches formatted alert JSON payloads to the `py-phone-caller` HTTP webhook.
pub struct PrometheusWebhookDispatcher {
    client: Client,
    config: PyPhoneCallerConfig,
    template_engine: Arc<TemplateEngine>,
}

impl PrometheusWebhookDispatcher {
    /// Constructs a new webhook dispatcher with the specified configuration and template engine.
    pub fn new(config: PyPhoneCallerConfig, template_engine: Arc<TemplateEngine>) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs_f64(config.timeout_seconds))
            .build()
            .unwrap_or_default();

        Self {
            client,
            config,
            template_engine,
        }
    }

    /// Renders the alert payload and transmits it to the webhook endpoint with retries.
    pub async fn dispatch(&self, alert: &Alert) -> Result<()> {
        let payload_json = self.template_engine.render_alert(alert, None)?;

        info!(
            "Dispatching alert [{}] to py-phone-caller Prometheus webhook at [{}]",
            alert.alert_id, self.config.webhook_url
        );

        let mut attempts = 0;
        let mut last_error = None;

        while attempts < self.config.max_retries {
            attempts += 1;
            match self
                .client
                .post(&self.config.webhook_url)
                .header("Content-Type", "application/json")
                .header("User-Agent", "openalertd/0.1.0")
                .body(payload_json.clone())
                .send()
                .await
            {
                Ok(resp) if resp.status().is_success() => {
                    info!(
                        "✅ Webhook dispatch succeeded for alert [{}] (status {})",
                        alert.alert_id,
                        resp.status()
                    );
                    return Ok(());
                }
                Ok(resp) => {
                    warn!(
                        "⚠️ Webhook endpoint returned status {} (attempt {}/{})",
                        resp.status(),
                        attempts,
                        self.config.max_retries
                    );
                    last_error = Some(OpenAlertError::Routing(format!(
                        "Webhook status {}",
                        resp.status()
                    )));
                }
                Err(err) => {
                    warn!(
                        "⚠️ Webhook connection failed: {} (attempt {}/{})",
                        err, attempts, self.config.max_retries
                    );
                    last_error = Some(OpenAlertError::HttpClient(err));
                }
            }

            tokio::time::sleep(Duration::from_millis(300 * attempts as u64)).await;
        }

        error!(
            "❌ All {} attempts to dispatch alert [{}] to py-phone-caller webhook exhausted",
            self.config.max_retries, alert.alert_id
        );

        Err(last_error.unwrap_or_else(|| OpenAlertError::Routing("Webhook failed".to_string())))
    }
}
