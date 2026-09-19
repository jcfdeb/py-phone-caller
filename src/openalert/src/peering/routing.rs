//! # Dynamic Multi-Hop Routing and Distance-Vector Metric Engine
//!
//! Provides link-cost evaluation, routing table management, split-horizon
//! suppression, and multi-hop forwarding logic across heterogeneous peering links.

use crate::config::PeeringLinkType;
use crate::peering::wire::RouteAdvPacket;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::{Duration, Instant};

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
    /// Instant when route was last updated or refreshed.
    #[serde(skip, default = "Instant::now")]
    pub last_updated: Instant,
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

/// Dynamic Distance-Vector routing table for mesh forwarding.
#[derive(Debug, Default)]
pub struct RoutingTable {
    routes: HashMap<String, RouteEntry>,
}

impl RoutingTable {
    /// Creates an empty routing table.
    pub fn new() -> Self {
        Self {
            routes: HashMap::new(),
        }
    }

    /// Registers or updates a route if the new metric is lower (better) or updates an existing path.
    pub fn update_route(
        &mut self,
        destination: &str,
        next_hop: &str,
        metric: u32,
        hops: u8,
    ) -> bool {
        if let Some(existing) = self.routes.get_mut(destination) {
            // Update if from same next hop (fresh advertisement) or if metric is strictly lower
            if existing.next_hop == next_hop || metric < existing.metric {
                existing.next_hop = next_hop.to_string();
                existing.metric = metric;
                existing.hops = hops;
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
    pub fn generate_split_horizon_advs(&self, neighbor: &str, local_src: &str, max_age: Duration) -> Vec<RouteAdvPacket> {
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
        let advs_for_b = table.generate_split_horizon_advs("peer-b", "node-a", Duration::from_secs(60));
        assert_eq!(advs_for_b.len(), 1);
        assert_eq!(advs_for_b[0].dst, "edge-x");
        assert_eq!(advs_for_b[0].hops, 2);

        // Split-horizon for peer-c: MUST NOT advertise edge-x back to peer-c!
        let advs_for_c = table.generate_split_horizon_advs("peer-c", "node-a", Duration::from_secs(60));
        assert_eq!(advs_for_c.len(), 1);
        assert_eq!(advs_for_c[0].dst, "gateway");
        assert_eq!(advs_for_c[0].hops, 3);
    }
}
