//! # Dynamic Multi-Hop Routing and Distance-Vector Metric Engine
//!
//! Provides link-cost evaluation, routing table management, split-horizon
//! suppression, and multi-hop forwarding logic across heterogeneous peering links,
//! enhanced with physical RF Signal-to-Noise Ratio (SNR) and RSSI predictive link metrics.

use crate::config::PeeringLinkType;
use crate::peering::wire::RouteAdvPacket;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::{Duration, Instant};

/// Standard SNR threshold in dB below which RF signal quality incurs routing penalties.
pub const DEFAULT_SNR_THRESH_DB: f32 = 0.0;

/// Demodulation floor in dB for Spreading Factor 7-10 (minimum receivable SNR).
pub const DEFAULT_SNR_FLOOR_DB: f32 = -12.5;

/// Single route entry representing path to a destination node.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RouteEntry {
    /// Remote destination node identifier (e.g. "gateway-central" or "hub-dc").
    pub destination: String,
    /// Next-hop immediate neighbor peer to forward datagrams to.
    pub next_hop: String,
    /// Calculated composite path metric (lower is better).
    pub metric: u32,
    /// Number of hops to destination.
    pub hops: u8,
    /// Real-time Received Signal Strength Indicator in dBm (if RF link).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rssi_dbm: Option<i16>,
    /// Real-time Signal-to-Noise Ratio in dB (if RF link).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub snr_db: Option<f32>,
    /// Applied RF degradation penalty points.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rf_penalty: Option<u32>,
    /// Instant when route was last updated or refreshed.
    #[serde(skip, default = "Instant::now")]
    pub last_updated: Instant,
}

/// Rolling physical telemetry buffer for a peer node.
#[derive(Debug, Clone, Default)]
pub struct PeerRfMetrics {
    /// Moving average RSSI in dBm.
    pub avg_rssi_dbm: i16,
    /// Moving average SNR in dB.
    pub avg_snr_db: f32,
    /// Calculated RF degradation penalty points.
    pub penalty: u32,
    /// Sliding window of recent samples: (rssi, snr).
    pub samples: Vec<(i16, f32)>,
}

/// Calculates the RF degradation penalty points based on Signal-to-Noise Ratio (SNR).
///
/// Formula:
/// If SNR >= SNR_thresh: P_rf = 0
/// If SNR <= SNR_floor:  P_rf = 500
/// Else: P_rf = min(500, ((SNR_thresh - SNR) / (SNR_thresh - SNR_floor))^2 * 500)
pub fn calculate_rf_penalty(snr: f32, snr_thresh: f32, snr_floor: f32) -> u32 {
    if snr >= snr_thresh {
        0
    } else if snr <= snr_floor {
        500
    } else {
        let ratio = (snr_thresh - snr) / (snr_thresh - snr_floor);
        let penalty = (ratio * ratio * 500.0).round() as u32;
        penalty.min(500)
    }
}

/// Calculates the dynamic composite cost metric for a peering link.
///
/// Metric Formula:
/// W_type * 10 + min(RTT / 10, 500) + (LossRate * 500)
///
/// Base weights:
/// - LAN: 10
/// - VPN: 20
/// - LoRa / LoRaSerial: 100
pub fn calculate_link_cost(link_type: PeeringLinkType, rtt_ms: u64, loss_rate: f32) -> u32 {
    let base_weight: u32 = match link_type {
        PeeringLinkType::Lan => 10,
        PeeringLinkType::Vpn => 20,
        PeeringLinkType::Lora | PeeringLinkType::LoraSerial => 100,
    };
    let rtt_cost = (rtt_ms / 10).min(500) as u32;
    let clamped_loss = loss_rate.clamp(0.0, 1.0);
    let loss_cost = (clamped_loss * 500.0) as u32;

    base_weight + rtt_cost + loss_cost
}

/// Calculates link cost incorporating physical RF Signal-to-Noise Ratio (SNR) telemetry.
pub fn calculate_link_cost_with_rf(
    link_type: PeeringLinkType,
    rtt_ms: u64,
    loss_rate: f32,
    snr: Option<f32>,
) -> u32 {
    let base = calculate_link_cost(link_type, rtt_ms, loss_rate);
    let penalty = match (link_type, snr) {
        (PeeringLinkType::Lora | PeeringLinkType::LoraSerial, Some(s)) => {
            calculate_rf_penalty(s, DEFAULT_SNR_THRESH_DB, DEFAULT_SNR_FLOOR_DB)
        }
        _ => 0,
    };
    base.saturating_add(penalty)
}

/// Dynamic Distance-Vector routing table for mesh forwarding.
#[derive(Debug, Default)]
pub struct RoutingTable {
    routes: HashMap<String, RouteEntry>,
    peer_telemetry: HashMap<String, PeerRfMetrics>,
}

impl RoutingTable {
    /// Creates an empty routing table.
    pub fn new() -> Self {
        Self {
            routes: HashMap::new(),
            peer_telemetry: HashMap::new(),
        }
    }

    /// Records physical RF telemetry (RSSI, SNR) for a neighbor peer,
    /// computes moving averages, and dynamically updates route metrics.
    pub fn update_peer_rf_telemetry(&mut self, peer: &str, rssi: i16, snr: f32) -> u32 {
        let entry = self.peer_telemetry.entry(peer.to_string()).or_default();
        entry.samples.push((rssi, snr));
        if entry.samples.len() > 5 {
            entry.samples.remove(0);
        }

        let count = entry.samples.len() as f32;
        let sum_rssi: f32 = entry.samples.iter().map(|&(r, _)| r as f32).sum();
        let sum_snr: f32 = entry.samples.iter().map(|&(_, s)| s).sum();

        entry.avg_rssi_dbm = (sum_rssi / count).round() as i16;
        entry.avg_snr_db = sum_snr / count;
        let penalty = calculate_rf_penalty(entry.avg_snr_db, DEFAULT_SNR_THRESH_DB, DEFAULT_SNR_FLOOR_DB);
        entry.penalty = penalty;

        let avg_rssi = entry.avg_rssi_dbm;
        let avg_snr = entry.avg_snr_db;

        // Apply updated RF telemetry to all routes routed via this peer
        for route in self.routes.values_mut() {
            if route.next_hop == peer {
                route.rssi_dbm = Some(avg_rssi);
                route.snr_db = Some(avg_snr);
                route.rf_penalty = Some(penalty);
            }
        }

        penalty
    }

    /// Returns the active RF metrics for a specific peer if available.
    pub fn get_peer_rf_telemetry(&self, peer: &str) -> Option<&PeerRfMetrics> {
        self.peer_telemetry.get(peer)
    }

    /// Registers or updates a route if the new metric is lower (better) or updates an existing path.
    pub fn update_route(
        &mut self,
        destination: &str,
        next_hop: &str,
        metric: u32,
        hops: u8,
    ) -> bool {
        let rf_meta = self.peer_telemetry.get(next_hop);
        let rssi_dbm = rf_meta.map(|m| m.avg_rssi_dbm);
        let snr_db = rf_meta.map(|m| m.avg_snr_db);
        let rf_penalty = rf_meta.map(|m| m.penalty);

        if let Some(existing) = self.routes.get_mut(destination) {
            // Update if from same next hop (fresh advertisement) or if metric is strictly lower
            if existing.next_hop == next_hop || metric < existing.metric {
                existing.next_hop = next_hop.to_string();
                existing.metric = metric;
                existing.hops = hops;
                existing.rssi_dbm = rssi_dbm;
                existing.snr_db = snr_db;
                existing.rf_penalty = rf_penalty;
                existing.last_updated = Instant::now();
                return true;
            }
            false
        } else {
            self.routes.insert(
                destination.to_string(),
                RouteEntry {
                    destination: destination.to_string(),
                    next_hop: next_hop.to_string(),
                    metric,
                    hops,
                    rssi_dbm,
                    snr_db,
                    rf_penalty,
                    last_updated: Instant::now(),
                },
            );
            true
        }
    }

    /// Finds the best next-hop neighbor for a given destination.
    pub fn find_next_hop(&self, destination: &str, max_age: Duration) -> Option<String> {
        let now = Instant::now();
        self.routes.get(destination).and_then(|r| {
            if now.duration_since(r.last_updated) <= max_age {
                Some(r.next_hop.clone())
            } else {
                None
            }
        })
    }

    /// Returns a snapshot of all routes in the table.
    pub fn get_active_routes(&self) -> Vec<RouteEntry> {
        self.routes.values().cloned().collect()
    }

    /// Prunes stale routes exceeding the specified TTL.
    pub fn prune_stale(&mut self, max_age: Duration) {
        let now = Instant::now();
        self.routes
            .retain(|_, r| now.duration_since(r.last_updated) <= max_age);
    }

    /// Generates distance-vector advertisements using Split-Horizon:
    /// Never advertises a route back to the next-hop neighbor from which it was learned.
    pub fn generate_split_horizon_advs(
        &self,
        neighbor: &str,
        local_src: &str,
        max_age: Duration,
    ) -> Vec<RouteAdvPacket> {
        let now = Instant::now();
        let now_epoch = Utc::now().timestamp() as u32;

        self.routes
            .values()
            .filter(|r| now.duration_since(r.last_updated) <= max_age)
            .filter(|r| r.next_hop != neighbor && r.destination != neighbor)
            .map(|r| RouteAdvPacket {
                src: local_src.to_string(),
                ts: now_epoch,
                dst: r.destination.clone(),
                metric: r.metric,
                hops: r.hops.saturating_add(1),
            })
            .collect()
    }

    /// Returns a snapshot of all active routes.
    pub fn get_routes(&self, max_age: Duration) -> Vec<RouteEntry> {
        let now = Instant::now();
        self.routes
            .values()
            .filter(|r| now.duration_since(r.last_updated) <= max_age)
            .cloned()
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_calculate_link_cost() {
        // LAN: base 10 + rtt 5ms (0) + 0% loss = 10
        let lan_cost = calculate_link_cost(PeeringLinkType::Lan, 5, 0.0);
        assert_eq!(lan_cost, 10);

        // VPN: base 20 + rtt 80ms (8) + 10% loss (50) = 78
        let vpn_cost = calculate_link_cost(PeeringLinkType::Vpn, 80, 0.10);
        assert_eq!(vpn_cost, 78);

        // LoRa: base 100 + rtt 300ms (30) + 0% loss = 130
        let lora_cost = calculate_link_cost(PeeringLinkType::Lora, 300, 0.0);
        assert_eq!(lora_cost, 130);
    }

    #[test]
    fn test_rf_penalty_calculation() {
        // 1. Positive SNR: zero penalty
        let penalty_good = calculate_rf_penalty(6.0, DEFAULT_SNR_THRESH_DB, DEFAULT_SNR_FLOOR_DB);
        assert_eq!(penalty_good, 0);

        // 2. SNR at exactly threshold (0.0): zero penalty
        let penalty_zero = calculate_rf_penalty(0.0, DEFAULT_SNR_THRESH_DB, DEFAULT_SNR_FLOOR_DB);
        assert_eq!(penalty_zero, 0);

        // 3. SNR approaching floor (-9.0 dB): quadratic penalty approx 259
        let penalty_fading = calculate_rf_penalty(-9.0, DEFAULT_SNR_THRESH_DB, DEFAULT_SNR_FLOOR_DB);
        assert_eq!(penalty_fading, 259);

        // 4. SNR at or below floor: max 500 penalty
        let penalty_floor = calculate_rf_penalty(-12.5, DEFAULT_SNR_THRESH_DB, DEFAULT_SNR_FLOOR_DB);
        assert_eq!(penalty_floor, 500);

        let penalty_sub_floor = calculate_rf_penalty(-15.0, DEFAULT_SNR_THRESH_DB, DEFAULT_SNR_FLOOR_DB);
        assert_eq!(penalty_sub_floor, 500);
    }

    #[test]
    fn test_routing_table_rf_telemetry_updating() {
        let mut table = RoutingTable::new();
        table.update_route("field-sensor", "relay-node", 120, 1);

        // Link telemetry is nominal
        let penalty = table.update_peer_rf_telemetry("relay-node", -70, 5.0);
        assert_eq!(penalty, 0);

        let route = table.get_routes(Duration::from_secs(60))[0].clone();
        assert_eq!(route.rssi_dbm, Some(-70));
        assert_eq!(route.snr_db, Some(5.0));
        assert_eq!(route.rf_penalty, Some(0));

        // Signal degrades to -10.0 dB SNR (rain fade)
        let new_penalty = table.update_peer_rf_telemetry("relay-node", -115, -10.0);
        assert!(new_penalty > 0);

        let degraded_route = table.get_routes(Duration::from_secs(60))[0].clone();
        assert!(degraded_route.rf_penalty.unwrap() > 0);
    }

    #[test]
    fn test_routing_table_split_horizon_and_pruning() {
        let mut table = RoutingTable::new();

        // Node A reaches Gateway via Peer B with metric 30, 2 hops
        table.update_route("gateway", "peer-b", 30, 2);

        // Node A reaches Edge-X via Peer C with metric 15, 1 hop
        table.update_route("edge-x", "peer-c", 15, 1);

        assert_eq!(
            table.find_next_hop("gateway", Duration::from_secs(60)),
            Some("peer-b".to_string())
        );

        // Split-horizon for peer-b: MUST NOT advertise gateway back to peer-b!
        let advs_for_b =
            table.generate_split_horizon_advs("peer-b", "node-a", Duration::from_secs(60));
        assert_eq!(advs_for_b.len(), 1);
        assert_eq!(advs_for_b[0].dst, "edge-x");
        assert_eq!(advs_for_b[0].hops, 2);

        // Split-horizon for peer-c: MUST NOT advertise edge-x back to peer-c!
        let advs_for_c =
            table.generate_split_horizon_advs("peer-c", "node-a", Duration::from_secs(60));
        assert_eq!(advs_for_c.len(), 1);
        assert_eq!(advs_for_c[0].dst, "gateway");
        assert_eq!(advs_for_c[0].hops, 3);
    }
}
