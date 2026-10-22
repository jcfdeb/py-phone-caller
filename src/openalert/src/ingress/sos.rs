//! # Simplified Emergency SOS Web Portal & Offline CAPTCHA Ingress
//!
//! Provides a dedicated, configurable emergency web interface (default `/sos`) separate from
//! the administrative NOC dashboard (`/dashboard`). Designed for field and Wi-Fi Access Point
//! deployments where bystanders or operators without BitChat/0xChat can trigger emergency alerts
//! from any mobile browser, protected by an offline SVG visual CAPTCHA, rate-limiting cooldown,
//! optional PIN-protected Nostr/0xChat encrypted DM delivery, and optional independent authentication.

use crate::config::AppConfig;
use crate::ingress::rest::{AppState, compute_hmac_sha256, verify_constant_time};
use crate::models::{Alert, AlertSeverity, AlertSource};
use axum::{
    Json,
    extract::State,
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::VecDeque;
use std::sync::{Mutex, OnceLock};
use std::time::Instant;
use tracing::{info, warn};

/// Maximum number of consumed CAPTCHA nonces retained in memory to prevent replay attacks.
const MAX_USED_NONCES: usize = 1024;

/// Maximum validity window of a generated CAPTCHA token in seconds (10 minutes).
const CAPTCHA_TTL_SECS: i64 = 600;

/// Global ephemeral secret and anti-replay / cooldown state for the SOS subsystem.
struct SosSecurityState {
    secret: [u8; 32],
    used_nonces: Mutex<VecDeque<String>>,
    last_trigger: Mutex<Option<Instant>>,
}

static SOS_STATE: OnceLock<SosSecurityState> = OnceLock::new();

fn get_security_state() -> &'static SosSecurityState {
    SOS_STATE.get_or_init(|| {
        let mut hasher = Sha256::new();
        hasher.update(uuid::Uuid::new_v4().as_bytes());
        hasher.update(uuid::Uuid::new_v4().as_bytes());
        hasher.update(
            crate::time_sync::now_utc()
                .timestamp_nanos_opt()
                .unwrap_or(0)
                .to_le_bytes(),
        );
        let secret: [u8; 32] = hasher.finalize().into();
        SosSecurityState {
            secret,
            used_nonces: Mutex::new(VecDeque::with_capacity(MAX_USED_NONCES)),
            last_trigger: Mutex::new(None),
        }
    })
}

/// Generates an inline SVG QR code for a Nostr `npub1...` string so mobile users can scan it with 0xChat.
pub fn generate_qr_svg(data: &str) -> String {
    let clean = data.trim();
    if clean.is_empty() {
        return String::new();
    }
    if let Ok(code) = qrcode::QrCode::new(clean.as_bytes()) {
        code.render::<qrcode::render::svg::Color<'_>>()
            .min_dimensions(168, 168)
            .dark_color(qrcode::render::svg::Color("#090d16"))
            .light_color(qrcode::render::svg::Color("#ffffff"))
            .build()
    } else {
        String::new()
    }
}

/// Checks whether a Nostr PIN is configured on `[sos]`.
pub fn is_nostr_pin_active(config: &AppConfig) -> bool {
    config
        .sos
        .nostr_pin
        .as_deref()
        .map(|p| !p.trim().is_empty())
        .unwrap_or(false)
}

/// Verifies a user-supplied PIN against `[sos] nostr_pin` (supports plaintext or `sha256:<hex>`).
pub fn verify_nostr_pin(config: &AppConfig, given_pin: Option<&str>) -> bool {
    let Some(expected_raw) = config.sos.nostr_pin.as_deref() else {
        return true;
    };
    let expected = expected_raw.trim();
    if expected.is_empty() {
        return true;
    }

    let given = given_pin.unwrap_or("").trim();
    if given.is_empty() {
        return false;
    }

    if let Some(expected_hash) = expected.strip_prefix("sha256:") {
        let given_hash = hex::encode(Sha256::digest(given.as_bytes()));
        verify_constant_time(&given_hash, &expected_hash.trim().to_lowercase())
    } else if expected.len() == 64 && expected.chars().all(|c| c.is_ascii_hexdigit()) {
        let given_hash = hex::encode(Sha256::digest(given.as_bytes()));
        verify_constant_time(&given_hash, &expected.to_lowercase())
            || verify_constant_time(given, expected)
    } else {
        verify_constant_time(given, expected)
    }
}

/// Validates SOS portal credentials if `[sos.auth] enabled = true`.
pub fn check_sos_auth(
    headers: &HeaderMap,
    config: &AppConfig,
) -> std::result::Result<(), Box<Response>> {
    if !config.sos.auth.is_active() {
        return Ok(());
    }

    let auth_header = headers
        .get(axum::http::header::AUTHORIZATION)
        .and_then(|h| h.to_str().ok());

    if let Some(auth_val) = auth_header {
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
                let given_hash = hex::encode(Sha256::digest(password.as_bytes()));
                let expected_hash = config.sos.auth.password_hash.trim().to_lowercase();
                let clean_expected = expected_hash
                    .strip_prefix("sha256:")
                    .unwrap_or(&expected_hash);

                let user_match = verify_constant_time(username.trim(), &config.sos.auth.username);
                let pass_match = verify_constant_time(&given_hash, clean_expected);

                if user_match && pass_match {
                    return Ok(());
                }
            }
        }

        if let Some(token) = auth_val.strip_prefix("Bearer ") {
            let token_hash = hex::encode(Sha256::digest(token.trim().as_bytes()));
            let expected_hash = config.sos.auth.password_hash.trim().to_lowercase();
            let clean_expected = expected_hash
                .strip_prefix("sha256:")
                .unwrap_or(&expected_hash);
            if verify_constant_time(&token_hash, clean_expected) {
                return Ok(());
            }
        }
    }

    let response = (
        StatusCode::UNAUTHORIZED,
        [
            (
                axum::http::header::WWW_AUTHENTICATE,
                r#"Basic realm="OpenAlert Emergency SOS", charset="UTF-8""#,
            ),
            (
                axum::http::header::CONTENT_TYPE,
                "text/html; charset=utf-8",
            ),
        ],
        "<!DOCTYPE html><html><head><title>401 Unauthorized</title><style>body{background:#090d16;color:#f87171;font-family:sans-serif;display:flex;justify-content:center;align-items:center;height:100vh;margin:0;}</style></head><body><div style='text-align:center'><h1>401 Unauthorized</h1><p style='color:#94a3b8'>Valid credentials are required to access the OpenAlert SOS terminal.</p></div></body></html>",
    )
        .into_response();

    Err(Box::new(response))
}

/// Response returned when generating a new offline CAPTCHA challenge.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SosChallengeResponse {
    pub captcha_enabled: bool,
    pub token: String,
    pub svg: String,
}

/// Request payload to unlock PIN-protected Nostr identity & relay info on the SOS portal.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SosNostrInfoRequest {
    #[serde(default)]
    pub pin: Option<String>,
}

/// Request payload submitted by the simplified SOS form.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SosTriggerRequest {
    /// Emergency message text.
    pub message: String,
    /// Optional sender name, callsign, or phone number.
    #[serde(default)]
    pub sender: Option<String>,
    /// Optional emergency category tag (e.g., "MEDICAL", "FIRE", "RESCUE", "SOS").
    #[serde(default)]
    pub category: Option<String>,
    /// Signed CAPTCHA token obtained from `/api/v1/sos/challenge`.
    #[serde(default)]
    pub captcha_token: Option<String>,
    /// User's 4-digit answer to the visual CAPTCHA.
    #[serde(default)]
    pub captcha_answer: Option<String>,
    /// Optional recipient Nostr public key (`npub1...` or 64-char hex) for direct E2EE 0xChat delivery.
    #[serde(default)]
    pub recipient_npub: Option<String>,
    /// Optional Nostr PIN when `[sos] nostr_pin` is configured.
    #[serde(default)]
    pub nostr_pin: Option<String>,
}

/// Generates a 4-digit visual SVG challenge and a stateless HMAC-SHA256 verification token.
pub fn generate_challenge_pair() -> (String, String, String) {
    let sec = get_security_state();
    let raw_uuid = uuid::Uuid::new_v4();
    let bytes = raw_uuid.as_bytes();

    // Derive a 4-digit code (1000..=9999)
    let num = 1000 + (u16::from_le_bytes([bytes[0], bytes[1]]) % 9000);
    let code = format!("{:04}", num);
    let nonce = hex::encode(&bytes[2..10]);
    let ts = crate::time_sync::now_utc_secs();

    let payload = format!("{}:{}:{}", ts, nonce, code);
    let sig = compute_hmac_sha256(&sec.secret, payload.as_bytes());
    let token = format!("{}:{}:{}", ts, nonce, sig);

    // Build an inline SVG with deterministic per-challenge visual jitter
    let digits: Vec<char> = code.chars().collect();
    let colors = ["#f43f5e", "#38bdf8", "#10b981", "#f59e0b"];
    let mut chars_svg = String::new();

    for (i, ch) in digits.iter().enumerate() {
        let x = 34 + (i as i32) * 44 + ((bytes[10 + i] as i32 % 7) - 3);
        let y = 42 + ((bytes[12 + i] as i32 % 9) - 4);
        let rot = (bytes[6 + i] as i32 % 25) - 12;
        let color = colors[(bytes[10 + i] as usize + i) % colors.len()];
        chars_svg.push_str(&format!(
            r#"<text x="{x}" y="{y}" fill="{color}" font-family="monospace" font-size="30" font-weight="900" transform="rotate({rot} {x} {y})">{ch}</text>"#
        ));
    }

    let y1 = 15 + (bytes[4] % 35);
    let y2 = 15 + (bytes[5] % 35);
    let y3 = 15 + (bytes[6] % 35);
    let svg = format!(
        r#"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 210 60" width="100%" height="60" style="background:#0b0f19;border-radius:8px;border:1px solid rgba(255,255,255,0.12);user-select:none;">
  <path d="M 8 {y1} Q 105 {y2} 202 {y3}" stroke="rgba(244,63,94,0.35)" stroke-width="2" fill="none"/>
  <path d="M 12 {y3} Q 95 {y1} 198 {y2}" stroke="rgba(56,189,248,0.3)" stroke-width="1.5" stroke-dasharray="4,4" fill="none"/>
  {chars_svg}
</svg>"#
    );

    (code, token, svg)
}

/// Verifies a submitted CAPTCHA token and 4-digit answer, consuming the nonce on success.
pub fn verify_captcha_challenge(token: &str, answer: &str) -> std::result::Result<(), &'static str> {
    let clean_answer = answer.trim();
    if clean_answer.len() != 4 || !clean_answer.chars().all(|c| c.is_ascii_digit()) {
        return Err("Please enter the 4-digit security code shown in the image.");
    }

    let parts: Vec<&str> = token.split(':').collect();
    if parts.len() != 3 {
        return Err("Malformed security challenge token. Please refresh the code.");
    }

    let ts: i64 = parts[0]
        .parse()
        .map_err(|_| "Invalid challenge timestamp.")?;
    let nonce = parts[1];
    let given_sig = parts[2];

    let now = crate::time_sync::now_utc_secs();
    if (now - ts).abs() > CAPTCHA_TTL_SECS {
        return Err("Security code has expired. Please tap Refresh to get a new code.");
    }

    let sec = get_security_state();
    let expected_payload = format!("{}:{}:{}", ts, nonce, clean_answer);
    let expected_sig = compute_hmac_sha256(&sec.secret, expected_payload.as_bytes());

    if !verify_constant_time(given_sig, &expected_sig) {
        return Err("Incorrect 4-digit security code. Please try again.");
    }

    // Check and record one-time nonce to prevent replay attacks
    let mut nonces = sec.used_nonces.lock().unwrap();
    if nonces.iter().any(|n| n == nonce) {
        return Err("This security code was already used. Please use the newly generated code.");
    }
    if nonces.len() >= MAX_USED_NONCES {
        nonces.pop_front();
    }
    nonces.push_back(nonce.to_string());

    Ok(())
}

/// HTTP GET handler returning a fresh offline SVG CAPTCHA challenge.
pub async fn sos_challenge_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
) -> Response {
    let app_cfg = state.engine.config();
    if !app_cfg.sos.enabled {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({ "status": "error", "message": "SOS endpoint is disabled" })),
        )
            .into_response();
    }

    if let Err(resp) = check_sos_auth(&headers, app_cfg) {
        return *resp;
    }

    let (_, token, svg) = generate_challenge_pair();
    (
        StatusCode::OK,
        Json(SosChallengeResponse {
            captcha_enabled: app_cfg.sos.captcha_enabled,
            token,
            svg,
        }),
    )
        .into_response()
}

/// HTTP POST handler verifying the Nostr PIN and returning the daemon's `npub`, QR code SVG, and relay URL.
pub async fn sos_nostr_info_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(req): Json<SosNostrInfoRequest>,
) -> Response {
    let app_cfg = state.engine.config();
    if !app_cfg.sos.enabled || !app_cfg.sos.nostr_dm_enabled {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "error",
                "message": "SOS Nostr integration is disabled"
            })),
        )
            .into_response();
    }

    if let Err(resp) = check_sos_auth(&headers, app_cfg) {
        return *resp;
    }

    if !verify_nostr_pin(app_cfg, req.pin.as_deref()) {
        warn!("🔒 [SOS Portal] Invalid PIN attempt when unlocking Nostr identity");
        return (
            StatusCode::FORBIDDEN,
            Json(serde_json::json!({
                "status": "error",
                "message": "Invalid Nostr PIN code."
            })),
        )
            .into_response();
    }

    let bot_npub = state.engine.nostr_publisher().public_key_npub();
    let bot_npub_qr_svg = generate_qr_svg(&bot_npub);
    let bot_hex = state.engine.nostr_publisher().public_key().to_string();
    let relay_url = app_cfg
        .sos
        .public_relay_url
        .clone()
        .or_else(|| app_cfg.nostr.relays.first().cloned())
        .unwrap_or_default();

    (
        StatusCode::OK,
        Json(serde_json::json!({
            "status": "ok",
            "bot_npub": bot_npub,
            "bot_npub_qr_svg": bot_npub_qr_svg,
            "bot_pubkey_hex": bot_hex,
            "relay_url": relay_url,
        })),
    )
        .into_response()
}

/// Formats the canonical SOS emergency text, appending the originating `openalertd` node name
/// at the end so downstream operators and voice/SMS recipients immediately know the physical source location.
pub fn format_sos_alert_text(
    category: Option<&str>,
    sender: Option<&str>,
    message: &str,
    node_name: &str,
) -> String {
    let mut formatted_text = String::new();
    if let Some(cat) = category.map(|c| c.trim().to_uppercase()).filter(|c| !c.is_empty() && c != "GENERAL") {
        formatted_text.push_str(&format!("[{}] ", cat));
    }
    if let Some(snd) = sender.map(|s| s.trim()).filter(|s| !s.is_empty()) {
        formatted_text.push_str(&format!("({}): ", snd));
    }
    formatted_text.push_str(message.trim());

    let clean_node = node_name.trim();
    if !clean_node.is_empty() {
        let suffix = format!("[{}]", clean_node);
        if !formatted_text.ends_with(&suffix) {
            formatted_text.push_str(&format!(" {}", suffix));
        }
    }

    formatted_text
}

/// Resolves a user-supplied Nostr public key (`npub1...` or 64-character hex) into a 32-byte lowercase hex string.
pub fn parse_recipient_pubkey_hex(input: &str) -> std::result::Result<String, String> {
    let res = crate::cli::convert_key(input)?;
    if res.input_format.starts_with("nsec") {
        return Err("Please provide a public key (npub1... or hex), never a private key (nsec1...).".to_string());
    }
    Ok(res.hex_value.to_lowercase())
}

/// HTTP POST handler that validates the CAPTCHA and dispatches the SOS emergency alert.
pub async fn sos_trigger_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(req): Json<SosTriggerRequest>,
) -> Response {
    let app_cfg = state.engine.config();
    if !app_cfg.sos.enabled {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({ "status": "error", "message": "SOS endpoint is disabled" })),
        )
            .into_response();
    }

    if let Err(resp) = check_sos_auth(&headers, app_cfg) {
        return *resp;
    }

    let clean_msg = req.message.trim();
    if clean_msg.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "status": "error",
                "message": "Emergency message cannot be empty."
            })),
        )
            .into_response();
    }

    if clean_msg.len() > 500 {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "status": "error",
                "message": "Message is too long (maximum 500 characters for radio transport)."
            })),
        )
            .into_response();
    }

    // 0. Validate optional custom Nostr recipient npub & PIN if provided
    let resolved_dm_recipient = if let Some(raw_npub) = req
        .recipient_npub
        .as_deref()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        if !app_cfg.sos.nostr_dm_enabled {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "status": "error",
                    "message": "Custom Nostr DM delivery is disabled on this node."
                })),
            )
                .into_response();
        }
        if !verify_nostr_pin(app_cfg, req.nostr_pin.as_deref()) {
            warn!("🔒 [SOS Portal] Rejected custom Nostr DM due to invalid or missing Nostr PIN");
            return (
                StatusCode::FORBIDDEN,
                Json(serde_json::json!({
                    "status": "error",
                    "message": "Valid Nostr PIN is required to dispatch custom Nostr DMs."
                })),
            )
                .into_response();
        }
        match parse_recipient_pubkey_hex(raw_npub) {
            Ok(hex_pk) => Some(hex_pk),
            Err(err_msg) => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(serde_json::json!({
                        "status": "error",
                        "message": format!("Invalid Nostr recipient key: {}", err_msg)
                    })),
                )
                    .into_response();
            }
        }
    } else {
        None
    };

    // 1. Validate CAPTCHA if enabled
    if app_cfg.sos.captcha_enabled {
        let token = req.captcha_token.as_deref().unwrap_or_default();
        let answer = req.captcha_answer.as_deref().unwrap_or_default();
        if let Err(err_msg) = verify_captcha_challenge(token, answer) {
            warn!("🛑 [SOS Portal] Rejected SOS submission due to CAPTCHA failure: {}", err_msg);
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "status": "error",
                    "message": err_msg
                })),
            )
                .into_response();
        }
    }

    // 2. Enforce rate-limiting cooldown to protect LoRa duty cycle
    if app_cfg.sos.cooldown_seconds > 0 {
        let sec = get_security_state();
        let mut last_guard = sec.last_trigger.lock().unwrap();
        if let Some(prev) = *last_guard {
            let elapsed = prev.elapsed().as_secs();
            if elapsed < app_cfg.sos.cooldown_seconds {
                let wait_rem = app_cfg.sos.cooldown_seconds - elapsed;
                return (
                    StatusCode::TOO_MANY_REQUESTS,
                    Json(serde_json::json!({
                        "status": "error",
                        "message": format!("Radio cooldown active. Please wait {}s before sending another alert.", wait_rem)
                    })),
                )
                    .into_response();
            }
        }
        *last_guard = Some(Instant::now());
    }

    // 3. Build canonical Alert with originating node name appended at the end of the message
    let severity = match app_cfg.sos.default_severity.trim().to_lowercase().as_str() {
        "info" => AlertSeverity::Info,
        "warning" | "warn" => AlertSeverity::Warning,
        _ => AlertSeverity::Critical,
    };

    let sender_clean = req
        .sender
        .as_ref()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty());

    let formatted_text = format_sos_alert_text(
        req.category.as_deref(),
        sender_clean,
        clean_msg,
        &app_cfg.daemon.name,
    );

    let now_dt = crate::time_sync::now_utc();
    let short_id = &uuid::Uuid::new_v4().to_string()[..8];
    let alert_id = format!("sos-{}-{}", short_id, now_dt.timestamp_millis());

    let alert = Alert {
        alert_id: alert_id.clone(),
        severity,
        summary: formatted_text.clone(),
        description: Some(formatted_text.clone()),
        source: AlertSource::Rest,
        sender: Some(sender_clean.unwrap_or("SOS-Portal").to_string()),
        node: Some(app_cfg.daemon.name.clone()),
        starts_at: now_dt,
        destinations: Vec::new(),
        origin_peer: None,
        hop: 5,
    };

    info!(
        "🚨 [SOS Portal] Emergency Alert triggered [{}] -> \"{}\"",
        alert_id, formatted_text
    );

    // 4. Register custom Nostr recipient pubkey if provided, and dispatch if engine won't already fan out to oxchat
    let engine_handles_oxchat = app_cfg.nostr.oxchat.enabled
        && app_cfg
            .routing
            .default_destinations
            .iter()
            .any(|d| matches!(d.as_str(), "nostr" | "oxchat" | "0xchat"));

    if let Some(ref recipient_hex) = resolved_dm_recipient {
        let _ = state
            .engine
            .nostr_publisher()
            .register_oxchat_subscriber(recipient_hex)
            .await;

        if !engine_handles_oxchat {
            let engine_clone = state.engine.clone();
            let alert_for_dm = alert.clone();
            let rec_hex = recipient_hex.clone();
            tokio::spawn(async move {
                match engine_clone
                    .nostr_publisher()
                    .dispatch_direct_oxchat_alert(&rec_hex, &alert_for_dm)
                    .await
                {
                    Ok(cnt) => info!(
                        "🔐 [SOS Portal] Dispatched encrypted 0xChat DM for alert [{}] to {} ({} relay confirmations)",
                        alert_for_dm.alert_id,
                        &rec_hex[..12.min(rec_hex.len())],
                        cnt
                    ),
                    Err(e) => warn!(
                        "⚠️ [SOS Portal] Failed to dispatch encrypted 0xChat DM for alert [{}]: {}",
                        alert_for_dm.alert_id, e
                    ),
                }
            });
        }
    }

    let subs_count = state
        .engine
        .nostr_publisher()
        .get_oxchat_subscribers()
        .await
        .len();
    let dm_dispatched = resolved_dm_recipient.is_some() || (engine_handles_oxchat && subs_count > 0);

    match state.engine.route_alert(alert).await {
        Ok(()) => (
            StatusCode::ACCEPTED,
            Json(serde_json::json!({
                "status": "accepted",
                "alert_id": alert_id,
                "summary": formatted_text,
                "node": app_cfg.daemon.name,
                "nostr_dm_dispatched": dm_dispatched,
                "nostr_subscribers_count": subs_count,
                "timestamp": now_dt
            })),
        )
            .into_response(),
        Err(e) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            Json(serde_json::json!({
                "status": "error",
                "message": format!("Failed to dispatch alert: {}", e)
            })),
        )
            .into_response(),
    }
}

/// HTTP GET handler serving the simplified mobile-first SOS Emergency Web UI.
pub async fn sos_page_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
) -> Response {
    let app_cfg = state.engine.config();
    if !app_cfg.sos.enabled {
        return (
            StatusCode::NOT_FOUND,
            [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
            "404 Not Found: OpenAlert SOS Portal is disabled in configuration.",
        )
            .into_response();
    }

    if let Err(resp) = check_sos_auth(&headers, app_cfg) {
        return *resp;
    }

    let pin_required = is_nostr_pin_active(app_cfg);
    // Only embed the Bot npub, QR SVG, and relay URL directly in initial HTML when NOT protected by a PIN
    let initial_bot_npub = if app_cfg.sos.nostr_dm_enabled && !pin_required {
        state.engine.nostr_publisher().public_key_npub()
    } else {
        String::new()
    };

    let initial_bot_qr_svg = if !initial_bot_npub.is_empty() {
        generate_qr_svg(&initial_bot_npub)
    } else {
        String::new()
    };

    let initial_relay_url = if app_cfg.sos.nostr_dm_enabled && !pin_required {
        app_cfg
            .sos
            .public_relay_url
            .clone()
            .or_else(|| app_cfg.nostr.relays.first().cloned())
            .unwrap_or_default()
    } else {
        String::new()
    };

    let html = render_sos_html(
        &app_cfg.sos.title,
        &app_cfg.daemon.name,
        app_cfg.sos.captcha_enabled,
        app_cfg.sos.gps_enabled,
        app_cfg.sos.nostr_dm_enabled,
        pin_required,
        &initial_bot_npub,
        &initial_bot_qr_svg,
        &initial_relay_url,
    );

    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        html,
    )
        .into_response()
}

#[allow(clippy::too_many_arguments)]
fn render_sos_html(
    title: &str,
    node_name: &str,
    captcha_enabled: bool,
    gps_enabled: bool,
    nostr_dm_enabled: bool,
    pin_required: bool,
    initial_bot_npub: &str,
    initial_bot_qr_svg: &str,
    initial_relay_url: &str,
) -> String {
    let captcha_display = if captcha_enabled { "block" } else { "none" };
    let gps_btn_display = if gps_enabled { "inline-flex" } else { "none" };
    let nostr_section_display = if nostr_dm_enabled { "block" } else { "none" };
    let pin_lock_display = if pin_required { "block" } else { "none" };
    let nostr_unlocked_display = if pin_required { "none" } else { "block" };
    let relay_row_display = if initial_relay_url.is_empty() { "none" } else { "block" };

    format!(
        r##"<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>{title}</title>
  <link rel="icon" type="image/png" href="/api/v1/logo">
  <style>
    :root {{
      --bg: #070a13;
      --card: #111827;
      --border: rgba(255, 255, 255, 0.12);
      --text: #f8fafc;
      --muted: #94a3b8;
      --danger: #e11d48;
      --danger-hover: #be123c;
      --danger-glow: rgba(225, 29, 72, 0.4);
      --accent: #38bdf8;
      --purple: #a855f7;
      --success: #10b981;
      --input-bg: #0b0f19;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: radial-gradient(circle at top, rgba(225, 29, 72, 0.15), transparent 55%), var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 1rem;
    }}
    .container {{
      width: 100%;
      max-width: 460px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 1.5rem;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
    }}
    .header {{
      display: flex;
      align-items: center;
      gap: 0.85rem;
      margin-bottom: 1rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--border);
    }}
    .header img {{
      width: 44px;
      height: 44px;
      border-radius: 10px;
    }}
    .header-title h1 {{
      font-size: 1.2rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #fff;
    }}
    .node-badge {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.75rem;
      color: var(--success);
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      padding: 0.18rem 0.55rem;
      border-radius: 999px;
      margin-top: 0.25rem;
      font-family: monospace;
    }}
    .dot {{
      width: 7px;
      height: 7px;
      background: var(--success);
      border-radius: 50%;
      box-shadow: 0 0 8px var(--success);
    }}
    label {{
      display: block;
      font-size: 0.8rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      color: var(--muted);
      margin-bottom: 0.45rem;
      margin-top: 1rem;
    }}
    .presets {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 0.5rem;
    }}
    .preset-btn {{
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.55rem 0.65rem;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      text-align: left;
      transition: all 0.15s ease;
    }}
    .preset-btn.active, .preset-btn:hover {{
      border-color: var(--danger);
      background: rgba(225, 29, 72, 0.15);
    }}
    input, textarea {{
      width: 100%;
      background: var(--input-bg);
      border: 1px solid var(--border);
      border-radius: 10px;
      color: var(--text);
      padding: 0.75rem;
      font-size: 0.96rem;
      font-family: inherit;
      outline: none;
    }}
    input:focus, textarea:focus {{
      border-color: var(--accent);
    }}
    textarea {{
      min-height: 90px;
      resize: vertical;
    }}
    .nostr-details {{
      display: {nostr_section_display};
      margin-top: 1rem;
      background: rgba(168, 85, 247, 0.06);
      border: 1px solid rgba(168, 85, 247, 0.28);
      border-radius: 12px;
      padding: 0.75rem 0.9rem;
    }}
    .nostr-summary {{
      cursor: pointer;
      font-size: 0.82rem;
      font-weight: 700;
      color: #d8b4fe;
      display: flex;
      align-items: center;
      justify-content: space-between;
      user-select: none;
      list-style: none;
    }}
    .nostr-summary::-webkit-details-marker {{ display: none; }}
    .nostr-body {{
      margin-top: 0.75rem;
      padding-top: 0.75rem;
      border-top: 1px solid rgba(168, 85, 247, 0.2);
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .mono-row {{
      display: flex;
      align-items: center;
      gap: 0.4rem;
      margin-top: 0.3rem;
      margin-bottom: 0.65rem;
    }}
    .mono-box {{
      flex: 1;
      background: var(--input-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.45rem 0.6rem;
      font-family: monospace;
      font-size: 0.74rem;
      color: #e2e8f0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .mini-btn {{
      background: rgba(168, 85, 247, 0.2);
      color: #f3e8ff;
      border: 1px solid rgba(168, 85, 247, 0.4);
      border-radius: 8px;
      padding: 0.45rem 0.65rem;
      font-size: 0.74rem;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}
    .mini-btn:hover {{
      background: rgba(168, 85, 247, 0.35);
    }}
    .qr-card {{
      display: none;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: rgba(11, 15, 25, 0.85);
      border: 1px solid rgba(168, 85, 247, 0.35);
      border-radius: 12px;
      padding: 0.85rem;
      margin-bottom: 0.75rem;
      text-align: center;
    }}
    .qr-svg-wrap {{
      background: #ffffff;
      padding: 8px;
      border-radius: 10px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
    }}
    .qr-svg-wrap svg {{
      width: 168px;
      height: 168px;
      display: block;
    }}
    .captcha-box {{
      display: {captcha_display};
      margin-top: 1rem;
      padding: 0.85rem;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--border);
      border-radius: 12px;
    }}
    .captcha-row {{
      display: flex;
      align-items: center;
      gap: 0.6rem;
      margin-bottom: 0.6rem;
    }}
    .captcha-svg {{
      flex: 1;
      height: 60px;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .refresh-btn {{
      background: var(--input-bg);
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 0.6rem 0.75rem;
      cursor: pointer;
      font-size: 0.85rem;
      font-weight: 600;
      height: 60px;
    }}
    .captcha-input {{
      text-align: center;
      font-size: 1.35rem;
      font-weight: 800;
      letter-spacing: 0.35em;
      font-family: monospace;
    }}
    .sos-btn {{
      width: 100%;
      margin-top: 1.35rem;
      background: var(--danger);
      color: #fff;
      border: none;
      border-radius: 12px;
      padding: 1rem;
      font-size: 1.08rem;
      font-weight: 800;
      letter-spacing: 0.03em;
      cursor: pointer;
      box-shadow: 0 6px 24px var(--danger-glow);
      transition: transform 0.1s ease, background 0.15s ease;
    }}
    .sos-btn:hover {{ background: var(--danger-hover); }}
    .sos-btn:active {{ transform: scale(0.98); }}
    .sos-btn:disabled {{ opacity: 0.55; cursor: not-allowed; }}
    .status-banner {{
      display: none;
      margin-top: 1rem;
      padding: 0.85rem;
      border-radius: 10px;
      font-size: 0.88rem;
      line-height: 1.4;
      word-break: break-word;
    }}
    .status-ok {{
      display: block;
      background: rgba(16, 185, 129, 0.14);
      border: 1px solid rgba(16, 185, 129, 0.4);
      color: #6ee7b7;
    }}
    .status-err {{
      display: block;
      background: rgba(244, 63, 94, 0.15);
      border: 1px solid rgba(244, 63, 94, 0.45);
      color: #fda4af;
    }}
    .footer {{
      margin-top: 1.1rem;
      text-align: center;
      font-size: 0.72rem;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <img src="/api/v1/logo" alt="OpenAlert">
      <div class="header-title">
        <h1>{title}</h1>
        <div class="node-badge"><span class="dot"></span> {node_name}</div>
      </div>
    </div>

    <form id="sosForm" onsubmit="submitSos(event)">
      <label>1. Emergency Category (Optional)</label>
      <div class="presets">
        <button type="button" class="preset-btn" onclick="selectPreset(this, 'SOS')">🆘 General SOS</button>
        <button type="button" class="preset-btn" onclick="selectPreset(this, 'MEDICAL')">🚑 Medical Help</button>
        <button type="button" class="preset-btn" onclick="selectPreset(this, 'FIRE')">🔥 Fire / Hazard</button>
        <button type="button" class="preset-btn" onclick="selectPreset(this, 'RESCUE')">🚁 Evacuation</button>
      </div>

      <div style="display:flex;align-items:center;justify-content:space-between;margin-top:1rem;margin-bottom:0.45rem;">
        <label for="sender" style="margin:0;">2. Your Name / Phone / Location (Optional)</label>
        <button type="button" id="gpsBtn" class="mini-btn" style="display:{gps_btn_display};align-items:center;gap:0.25rem;background:rgba(56,189,248,0.15);border-color:rgba(56,189,248,0.4);color:#bae6fd;padding:0.28rem 0.55rem;font-size:0.72rem;" onclick="attachGps(this)" title="Optionally attach your phone's GPS coordinates">📍 GPS</button>
      </div>
      <input type="text" id="sender" placeholder="e.g. YourName - Your Location" maxlength="120">

      <label for="message">3. Emergency Message *</label>
      <textarea id="message" placeholder="Describe the emergency clearly..." required maxlength="500"></textarea>

      <details class="nostr-details" id="nostrDetails">
        <summary class="nostr-summary">
          <span>🔐 0xChat / Nostr Encrypted DM (Optional)</span>
          <span style="font-size:0.72rem;opacity:0.8;">Tap to configure ▾</span>
        </summary>
        <div class="nostr-body">
          <div id="nostrPinLock" style="display:{pin_lock_display};">
            <div style="margin-bottom:0.45rem;">🔒 Enter the Nostr Access PIN to view this node's Bot <code>npub</code> / QR Code and enable direct encrypted DM delivery:</div>
            <div class="mono-row">
              <input type="password" id="nostrPinInput" placeholder="Enter PIN..." style="padding:0.5rem 0.65rem;font-size:0.85rem;">
              <button type="button" class="mini-btn" onclick="unlockNostrInfo()">Unlock</button>
            </div>
            <div id="nostrPinErr" style="color:#fda4af;font-size:0.75rem;display:none;"></div>
          </div>

          <div id="nostrUnlocked" style="display:{nostr_unlocked_display};">
            <div id="relayUrlContainer" style="display:{relay_row_display};">
              <div>1. Connect your 0xChat / Nostr client to Relay:</div>
              <div class="mono-row">
                <div class="mono-box" id="relayUrlBox">{initial_relay_url}</div>
                <button type="button" class="mini-btn" onclick="copyText('relayUrlBox', this)">Copy</button>
              </div>
            </div>

            <div>2. OpenAlert Node Bot <code>npub</code> (Add Contact in 0xChat):</div>
            <div class="mono-row">
              <div class="mono-box" id="botNpubBox">{initial_bot_npub}</div>
              <button type="button" class="mini-btn" onclick="copyText('botNpubBox', this)">Copy</button>
              <button type="button" class="mini-btn" onclick="toggleBotQr()">📱 QR</button>
            </div>

            <div class="qr-card" id="botQrCard">
              <div style="font-size:0.75rem;color:#e2e8f0;margin-bottom:0.5rem;font-weight:600;">
                Scan with 0xChat (Contacts → + → Scan QR Code)
              </div>
              <div class="qr-svg-wrap" id="botQrSvgWrap">{initial_bot_qr_svg}</div>
              <div style="font-size:0.68rem;color:var(--muted);margin-top:0.45rem;">
                Once connected to the relay above, all alerts arrive automatically in 0xChat!
              </div>
            </div>

            <div style="margin-top:0.4rem;margin-bottom:0.3rem;">3. Optional: Your 0xChat Public Key (<code>npub1...</code> or hex):</div>
            <input type="text" id="recipientNpub" placeholder="npub1... (optional if already connected to relay)" maxlength="120" style="font-family:monospace;font-size:0.8rem;padding:0.6rem;">
          </div>
        </div>
      </details>

      <div class="captcha-box" id="captchaBox">
        <label style="margin-top:0;">4. Anti-Bot Security Code *</label>
        <div class="captcha-row">
          <div class="captcha-svg" id="captchaSvg">Loading...</div>
          <button type="button" class="refresh-btn" onclick="loadChallenge()" title="New Code">🔄 New</button>
        </div>
        <input type="text" id="captchaAnswer" class="captcha-input" inputmode="numeric" pattern="[0-9]*" maxlength="4" placeholder="----" autocomplete="off">
      </div>

      <button type="submit" class="sos-btn" id="submitBtn">🚨 SEND EMERGENCY ALERT</button>
    </form>

    <div id="statusBanner" class="status-banner"></div>

    <div class="footer">
      OpenAlert Off-Grid LoRa / Mesh &amp; Nostr Emergency Terminal
    </div>
  </div>

  <script>
    let currentCategory = "GENERAL";
    let captchaToken = "";
    let unlockedPin = "";
    const captchaEnabled = {captcha_enabled};

    function selectPreset(btn, cat) {{
      document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
      if (currentCategory === cat) {{
        currentCategory = "GENERAL";
      }} else {{
        btn.classList.add('active');
        currentCategory = cat;
      }}
    }}

    function attachGps(btn) {{
      if (!navigator.geolocation) {{
        btn.innerText = "⚠️ No GPS";
        return;
      }}
      const orig = btn.innerText;
      btn.innerText = "⏳ Locating...";
      btn.disabled = true;
      navigator.geolocation.getCurrentPosition(
        (pos) => {{
          const lat = pos.coords.latitude.toFixed(5);
          const lon = pos.coords.longitude.toFixed(5);
          const acc = pos.coords.accuracy ? `±${{Math.round(pos.coords.accuracy)}}m` : "";
          const coordStr = `GPS:${{lat}},${{lon}}${{acc ? " (" + acc + ")" : ""}}`;
          const senderEl = document.getElementById('sender');
          const current = senderEl.value.replace(/\s*\|?\s*GPS:[-0-9.,]+(?:\s*\([^)]*\))?/g, "").trim();
          senderEl.value = current ? `${{current}} | ${{coordStr}}` : coordStr;
          btn.innerText = "✅ GPS Added";
          btn.disabled = false;
          setTimeout(() => {{ btn.innerText = orig; }}, 2500);
        }},
        (_err) => {{
          btn.innerText = "⚠️ GPS Denied";
          btn.disabled = false;
          setTimeout(() => {{ btn.innerText = orig; }}, 2500);
        }},
        {{ enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }}
      );
    }}

    function copyText(elementId, btn) {{
      const txt = document.getElementById(elementId).innerText.trim();
      if (!txt) return;
      navigator.clipboard.writeText(txt).then(() => {{
        const orig = btn.innerText;
        btn.innerText = "Copied!";
        setTimeout(() => {{ btn.innerText = orig; }}, 1500);
      }});
    }}

    function toggleBotQr() {{
      const card = document.getElementById('botQrCard');
      if (!card) return;
      card.style.display = (card.style.display === 'flex') ? 'none' : 'flex';
    }}

    async function unlockNostrInfo() {{
      const pin = document.getElementById('nostrPinInput').value.trim();
      const errEl = document.getElementById('nostrPinErr');
      errEl.style.display = 'none';
      if (!pin) return;

      try {{
        const res = await fetch('/api/v1/sos/nostr-info', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ pin }})
        }});
        const data = await res.json();
        if (res.ok) {{
          unlockedPin = pin;
          document.getElementById('botNpubBox').innerText = data.bot_npub || '';
          if (data.bot_npub_qr_svg) {{
            document.getElementById('botQrSvgWrap').innerHTML = data.bot_npub_qr_svg;
          }}
          if (data.relay_url) {{
            document.getElementById('relayUrlBox').innerText = data.relay_url;
            document.getElementById('relayUrlContainer').style.display = 'block';
          }}
          document.getElementById('nostrPinLock').style.display = 'none';
          document.getElementById('nostrUnlocked').style.display = 'block';
        }} else {{
          errEl.innerText = data.message || 'Invalid PIN';
          errEl.style.display = 'block';
        }}
      }} catch (e) {{
        errEl.innerText = 'Error verifying PIN';
        errEl.style.display = 'block';
      }}
    }}

    async function loadChallenge() {{
      if (!captchaEnabled) return;
      try {{
        const res = await fetch('/api/v1/sos/challenge', {{ cache: 'no-store' }});
        if (res.ok) {{
          const data = await res.json();
          captchaToken = data.token;
          document.getElementById('captchaSvg').innerHTML = data.svg;
          document.getElementById('captchaAnswer').value = '';
        }}
      }} catch (e) {{
        document.getElementById('captchaSvg').innerText = 'Error loading code';
      }}
    }}

    async function submitSos(e) {{
      e.preventDefault();
      const btn = document.getElementById('submitBtn');
      const banner = document.getElementById('statusBanner');
      const message = document.getElementById('message').value.trim();
      const sender = document.getElementById('sender').value.trim();
      const captchaAnswer = document.getElementById('captchaAnswer').value.trim();
      const recipientNpubEl = document.getElementById('recipientNpub');
      const recipientNpub = recipientNpubEl ? recipientNpubEl.value.trim() : '';

      if (!message) return;
      if (captchaEnabled && captchaAnswer.length !== 4) {{
        banner.className = 'status-banner status-err';
        banner.innerText = '⚠️ Please enter the 4-digit security code shown in the box.';
        return;
      }}

      btn.disabled = true;
      btn.innerText = '📡 TRANSMITTING ALERT...';
      banner.className = 'status-banner';
      banner.style.display = 'none';

      try {{
        const res = await fetch('/api/v1/sos/trigger', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            message,
            sender: sender || null,
            category: currentCategory,
            captcha_token: captchaToken,
            captcha_answer: captchaAnswer,
            recipient_npub: recipientNpub || null,
            nostr_pin: unlockedPin || null
          }})
        }});
        const data = await res.json();
        if (res.ok) {{
          banner.className = 'status-banner status-ok';
          banner.style.display = 'block';
          const dmNote = data.nostr_dm_dispatched
            ? `<br>🔐 <em>Encrypted 0xChat DM dispatched (${{data.nostr_subscribers_count || 1}} active subscriber(s))!</em>`
            : '';
          banner.innerHTML = `✅ <strong>SOS Alert Dispatched!</strong><br>ID: <code>${{data.alert_id}}</code><br>Payload: "${{data.summary}}"${{dmNote}}`;
          document.getElementById('message').value = '';
          await loadChallenge();
        }} else {{
          banner.className = 'status-banner status-err';
          banner.style.display = 'block';
          banner.innerText = `❌ ${{data.message || 'Failed to send alert'}}`;
          await loadChallenge();
        }}
      }} catch (err) {{
        banner.className = 'status-banner status-err';
        banner.style.display = 'block';
        banner.innerText = '❌ Network error communicating with OpenAlert node.';
      }} finally {{
        btn.disabled = false;
        btn.innerText = '🚨 SEND EMERGENCY ALERT';
      }}
    }}

    window.addEventListener('DOMContentLoaded', loadChallenge);
  </script>
</body>
</html>"##
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_offline_svg_captcha_roundtrip_and_anti_replay() {
        let (code, token, svg) = generate_challenge_pair();
        assert_eq!(code.len(), 4);
        assert!(svg.contains("<svg"));

        // 1. Wrong code should be rejected
        let wrong_code = if code == "1234" { "9999" } else { "1234" };
        assert!(verify_captcha_challenge(&token, wrong_code).is_err());

        // 2. Correct code should pass on first use
        assert!(verify_captcha_challenge(&token, &code).is_ok());

        // 3. Replaying the exact same token + code a second time must be rejected
        let replay_res = verify_captcha_challenge(&token, &code);
        assert!(replay_res.is_err());
        assert!(replay_res.unwrap_err().contains("already used"));
    }

    #[test]
    fn test_format_sos_alert_text_appends_node_name() {
        let formatted = format_sos_alert_text(
            Some("MEDICAL"),
            Some("Jorge"),
            "Need assistance on floor 2",
            "openalertd-fog-arm",
        );
        assert_eq!(
            formatted,
            "[MEDICAL] (Jorge): Need assistance on floor 2 [openalertd-fog-arm]"
        );

        let no_cat_no_sender = format_sos_alert_text(
            Some("GENERAL"),
            None,
            "Power outage",
            "openalertd-fog-arm",
        );
        assert_eq!(no_cat_no_sender, "Power outage [openalertd-fog-arm]");
    }

    #[test]
    fn test_nostr_pin_verification_and_npub_parsing() {
        let mut cfg = AppConfig::default();
        assert!(!is_nostr_pin_active(&cfg));
        assert!(verify_nostr_pin(&cfg, None));

        cfg.sos.nostr_pin = Some("2026".to_string());
        assert!(is_nostr_pin_active(&cfg));
        assert!(!verify_nostr_pin(&cfg, None));
        assert!(!verify_nostr_pin(&cfg, Some("9999")));
        assert!(verify_nostr_pin(&cfg, Some("2026")));

        // Also test sha256 hashed PIN
        let hash = crate::cli::hash_password("secret-pin");
        cfg.sos.nostr_pin = Some(format!("sha256:{}", hash));
        assert!(verify_nostr_pin(&cfg, Some("secret-pin")));
        assert!(!verify_nostr_pin(&cfg, Some("wrong-pin")));

        // Test npub parsing and QR SVG generation
        let id = crate::cli::generate_keypair();
        let parsed_hex = parse_recipient_pubkey_hex(&id.npub).expect("valid npub");
        assert_eq!(parsed_hex, id.pub_hex);
        assert!(parse_recipient_pubkey_hex(&id.nsec).is_err());

        let qr_svg = generate_qr_svg(&id.npub);
        assert!(qr_svg.contains("<svg"));
    }
}
