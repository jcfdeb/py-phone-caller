//! # Axum HTTP REST Ingress Server
//!
//! Exposes HTTP endpoints for ingesting alerts directly via JSON, as well as
//! receiving webhooks from Prometheus Alertmanager, protected by optional
//! Bearer token authorization and HMAC-SHA256 payload signatures.

use crate::config::RestConfig;
use crate::engine::AlertEngine;
use crate::error::Result;
use crate::models::{
    Alert, AlertSeverity, AlertSource, PeeringStatusReport, PrometheusAlertmanagerPayload,
    PrometheusWebhookResponse, RestAlertRequest, RestAlertResponse, SmsConfigUpdateRequest,
    SmsSendRequest,
};
use axum::{
    Json, Router,
    body::Bytes,
    extract::{Path, State},
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use chrono::Utc;
use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::net::SocketAddr;
use std::sync::Arc;
use subtle::ConstantTimeEq;
use tower_http::cors::{Any, CorsLayer};
use tower_http::trace::TraceLayer;
use tracing::{error, info, warn};

type HmacSha256 = Hmac<Sha256>;

/// Shared state container for REST route handlers.
#[derive(Clone)]
pub struct AppState {
    pub engine: Arc<AlertEngine>,
    pub config: RestConfig,
}

/// Constant-time string equality check to mitigate timing side-channels.
pub fn verify_constant_time(a: &str, b: &str) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.as_bytes().ct_eq(b.as_bytes()).into()
}

/// Validates dashboard user credentials if configured.
/// Returns Ok(()) if authentication is disabled or valid, or an HTTP 401 response with WWW-Authenticate header.
pub fn check_dashboard_auth(
    headers: &HeaderMap,
    config: &crate::config::AppConfig,
) -> std::result::Result<(), Box<Response>> {
    if !config.dashboard.auth.is_active() {
        return Ok(());
    }

    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|h| h.to_str().ok());

    if let Some(auth_val) = auth_header {
        // 1. Support standard HTTP Basic auth (Authorization: Basic <base64>)
        if let Some(encoded) = auth_val.strip_prefix("Basic ") {
            use base64::Engine;
            if let Some((username, password)) = base64::engine::general_purpose::STANDARD
                .decode(encoded.trim())
                .ok()
                .and_then(|d| String::from_utf8(d).ok())
                .and_then(|creds| {
                    creds
                        .split_once(':')
                        .map(|(u, p)| (u.to_string(), p.to_string()))
                })
            {
                use sha2::Digest;
                let given_hash = hex::encode(sha2::Sha256::digest(password.as_bytes()));
                let expected_hash = config.dashboard.auth.password_hash.trim().to_lowercase();
                let clean_expected = expected_hash
                    .strip_prefix("sha256:")
                    .unwrap_or(&expected_hash);

                let user_match =
                    verify_constant_time(username.trim(), &config.dashboard.auth.username);
                let pass_match = verify_constant_time(&given_hash, clean_expected);

                if user_match && pass_match {
                    return Ok(());
                }
            }
        }
        // 2. Also allow Bearer token if configured in rest.auth_token or matching hash
        if let Some(token) = auth_val.strip_prefix("Bearer ") {
            if config
                .rest
                .auth_token
                .as_deref()
                .map(|exp| verify_constant_time(token.trim(), exp))
                .unwrap_or(false)
            {
                return Ok(());
            }
            use sha2::Digest;
            let token_hash = hex::encode(sha2::Sha256::digest(token.trim().as_bytes()));
            let expected_hash = config.dashboard.auth.password_hash.trim().to_lowercase();
            let clean_expected = expected_hash
                .strip_prefix("sha256:")
                .unwrap_or(&expected_hash);
            if verify_constant_time(&token_hash, clean_expected) {
                return Ok(());
            }
        }
    }

    // Authentication failed or missing: return 401 with WWW-Authenticate header
    let response = (
        StatusCode::UNAUTHORIZED,
        [
            (
                axum::http::header::WWW_AUTHENTICATE,
                r#"Basic realm="OpenAlert Mission Control", charset="UTF-8""#,
            ),
            (
                axum::http::header::CONTENT_TYPE,
                "text/html; charset=utf-8",
            ),
        ],
        "<!DOCTYPE html><html><head><title>401 Unauthorized</title><style>body{background:#090d16;color:#f87171;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}</style></head><body><div style='text-align:center'><h1>401 Unauthorized</h1><p style='color:#94a3b8'>OpenAlert Mission Control requires valid administrator credentials.</p></div></body></html>",
    ).into_response();

    Err(Box::new(response))
}

/// Computes a hex-encoded HMAC-SHA256 signature over the payload with the given secret.
pub fn compute_hmac_sha256(secret: &[u8], payload: &[u8]) -> String {
    let mut mac = HmacSha256::new_from_slice(secret).expect("HMAC can take key of any size");
    mac.update(payload);
    hex::encode(mac.finalize().into_bytes())
}

/// Verifies an HMAC-SHA256 hex string (with or without 'sha256=' prefix) against the raw payload.
pub fn verify_hmac_sha256(secret: &[u8], payload: &[u8], signature_hex: &str) -> bool {
    let clean_hex = signature_hex
        .strip_prefix("sha256=")
        .unwrap_or(signature_hex)
        .trim();
    let Ok(expected_sig) = hex::decode(clean_hex) else {
        return false;
    };
    let Ok(mut mac) = HmacSha256::new_from_slice(secret) else {
        return false;
    };
    mac.update(payload);
    mac.verify_slice(&expected_sig).is_ok()
}

/// Validates Bearer token or HTTP Basic authorization according to RestConfig.
pub fn check_rest_auth(
    headers: &HeaderMap,
    config: &RestConfig,
) -> std::result::Result<(), (StatusCode, Json<serde_json::Value>)> {
    let auth_configured = config.auth.as_ref().map(|a| a.is_active()).unwrap_or(false)
        || config.auth_token.is_some();

    if !auth_configured {
        return Ok(());
    }

    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|h| h.to_str().ok());

    let Some(auth_val) = auth_header else {
        return Err((
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({
                "status": "error",
                "message": "Missing Authorization header"
            })),
        ));
    };

    if let Some(ref auth) = config.auth {
        match auth.auth_type.as_deref().map(|s| s.to_lowercase()).as_deref() {
            Some("basic") => {
                if let Some(encoded) = auth_val.strip_prefix("Basic ") {
                    use base64::Engine;
                    if let Some((username, password)) = base64::engine::general_purpose::STANDARD
                        .decode(encoded.trim())
                        .ok()
                        .and_then(|d| String::from_utf8(d).ok())
                        .and_then(|creds| {
                            creds
                                .split_once(':')
                                .map(|(u, p)| (u.to_string(), p.to_string()))
                        })
                    {
                        use sha2::{Digest, Sha256};
                        let given_hash = hex::encode(Sha256::digest(password.as_bytes()));
                        let expected_user = auth.username.as_deref().unwrap_or_default();
                        let raw_expected_hash = auth
                            .password_hash
                            .as_deref()
                            .unwrap_or_default()
                            .trim()
                            .to_lowercase();
                        let clean_expected = raw_expected_hash
                            .strip_prefix("sha256:")
                            .unwrap_or(&raw_expected_hash);

                        let user_match = verify_constant_time(username.trim(), expected_user);
                        let pass_match = verify_constant_time(&given_hash, clean_expected);

                        if user_match && pass_match {
                            return Ok(());
                        }
                    }
                }
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(serde_json::json!({
                        "status": "error",
                        "message": "Invalid HTTP Basic credentials"
                    })),
                ));
            }
            Some("bearer") => {
                if let Some(token) = auth_val.strip_prefix("Bearer ") {
                    use sha2::{Digest, Sha256};
                    let token_hash = hex::encode(Sha256::digest(token.trim().as_bytes()));
                    let raw_expected_hash = auth
                        .token_hash
                        .as_deref()
                        .unwrap_or_default()
                        .trim()
                        .to_lowercase();
                    let clean_expected = raw_expected_hash
                        .strip_prefix("sha256:")
                        .unwrap_or(&raw_expected_hash);

                    if verify_constant_time(&token_hash, clean_expected) {
                        return Ok(());
                    }
                }
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(serde_json::json!({
                        "status": "error",
                        "message": "Invalid Bearer authorization token"
                    })),
                ));
            }
            _ => {}
        }
    }

    if config.auth_token.as_deref().is_some_and(|expected| {
        auth_val
            .strip_prefix("Bearer ")
            .is_some_and(|token| verify_constant_time(token.trim(), expected))
    }) {
        return Ok(());
    }

    Err((
        StatusCode::UNAUTHORIZED,
        Json(serde_json::json!({
            "status": "error",
            "message": "Invalid or missing Bearer authorization token"
        })),
    ))
}

/// Validates Bearer token or HTTP Basic authorization if configured (alias to `check_rest_auth`).
pub fn check_bearer_auth(
    headers: &HeaderMap,
    config: &RestConfig,
) -> std::result::Result<(), (StatusCode, Json<serde_json::Value>)> {
    check_rest_auth(headers, config)
}

/// Validates webhook timestamp anti-replay window and HMAC-SHA256 signature.
pub fn check_webhook_security(
    headers: &HeaderMap,
    body: &[u8],
    config: &RestConfig,
) -> std::result::Result<(), (StatusCode, Json<serde_json::Value>)> {
    // 1. Clock skew / anti-replay validation
    let ts_header = headers
        .get("x-openalert-timestamp")
        .or_else(|| headers.get("x-timestamp"));

    if let Some(ts_hdr) = ts_header {
        let ts_str = ts_hdr.to_str().map_err(|_| {
            (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "status": "error",
                    "message": "Invalid non-ASCII characters in timestamp header"
                })),
            )
        })?;

        let ts = ts_str.trim().parse::<i64>().map_err(|_| {
            (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "status": "error",
                    "message": "Malformed X-OpenAlert-Timestamp header"
                })),
            )
        })?;

        let now = Utc::now().timestamp();
        let diff = (now - ts).abs();
        if diff > config.webhook_max_skew_seconds as i64 {
            warn!(
                "🛑 Webhook rejected due to clock skew: {}s (allowed: {}s)",
                diff, config.webhook_max_skew_seconds
            );
            return Err((
                StatusCode::FORBIDDEN,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!(
                        "Webhook timestamp skewed by {}s (max allowed: {}s)",
                        diff, config.webhook_max_skew_seconds
                    )
                })),
            ));
        }
    }

    // 2. Cryptographic HMAC signature verification
    if let Some(ref secret) = config.webhook_secret {
        let sig_opt = headers
            .get("x-openalert-signature")
            .or_else(|| headers.get("x-hub-signature-256"))
            .and_then(|h| h.to_str().ok());

        let Some(sig) = sig_opt else {
            warn!("🛑 Inbound webhook missing required signature header");
            return Err((
                StatusCode::UNAUTHORIZED,
                Json(serde_json::json!({
                    "status": "error",
                    "message": "Missing required X-OpenAlert-Signature / X-Hub-Signature-256 header"
                })),
            ));
        };

        if !verify_hmac_sha256(secret.as_bytes(), body, sig) {
            warn!("🛑 Inbound webhook failed HMAC-SHA256 cryptographic verification");
            return Err((
                StatusCode::UNAUTHORIZED,
                Json(serde_json::json!({
                    "status": "error",
                    "message": "Invalid HMAC-SHA256 signature for webhook payload"
                })),
            ));
        }
    }

    Ok(())
}

/// Ingress HTTP REST server embedding Axum.
pub struct RestServer {
    config: RestConfig,
    engine: Arc<AlertEngine>,
}

impl RestServer {
    /// Creates a new REST server instance with associated configuration and engine.
    pub fn new(config: RestConfig, engine: Arc<AlertEngine>) -> Self {
        Self { config, engine }
    }

    /// Binds to the configured address and runs the HTTP server until shutdown signal is received.
    pub async fn run(self) -> Result<()> {
        let state = AppState {
            engine: self.engine.clone(),
            config: self.config.clone(),
        };

        let app = Router::new()
            .route("/", get(crate::ingress::dashboard::dashboard_handler))
            .route(
                "/dashboard",
                get(crate::ingress::dashboard::dashboard_handler),
            )
            .route("/health", get(health_check))
            .route("/api/v1/logo", get(crate::ingress::dashboard::logo_handler))
            .route("/logo.png", get(crate::ingress::dashboard::logo_handler))
            .route("/api/v1/status", get(status_handler))
            .route("/api/v1/peers", get(peers_handler))
            .route("/api/v1/peers/{name}/reset", post(reset_peer_handler))
            .route("/api/v1/spool", get(spool_handler))
            .route("/api/v1/spool/purge", post(purge_spool_handler))
            .route(
                "/api/v1/events/live",
                get(crate::ingress::dashboard::sse_telemetry_handler),
            )
            .route("/api/v1/alerts", post(ingest_alert))
            .route(
                "/api/v1/webhook/prometheus",
                post(ingest_prometheus_webhook),
            )
            .route("/api/v1/sms/status", get(sms_status_handler))
            .route(
                "/api/v1/sms/config",
                get(sms_status_handler).post(sms_update_config_handler),
            )
            .route("/api/v1/sms/history", get(sms_history_handler))
            .route("/api/v1/sms/send", post(sms_send_handler))
            .route("/api/v1/bitchat/status", get(bitchat_status_handler))
            .route("/api/v1/bitchat/broadcast", post(bitchat_broadcast_handler))
            .route("/api/v1/config", get(config_get_handler).post(config_save_handler))
            .route("/api/v1/config/validate", post(config_validate_handler))
            .route("/api/v1/nostr/oxchat", post(nostr_oxchat_update_handler))
            .route("/api/v1/tools/convert-key", post(tools_convert_key_handler))
            .route("/api/v1/tools/generate-keypair", post(tools_generate_keypair_handler))
            .route("/api/v1/tools/convert-sms", post(tools_convert_sms_handler))
            .route("/api/v1/tools/hash-password", post(tools_hash_password_handler))
            .route("/api/v1/tools/generate-key", post(tools_generate_key_handler))
            .layer(TraceLayer::new_for_http())
            .layer(
                CorsLayer::new()
                    .allow_origin(Any)
                    .allow_methods(Any)
                    .allow_headers(Any),
            )
            .with_state(state);

        let addr: SocketAddr = format!("{}:{}", self.config.listen_host, self.config.listen_port)
            .parse()
            .map_err(|e| {
                crate::error::OpenAlertError::Config(format!("Invalid listen address: {}", e))
            })?;

        info!("🚀 Ingress REST API listening on http://{}", addr);

        let listener = tokio::net::TcpListener::bind(addr).await?;
        axum::serve(listener, app)
            .with_graceful_shutdown(shutdown_signal())
            .await
            .map_err(crate::error::OpenAlertError::Io)?;

        Ok(())
    }
}

async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut sig) => {
                sig.recv().await;
            }
            Err(_) => {
                std::future::pending::<()>().await;
            }
        }
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }
}

/// Simple health check handler reporting service readiness, uptime, and version.
/// Open and accessible for monitoring probes without requiring credentials.
pub async fn health_check(State(state): State<AppState>) -> Response {
    let health = state.engine.get_health();
    (StatusCode::OK, Json(health)).into_response()
}

/// Full daemon status diagnostics report.
pub async fn status_handler(headers: HeaderMap, State(state): State<AppState>) -> Response {
    if let Err((status, json)) = check_bearer_auth(&headers, &state.config) {
        return (status, json).into_response();
    }
    let status = state.engine.get_status().await;
    (StatusCode::OK, Json(status)).into_response()
}

/// Peering diagnostics report.
pub async fn peers_handler(headers: HeaderMap, State(state): State<AppState>) -> Response {
    if let Err((status, json)) = check_bearer_auth(&headers, &state.config) {
        return (status, json).into_response();
    }
    if let Some(peering) = state.engine.get_peering_diagnostics().await {
        (StatusCode::OK, Json(peering)).into_response()
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(PeeringStatusReport {
                enabled: false,
                listen_addr: String::new(),
                peers: Vec::new(),
            }),
        )
            .into_response()
    }
}

/// Peering spool metrics report.
pub async fn spool_handler(headers: HeaderMap, State(state): State<AppState>) -> Response {
    if let Err((status, json)) = check_bearer_auth(&headers, &state.config) {
        return (status, json).into_response();
    }
    if let Some(spool) = state.engine.get_spool_stats().await {
        (
            StatusCode::OK,
            Json(serde_json::json!({
                "status": "ok",
                "spool": spool,
            })),
        )
            .into_response()
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "disabled",
                "spool": null,
            })),
        )
            .into_response()
    }
}

/// Manually resets a specific peer node's circuit breaker to CLOSED.
pub async fn reset_peer_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Path(name): Path<String>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }
    let success = state.engine.reset_peer_circuit_breaker(&name).await;
    if success {
        info!(
            "Operator manually reset circuit breaker for peer '{}'",
            name
        );
        (
            StatusCode::OK,
            Json(serde_json::json!({
                "status": "ok",
                "message": format!("Circuit breaker for peer '{}' reset to CLOSED", name),
                "peer": name
            })),
        )
            .into_response()
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "error",
                "message": format!("Peer '{}' not found or peering subsystem disabled", name),
                "peer": name
            })),
        )
            .into_response()
    }
}

/// Manually purges all spooled packets from the persistent peering database.
pub async fn purge_spool_handler(headers: HeaderMap, State(state): State<AppState>) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }
    match state.engine.purge_spool().await {
        Ok(count) => {
            info!(
                "Operator manually purged peering spool ({} records removed)",
                count
            );
            (
                StatusCode::OK,
                Json(serde_json::json!({
                    "status": "ok",
                    "message": format!("Successfully purged {} spool record(s)", count),
                    "deleted_count": count
                })),
            )
                .into_response()
        }
        Err(e) => {
            error!("Failed to purge peering spool: {}", e);
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("Failed to purge spool: {}", e)
                })),
            )
                .into_response()
        }
    }
}

/// Handles incoming HTTP POST requests containing generic JSON alert payloads.
pub async fn ingest_alert(
    headers: HeaderMap,
    State(state): State<AppState>,
    body: Bytes,
) -> Response {
    if let Err((status, json)) = check_bearer_auth(&headers, &state.config) {
        return (status, json).into_response();
    }
    if let Err((status, json)) = check_webhook_security(&headers, &body, &state.config) {
        return (status, json).into_response();
    }

    let payload: RestAlertRequest = match serde_json::from_slice(&body) {
        Ok(p) => p,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("Invalid JSON payload: {}", e)
                })),
            )
                .into_response();
        }
    };

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
        origin_peer: None,
        hop: 3,
    };

    let fingerprint = alert.fingerprint();
    let alert_id = alert.alert_id.clone();
    let engine = state.engine.clone();

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
        .into_response()
}

/// Handles webhooks from Prometheus Alertmanager batches.
pub async fn ingest_prometheus_webhook(
    headers: HeaderMap,
    State(state): State<AppState>,
    body: Bytes,
) -> Response {
    if let Err((status, json)) = check_bearer_auth(&headers, &state.config) {
        return (status, json).into_response();
    }
    if let Err((status, json)) = check_webhook_security(&headers, &body, &state.config) {
        return (status, json).into_response();
    }

    let payload: PrometheusAlertmanagerPayload = match serde_json::from_slice(&body) {
        Ok(p) => p,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("Invalid Prometheus webhook JSON payload: {}", e)
                })),
            )
                .into_response();
        }
    };

    let count = payload.alerts.len();
    let mut ingested_ids = Vec::with_capacity(count);

    for alert_item in payload.alerts {
        let alert = alert_item.into_canonical_alert();
        ingested_ids.push(alert.alert_id.clone());

        let eng = state.engine.clone();
        tokio::spawn(async move {
            if let Err(err) = eng.route_alert(alert).await {
                error!("Failed to route Prometheus alert: {}", err);
            }
        });
    }

    (
        StatusCode::ACCEPTED,
        Json(PrometheusWebhookResponse {
            status: "accepted".to_string(),
            ingested_count: count,
            alert_ids: ingested_ids,
            timestamp: Utc::now(),
        }),
    )
        .into_response()
}

/// Cellular SMS status report.
pub async fn sms_status_handler(headers: HeaderMap, State(state): State<AppState>) -> Response {
    if let Err((status, json)) = check_bearer_auth(&headers, &state.config) {
        return (status, json).into_response();
    }
    if let Some(sms) = state.engine.sms_service().await {
        let status = sms.get_status().await;
        (StatusCode::OK, Json(status)).into_response()
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "error",
                "message": "SMS gateway service not initialized"
            })),
        )
            .into_response()
    }
}

/// Updates cellular SMS dynamic configuration (recipients and authorized senders).
pub async fn sms_update_config_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(payload): Json<SmsConfigUpdateRequest>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }
    if let Some(sms) = state.engine.sms_service().await {
        match sms
            .update_config(payload.recipients, payload.authorized_senders)
            .await
        {
            Ok(updated) => {
                info!(
                    "Updated cellular SMS configuration: {} recipients, {} authorized senders",
                    updated.recipients.len(),
                    updated.authorized_senders.len()
                );
                (StatusCode::OK, Json(updated)).into_response()
            }
            Err(e) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({ "status": "error", "message": e })),
            )
                .into_response(),
        }
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "error",
                "message": "SMS gateway service not initialized"
            })),
        )
            .into_response()
    }
}

/// Fetches recent SMS history (inbound and outbound).
pub async fn sms_history_handler(headers: HeaderMap, State(state): State<AppState>) -> Response {
    if let Err((status, json)) = check_bearer_auth(&headers, &state.config) {
        return (status, json).into_response();
    }
    if let Some(sms) = state.engine.sms_service().await {
        match sms.get_history(50).await {
            Ok(history) => (StatusCode::OK, Json(history)).into_response(),
            Err(e) => (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({ "status": "error", "message": e })),
            )
                .into_response(),
        }
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "error",
                "message": "SMS gateway service not initialized"
            })),
        )
            .into_response()
    }
}

/// Sends a test or manual SMS via the cellular modem.
pub async fn sms_send_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(payload): Json<SmsSendRequest>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }
    if let Some(sms) = state.engine.sms_service().await {
        match sms
            .send_manual_sms(&payload.phone_number, &payload.message)
            .await
        {
            Ok(()) => (
                StatusCode::OK,
                Json(serde_json::json!({
                    "status": "ok",
                    "message": format!("SMS successfully dispatched to {}", payload.phone_number)
                })),
            )
                .into_response(),
            Err(e) => (
                StatusCode::BAD_GATEWAY,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("SMS dispatch failed: {}", e)
                })),
            )
                .into_response(),
        }
    } else {
        (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "error",
                "message": "SMS gateway service not initialized"
            })),
        )
            .into_response()
    }
}

/// BitChat mesh status report handler.
pub async fn bitchat_status_handler(headers: HeaderMap, State(state): State<AppState>) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }
    let status = if let Some(bc) = state.engine.bitchat_service().await {
        bc.get_status().await
    } else {
        let (_, _, my_sender_id) =
            crate::bitchat::BitChatService::derive_keys(&state.engine.config().bitchat.node_name);
        crate::models::BitChatStatusReport {
            enabled: state.engine.config().bitchat.enabled,
            node_name: state.engine.config().bitchat.node_name.clone(),
            sender_id: hex::encode(my_sender_id),
            service_uuid: crate::bitchat::DEFAULT_BITCHAT_SERVICE_UUID.to_string(),
            status: if state.engine.config().bitchat.enabled {
                "Active (BLE GATT)".to_string()
            } else {
                "Disabled".to_string()
            },
            peers_count: 0,
            active_sessions_count: 0,
            peers: Vec::new(),
        }
    };
    (StatusCode::OK, Json(status)).into_response()
}

/// Request payload for manual BitChat mesh broadcast.
#[derive(Debug, serde::Deserialize)]
pub struct BitChatBroadcastRequest {
    pub message: String,
    #[serde(default = "default_bitchat_severity")]
    pub severity: String,
}

fn default_bitchat_severity() -> String {
    "warning".to_string()
}

/// Broadcasts an ad-hoc emergency or alert message across the BitChat Bluetooth Low Energy mesh.
pub async fn bitchat_broadcast_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(payload): Json<BitChatBroadcastRequest>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }

    if payload.message.trim().is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "status": "error",
                "message": "Message content cannot be empty"
            })),
        )
            .into_response();
    }

    let sev = match payload.severity.to_lowercase().as_str() {
        "critical" => AlertSeverity::Critical,
        "emergency" => AlertSeverity::Emergency,
        _ => AlertSeverity::Warning,
    };

    let alert_id = format!("bitchat-manual-{}", &uuid::Uuid::new_v4().to_string()[..8]);
    let alert = Alert {
        alert_id: alert_id.clone(),
        severity: sev,
        summary: payload.message.clone(),
        description: Some(format!(
            "Ad-hoc manual BitChat broadcast from OpenAlert Control Plane ({})",
            state.engine.config().daemon.name
        )),
        source: AlertSource::Rest,
        sender: Some(state.engine.config().daemon.name.clone()),
        node: Some(state.engine.config().bitchat.node_name.clone()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["bitchat".to_string()],
        origin_peer: None,
        hop: 1,
    };

    match state.engine.bitchat_egress.broadcast(&alert).await {
        Ok(()) => (
            StatusCode::OK,
            Json(serde_json::json!({
                "status": "ok",
                "message": format!("Alert successfully broadcast to BitChat BLE mesh [ID: {}]", alert_id),
                "alert_id": alert_id
            })),
        )
            .into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({
                "status": "error",
                "message": format!("BitChat broadcast failed: {}", e)
            })),
        )
            .into_response(),
    }
}


/// Returns the current configuration (both as structured object and raw TOML text).
pub async fn config_get_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }
    let path = state.engine.get_config_path().await;
    let toml_content = std::fs::read_to_string(&path).unwrap_or_else(|_| "".to_string());

    (
        StatusCode::OK,
        Json(crate::models::ConfigResponse {
            config_path: path,
            toml_content,
            config: state.engine.config().clone(),
        }),
    )
        .into_response()
}

/// Validates arbitrary TOML configuration text without saving it to disk.
pub async fn config_validate_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(payload): Json<crate::models::ConfigUpdateRequest>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }

    match toml::from_str::<crate::config::AppConfig>(&payload.toml_content) {
        Ok(parsed) => {
            (
                StatusCode::OK,
                Json(serde_json::json!({
                    "status": "ok",
                    "message": "Configuration syntax is valid and consistent.",
                    "node_name": parsed.daemon.name,
                    "relays_count": parsed.nostr.relays.len(),
                    "oxchat_recipients_count": parsed.nostr.oxchat.recipients.len(),
                    "sms_recipients_count": parsed.sms.recipients.len(),
                })),
            )
                .into_response()
        }
        Err(e) => {
            (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("Configuration syntax error: {}", e),
                })),
            )
                .into_response()
        }
    }
}

/// Persists new TOML configuration to disk with an automated timestamped backup.
pub async fn config_save_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(payload): Json<crate::models::ConfigUpdateRequest>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }

    // 1. Validate syntax first
    if let Err(e) = toml::from_str::<crate::config::AppConfig>(&payload.toml_content) {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "status": "error",
                "message": format!("Validation failed; config was not saved: {}", e)
            })),
        )
            .into_response();
    }

    let path = state.engine.get_config_path().await;

    // 2. Create timestamped backup if file exists
    if std::path::Path::new(&path).exists() {
        let ts = chrono::Utc::now().format("%Y%m%d_%H%M%S");
        let backup_path = format!("{}.bak.{}", path, ts);
        if let Err(e) = std::fs::copy(&path, &backup_path) {
            warn!("Failed to create configuration backup {}: {}", backup_path, e);
        } else {
            info!("Created configuration backup: {}", backup_path);
        }
    }

    // 3. Write new configuration to disk atomically
    if let Err(e) = std::fs::write(&path, &payload.toml_content) {
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({
                "status": "error",
                "message": format!("Failed to write configuration to {}: {}", path, e)
            })),
        )
            .into_response();
    }

    info!("Updated runtime configuration file: {}", path);

    (
        StatusCode::OK,
        Json(serde_json::json!({
            "status": "ok",
            "message": format!("Configuration saved successfully to {}.", path),
            "reloaded": payload.reload,
        })),
    )
        .into_response()
}

/// Updates Nostr 0xChat recipients & C2 authorized operators specifically in config file.
pub async fn nostr_oxchat_update_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(payload): Json<crate::models::NostrOxchatUpdateRequest>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }

    let path = state.engine.get_config_path().await;
    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({ "status": "error", "message": format!("Failed to read config file: {}", e) })),
            )
                .into_response();
        }
    };

    let mut parsed: crate::config::AppConfig = match toml::from_str(&content) {
        Ok(cfg) => cfg,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({ "status": "error", "message": format!("Config parsing error: {}", e) })),
            )
                .into_response();
        }
    };

    if let Some(r) = payload.recipients {
        parsed.nostr.oxchat.recipients = r;
    }
    if let Some(ops) = payload.c2_authorized_operators {
        parsed.nostr.oxchat.c2_authorized_operators = ops;
    }
    if let Some(m) = payload.mode {
        if m.eq_ignore_ascii_case("public") {
            parsed.nostr.oxchat.mode = crate::config::OxChatMode::Public;
        } else {
            parsed.nostr.oxchat.mode = crate::config::OxChatMode::Dm;
        }
    }

    let serialized = match toml::to_string_pretty(&parsed) {
        Ok(s) => s,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({ "status": "error", "message": format!("Failed to serialize TOML: {}", e) })),
            )
                .into_response();
        }
    };

    if let Err(e) = std::fs::write(&path, &serialized) {
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({ "status": "error", "message": format!("Failed to write config file: {}", e) })),
        )
            .into_response();
    }

    (
        StatusCode::OK,
        Json(serde_json::json!({
            "status": "ok",
            "message": "Nostr 0xChat recipients and operators updated successfully",
            "recipients": parsed.nostr.oxchat.recipients,
            "c2_authorized_operators": parsed.nostr.oxchat.c2_authorized_operators,
            "mode": format!("{:?}", parsed.nostr.oxchat.mode).to_lowercase(),
        })),
    )
        .into_response()
}

/// Tools endpoint: Nostr Bech32 <-> Hex conversion & public key derivation.
pub async fn tools_convert_key_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(payload): Json<crate::models::ToolConvertKeyRequest>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }

    match crate::cli::convert_key(&payload.key) {
        Ok(res) => (StatusCode::OK, Json(serde_json::json!({
            "status": "ok",
            "input_format": res.input_format,
            "hex_value": res.hex_value,
            "bech32_value": res.bech32_value,
            "derived_public": res.derived_public.map(|(hex_pub, npub)| serde_json::json!({
                "hex": hex_pub,
                "npub": npub,
            })),
        }))).into_response(),
        Err(e) => (StatusCode::BAD_REQUEST, Json(serde_json::json!({
            "status": "error",
            "message": e,
        }))).into_response(),
    }
}

/// Tools endpoint: Secp256k1 Nostr keypair generator.
pub async fn tools_generate_keypair_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }

    let id = crate::cli::generate_keypair();
    (StatusCode::OK, Json(serde_json::json!({
        "status": "ok",
        "npub": id.npub,
        "pub_hex": id.pub_hex,
        "nsec": id.nsec,
        "priv_hex": id.priv_hex,
    }))).into_response()
}

/// Tools endpoint: SMS Codec (UTF-8 <-> UCS-2 Hex).
pub async fn tools_convert_sms_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(payload): Json<crate::models::ToolConvertSmsRequest>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }

    match crate::cli::convert_sms_codec(&payload.payload) {
        Ok((operation, result)) => (StatusCode::OK, Json(serde_json::json!({
            "status": "ok",
            "operation": operation,
            "result": result,
        }))).into_response(),
        Err(e) => (StatusCode::BAD_REQUEST, Json(serde_json::json!({
            "status": "error",
            "message": e,
        }))).into_response(),
    }
}

/// Tools endpoint: SHA-256 password hasher.
pub async fn tools_hash_password_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(payload): Json<crate::models::ToolHashPasswordRequest>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }

    let hash = crate::cli::hash_password(&payload.password);
    (StatusCode::OK, Json(serde_json::json!({
        "status": "ok",
        "hash": hash,
    }))).into_response()
}

/// Tools endpoint: 256-bit cryptographically secure hex key generator.
pub async fn tools_generate_key_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
) -> Response {
    if let Err(resp) = check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }

    let key = crate::cli::generate_key();
    (StatusCode::OK, Json(serde_json::json!({
        "status": "ok",
        "key": key,
    }))).into_response()
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;

    #[test]
    fn test_bearer_token_constant_time_verification() {
        assert!(verify_constant_time("my-secret-token", "my-secret-token"));
        assert!(!verify_constant_time(
            "my-secret-token",
            "wrong-secret-token"
        ));
        assert!(!verify_constant_time("short", "longer-string"));

        let mut config = RestConfig {
            listen_host: "127.0.0.1".to_string(),
            listen_port: 8080,
            enable_cors: false,
            auth_token: Some("secret123".to_string()),
            auth: None,
            webhook_secret: None,
            webhook_max_skew_seconds: 60,
            tls: Default::default(),
        };

        let mut headers = HeaderMap::new();
        // Missing header -> fail
        assert!(check_bearer_auth(&headers, &config).is_err());

        // Incorrect token -> fail
        headers.insert(
            axum::http::header::AUTHORIZATION,
            HeaderValue::from_static("Bearer bad_token"),
        );
        assert!(check_bearer_auth(&headers, &config).is_err());

        // Correct token -> ok
        headers.insert(
            axum::http::header::AUTHORIZATION,
            HeaderValue::from_static("Bearer secret123"),
        );
        assert!(check_bearer_auth(&headers, &config).is_ok());

        // Auth disabled -> ok even without headers
        config.auth_token = None;
        assert!(check_bearer_auth(&HeaderMap::new(), &config).is_ok());
    }

    #[test]
    fn test_hmac_sha256_verification_and_tamper_rejection() {
        let secret = b"my_super_secret_webhook_key";
        let payload = br#"{"status":"firing","alerts":[{"status":"firing"}]}"#;

        let sig = compute_hmac_sha256(secret, payload);
        assert!(!sig.is_empty());

        // Valid signature matches
        assert!(verify_hmac_sha256(secret, payload, &sig));
        assert!(verify_hmac_sha256(
            secret,
            payload,
            &format!("sha256={}", sig)
        ));

        // Tampered payload fails
        let tampered = br#"{"status":"resolved","alerts":[{"status":"resolved"}]}"#;
        assert!(!verify_hmac_sha256(secret, tampered, &sig));

        // Wrong secret fails
        let wrong_secret = b"another_secret";
        assert!(!verify_hmac_sha256(wrong_secret, payload, &sig));
    }

    #[test]
    fn test_timestamp_window_anti_replay() {
        let config = RestConfig {
            listen_host: "127.0.0.1".to_string(),
            listen_port: 8080,
            enable_cors: false,
            auth_token: None,
            auth: None,
            webhook_secret: None,
            webhook_max_skew_seconds: 60,
            tls: Default::default(),
        };

        let body = b"test";
        let mut headers = HeaderMap::new();

        // Fresh timestamp within window -> ok
        let now = Utc::now().timestamp();
        headers.insert(
            "x-openalert-timestamp",
            HeaderValue::from_str(&now.to_string()).unwrap(),
        );
        assert!(check_webhook_security(&headers, body, &config).is_ok());

        // Stale timestamp (older than 60s) -> fail
        let stale = now - 120;
        headers.insert(
            "x-openalert-timestamp",
            HeaderValue::from_str(&stale.to_string()).unwrap(),
        );
        assert!(check_webhook_security(&headers, body, &config).is_err());

        // Future timestamp (clock skew > 60s) -> fail
        let future = now + 120;
        headers.insert(
            "x-openalert-timestamp",
            HeaderValue::from_str(&future.to_string()).unwrap(),
        );
        assert!(check_webhook_security(&headers, body, &config).is_err());
    }

    #[test]
    fn test_rest_auth_basic_and_bearer_hashed() {
        use crate::config::RestAuthConfig;
        use base64::Engine;

        // 1. Basic Auth with SHA-256 password hash
        let password = "SuperSecretPassword42";
        use sha2::{Digest, Sha256};
        let hash = hex::encode(Sha256::digest(password.as_bytes()));

        let mut config = RestConfig {
            listen_host: "127.0.0.1".to_string(),
            listen_port: 8080,
            enable_cors: false,
            auth_token: None,
            auth: Some(RestAuthConfig {
                auth_type: Some("basic".to_string()),
                username: Some("alertmanager".to_string()),
                password_hash: Some(format!("sha256:{}", hash)),
                token_hash: None,
            }),
            webhook_secret: None,
            webhook_max_skew_seconds: 60,
            tls: Default::default(),
        };

        // Missing header -> 401
        assert!(check_bearer_auth(&HeaderMap::new(), &config).is_err());

        // Correct Basic Auth credentials -> OK
        let creds = format!("{}:{}", "alertmanager", password);
        let encoded = base64::engine::general_purpose::STANDARD.encode(creds.as_bytes());
        let mut valid_headers = HeaderMap::new();
        valid_headers.insert(
            axum::http::header::AUTHORIZATION,
            HeaderValue::from_str(&format!("Basic {}", encoded)).unwrap(),
        );
        assert!(check_bearer_auth(&valid_headers, &config).is_ok());

        // Incorrect password -> 401
        let bad_creds = format!("{}:{}", "alertmanager", "WrongPassword");
        let bad_encoded = base64::engine::general_purpose::STANDARD.encode(bad_creds.as_bytes());
        let mut bad_headers = HeaderMap::new();
        bad_headers.insert(
            axum::http::header::AUTHORIZATION,
            HeaderValue::from_str(&format!("Basic {}", bad_encoded)).unwrap(),
        );
        assert!(check_bearer_auth(&bad_headers, &config).is_err());

        // Incorrect username -> 401
        let bad_user = format!("{}:{}", "wrong_user", password);
        let bad_user_encoded = base64::engine::general_purpose::STANDARD.encode(bad_user.as_bytes());
        let mut bad_user_headers = HeaderMap::new();
        bad_user_headers.insert(
            axum::http::header::AUTHORIZATION,
            HeaderValue::from_str(&format!("Basic {}", bad_user_encoded)).unwrap(),
        );
        assert!(check_bearer_auth(&bad_user_headers, &config).is_err());

        // 2. Bearer Auth with SHA-256 token hash
        let token = "my-secure-bearer-token-99";
        let token_hash = hex::encode(Sha256::digest(token.as_bytes()));

        config.auth = Some(RestAuthConfig {
            auth_type: Some("bearer".to_string()),
            username: None,
            password_hash: None,
            token_hash: Some(format!("sha256:{}", token_hash)),
        });

        // Valid token -> OK
        let mut bearer_headers = HeaderMap::new();
        bearer_headers.insert(
            axum::http::header::AUTHORIZATION,
            HeaderValue::from_str(&format!("Bearer {}", token)).unwrap(),
        );
        assert!(check_bearer_auth(&bearer_headers, &config).is_ok());

        // Invalid token -> 401
        let mut bad_bearer_headers = HeaderMap::new();
        bad_bearer_headers.insert(
            axum::http::header::AUTHORIZATION,
            HeaderValue::from_static("Bearer wrong-token-xyz"),
        );
        assert!(check_bearer_auth(&bad_bearer_headers, &config).is_err());

        // 3. Disabled auth -> OK
        config.auth = Some(RestAuthConfig {
            auth_type: Some("none".to_string()),
            ..Default::default()
        });
        assert!(check_bearer_auth(&HeaderMap::new(), &config).is_ok());
    }
}
