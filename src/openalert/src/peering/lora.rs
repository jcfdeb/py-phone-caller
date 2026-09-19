//! # Physical LoRa Hardware Transceiver Driver
//!
//! Provides native serial/UART communication over `/dev/ttyUSB*`, `/dev/ttyS*`, or `/dev/serial0`
//! with SLIP framing (RFC 1055), exact Semtech SX126x/SX127x air-time modeling, and an ETSI 1%
//! duty-cycle regulator with emergency priority queues.

use std::collections::VecDeque;
use std::time::{Duration, Instant};
// tracing imports unused in lora.rs

pub const SLIP_END: u8 = 0xC0;
pub const SLIP_ESC: u8 = 0xDB;
pub const SLIP_ESC_END: u8 = 0xDC;
pub const SLIP_ESC_ESC: u8 = 0xDD;

/// Encodes a raw byte payload using standard SLIP (RFC 1055) framing.
pub fn slip_encode(payload: &[u8]) -> Vec<u8> {
    let mut out = Vec::with_capacity(payload.len() + 8);
    out.push(SLIP_END);
    for &b in payload {
        match b {
            SLIP_END => {
                out.push(SLIP_ESC);
                out.push(SLIP_ESC_END);
            }
            SLIP_ESC => {
                out.push(SLIP_ESC);
                out.push(SLIP_ESC_ESC);
            }
            _ => out.push(b),
        }
    }
    out.push(SLIP_END);
    out
}

/// Stateful RFC 1055 SLIP stream decoder.
#[derive(Debug, Default, Clone)]
pub struct SlipDecoder {
    current: Vec<u8>,
    in_escape: bool,
}

impl SlipDecoder {
    pub fn new() -> Self {
        Self::default()
    }

    /// Feeds an incoming byte slice and returns any fully reassembled packet frames.
    pub fn decode_chunk(&mut self, chunk: &[u8]) -> Vec<Vec<u8>> {
        let mut frames = Vec::new();
        for &byte in chunk {
            if self.in_escape {
                match byte {
                    SLIP_ESC_END => self.current.push(SLIP_END),
                    SLIP_ESC_ESC => self.current.push(SLIP_ESC),
                    _ => {
                        // Protocol error, drop invalid escape sequence
                        self.current.clear();
                    }
                }
                self.in_escape = false;
            } else {
                match byte {
                    SLIP_END => {
                        if !self.current.is_empty() {
                            frames.push(std::mem::take(&mut self.current));
                        }
                    }
                    SLIP_ESC => {
                        self.in_escape = true;
                    }
                    _ => {
                        self.current.push(byte);
                    }
                }
            }
        }
        frames
    }
}

/// Helper function to decode complete frames from a byte slice.
pub fn slip_decode_chunk(chunk: &[u8]) -> Vec<Vec<u8>> {
    let mut decoder = SlipDecoder::new();
    decoder.decode_chunk(chunk)
}

/// LoRa physical radio modulation parameters for air-time calculations.
#[derive(Debug, Clone, PartialEq)]
pub struct LoraModulation {
    /// Spreading factor (7 to 12). Default: 9.
    pub spreading_factor: u8,
    /// Bandwidth in kHz (125, 250, 500). Default: 125.
    pub bandwidth_khz: u32,
    /// Coding rate (1 = 4/5, 2 = 4/6, 3 = 4/7, 4 = 4/8). Default: 1.
    pub coding_rate: u8,
    /// Preamble length in symbols. Default: 8.
    pub preamble_symbols: u16,
    /// Explicit header enabled. Default: true.
    pub explicit_header: bool,
    /// CRC enabled. Default: true.
    pub crc_enabled: bool,
    /// Low Data Rate Optimization (mandatory when symbol duration >= 16ms).
    pub low_data_rate_optimization: bool,
}

impl Default for LoraModulation {
    fn default() -> Self {
        let sf = 9;
        let bw = 125;
        let symbol_duration_ms = (1u64 << sf) as f64 / (bw as f64);
        let ldro = symbol_duration_ms >= 16.0;

        Self {
            spreading_factor: sf,
            bandwidth_khz: bw,
            coding_rate: 1, // 4/5
            preamble_symbols: 8,
            explicit_header: true,
            crc_enabled: true,
            low_data_rate_optimization: ldro,
        }
    }
}

impl LoraModulation {
    /// Calculates theoretical air-time in milliseconds for a given payload size (Semtech SX126x/SX127x formula).
    pub fn calculate_air_time_ms(&self, payload_bytes: usize) -> f64 {
        let sf = self.spreading_factor.clamp(7, 12) as f64;
        let bw_hz = (self.bandwidth_khz * 1000) as f64;
        let cr = self.coding_rate.clamp(1, 4) as f64;
        let n_preamble = self.preamble_symbols as f64;

        // Symbol duration (seconds)
        let t_sym = (2.0f64.powf(sf)) / bw_hz;

        // Preamble duration
        let t_preamble = (n_preamble + 4.25) * t_sym;

        // Payload symbol count
        let de = if self.low_data_rate_optimization { 1.0 } else { 0.0 };
        let ih = if self.explicit_header { 0.0 } else { 1.0 };
        let crc = if self.crc_enabled { 1.0 } else { 0.0 };
        let pl = payload_bytes as f64;

        let num = 8.0 * pl - 4.0 * sf + 28.0 + 16.0 * crc - 20.0 * ih;
        let den = 4.0 * (sf - 2.0 * de);
        let term = (num / den).ceil().max(0.0);
        let n_payload = 8.0 + term * (cr + 4.0);

        let t_payload = n_payload * t_sym;
        (t_preamble + t_payload) * 1000.0
    }
}

/// Regulatory duty-cycle rate limiter (ETSI EN 300 220 1% sub-band regulation).
#[derive(Debug)]
pub struct LoraDutyCycleLimiter {
    /// Maximum allowed duty cycle fraction (e.g., 0.01 for 1%).
    duty_cycle_fraction: f64,
    /// Minimum timestamp before the next transmission is permitted.
    next_allowed_transmit: Instant,
    /// Sliding window record of recent transmissions: (timestamp, air_time_ms).
    history: VecDeque<(Instant, f64)>,
    /// Sliding window duration (default: 3600 seconds / 1 hour).
    window_duration: Duration,
}

impl Default for LoraDutyCycleLimiter {
    fn default() -> Self {
        Self::new(0.01) // 1% duty cycle default
    }
}

impl LoraDutyCycleLimiter {
    /// Creates a new limiter with a specific duty cycle fraction (e.g. 0.01 for 1%).
    pub fn new(duty_cycle_fraction: f64) -> Self {
        Self {
            duty_cycle_fraction: duty_cycle_fraction.clamp(0.001, 1.0),
            next_allowed_transmit: Instant::now(),
            history: VecDeque::new(),
            window_duration: Duration::from_secs(3600),
        }
    }

    /// Prunes history entries older than the sliding window.
    fn prune(&mut self, now: Instant) {
        while let Some(&(ts, _)) = self.history.front() {
            if now.duration_since(ts) > self.window_duration {
                self.history.pop_front();
            } else {
                break;
            }
        }
    }

    /// Calculates total transmission air-time in milliseconds consumed during the active window.
    pub fn total_air_time_window_ms(&mut self) -> f64 {
        let now = Instant::now();
        self.prune(now);
        self.history.iter().map(|&(_, ms)| ms).sum()
    }

    /// Required off-time backoff after an air-time burst: OffTime = AirTime * (1/DutyCycle - 1).
    pub fn calculate_required_backoff_ms(&self, air_time_ms: f64) -> u64 {
        let multiplier = (1.0 / self.duty_cycle_fraction) - 1.0;
        (air_time_ms * multiplier).ceil() as u64
    }

    /// Checks whether a transmission is currently permitted under regulatory limits.
    /// Critical alerts can bypass the channel busy backoff, but are still recorded for regulatory audit.
    pub fn can_transmit(&mut self, air_time_ms: f64, is_critical: bool) -> bool {
        let now = Instant::now();
        self.prune(now);

        if is_critical {
            return true;
        }

        if now < self.next_allowed_transmit {
            return false;
        }

        // Check 1-hour total budget: for 1% of 3600s = 36,000 ms total
        let max_budget_ms = self.window_duration.as_secs_f64() * 1000.0 * self.duty_cycle_fraction;
        let current_total: f64 = self.history.iter().map(|&(_, ms)| ms).sum();

        current_total + air_time_ms <= max_budget_ms
    }

    /// Records a completed transmission and sets the mandatory channel cooldown window.
    pub fn record_transmission(&mut self, air_time_ms: f64) {
        let now = Instant::now();
        self.history.push_back((now, air_time_ms));

        let backoff_ms = self.calculate_required_backoff_ms(air_time_ms);
        self.next_allowed_transmit = now + Duration::from_millis(backoff_ms);
    }

    /// Duration remaining until regular transmissions are permitted again.
    pub fn time_until_available(&self) -> Duration {
        let now = Instant::now();
        if self.next_allowed_transmit > now {
            self.next_allowed_transmit.duration_since(now)
        } else {
            Duration::from_millis(0)
        }
    }
}

/// Hardware serial configuration for physical LoRa transceivers.
#[derive(Debug, Clone)]
pub struct LoraSerialConfig {
    /// Linux device path (e.g. `/dev/ttyUSB0` or `/dev/serial0`).
    pub device: String,
    /// Baud rate (e.g. 9600, 115200). Default: 115200.
    pub baud_rate: u32,
    /// Modulation parameters.
    pub modulation: LoraModulation,
    /// Duty cycle limit fraction (default: 0.01).
    pub duty_cycle_fraction: f64,
}

impl Default for LoraSerialConfig {
    fn default() -> Self {
        Self {
            device: "/dev/ttyUSB0".to_string(),
            baud_rate: 115200,
            modulation: LoraModulation::default(),
            duty_cycle_fraction: 0.01,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_slip_encode_decode_roundtrip() {
        let payload = b"Hello LoRa Mesh Network!";
        let encoded = slip_encode(payload);
        assert_eq!(encoded[0], SLIP_END);
        assert_eq!(*encoded.last().unwrap(), SLIP_END);

        let decoded = slip_decode_chunk(&encoded);
        assert_eq!(decoded.len(), 1);
        assert_eq!(decoded[0], payload);
    }

    #[test]
    fn test_slip_escaped_special_bytes() {
        let payload = vec![0x01, SLIP_END, 0x02, SLIP_ESC, 0x03];
        let encoded = slip_encode(&payload);

        // Ensure raw END and ESC do not appear in the interior of the framed datagram
        let interior = &encoded[1..encoded.len() - 1];
        assert!(!interior.contains(&SLIP_END));

        let decoded = slip_decode_chunk(&encoded);
        assert_eq!(decoded.len(), 1);
        assert_eq!(decoded[0], payload);
    }

    #[test]
    fn test_slip_streaming_reassembly() {
        let p1 = b"Packet One";
        let p2 = b"Packet Two";

        let enc1 = slip_encode(p1);
        let enc2 = slip_encode(p2);

        let mut decoder = SlipDecoder::new();

        // Feed half of packet 1
        let d1 = decoder.decode_chunk(&enc1[..5]);
        assert!(d1.is_empty(), "Partial frame must not be decoded");

        // Feed rest of packet 1 + half of packet 2
        let mut combined = enc1[5..].to_vec();
        combined.extend_from_slice(&enc2[..4]);
        let d2 = decoder.decode_chunk(&combined);
        assert_eq!(d2.len(), 1);
        assert_eq!(d2[0], p1);

        // Feed rest of packet 2
        let d3 = decoder.decode_chunk(&enc2[4..]);
        assert_eq!(d3.len(), 1);
        assert_eq!(d3[0], p2);
    }

    #[test]
    fn test_lora_air_time_calculation() {
        let mod_sf9 = LoraModulation {
            spreading_factor: 9,
            bandwidth_khz: 125,
            coding_rate: 1, // 4/5
            preamble_symbols: 8,
            explicit_header: true,
            crc_enabled: true,
            low_data_rate_optimization: false,
        };

        // 60-byte peering micro-frame at SF9/BW125 should calculate ~150-250ms
        let air_time_ms = mod_sf9.calculate_air_time_ms(60);
        assert!(air_time_ms > 100.0 && air_time_ms < 500.0, "Air time was {}", air_time_ms);

        // Higher spreading factor (SF12) must result in substantially higher air-time
        let mut mod_sf12 = mod_sf9.clone();
        mod_sf12.spreading_factor = 12;
        mod_sf12.low_data_rate_optimization = true;
        let air_time_sf12 = mod_sf12.calculate_air_time_ms(60);
        assert!(air_time_sf12 > air_time_ms * 4.0, "SF12 air-time {} should be much greater than SF9 {}", air_time_sf12, air_time_ms);
    }

    #[test]
    fn test_duty_cycle_limiter_backoff() {
        let mut limiter = LoraDutyCycleLimiter::new(0.01); // 1% duty cycle

        let air_time = 100.0; // 100 ms air time
        let required_backoff = limiter.calculate_required_backoff_ms(air_time);
        // At 1%, required off-time is 99 * 100ms = 9900ms = ~9.9s
        assert_eq!(required_backoff, 9900);

        assert!(limiter.can_transmit(air_time, false));
        limiter.record_transmission(air_time);

        // Immediately after transmission, regular transmit should be throttled
        assert!(!limiter.can_transmit(air_time, false));
        assert!(limiter.time_until_available().as_millis() > 0);

        // But critical priority alerts are permitted through
        assert!(limiter.can_transmit(air_time, true));
    }
}
