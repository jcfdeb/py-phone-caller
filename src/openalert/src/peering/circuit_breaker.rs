//! # Asymmetric Circuit Breaker for Peering Links
//!
//! Provides link-aware fault isolation:
//! - **Profile B (LAN/VPN):** Active Canary ARQ probes during `HalfOpen` awaiting acknowledgments.
//! - **Profile A (LoRa / Radio):** Optimistic Socket Health verification without requiring radio ACKs,
//!   preserving strict European 868 MHz 1% Duty Cycle compliance.

use crate::config::PeeringLinkType;
use serde::{Deserialize, Serialize};
use std::time::{Duration, Instant};
use tracing::{info, warn};

/// Operational states of the peer circuit breaker.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitState {
    /// Traffic enabled normally under designated link retry profile.
    Closed,
    /// Traffic blocked due to consecutive failures; alerts spooled directly to SQLite.
    Open,
    /// Probing channel recovery (Canary ARQ for IP, optimistic socket check for LoRa).
    HalfOpen,
}

/// Link-aware circuit breaker protecting bandwidth-constrained and radio interfaces.
#[derive(Debug)]
pub struct PeeringCircuitBreaker {
    peer_name: String,
    link_type: PeeringLinkType,
    state: CircuitState,
    consecutive_failures: u32,
    failure_threshold: u32,
    base_cooldown: Duration,
    max_cooldown: Duration,
    current_cooldown: Duration,
    last_state_change: Instant,
    canary_timeout: Duration,
    canary_in_flight: bool,
}

impl PeeringCircuitBreaker {
    /// Creates a new circuit breaker initialized in the `Closed` state.
    pub fn new(
        peer_name: String,
        link_type: PeeringLinkType,
        failure_threshold: u32,
        base_cooldown_secs: u64,
        max_cooldown_secs: u64,
        canary_timeout_ms: u64,
    ) -> Self {
        let base_cooldown = Duration::from_secs(base_cooldown_secs);
        let max_cooldown = Duration::from_secs(max_cooldown_secs);
        let canary_timeout = Duration::from_millis(canary_timeout_ms);

        Self {
            peer_name,
            link_type,
            state: CircuitState::Closed,
            consecutive_failures: 0,
            failure_threshold,
            base_cooldown,
            max_cooldown,
            current_cooldown: base_cooldown,
            last_state_change: Instant::now(),
            canary_timeout,
            canary_in_flight: false,
        }
    }

    /// Evaluates if an outbound transmission is permitted.
    ///
    /// Automatically advances `Open` to `HalfOpen` when the cooldown duration has expired.
    pub fn can_send(&mut self) -> bool {
        let now = Instant::now();
        match self.state {
            CircuitState::Closed => true,
            CircuitState::Open => {
                if now.duration_since(self.last_state_change) >= self.current_cooldown {
                    info!(
                        "⏱️ Circuit Breaker for peer '{}' [{:?}]: Cooldown ({:?}) elapsed. Advancing to HALF-OPEN",
                        self.peer_name, self.link_type, self.current_cooldown
                    );
                    self.state = CircuitState::HalfOpen;
                    self.last_state_change = now;
                    self.canary_in_flight = false;
                    true
                } else {
                    false
                }
            }
            CircuitState::HalfOpen => {
                match self.link_type {
                    // Radio / LoRa: Optimistic transmission without ACKs
                    PeeringLinkType::Lora | PeeringLinkType::LoraSerial => true,
                    // LAN / VPN: Permit single canary probe at a time
                    PeeringLinkType::Lan | PeeringLinkType::Vpn => !self.canary_in_flight,
                }
            }
        }
    }

    /// Marks that a canary probe has been dispatched over the network.
    pub fn mark_canary_dispatched(&mut self) {
        if self.state == CircuitState::HalfOpen {
            self.canary_in_flight = true;
            self.last_state_change = Instant::now();
        }
    }

    /// Records a successful delivery or verified socket transmission.
    pub fn record_success(&mut self) {
        if self.state != CircuitState::Closed {
            info!(
                "✅ Circuit Breaker for peer '{}' [{:?}]: Recovery verified! Transitioning to CLOSED",
                self.peer_name, self.link_type
            );
        }
        self.state = CircuitState::Closed;
        self.consecutive_failures = 0;
        self.current_cooldown = self.base_cooldown;
        self.canary_in_flight = false;
    }

    /// Manually resets the circuit breaker to CLOSED and clears failure counters.
    pub fn reset(&mut self) {
        info!(
            "🔄 Circuit Breaker for peer '{}' [{:?}]: Manually reset to CLOSED",
            self.peer_name, self.link_type
        );
        self.state = CircuitState::Closed;
        self.consecutive_failures = 0;
        self.current_cooldown = self.base_cooldown;
        self.canary_in_flight = false;
        self.last_state_change = Instant::now();
    }

    /// Records a delivery failure or socket error.
    pub fn record_failure(&mut self) {
        let now = Instant::now();
        match self.state {
            CircuitState::Closed => {
                self.consecutive_failures += 1;
                warn!(
                    "⚠️ Circuit Breaker for peer '{}': Failure {}/{}",
                    self.peer_name, self.consecutive_failures, self.failure_threshold
                );

                if self.consecutive_failures >= self.failure_threshold {
                    self.state = CircuitState::Open;
                    self.last_state_change = now;
                    warn!(
                        "🚨 Circuit Breaker for peer '{}' [{:?}] TRIPPED TO OPEN! Traffic suppressed for {:?}",
                        self.peer_name, self.link_type, self.current_cooldown
                    );
                }
            }
            CircuitState::HalfOpen => {
                // Failure during probe immediately trips back to Open with exponential backoff
                let next_cooldown = std::cmp::min(self.max_cooldown, self.current_cooldown * 2);
                warn!(
                    "🚨 Circuit Breaker for peer '{}' [{:?}]: Half-Open probe failed! Re-opening circuit with doubled cooldown {:?}",
                    self.peer_name, self.link_type, next_cooldown
                );
                self.state = CircuitState::Open;
                self.current_cooldown = next_cooldown;
                self.last_state_change = now;
                self.canary_in_flight = false;
            }
            CircuitState::Open => {
                // Already open
            }
        }
    }

    /// Returns the current operational state.
    pub fn state(&self) -> CircuitState {
        self.state
    }

    /// Returns the number of consecutive recorded delivery failures.
    pub fn consecutive_failures(&self) -> u32 {
        self.consecutive_failures
    }

    /// Returns the current cooldown duration applied upon trip.
    pub fn current_cooldown(&self) -> Duration {
        self.current_cooldown
    }

    /// Returns elapsed seconds since the last circuit state transition.
    pub fn last_state_change_secs(&self) -> u64 {
        self.last_state_change.elapsed().as_secs()
    }

    /// Returns the canary acknowledgment timeout duration.
    pub fn canary_timeout(&self) -> Duration {
        self.canary_timeout
    }

    /// Returns the configured link type.
    pub fn link_type(&self) -> PeeringLinkType {
        self.link_type
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_circuit_breaker_trip_and_cooldown_progression() {
        let mut cb = PeeringCircuitBreaker::new(
            "test-peer".to_string(),
            PeeringLinkType::Lan,
            2,
            1, // 1 sec cooldown
            10,
            500,
        );

        assert_eq!(cb.state(), CircuitState::Closed);
        assert!(cb.can_send());

        // Failure 1
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Closed);
        assert_eq!(cb.consecutive_failures(), 1);

        // Failure 2 -> Trip
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Open);
        assert_eq!(cb.consecutive_failures(), 2);
        assert!(!cb.can_send());

        // Wait cooldown (1 sec)
        std::thread::sleep(Duration::from_millis(1100));
        assert!(cb.can_send());
        assert_eq!(cb.state(), CircuitState::HalfOpen);

        // Canary probe succeeds
        cb.record_success();
        assert_eq!(cb.state(), CircuitState::Closed);
        assert_eq!(cb.consecutive_failures(), 0);
    }

    #[test]
    fn test_half_open_failure_doubles_cooldown() {
        let mut cb = PeeringCircuitBreaker::new(
            "test-peer-radio".to_string(),
            PeeringLinkType::Lora,
            1,
            2,
            10,
            500,
        );

        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Open);
        assert_eq!(cb.current_cooldown.as_secs(), 2);

        // Cooldown elapse
        std::thread::sleep(Duration::from_millis(2100));
        assert!(cb.can_send());
        assert_eq!(cb.state(), CircuitState::HalfOpen);

        // HalfOpen probe failure -> double cooldown
        cb.record_failure();
        assert_eq!(cb.state(), CircuitState::Open);
        assert_eq!(cb.current_cooldown.as_secs(), 4);
    }
}
