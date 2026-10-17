//! # Simplified Emergency SOS Web Portal & Offline CAPTCHA Ingress
//!
//! Provides a dedicated, configurable emergency web interface (default `/sos`) separate from
//! the administrative NOC dashboard (`/dashboard`). Designed for field and Wi-Fi Access Point
//! deployments where bystanders or operators without BitChat/0xChat can trigger emergency alerts
//! from any mobile browser, protected by an offline SVG visual CAPTCHA, rate-limiting cooldown,
//! and optional independent authentication.

use crate::config::AppConfig;
use crate::ingress::rest::{AppState, compute_hmac_sha256, verify_constant_time};
use crate::models::{Alert, AlertSeverity, AlertSource};
use axum::{
    Json,
    extract::State,
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
};
use chrono::Utc;
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
        hasher.update(Utc::now().timestamp_nanos_opt().unwrap_or(0).to_le_bytes());
        let secret: [u8; 32] = hasher.finalize().into();
        SosSecurityState {
            secret,
            used_nonces: Mutex::new(VecDeque::with_capacity(MAX_USED_NONCES)),
            last_trigger: Mutex::new(None),
        }
    })
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
    let ts = Utc::now().timestamp();

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

    let now = Utc::now().timestamp();
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

    // 3. Build canonical Alert
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

    let category_clean = req
        .category
        .as_ref()
        .map(|c| c.trim().to_uppercase())
        .filter(|c| !c.is_empty() && c != "GENERAL");

    let mut formatted_text = String::new();
    if let Some(cat) = category_clean {
        formatted_text.push_str(&format!("[{}] ", cat));
    }
    if let Some(snd) = sender_clean {
        formatted_text.push_str(&format!("({}): ", snd));
    }
    formatted_text.push_str(clean_msg);

    let short_id = &uuid::Uuid::new_v4().to_string()[..8];
    let alert_id = format!("sos-{}-{}", short_id, Utc::now().timestamp_millis());

    let alert = Alert {
        alert_id: alert_id.clone(),
        severity,
        summary: formatted_text.clone(),
        description: Some(formatted_text.clone()),
        source: AlertSource::Rest,
        sender: Some(sender_clean.unwrap_or("SOS-Portal").to_string()),
        node: Some(app_cfg.daemon.name.clone()),
        starts_at: Utc::now(),
        destinations: Vec::new(),
        origin_peer: None,
        hop: 3,
    };

    info!(
        "🚨 [SOS Portal] Emergency Alert triggered [{}] -> \"{}\"",
        alert_id, formatted_text
    );

    match state.engine.route_alert(alert).await {
        Ok(()) => (
            StatusCode::ACCEPTED,
            Json(serde_json::json!({
                "status": "accepted",
                "alert_id": alert_id,
                "summary": formatted_text,
                "node": app_cfg.daemon.name,
                "timestamp": Utc::now()
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

    let html = render_sos_html(
        &app_cfg.sos.title,
        &app_cfg.daemon.name,
        app_cfg.sos.captcha_enabled,
    );

    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        html,
    )
        .into_response()
}

fn render_sos_html(title: &str, node_name: &str, captcha_enabled: bool) -> String {
    let captcha_display = if captcha_enabled { "block" } else { "none" };
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
      max-width: 440px;
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
      font-size: 0.98rem;
      font-family: inherit;
      outline: none;
    }}
    input:focus, textarea:focus {{
      border-color: var(--accent);
    }}
    textarea {{
      min-height: 95px;
      resize: vertical;
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

      <label for="sender">2. Your Name / Phone / Location</label>
      <input type="text" id="sender" placeholder="e.g. Jorge - Sector Norte" maxlength="80">

      <label for="message">3. Emergency Message *</label>
      <textarea id="message" placeholder="Describe the emergency clearly..." required maxlength="500"></textarea>

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
      OpenAlert Off-Grid LoRa / Mesh Emergency Terminal
    </div>
  </div>

  <script>
    let currentCategory = "GENERAL";
    let captchaToken = "";
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

      if (!message) return;
      if (captchaEnabled && captchaAnswer.length !== 4) {{
        banner.className = 'status-banner status-err';
        banner.innerText = '⚠️ Please enter the 4-digit security code shown in the box.';
        return;
      }}

      btn.disabled = true;
      btn.innerText = '📡 TRANSMITTING OVER MESH...';
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
            captcha_answer: captchaAnswer
          }})
        }});
        const data = await res.json();
        if (res.ok) {{
          banner.className = 'status-banner status-ok';
          banner.style.display = 'block';
          banner.innerHTML = `✅ <strong>SOS Alert Dispatched!</strong><br>ID: <code>${{data.alert_id}}</code><br>Payload: "${{data.summary}}"`;
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
}
