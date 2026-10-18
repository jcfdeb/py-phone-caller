//! # Off-Grid Authenticated LoRa Time Synchronization Engine
//!
//! Provides a 3-tier battery-friendly, cryptographically authenticated time synchronization
//! subsystem for off-grid ARM field nodes (e.g., Orange Pi Zero 3, Raspberry Pi Zero 2W)
//! operating without a battery-backed RTC or WAN/NTP connectivity:
//!
//! - **Tier 1 (Zero-Air-Time Piggybacking):** Extracts authenticated UTC timestamps from
//!   inbound XChaCha20-Poly1305 Gateway frames (`Alert`, `Ack`) with 0 extra radio packets.
//! - **Tier 2 (Cold-Boot Challenge-Response & Sparse 12h Beacon):** One-shot `TimeSyncReq` /
//!   `TimeSyncResp` with a 64-bit random anti-replay nonce on cold boot, plus an optional
//!   ultra-sparse 12-hour `TimeBeacon` ($< 0.00015\%$ EU868 duty cycle).
//! - **Tier 3 (Monotonic In-Process Offset & Optional `CAP_SYS_TIME` Kernel Step):**
//!   Maintains `CLOCK_OFFSET_MS: AtomicI64` for `now_utc_ms()` / `now_utc()` across Peering,
//!   BitChat BLE, and Alert timestamps, and optionally steps `CLOCK_REALTIME` via `libc::clock_settime`
//!   when skew exceeds 2 seconds and `CAP_SYS_TIME` is available.

use chrono::{DateTime, TimeZone, Utc};
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicBool, AtomicI64, AtomicU64, Ordering};
use std::sync::{OnceLock, RwLock};
use tracing::{debug, info, warn};

/// In-process monotonic clock offset in milliseconds (`T_true_utc_ms - T_os_realtime_ms`).
static CLOCK_OFFSET_MS: AtomicI64 = AtomicI64::new(0);

/// Highest authenticated gateway UTC timestamp (in ms) accepted so far (monotonicity anti-rollback guard).
static LAST_VERIFIED_SYNC_MS: AtomicI64 = AtomicI64::new(0);

/// Total number of authenticated time synchronization adjustments applied since daemon boot.
static SYNC_COUNT: AtomicU64 = AtomicU64::new(0);

/// Whether this node has achieved verified time synchronization (via radio peer or local NTP).
static SYNCHRONIZED: AtomicBool = AtomicBool::new(false);

/// Name of the authoritative peer that provided the latest time synchronization.
static LAST_SOURCE_PEER: OnceLock<RwLock<Option<String>>> = OnceLock::new();

fn last_source_lock() -> &'static RwLock<Option<String>> {
    LAST_SOURCE_PEER.get_or_init(|| RwLock::new(None))
}

/// Minimum plausible Unix timestamp in milliseconds (2025-01-01T00:00:00Z) used for sanity checks.
pub const MIN_PLAUSIBLE_UTC_MS: i64 = 1_735_689_600_000;

/// Threshold in milliseconds above which `clock_settime(CLOCK_REALTIME)` is attempted when enabled.
pub const STEP_SYSTEM_CLOCK_THRESHOLD_MS: i64 = 2_000;

/// Returns the raw OS system clock in milliseconds since Unix epoch (without offset).
#[inline]
pub fn os_now_utc_ms() -> i64 {
    Utc::now().timestamp_millis()
}

/// Returns the synchronized UTC timestamp in milliseconds (`SystemTime::now() + CLOCK_OFFSET_MS`).
#[inline]
pub fn now_utc_ms() -> i64 {
    os_now_utc_ms().saturating_add(CLOCK_OFFSET_MS.load(Ordering::Relaxed))
}

/// Returns the synchronized UTC timestamp in seconds.
#[inline]
pub fn now_utc_secs() -> i64 {
    now_utc_ms() / 1000
}

/// Returns the synchronized `chrono::DateTime<Utc>` accounting for `CLOCK_OFFSET_MS`.
#[inline]
pub fn now_utc() -> DateTime<Utc> {
    let ms = now_utc_ms();
    Utc.timestamp_millis_opt(ms)
        .single()
        .unwrap_or_else(Utc::now)
}

/// Returns the current in-process clock offset in milliseconds.
#[inline]
pub fn clock_offset_ms() -> i64 {
    CLOCK_OFFSET_MS.load(Ordering::Relaxed)
}

/// Returns whether the node clock is currently synchronized (via NTP or authenticated LoRa peer).
#[inline]
pub fn is_synchronized() -> bool {
    SYNCHRONIZED.load(Ordering::Relaxed) || is_os_clock_ntp_synced()
}

/// Queries the Linux kernel NTP discipline state via `adjtimex` to determine if the OS clock
/// is synchronized by an external NTP/PTP daemon (`systemd-timesyncd`, `chronyd`, `ntpd`).
pub fn is_os_clock_ntp_synced() -> bool {
    let os_ms = os_now_utc_ms();
    if os_ms < MIN_PLAUSIBLE_UTC_MS {
        return false;
    }

    #[cfg(target_os = "linux")]
    {
        // STA_UNSYNC (0x0040) is set by the kernel when the clock is not synchronized.
        const STA_UNSYNC: i32 = 0x0040;
        let mut tx: libc::timex = unsafe { std::mem::zeroed() };
        tx.modes = 0; // Read-only query
        let rc = unsafe { libc::adjtimex(&mut tx) };
        if rc >= 0 {
            return (tx.status & STA_UNSYNC) == 0;
        }
    }

    false
}

/// Seeds a minimum floor timestamp from persistent SQLite storage on cold boot so that
/// even before the first radio packet arrives, the node never regresses behind its last known shutdown time.
pub fn seed_persisted_timestamp_floor(persisted_utc_ms: i64) {
    if persisted_utc_ms < MIN_PLAUSIBLE_UTC_MS {
        return;
    }

    // Record monotonicity floor
    let _ = LAST_VERIFIED_SYNC_MS.fetch_max(persisted_utc_ms, Ordering::SeqCst);

    let current_os_ms = os_now_utc_ms();
    if current_os_ms < persisted_utc_ms {
        let fallback_offset = persisted_utc_ms - current_os_ms;
        CLOCK_OFFSET_MS.store(fallback_offset, Ordering::SeqCst);
        info!(
            "🕰️ [TimeSync Cold-Boot Floor] OS clock ({}) lagged persisted SQLite state ({}); applied initial +{}ms offset while awaiting LoRa sync",
            current_os_ms, persisted_utc_ms, fallback_offset
        );
    }
}

/// Applies an authenticated UTC timestamp (in milliseconds) received from an authoritative Gateway peer.
///
/// - Enforces monotonicity on passive updates (`is_challenge_response == false`) to prevent replay rollback.
/// - Compensates for one-way LoRa RF time-of-flight ($\text{EstimatedAirTime}_{\text{ms}} / 2$).
/// - Optionally steps the Linux kernel `CLOCK_REALTIME` if `step_system_clock` is true and $|\Delta t| > 2000\text{ ms}$.
/// - Returns `Some(applied_delta_ms)` if accepted, or `None` if rejected by sanity/monotonicity guards.
pub fn apply_verified_gateway_time(
    gateway_utc_ms: i64,
    estimated_air_time_ms: f64,
    source_peer: &str,
    step_system_clock: bool,
    is_challenge_response: bool,
) -> Option<i64> {
    if gateway_utc_ms < MIN_PLAUSIBLE_UTC_MS {
        warn!(
            "⚠️ [TimeSync] Ignored implausible gateway timestamp ({} ms) from '{}'",
            gateway_utc_ms, source_peer
        );
        return None;
    }

    let one_way_flight_ms = (estimated_air_time_ms / 2.0).round() as i64;
    let target_utc_ms = gateway_utc_ms.saturating_add(one_way_flight_ms);

    // Monotonicity anti-rollback check for passive beacons and piggybacked timestamps
    let prev_verified = LAST_VERIFIED_SYNC_MS.load(Ordering::SeqCst);
    if !is_challenge_response && prev_verified > 0 && target_utc_ms < prev_verified.saturating_sub(2_000) {
        warn!(
            "🛑 [TimeSync Anti-Rollback] Rejected stale passive timestamp {}ms from '{}' (last verified: {}ms)",
            target_utc_ms, source_peer, prev_verified
        );
        return None;
    }

    let os_ms = os_now_utc_ms();
    let prior_effective_ms = os_ms.saturating_add(CLOCK_OFFSET_MS.load(Ordering::Relaxed));
    let delta_from_effective_ms = target_utc_ms - prior_effective_ms;
    let raw_os_delta_ms = target_utc_ms - os_ms;

    let mut kernel_stepped = false;
    if step_system_clock && raw_os_delta_ms.abs() > STEP_SYSTEM_CLOCK_THRESHOLD_MS {
        kernel_stepped = try_step_linux_system_clock(target_utc_ms);
    }

    if kernel_stepped {
        CLOCK_OFFSET_MS.store(0, Ordering::SeqCst);
    } else {
        CLOCK_OFFSET_MS.store(raw_os_delta_ms, Ordering::SeqCst);
    }

    LAST_VERIFIED_SYNC_MS.store(target_utc_ms, Ordering::SeqCst);
    SYNCHRONIZED.store(true, Ordering::SeqCst);
    let count = SYNC_COUNT.fetch_add(1, Ordering::SeqCst) + 1;

    if let Ok(mut guard) = last_source_lock().write() {
        *guard = Some(source_peer.to_string());
    }

    if count == 1 || delta_from_effective_ms.abs() > 500 || is_challenge_response {
        info!(
            "⏱️ [LoRa TimeSync] Synchronized clock with '{}' (mode: {}, Δt: {:+}ms, air-time/2: +{}ms, kernel_stepped: {}, active_offset: {:+}ms)",
            source_peer,
            if is_challenge_response {
                "challenge-response"
            } else {
                "passive/piggyback"
            },
            delta_from_effective_ms,
            one_way_flight_ms,
            kernel_stepped,
            CLOCK_OFFSET_MS.load(Ordering::Relaxed)
        );
    } else {
        debug!(
            "⏱️ [LoRa TimeSync] Fine drift adjustment from '{}': Δt={:+}ms (active_offset: {:+}ms)",
            source_peer,
            delta_from_effective_ms,
            CLOCK_OFFSET_MS.load(Ordering::Relaxed)
        );
    }

    Some(delta_from_effective_ms)
}

#[cfg(target_os = "linux")]
fn try_step_linux_system_clock(target_utc_ms: i64) -> bool {
    let secs = (target_utc_ms / 1000) as libc::time_t;
    let nsecs = ((target_utc_ms % 1000).unsigned_abs() * 1_000_000) as libc::c_long;
    let ts = libc::timespec {
        tv_sec: secs,
        tv_nsec: nsecs,
    };

    let rc = unsafe { libc::clock_settime(libc::CLOCK_REALTIME, &ts) };
    if rc == 0 {
        info!(
            "🕰️ [TimeSync Kernel Step] Stepped Linux CLOCK_REALTIME to {} ({} ms)",
            Utc.timestamp_millis_opt(target_utc_ms)
                .single()
                .map(|dt| dt.to_rfc3339())
                .unwrap_or_else(|| target_utc_ms.to_string()),
            target_utc_ms
        );
        true
    } else {
        debug!(
            "TimeSync kernel clock_settime skipped (CAP_SYS_TIME not granted or ProtectClock=yes); using in-process AtomicI64 offset"
        );
        false
    }
}

#[cfg(not(target_os = "linux"))]
fn try_step_linux_system_clock(_target_utc_ms: i64) -> bool {
    false
}

/// Live telemetry snapshot of the off-grid LoRa time synchronization subsystem.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimeSyncStatusReport {
    pub enabled: bool,
    pub role: String,
    pub synchronized: bool,
    pub os_ntp_synchronized: bool,
    pub clock_offset_ms: i64,
    pub current_utc: DateTime<Utc>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_verified_sync_utc: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub last_source_peer: Option<String>,
    pub sync_count: u64,
    pub effective_skew_tolerance_secs: u64,
}

/// Builds a diagnostic report for `/api/v1/status` and `/api/v1/peers`.
pub fn get_status_report(
    enabled: bool,
    role: &str,
    effective_skew_tolerance_secs: u64,
) -> TimeSyncStatusReport {
    let last_ms = LAST_VERIFIED_SYNC_MS.load(Ordering::Relaxed);
    let last_verified_sync_utc = if last_ms > 0 {
        Utc.timestamp_millis_opt(last_ms).single()
    } else {
        None
    };

    let last_source_peer = last_source_lock()
        .read()
        .ok()
        .and_then(|g| g.clone());

    TimeSyncStatusReport {
        enabled,
        role: role.to_string(),
        synchronized: is_synchronized(),
        os_ntp_synchronized: is_os_clock_ntp_synced(),
        clock_offset_ms: clock_offset_ms(),
        current_utc: now_utc(),
        last_verified_sync_utc,
        last_source_peer,
        sync_count: SYNC_COUNT.load(Ordering::Relaxed),
        effective_skew_tolerance_secs,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_time_sync_offset_and_monotonic_guard() {
        let base_os = os_now_utc_ms();
        let simulated_gw_ms = base_os + 60_000; // Gateway is +60s ahead

        // 1. Apply challenge-response sync (+60s, 100ms air time -> +50ms flight)
        let delta = apply_verified_gateway_time(simulated_gw_ms, 100.0, "gw-node01", false, true);
        assert!(delta.is_some());
        assert!(is_synchronized());
        assert!((clock_offset_ms() - 60_050).abs() < 200);

        // 2. Attempt passive rollback attack (-30s older than last verified sync) -> must be rejected
        let stale_gw_ms = simulated_gw_ms - 30_000;
        let rollback = apply_verified_gateway_time(stale_gw_ms, 100.0, "gw-node01", false, false);
        assert!(rollback.is_none(), "Passive rollback must be rejected");

        // 3. Subsequent forward passive timestamp (+5s) -> must be accepted
        let newer_gw_ms = simulated_gw_ms + 5_000;
        let forward = apply_verified_gateway_time(newer_gw_ms, 100.0, "gw-node01", false, false);
        assert!(forward.is_some(), "Forward passive sync must be accepted");

        // Reset offset for other tests
        CLOCK_OFFSET_MS.store(0, Ordering::SeqCst);
        LAST_VERIFIED_SYNC_MS.store(0, Ordering::SeqCst);
    }
}
