//! # REST API Ingress Server
//!
//! Provides high-throughput HTTP endpoints using Axum for health checking, generic alert submission,
//! and native Prometheus Alertmanager webhook ingestion.

use crate::config::RestConfig;
use crate::engine::AlertEngine;
use crate::error::Result;
use crate::models::{
    Alert, AlertSource, PrometheusAlertmanagerPayload, PrometheusWebhookResponse, RestAlertRequest,
    RestAlertResponse,
};
use axum::{
    Json, Router,
    extract::State,
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
};
use chrono::Utc;
use std::net::SocketAddr;
use std::sync::Arc;
use tower_http::cors::{Any, CorsLayer};
use tower_http::trace::TraceLayer;
use tracing::{error, info};

/// HTTP REST server hosting the ingress API.
pub struct RestServer {
    config: RestConfig,
    engine: Arc<AlertEngine>,
}

impl RestServer {
    /// Creates a new REST server instance bound to the given configuration and alert engine.
    pub fn new(config: RestConfig, engine: Arc<AlertEngine>) -> Self {
        Self { config, engine }
    }

    /// Binds the TCP listener and runs the Axum HTTP server until process termination.
    pub async fn run(self) -> Result<()> {
        let app = Router::new()
            .route("/health", get(health_check))
            .route("/api/v1/alerts", post(ingest_alert))
            .route(
                "/api/v1/webhook/prometheus",
                post(ingest_prometheus_webhook),
            )
            .layer(TraceLayer::new_for_http())
            .layer(
                CorsLayer::new()
                    .allow_origin(Any)
                    .allow_methods(Any)
                    .allow_headers(Any),
            )
            .with_state(self.engine);

        let addr: SocketAddr = format!("{}:{}", self.config.listen_host, self.config.listen_port)
            .parse()
            .map_err(|e| {
                crate::error::OpenAlertError::Config(format!("Invalid listen address: {}", e))
            })?;

        info!("🚀 Ingress REST API listening on http://{}", addr);

        let listener = tokio::net::TcpListener::bind(addr).await?;
        axum::serve(listener, app)
            .await
            .map_err(crate::error::OpenAlertError::Io)?;

        Ok(())
    }
}

/// Simple health check handler reporting service readiness and current time.
async fn health_check() -> impl IntoResponse {
    (
        StatusCode::OK,
        Json(serde_json::json!({
            "status": "healthy",
            "service": "openalertd",
            "timestamp": Utc::now()
        })),
    )
}

/// Handles incoming HTTP POST requests containing generic JSON alert payloads.
async fn ingest_alert(
    State(engine): State<Arc<AlertEngine>>,
    Json(payload): Json<RestAlertRequest>,
) -> impl IntoResponse {
    let alert = Alert {
        alert_id: payload.alert_id.clone(),
        severity: payload.severity,
        summary: payload.summary,
        description: payload.description,
        source: AlertSource::Rest,
        sender: payload.sender,
        node: payload.node,
        starts_at: Utc::now(),
        destinations: payload.destinations,
    };

    let fingerprint = alert.fingerprint();
    let alert_id = alert.alert_id.clone();

    tokio::spawn(async move {
        if let Err(err) = engine.route_alert(alert).await {
            error!("Failed to route REST alert: {}", err);
        }
    });

    (
        StatusCode::ACCEPTED,
        Json(RestAlertResponse {
            status: "accepted".to_string(),
            alert_id,
            fingerprint,
            timestamp: Utc::now(),
        }),
    )
}

/// Handles incoming HTTP POST webhooks directly from Prometheus Alertmanager.
async fn ingest_prometheus_webhook(
    State(engine): State<Arc<AlertEngine>>,
    Json(payload): Json<PrometheusAlertmanagerPayload>,
) -> impl IntoResponse {
    let mut ingested_ids = Vec::new();

    for item in payload.alerts {
        if item.status.eq_ignore_ascii_case("resolved") {
            continue;
        }

        let alert = item.into_canonical_alert();
        ingested_ids.push(alert.alert_id.clone());

        let engine = engine.clone();
        tokio::spawn(async move {
            if let Err(err) = engine.route_alert(alert).await {
                error!("Failed to route Prometheus alert: {}", err);
            }
        });
    }

    info!(
        "📥 [Prometheus Webhook Ingress] Ingested {} firing alerts ({:?})",
        ingested_ids.len(),
        ingested_ids
    );

    (
        StatusCode::ACCEPTED,
        Json(PrometheusWebhookResponse {
            status: "accepted".to_string(),
            ingested_count: ingested_ids.len(),
            alert_ids: ingested_ids,
            timestamp: Utc::now(),
        }),
    )
}
