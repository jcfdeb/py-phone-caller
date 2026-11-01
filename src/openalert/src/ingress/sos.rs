//! # Simplified Emergency SOS Web Portal & Offline CAPTCHA Ingress
//!
//! Provides a dedicated, configurable emergency web interface (default `/sos`) separate from
//! the administrative NOC dashboard (`/dashboard`). Designed for field and Wi-Fi Access Point
//! deployments where bystanders or operators without BitChat/0xChat can trigger emergency alerts
//! from any mobile browser, protected by an offline SVG visual CAPTCHA, rate-limiting cooldown,
//! optional PIN-protected Nostr/0xChat encrypted DM delivery, NIP-57 Lightning Zap Alert adapter,
//! and optional independent authentication.

use crate::config::AppConfig;
use crate::ingress::rest::{AppState, compute_hmac_sha256, verify_constant_time};
use crate::models::{Alert, AlertSeverity, AlertSource, NostrEvent};
use axum::{
    Json,
    extract::{Path, State},
    http::{HeaderMap, StatusCode, header},
    response::{IntoResponse, Response},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::VecDeque;
use std::io::Write;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};
use tracing::{info, warn};

/// Maximum number of consumed CAPTCHA nonces retained in memory to prevent replay attacks.
const MAX_USED_NONCES: usize = 1024;

/// Maximum validity window of a generated CAPTCHA token in seconds (10 minutes).
const CAPTCHA_TTL_SECS: i64 = 600;

/// Maximum number of generated BOLT-11 invoices cached in memory for PNG QR rendering and 0xChat forwarding.
const MAX_CACHED_ZAP_INVOICES: usize = 256;

/// Cached BOLT-11 Zap invoice metadata for serving `.png` QR codes and forwarding to 0xChat.
#[derive(Debug, Clone)]
pub struct CachedZapInvoice {
    pub zap_request_id: String,
    pub bolt11: String,
    pub amount_sats: u64,
    pub severity: String,
    pub lud16: String,
    pub summary: String,
    pub created_at: i64,
}

/// Global ephemeral secret and anti-replay / cooldown state for the SOS subsystem.
struct SosSecurityState {
    secret: [u8; 32],
    used_nonces: Mutex<VecDeque<String>>,
    last_trigger: Mutex<Option<Instant>>,
    zap_invoices: Mutex<VecDeque<CachedZapInvoice>>,
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
            zap_invoices: Mutex::new(VecDeque::with_capacity(MAX_CACHED_ZAP_INVOICES)),
        }
    })
}

/// Generates an inline SVG QR code for a Nostr `npub1...` or BOLT-11 string so mobile users can scan it.
/// Uses `EcLevel::L` and uppercase alphanumeric encoding for long BOLT-11 invoices so QR modules stay large and easy for phone cameras to scan.
pub fn generate_qr_svg(data: &str) -> String {
    let clean = data.trim();
    if clean.is_empty() {
        return String::new();
    }
    let ec_level = if clean.len() > 120 {
        qrcode::EcLevel::L
    } else {
        qrcode::EcLevel::M
    };
    if let Ok(code) = qrcode::QrCode::with_error_correction_level(clean.as_bytes(), ec_level) {
        code.render::<qrcode::render::svg::Color<'_>>()
            .min_dimensions(240, 240)
            .dark_color(qrcode::render::svg::Color("#090d16"))
            .light_color(qrcode::render::svg::Color("#ffffff"))
            .build()
    } else {
        String::new()
    }
}

/// Computes IEEE 802.3 CRC-32 for a PNG chunk (`chunk_type || data`).
fn png_crc32(chunk_type: &[u8; 4], data: &[u8]) -> u32 {
    let mut crc: u32 = 0xFFFF_FFFF;
    for &b in chunk_type.iter().chain(data.iter()) {
        crc ^= b as u32;
        for _ in 0..8 {
            if (crc & 1) != 0 {
                crc = (crc >> 1) ^ 0xEDB8_8320;
            } else {
                crc >>= 1;
            }
        }
    }
    !crc
}

/// Appends a framed PNG chunk (`length || type || data || crc32`) to `out`.
fn write_png_chunk(out: &mut Vec<u8>, chunk_type: &[u8; 4], data: &[u8]) {
    out.extend_from_slice(&(data.len() as u32).to_be_bytes());
    out.extend_from_slice(chunk_type);
    out.extend_from_slice(data);
    out.extend_from_slice(&png_crc32(chunk_type, data).to_be_bytes());
}

/// Generates a high-contrast 8-bit grayscale PNG image (`image/png`) for a QR code with a 4-module quiet zone.
/// Designed for mobile gallery import ("Scan from Photo"), native Web Share API, and inline rendering inside 0xChat.
pub fn generate_qr_png(data: &str) -> Vec<u8> {
    let clean = data.trim();
    if clean.is_empty() {
        return Vec::new();
    }
    let ec_level = if clean.len() > 120 {
        qrcode::EcLevel::L
    } else {
        qrcode::EcLevel::M
    };
    let Ok(code) = qrcode::QrCode::with_error_correction_level(clean.as_bytes(), ec_level) else {
        return Vec::new();
    };

    let qr_width = code.width();
    let colors = code.to_colors();
    let quiet_zone = 4usize;
    let total_modules = qr_width + quiet_zone * 2;
    let scale = (560 / total_modules).max(8);
    let img_size = total_modules * scale;

    let mut raw_scanlines = Vec::with_capacity(img_size * (img_size + 1));
    for y in 0..img_size {
        raw_scanlines.push(0u8); // Filter type 0 (None)
        let mod_y = y / scale;
        for x in 0..img_size {
            let mod_x = x / scale;
            let is_dark = if mod_x >= quiet_zone
                && mod_x < quiet_zone + qr_width
                && mod_y >= quiet_zone
                && mod_y < quiet_zone + qr_width
            {
                let qx = mod_x - quiet_zone;
                let qy = mod_y - quiet_zone;
                matches!(colors[qy * qr_width + qx], qrcode::Color::Dark)
            } else {
                false
            };
            raw_scanlines.push(if is_dark { 0x00 } else { 0xFF });
        }
    }

    let mut encoder =
        flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::default());
    if encoder.write_all(&raw_scanlines).is_err() {
        return Vec::new();
    }
    let Ok(idat_data) = encoder.finish() else {
        return Vec::new();
    };

    let mut png = Vec::with_capacity(idat_data.len() + 64);
    png.extend_from_slice(b"\x89PNG\r\n\x1a\n");

    let mut ihdr = Vec::with_capacity(13);
    ihdr.extend_from_slice(&(img_size as u32).to_be_bytes());
    ihdr.extend_from_slice(&(img_size as u32).to_be_bytes());
    ihdr.push(8); // Bit depth: 8-bit
    ihdr.push(0); // Color type: 0 (Grayscale)
    ihdr.push(0); // Compression method: 0 (Deflate)
    ihdr.push(0); // Filter method: 0
    ihdr.push(0); // Interlace method: 0 (None)
    write_png_chunk(&mut png, b"IHDR", &ihdr);
    write_png_chunk(&mut png, b"IDAT", &idat_data);
    write_png_chunk(&mut png, b"IEND", &[]);

    png
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

/// Request payload for generating a NIP-57 Lightning Zap BOLT-11 invoice from the `/sos` portal.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SosZapInvoiceRequest {
    /// Zap amount in satoshis (must be >= `min_sats_warning`).
    pub amount_sats: u64,
    /// Alert message to embed inside the signed `Kind 9734` Zap Request.
    pub message: String,
    /// Optional dynamic recipient Lightning Address (`user@domain`) or LNURLp URL from the `/sos` form.
    /// Falls back to `[nostr.profile] lud16` when omitted or empty.
    #[serde(default)]
    pub lud16: Option<String>,
    /// Optional sender name, callsign, or location.
    #[serde(default)]
    pub sender: Option<String>,
    /// Optional emergency category tag.
    #[serde(default)]
    pub category: Option<String>,
    /// Optional 0xChat recipient `npub1...` or hex pubkey for direct NIP-17 Gift Wrap delivery upon settlement.
    #[serde(default)]
    pub recipient_npub: Option<String>,
    /// Optional Nostr PIN when `[sos] nostr_pin` is active.
    #[serde(default)]
    pub nostr_pin: Option<String>,
    /// Signed CAPTCHA token obtained from `/api/v1/sos/challenge`.
    #[serde(default)]
    pub captcha_token: Option<String>,
    /// User's 4-digit answer to the visual CAPTCHA.
    #[serde(default)]
    pub captcha_answer: Option<String>,
}

/// Response returned by `POST /api/v1/sos/zap-invoice`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SosZapInvoiceResponse {
    pub status: String,
    pub bolt11: String,
    pub bolt11_qr_svg: String,
    pub qr_png_url: String,
    pub zap_request_id: String,
    pub amount_sats: u64,
    pub severity: String,
    pub target_pubkey: String,
}

/// Request payload for `POST /api/v1/sos/zap-send-oxchat` to forward a generated Zap QR code & BOLT-11 invoice to 0xChat.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SosZapSendOxChatRequest {
    pub zap_request_id: String,
    #[serde(default)]
    pub recipient_npub: Option<String>,
    #[serde(default)]
    pub nostr_pin: Option<String>,
    #[serde(default)]
    pub public_origin: Option<String>,
}

/// Resolves a `lud16` Lightning Address (`user@domain`) or direct HTTP(S) LNURLp URL into a well-known LNURLp metadata URL.
pub fn resolve_lud16_lnurlp_url(lud16: &str) -> std::result::Result<String, String> {
    let clean = lud16.trim();
    if clean.is_empty() {
        return Err("Please enter a destination Lightning Address (e.g. user@wallet.com) or configure [nostr.profile] lud16.".to_string());
    }
    if clean.starts_with("https://") || clean.starts_with("http://") {
        return Ok(clean.to_string());
    }
    let Some((user, domain)) = clean.split_once('@') else {
        return Err(format!(
            "Invalid lud16 format '{}': expected 'user@domain'",
            clean
        ));
    };
    let user = user.trim();
    let domain = domain.trim();
    if user.is_empty() || domain.is_empty() {
        return Err(format!("Invalid lud16 format '{}'", clean));
    }
    let scheme = if domain.starts_with("127.0.0.1")
        || domain.starts_with("localhost")
        || domain.starts_with("[::1]")
    {
        "http"
    } else {
        "https"
    };
    Ok(format!("{}://{}/.well-known/lnurlp/{}", scheme, domain, user))
}

/// Minimal percent-encoder for query parameter values (RFC 3986 unreserved characters).
fn url_encode_param(input: &str) -> String {
    let mut out = String::with_capacity(input.len() * 2);
    for &b in input.as_bytes() {
        if b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.' | b'~') {
            out.push(b as char);
        } else {
            out.push_str(&format!("%{:02X}", b));
        }
    }
    out
}

/// Builds and signs a canonical NIP-57 `Kind 9734` Zap Request using an ephemeral secp256k1 keypair.
pub fn build_signed_zap_request_9734(
    target_pubkey_hex: &str,
    amount_msats: u64,
    relays: &[String],
    content: &str,
    lud16: Option<&str>,
    custom_recipient_hex: Option<&str>,
) -> NostrEvent {
    use secp256k1::{Keypair, Secp256k1};
    let secp = Secp256k1::new();
    let mut rng = secp256k1::rand::rngs::OsRng;
    let kp = Keypair::new(&secp, &mut rng);
    let (xonly, _) = kp.x_only_public_key();
    let pubkey_hex = hex::encode(xonly.serialize());
    let created_at = crate::time_sync::now_utc_secs().max(0) as u64;

    let mut relays_tag = vec!["relays".to_string()];
    if relays.is_empty() {
        relays_tag.push("ws://127.0.0.1:8088".to_string());
    } else {
        for r in relays {
            relays_tag.push(r.clone());
        }
    }

    let mut tags = vec![
        relays_tag,
        vec!["amount".to_string(), amount_msats.to_string()],
        vec!["p".to_string(), target_pubkey_hex.trim().to_lowercase()],
    ];

    if let Some(l) = lud16.map(|s| s.trim()).filter(|s| !s.is_empty()) {
        tags.push(vec!["lnurl".to_string(), l.to_string()]);
    }
    if let Some(rec) = custom_recipient_hex.map(|s| s.trim()).filter(|s| !s.is_empty()) {
        tags.push(vec!["recipient_npub".to_string(), rec.to_lowercase()]);
    }

    let serialized = serde_json::to_string(&serde_json::json!([
        0,
        pubkey_hex,
        created_at,
        9734u64,
        tags,
        content
    ]))
    .expect("serialize Kind 9734");

    let id_bytes = Sha256::digest(serialized.as_bytes());
    let id_hex = hex::encode(id_bytes);
    let sig = secp.sign_schnorr(id_bytes.as_slice(), &kp);

    NostrEvent {
        id: id_hex,
        pubkey: pubkey_hex,
        created_at,
        kind: 9734,
        tags,
        content: content.to_string(),
        sig: hex::encode(sig.as_ref()),
    }
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

/// HTTP POST handler (`/api/v1/sos/zap-invoice`) that constructs a signed NIP-57 `Kind 9734` Zap Request,
/// resolves the node's `lud16` LNURLp callback, and returns a BOLT-11 invoice + inline SVG QR code.
pub async fn sos_zap_invoice_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(req): Json<SosZapInvoiceRequest>,
) -> Response {
    let app_cfg = state.engine.config();
    if !app_cfg.sos.enabled || !app_cfg.sos.zap_enabled || !app_cfg.nostr.zaps.enabled {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "error",
                "message": "NIP-57 Lightning Zap alerts are not enabled on this node."
            })),
        )
            .into_response();
    }

    if let Err(resp) = check_sos_auth(&headers, app_cfg) {
        return *resp;
    }

    let Some(severity) = app_cfg.nostr.zaps.classify_severity(req.amount_sats) else {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "status": "error",
                "message": format!(
                    "Zap amount must be at least {} sats (minimum anti-spam threshold).",
                    app_cfg.nostr.zaps.min_sats_warning
                )
            })),
        )
            .into_response();
    };

    let clean_msg = req.message.trim();
    if clean_msg.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "status": "error",
                "message": "Alert message cannot be empty."
            })),
        )
            .into_response();
    }
    if clean_msg.len() > 500 {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "status": "error",
                "message": "Message is too long (maximum 500 characters)."
            })),
        )
            .into_response();
    }

    // Validate optional custom Nostr recipient npub & PIN if provided
    let resolved_dm_recipient = if let Some(raw_npub) = req
        .recipient_npub
        .as_deref()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        if !verify_nostr_pin(app_cfg, req.nostr_pin.as_deref()) {
            return (
                StatusCode::FORBIDDEN,
                Json(serde_json::json!({
                    "status": "error",
                    "message": "Valid Nostr PIN is required to attach a custom 0xChat recipient."
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

    // Validate CAPTCHA if enabled
    if app_cfg.sos.captcha_enabled {
        let token = req.captcha_token.as_deref().unwrap_or_default();
        let answer = req.captcha_answer.as_deref().unwrap_or_default();
        if let Err(err_msg) = verify_captcha_challenge(token, answer) {
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

    let lud16 = req
        .lud16
        .as_deref()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .or_else(|| {
            app_cfg
                .nostr
                .profile
                .lud16
                .as_deref()
                .map(|s| s.trim())
                .filter(|s| !s.is_empty())
        })
        .unwrap_or("");
    let lnurlp_url = match resolve_lud16_lnurlp_url(lud16) {
        Ok(u) => u,
        Err(e) => {
            return (
                StatusCode::BAD_REQUEST,
                Json(serde_json::json!({
                    "status": "error",
                    "message": e
                })),
            )
                .into_response();
        }
    };

    let formatted_text = format_sos_alert_text(
        req.category.as_deref(),
        req.sender.as_deref(),
        clean_msg,
        &app_cfg.daemon.name,
    );

    let my_pubkey = state.engine.nostr_publisher().public_key();
    let target_pubkey = app_cfg.nostr.zaps.resolved_target_pubkey(my_pubkey);
    let amount_msats = req.amount_sats.saturating_mul(1000);

    let mut relays: Vec<String> = app_cfg
        .nostr
        .relays
        .iter()
        .filter(|r| !r.contains("127.0.0.1") && !r.contains("localhost"))
        .cloned()
        .collect();
    if let Some(ref pub_relay) = app_cfg.sos.public_relay_url
        && !pub_relay.trim().is_empty()
        && !relays.contains(pub_relay)
    {
        relays.insert(0, pub_relay.trim().to_string());
    }
    for well_known in ["wss://nos.lol", "wss://relay.primal.net"] {
        if !relays.iter().any(|r| r == well_known) {
            relays.push(well_known.to_string());
        }
    }

    let zap_req_event = build_signed_zap_request_9734(
        &target_pubkey,
        amount_msats,
        &relays,
        &formatted_text,
        Some(lud16),
        resolved_dm_recipient.as_deref(),
    );
    let zap_request_id = zap_req_event.id.clone();
    let zap_req_json = match serde_json::to_string(&zap_req_event) {
        Ok(j) => j,
        Err(e) => {
            return (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("Failed to serialize Kind 9734 Zap Request: {}", e)
                })),
            )
                .into_response();
        }
    };

    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(8))
        .build()
        .unwrap_or_default();

    // Step 1: Query LNURLp discovery document
    let meta_resp = match client.get(&lnurlp_url).send().await {
        Ok(r) => r,
        Err(e) => {
            warn!("⚠️ [SOS Zap] Failed to reach LNURLp endpoint '{}': {}", lnurlp_url, e);
            return (
                StatusCode::BAD_GATEWAY,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("Failed to query Lightning Address provider: {}", e)
                })),
            )
                .into_response();
        }
    };

    let meta_json: serde_json::Value = match meta_resp.json().await {
        Ok(v) => v,
        Err(e) => {
            return (
                StatusCode::BAD_GATEWAY,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("Invalid LNURLp discovery JSON from provider: {}", e)
                })),
            )
                .into_response();
        }
    };

    if meta_json.get("allowsNostr").and_then(|v| v.as_bool()) == Some(false) {
        return (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({
                "status": "error",
                "message": "Configured Lightning Address provider does not support NIP-57 Nostr Zaps (allowsNostr = false)."
            })),
        )
            .into_response();
    }

    let Some(callback_url) = meta_json.get("callback").and_then(|v| v.as_str()) else {
        return (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({
                "status": "error",
                "message": "LNURLp discovery response missing required 'callback' URL."
            })),
        )
            .into_response();
    };

    // Step 2: Request BOLT-11 invoice from LNURLp callback with signed Kind 9734 event
    let sep = if callback_url.contains('?') { '&' } else { '?' };
    let invoice_req_url = format!(
        "{}{}amount={}&nostr={}",
        callback_url,
        sep,
        amount_msats,
        url_encode_param(&zap_req_json)
    );

    let inv_resp = match client.get(&invoice_req_url).send().await {
        Ok(r) => r,
        Err(e) => {
            warn!("⚠️ [SOS Zap] Failed to call LNURLp callback '{}': {}", callback_url, e);
            return (
                StatusCode::BAD_GATEWAY,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("Failed to request BOLT-11 invoice from callback: {}", e)
                })),
            )
                .into_response();
        }
    };

    let inv_json: serde_json::Value = match inv_resp.json().await {
        Ok(v) => v,
        Err(e) => {
            return (
                StatusCode::BAD_GATEWAY,
                Json(serde_json::json!({
                    "status": "error",
                    "message": format!("Invalid JSON from LNURLp callback: {}", e)
                })),
            )
                .into_response();
        }
    };

    let Some(bolt11) = inv_json
        .get("pr")
        .and_then(|v| v.as_str())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
    else {
        let reason = inv_json
            .get("reason")
            .and_then(|v| v.as_str())
            .unwrap_or("Provider did not return a 'pr' BOLT-11 invoice.");
        return (
            StatusCode::BAD_GATEWAY,
            Json(serde_json::json!({
                "status": "error",
                "message": reason
            })),
        )
            .into_response();
    };

    let bolt11_qr_svg = generate_qr_svg(&bolt11.to_uppercase());
    let severity_str = format!("{:?}", severity).to_lowercase();
    let qr_png_url = format!("/api/v1/sos/zap-qr/{}.png", zap_request_id);

    // Cache invoice for `.png` QR downloads and 0xChat forwarding
    {
        let sec = get_security_state();
        let mut cache = sec.zap_invoices.lock().unwrap();
        if cache.len() >= MAX_CACHED_ZAP_INVOICES {
            cache.pop_front();
        }
        cache.push_back(CachedZapInvoice {
            zap_request_id: zap_request_id.clone(),
            bolt11: bolt11.clone(),
            amount_sats: req.amount_sats,
            severity: severity_str.clone(),
            lud16: lud16.to_string(),
            summary: formatted_text,
            created_at: crate::time_sync::now_utc_secs(),
        });
    }

    info!(
        "⚡ [SOS Portal] Generated NIP-57 Zap BOLT-11 invoice ({} sats -> {}) [zap_req: {}]",
        req.amount_sats,
        severity_str,
        &zap_request_id[..8.min(zap_request_id.len())]
    );

    (
        StatusCode::OK,
        Json(SosZapInvoiceResponse {
            status: "ok".to_string(),
            bolt11,
            bolt11_qr_svg,
            qr_png_url,
            zap_request_id,
            amount_sats: req.amount_sats,
            severity: severity_str,
            target_pubkey,
        }),
    )
        .into_response()
}

/// HTTP GET handler (`/api/v1/sos/zap-qr/{id}`) serving a crisp `image/png` QR code for a cached
/// BOLT-11 Zap invoice (`{zap_request_id}.png`) or the node's Bot `npub` (`bot-npub.png`).
/// Enables 0xChat inline image rendering, mobile gallery saving, and Web Share API sharing.
pub async fn sos_zap_qr_png_handler(
    Path(raw_id): Path<String>,
    State(state): State<AppState>,
) -> Response {
    let clean_id = raw_id.trim().trim_end_matches(".png");
    if clean_id.is_empty() || clean_id.len() > 128 {
        return (StatusCode::BAD_REQUEST, "Invalid QR identifier").into_response();
    }

    let (qr_payload, filename) = if clean_id == "bot-npub" {
        let app_cfg = state.engine.config();
        if !app_cfg.sos.enabled || !app_cfg.sos.nostr_dm_enabled {
            return (StatusCode::NOT_FOUND, "Bot QR unavailable").into_response();
        }
        let npub = state.engine.nostr_publisher().public_key_npub();
        (npub, "openalert-bot-npub-qr.png".to_string())
    } else {
        let sec = get_security_state();
        let found = {
            let cache = sec.zap_invoices.lock().unwrap();
            cache
                .iter()
                .rev()
                .find(|inv| inv.zap_request_id == clean_id)
                .cloned()
        };
        let Some(inv) = found else {
            return (StatusCode::NOT_FOUND, "Zap invoice QR expired or not found").into_response();
        };
        (
            inv.bolt11.to_uppercase(),
            format!("openalert-zap-{}sats-qr.png", inv.amount_sats),
        )
    };

    let png_bytes = generate_qr_png(&qr_payload);
    if png_bytes.is_empty() {
        return (
            StatusCode::INTERNAL_SERVER_ERROR,
            "Failed to render QR PNG",
        )
            .into_response();
    }

    let disp = format!("inline; filename=\"{}\"", filename);
    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "image/png".to_string()),
            (header::CACHE_CONTROL, "public, max-age=900".to_string()),
            (header::CONTENT_DISPOSITION, disp),
        ],
        png_bytes,
    )
        .into_response()
}

/// HTTP POST handler (`/api/v1/sos/zap-send-oxchat`) that dispatches the generated BOLT-11 QR code (`.png` URL)
/// and raw BOLT-11 invoice string directly to 0xChat via encrypted NIP-17 Gift Wrap (`Kind 1059`).
pub async fn sos_zap_send_oxchat_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
    Json(req): Json<SosZapSendOxChatRequest>,
) -> Response {
    let app_cfg = state.engine.config();
    if !app_cfg.sos.enabled || !app_cfg.sos.zap_enabled {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "error",
                "message": "SOS Zap endpoint is disabled."
            })),
        )
            .into_response();
    }

    if let Err(resp) = check_sos_auth(&headers, app_cfg) {
        return *resp;
    }

    let clean_id = req.zap_request_id.trim().trim_end_matches(".png");
    let found_inv = {
        let sec = get_security_state();
        let cache = sec.zap_invoices.lock().unwrap();
        cache
            .iter()
            .rev()
            .find(|inv| inv.zap_request_id == clean_id)
            .cloned()
    };

    let Some(inv) = found_inv else {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({
                "status": "error",
                "message": "Zap invoice not found or expired. Please generate a new invoice."
            })),
        )
            .into_response();
    };

    let mut recipients = state
        .engine
        .nostr_publisher()
        .get_oxchat_subscribers()
        .await;

    if let Some(raw_npub) = req
        .recipient_npub
        .as_deref()
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
    {
        if !verify_nostr_pin(app_cfg, req.nostr_pin.as_deref()) {
            return (
                StatusCode::FORBIDDEN,
                Json(serde_json::json!({
                    "status": "error",
                    "message": "Valid Nostr PIN is required to send to a custom 0xChat recipient."
                })),
            )
                .into_response();
        }
        match parse_recipient_pubkey_hex(raw_npub) {
            Ok(hex_pk) => {
                let _ = state
                    .engine
                    .nostr_publisher()
                    .register_oxchat_subscriber(&hex_pk)
                    .await;
                if !recipients.contains(&hex_pk) {
                    recipients.push(hex_pk);
                }
            }
            Err(err_msg) => {
                return (
                    StatusCode::BAD_REQUEST,
                    Json(serde_json::json!({
                        "status": "error",
                        "message": format!("Invalid 0xChat recipient key: {}", err_msg)
                    })),
                )
                    .into_response();
            }
        }
    }

    if recipients.is_empty() {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "status": "error",
                "message": "No active 0xChat subscriber found. Enter your npub1... in Section '🔐 0xChat / Nostr Encrypted DM' or message the Bot in 0xChat first."
            })),
        )
            .into_response();
    }

    // Resolve public HTTP(S) origin so 0xChat can fetch and render the `.png` QR code inline
    let base_origin = req
        .public_origin
        .as_deref()
        .map(|s| s.trim().trim_end_matches('/').to_string())
        .filter(|s| {
            (s.starts_with("https://") || s.starts_with("http://"))
                && !s.contains("127.0.0.1")
                && !s.contains("localhost")
        })
        .or_else(|| {
            app_cfg.sos.public_relay_url.as_deref().and_then(|r| {
                let clean = r.trim();
                if let Some(rest) = clean.strip_prefix("wss://") {
                    let host = rest.split('/').next()?;
                    Some(format!("https://{}", host))
                } else if let Some(rest) = clean.strip_prefix("ws://") {
                    let host = rest.split('/').next()?;
                    Some(format!("http://{}", host))
                } else {
                    None
                }
            })
        })
        .or_else(|| {
            req.public_origin
                .as_deref()
                .map(|s| s.trim().trim_end_matches('/').to_string())
                .filter(|s| s.starts_with("https://") || s.starts_with("http://"))
        })
        .unwrap_or_else(|| "https://py-phone-caller.link".to_string());

    let qr_url = if base_origin.ends_with(".png") {
        base_origin
    } else {
        format!("{}/api/v1/sos/zap-qr/{}.png", base_origin, inv.zap_request_id)
    };

    let dm_card = format!(
        "⚡ [LIGHTNING ZAP INVOICE] {} sats ({} Tier)\nRecipient: {}\nAlert: {}\n\n📷 Scan QR Code or copy the next message to pay:\n{}",
        inv.amount_sats,
        inv.severity.to_uppercase(),
        inv.lud16,
        inv.summary,
        qr_url
    );

    let mut delivered = 0usize;
    for rec in &recipients {
        if state
            .engine
            .nostr_publisher()
            .send_oxchat_c2_response(rec, &dm_card)
            .await
            .is_ok()
        {
            // Also send the standalone BOLT-11 string in its own bubble so the user can 1-tap Copy in 0xChat
            let _ = state
                .engine
                .nostr_publisher()
                .send_oxchat_c2_response(rec, &inv.bolt11)
                .await;
            delivered += 1;
        }
    }

    info!(
        "📲 [SOS Zap -> 0xChat] Sent QR PNG ({}) & BOLT-11 invoice [{}] to {} 0xChat subscriber(s)",
        qr_url,
        &inv.zap_request_id[..8.min(inv.zap_request_id.len())],
        delivered
    );

    (
        StatusCode::OK,
        Json(serde_json::json!({
            "status": "ok",
            "recipients_count": delivered,
            "qr_url": qr_url
        })),
    )
        .into_response()
}

/// HTTP GET handler (`/api/v1/sos/zap-status/{zap_request_id}`) polled by the `/sos` browser UI
/// to detect when the corresponding `Kind 9735` Zap Receipt has been cryptographically verified.
pub async fn sos_zap_status_handler(
    Path(zap_request_id): Path<String>,
    State(state): State<AppState>,
) -> Response {
    let clean_id = zap_request_id.trim();
    if clean_id.is_empty() || clean_id.len() > 128 {
        return (
            StatusCode::BAD_REQUEST,
            Json(serde_json::json!({
                "status": "error",
                "message": "Invalid zap_request_id"
            })),
        )
            .into_response();
    }

    let settled = state
        .engine
        .has_seen_dedup_key(&format!("zap-req:{}", clean_id))
        .await;

    (
        StatusCode::OK,
        Json(serde_json::json!({
            "status": "ok",
            "zap_request_id": clean_id,
            "settled": settled
        })),
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
    let severity = AlertSeverity::parse_str(app_cfg.sos.default_severity.trim());

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

    let zap_active = app_cfg.sos.zap_enabled && app_cfg.nostr.zaps.enabled;
    let default_lud16 = app_cfg
        .nostr
        .profile
        .lud16
        .as_deref()
        .map(|s| s.trim())
        .unwrap_or("");

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
        zap_active,
        default_lud16,
        app_cfg.nostr.zaps.min_sats_warning,
        app_cfg.nostr.zaps.min_sats_critical,
        app_cfg.nostr.zaps.min_sats_emergency,
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
    zap_active: bool,
    default_lud16: &str,
    min_sats_warning: u64,
    min_sats_critical: u64,
    min_sats_emergency: u64,
) -> String {
    let captcha_display = if captcha_enabled { "block" } else { "none" };
    let gps_btn_display = if gps_enabled { "inline-flex" } else { "none" };
    let nostr_section_display = if nostr_dm_enabled { "block" } else { "none" };
    let pin_lock_display = if pin_required { "block" } else { "none" };
    let nostr_unlocked_display = if pin_required { "none" } else { "block" };
    let relay_row_display = if initial_relay_url.is_empty() { "none" } else { "block" };
    let zap_section_display = if zap_active { "block" } else { "none" };

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
      --amber: #f59e0b;
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
    .zap-details {{
      display: {zap_section_display};
      margin-top: 1.15rem;
      background: rgba(245, 158, 11, 0.07);
      border: 1px solid rgba(245, 158, 11, 0.35);
      border-radius: 12px;
      padding: 0.85rem 0.95rem;
    }}
    .nostr-summary, .zap-summary {{
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
    .zap-summary {{
      color: #fcd34d;
    }}
    .nostr-summary::-webkit-details-marker, .zap-summary::-webkit-details-marker {{ display: none; }}
    .nostr-body, .zap-body {{
      margin-top: 0.75rem;
      padding-top: 0.75rem;
      border-top: 1px solid rgba(168, 85, 247, 0.2);
      font-size: 0.78rem;
      color: var(--muted);
    }}
    .zap-body {{
      border-top-color: rgba(245, 158, 11, 0.25);
    }}
    .zap-tiers {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 0.45rem;
      margin-top: 0.45rem;
      margin-bottom: 0.65rem;
    }}
    .zap-tier-btn {{
      background: var(--input-bg);
      color: #fde68a;
      border: 1px solid rgba(245, 158, 11, 0.35);
      border-radius: 8px;
      padding: 0.48rem 0.4rem;
      font-size: 0.74rem;
      font-weight: 700;
      cursor: pointer;
      text-align: center;
    }}
    .zap-tier-btn:hover, .zap-tier-btn.active {{
      background: rgba(245, 158, 11, 0.22);
      border-color: var(--amber);
    }}
    .zap-btn {{
      width: 100%;
      margin-top: 0.65rem;
      background: linear-gradient(135deg, #f59e0b, #d97706);
      color: #090d16;
      border: none;
      border-radius: 10px;
      padding: 0.75rem;
      font-size: 0.92rem;
      font-weight: 800;
      cursor: pointer;
    }}
    .zap-btn:disabled {{ opacity: 0.55; cursor: not-allowed; }}
    .mono-row {{
      display: flex;
      align-items: center;
      gap: 0.4rem;
      margin-top: 0.3rem;
      margin-bottom: 0.65rem;
    }}
    .qr-actions-row {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 0.4rem;
      width: 100%;
      margin-top: 0.35rem;
      margin-bottom: 0.35rem;
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
      text-decoration: none;
    }}
    .mini-btn:hover {{
      background: rgba(168, 85, 247, 0.35);
    }}
    .mini-btn:disabled {{
      opacity: 0.55;
      cursor: not-allowed;
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
      width: 224px;
      height: 224px;
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
              <div class="qr-actions-row" style="margin-top:0.55rem;">
                <button type="button" class="mini-btn" onclick="downloadQrFromUrl('/api/v1/sos/zap-qr/bot-npub.png', 'openalert-bot-npub-qr.png', this)">📥 Download QR</button>
                <button type="button" class="mini-btn" onclick="shareQrFromUrl('/api/v1/sos/zap-qr/bot-npub.png', 'openalert-bot-npub-qr.png', document.getElementById('botNpubBox').innerText, this)">📤 Share QR</button>
              </div>
              <div style="font-size:0.68rem;color:var(--muted);margin-top:0.35rem;">
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

    <details class="zap-details" id="zapDetails">
      <summary class="zap-summary">
        <span>⚡ Trigger Nostr Alert via Lightning Zap (NIP-57)</span>
        <span style="font-size:0.72rem;opacity:0.85;">Tap to open ▾</span>
      </summary>
      <div class="zap-body">
        <div style="margin-bottom:0.45rem;">
          Send a Proof-of-Payment Nostr &amp; 0xChat alert using Bitcoin Lightning (strictly Nostr-only; does not place phone/SMS calls):
        </div>
        <div class="zap-tiers">
          <button type="button" class="zap-tier-btn active" onclick="selectZapTier(this, {min_sats_warning})">⚡ {min_sats_warning} sats<br><span style="font-size:0.66rem;opacity:0.8;">Warning</span></button>
          <button type="button" class="zap-tier-btn" onclick="selectZapTier(this, {min_sats_critical})">⚡ {min_sats_critical} sats<br><span style="font-size:0.66rem;opacity:0.8;">Critical</span></button>
          <button type="button" class="zap-tier-btn" onclick="selectZapTier(this, {min_sats_emergency})">⚡ {min_sats_emergency} sats<br><span style="font-size:0.66rem;opacity:0.8;">Emergency</span></button>
        </div>
        <div style="margin-bottom:0.3rem;">Recipient Lightning Address (<code>user@domain</code>):</div>
        <input type="text" id="zapLud16" value="{default_lud16}" placeholder="e.g. yourwallet@walletofsatoshi.com or user@getalby.com" maxlength="160" style="padding:0.55rem 0.65rem;font-size:0.84rem;font-family:monospace;margin-bottom:0.6rem;">
        <div style="margin-bottom:0.3rem;">Custom Amount (satoshis, min {min_sats_warning}):</div>
        <input type="number" id="zapAmountSats" value="{min_sats_warning}" min="{min_sats_warning}" step="1" style="padding:0.55rem 0.65rem;font-size:0.9rem;font-family:monospace;">
        <button type="button" class="zap-btn" id="zapGenBtn" onclick="requestZapInvoice()">⚡ GENERATE LIGHTNING ZAP INVOICE</button>

        <div class="qr-card" id="zapInvoiceCard" style="margin-top:0.8rem;border-color:rgba(245,158,11,0.45);">
          <div style="font-size:0.76rem;color:#fde68a;margin-bottom:0.5rem;font-weight:700;" id="zapInvoiceTitle">
            Scan with Wallet of Satoshi, Phoenix, Zeus, or Alby
          </div>
          <div class="qr-svg-wrap" id="zapQrSvgWrap"></div>
          <div class="mono-row" style="width:100%;margin-top:0.65rem;margin-bottom:0.3rem;">
            <div class="mono-box" id="zapBolt11Box"></div>
            <button type="button" class="mini-btn" onclick="copyText('zapBolt11Box', this)">Copy</button>
            <a id="zapWalletLink" href="#" class="mini-btn" style="background:rgba(245,158,11,0.25);border-color:rgba(245,158,11,0.5);color:#fef3c7;">⚡ Wallet</a>
          </div>
          <div class="qr-actions-row">
            <button type="button" class="mini-btn" style="background:rgba(56,189,248,0.18);border-color:rgba(56,189,248,0.45);color:#e0f2fe;" onclick="downloadZapQrPng(this)">📥 Download QR</button>
            <button type="button" class="mini-btn" style="background:rgba(16,185,129,0.18);border-color:rgba(16,185,129,0.45);color:#d1fae5;" onclick="shareZapQrPng(this)">📤 Share QR</button>
            <button type="button" class="mini-btn" style="background:rgba(168,85,247,0.24);border-color:rgba(168,85,247,0.5);color:#f3e8ff;" onclick="sendZapQrToOxChat(this)">💬 Send to 0xChat</button>
          </div>
          <div id="zapPollStatus" style="font-size:0.74rem;color:#fcd34d;margin-top:0.3rem;">
            ⏳ Awaiting NIP-57 Kind 9735 Zap Receipt settlement...
          </div>
        </div>
      </div>
    </details>

    <div id="statusBanner" class="status-banner"></div>

    <div class="footer">
      OpenAlert Off-Grid LoRa / Mesh &amp; Nostr Emergency Terminal
    </div>
  </div>

  <script>
    let currentCategory = "GENERAL";
    let captchaToken = "";
    let unlockedPin = "";
    let zapPollTimer = null;
    let currentZapReqId = "";
    let currentZapQrPngUrl = "";
    let currentZapAmountSats = 0;
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

    function selectZapTier(btn, sats) {{
      document.querySelectorAll('.zap-tier-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('zapAmountSats').value = sats;
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

    async function downloadQrFromUrl(url, filename, btn) {{
      if (!url) return;
      const orig = btn ? btn.innerText : "";
      if (btn) btn.innerText = "⏳ Saving...";
      try {{
        const res = await fetch(url);
        if (!res.ok) throw new Error("Failed to fetch QR PNG");
        const blob = await res.blob();
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = blobUrl;
        a.download = filename || 'openalert-qr.png';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
        if (btn) {{
          btn.innerText = "✅ Saved!";
          setTimeout(() => {{ btn.innerText = orig; }}, 1800);
        }}
      }} catch (_) {{
        if (btn) {{
          btn.innerText = "⚠️ Error";
          setTimeout(() => {{ btn.innerText = orig; }}, 1800);
        }}
      }}
    }}

    async function shareQrFromUrl(url, filename, shareText, btn) {{
      if (!url) return;
      const orig = btn ? btn.innerText : "";
      try {{
        const res = await fetch(url);
        if (!res.ok) throw new Error("Failed to fetch QR PNG");
        const blob = await res.blob();
        const file = new File([blob], filename || 'openalert-qr.png', {{ type: 'image/png' }});
        if (navigator.canShare && navigator.canShare({{ files: [file] }})) {{
          await navigator.share({{
            title: 'OpenAlert QR Code',
            text: shareText || '',
            files: [file]
          }});
          return;
        }} else if (navigator.share) {{
          await navigator.share({{
            title: 'OpenAlert QR Code',
            text: shareText || window.location.origin + url,
            url: window.location.origin + url
          }});
          return;
        }}
        await downloadQrFromUrl(url, filename, btn);
      }} catch (err) {{
        if (err && err.name === 'AbortError') return;
        if (btn) {{
          btn.innerText = orig;
        }}
      }}
    }}

    function downloadZapQrPng(btn) {{
      if (!currentZapQrPngUrl) return;
      const fname = `openalert-zap-${{currentZapAmountSats || 21}}sats-qr.png`;
      downloadQrFromUrl(currentZapQrPngUrl, fname, btn);
    }}

    function shareZapQrPng(btn) {{
      if (!currentZapQrPngUrl) return;
      const bolt11 = document.getElementById('zapBolt11Box').innerText.trim();
      const fname = `openalert-zap-${{currentZapAmountSats || 21}}sats-qr.png`;
      shareQrFromUrl(currentZapQrPngUrl, fname, bolt11 ? `lightning:${{bolt11}}` : '', btn);
    }}

    async function sendZapQrToOxChat(btn) {{
      if (!currentZapReqId) return;
      const orig = btn.innerText;
      btn.disabled = true;
      btn.innerText = "⏳ Sending...";
      const recipientNpubEl = document.getElementById('recipientNpub');
      const recipientNpub = recipientNpubEl ? recipientNpubEl.value.trim() : '';
      const statusEl = document.getElementById('zapPollStatus');

      try {{
        const res = await fetch('/api/v1/sos/zap-send-oxchat', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            zap_request_id: currentZapReqId,
            recipient_npub: recipientNpub || null,
            nostr_pin: unlockedPin || null,
            public_origin: window.location.origin + currentZapQrPngUrl
          }})
        }});
        const data = await res.json();
        if (res.ok) {{
          btn.innerText = "✅ Sent to 0xChat!";
          statusEl.style.color = '#d8b4fe';
          statusEl.innerText = `📲 QR Code & BOLT-11 sent to ${{data.recipients_count || 1}} 0xChat subscriber(s)! Waiting for payment...`;
        }} else {{
          btn.innerText = "⚠️ Failed";
          statusEl.style.color = '#fda4af';
          statusEl.innerText = `⚠️ ${{data.message || 'Could not send to 0xChat'}}`;
        }}
      }} catch (_) {{
        btn.innerText = "⚠️ Error";
      }} finally {{
        btn.disabled = false;
        setTimeout(() => {{ btn.innerText = orig; }}, 2500);
      }}
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

    async function requestZapInvoice() {{
      const btn = document.getElementById('zapGenBtn');
      const banner = document.getElementById('statusBanner');
      const message = document.getElementById('message').value.trim();
      const sender = document.getElementById('sender').value.trim();
      const amountSats = parseInt(document.getElementById('zapAmountSats').value || '0', 10);
      const lud16El = document.getElementById('zapLud16');
      const lud16 = lud16El ? lud16El.value.trim() : '';
      const captchaAnswer = document.getElementById('captchaAnswer').value.trim();
      const recipientNpubEl = document.getElementById('recipientNpub');
      const recipientNpub = recipientNpubEl ? recipientNpubEl.value.trim() : '';

      if (!lud16) {{
        banner.className = 'status-banner status-err';
        banner.style.display = 'block';
        banner.innerText = '⚠️ Please enter a destination Lightning Address (e.g. user@wallet.com) in the Lightning Zap section.';
        return;
      }}
      if (!message) {{
        banner.className = 'status-banner status-err';
        banner.style.display = 'block';
        banner.innerText = '⚠️ Please enter an Emergency Message in section 3 before generating a Zap invoice.';
        return;
      }}
      if (captchaEnabled && captchaAnswer.length !== 4) {{
        banner.className = 'status-banner status-err';
        banner.style.display = 'block';
        banner.innerText = '⚠️ Please enter the 4-digit security code in section 4 first.';
        return;
      }}

      btn.disabled = true;
      btn.innerText = '⏳ REQUESTING BOLT-11 INVOICE...';
      banner.style.display = 'none';

      try {{
        const res = await fetch('/api/v1/sos/zap-invoice', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            amount_sats: amountSats,
            lud16: lud16 || null,
            message,
            sender: sender || null,
            category: currentCategory,
            recipient_npub: recipientNpub || null,
            nostr_pin: unlockedPin || null,
            captcha_token: captchaToken,
            captcha_answer: captchaAnswer
          }})
        }});
        const data = await res.json();
        await loadChallenge();
        if (res.ok) {{
          currentZapReqId = data.zap_request_id || '';
          currentZapQrPngUrl = `/api/v1/sos/zap-qr/${{data.zap_request_id}}.png`;
          currentZapAmountSats = data.amount_sats || amountSats;
          document.getElementById('zapQrSvgWrap').innerHTML = data.bolt11_qr_svg || '';
          document.getElementById('zapBolt11Box').innerText = data.bolt11 || '';
          document.getElementById('zapWalletLink').href = `lightning:${{data.bolt11}}`;
          document.getElementById('zapInvoiceTitle').innerText = `⚡ Pay ${{data.amount_sats}} sats (${{(data.severity || '').toUpperCase()}} Tier)`;
          const statusEl = document.getElementById('zapPollStatus');
          statusEl.style.color = '#fcd34d';
          statusEl.innerText = '⏳ Awaiting NIP-57 Kind 9735 Zap Receipt settlement...';
          document.getElementById('zapInvoiceCard').style.display = 'flex';
          startZapPolling(data.zap_request_id, data.amount_sats, data.severity);
        }} else {{
          banner.className = 'status-banner status-err';
          banner.style.display = 'block';
          banner.innerText = `❌ ${{data.message || 'Failed to generate Zap invoice'}}`;
        }}
      }} catch (err) {{
        banner.className = 'status-banner status-err';
        banner.style.display = 'block';
        banner.innerText = '❌ Network error requesting Lightning Zap invoice.';
      }} finally {{
        btn.disabled = false;
        btn.innerText = '⚡ GENERATE LIGHTNING ZAP INVOICE';
      }}
    }}

    function startZapPolling(zapReqId, amountSats, severity) {{
      if (zapPollTimer) clearInterval(zapPollTimer);
      zapPollTimer = setInterval(async () => {{
        try {{
          const res = await fetch(`/api/v1/sos/zap-status/${{encodeURIComponent(zapReqId)}}`, {{ cache: 'no-store' }});
          if (!res.ok) return;
          const data = await res.json();
          if (data.settled) {{
            clearInterval(zapPollTimer);
            zapPollTimer = null;
            const statusEl = document.getElementById('zapPollStatus');
            statusEl.style.color = '#6ee7b7';
            statusEl.innerHTML = `✅ <strong>Zap Settled &amp; Verified!</strong> (${{amountSats}} sats &rarr; ${{severity.toUpperCase()}} alert mirrored to Nostr &amp; 0xChat)`;
          }}
        }} catch (_) {{}}
      }}, 2000);
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

        // Test npub parsing and QR SVG + PNG generation
        let id = crate::cli::generate_keypair();
        let parsed_hex = parse_recipient_pubkey_hex(&id.npub).expect("valid npub");
        assert_eq!(parsed_hex, id.pub_hex);
        assert!(parse_recipient_pubkey_hex(&id.nsec).is_err());

        let qr_svg = generate_qr_svg(&id.npub);
        assert!(qr_svg.contains("<svg"));

        let qr_png = generate_qr_png(&id.npub);
        assert!(qr_png.starts_with(b"\x89PNG\r\n\x1a\n"));
        assert!(qr_png.windows(4).any(|w| w == b"IHDR"));
        assert!(qr_png.windows(4).any(|w| w == b"IDAT"));
        assert!(qr_png.windows(4).any(|w| w == b"IEND"));
    }

    #[test]
    fn test_lud16_resolution_and_kind_9734_builder() {
        assert_eq!(
            resolve_lud16_lnurlp_url("openalert@getalby.com").unwrap(),
            "https://getalby.com/.well-known/lnurlp/openalert"
        );
        assert_eq!(
            resolve_lud16_lnurlp_url("node@127.0.0.1:18080").unwrap(),
            "http://127.0.0.1:18080/.well-known/lnurlp/node"
        );
        assert_eq!(
            resolve_lud16_lnurlp_url("http://127.0.0.1:19000/lnurlp").unwrap(),
            "http://127.0.0.1:19000/lnurlp"
        );

        let target_pk = "11".repeat(32);
        let ev = build_signed_zap_request_9734(
            &target_pk,
            21000,
            &["ws://127.0.0.1:8088".to_string()],
            "Test Zap Alert",
            Some("openalert@getalby.com"),
            None,
        );
        assert_eq!(ev.kind, 9734);
        assert!(crate::ingress::nostr::verify_nostr_event_signature(&ev));
    }
}
