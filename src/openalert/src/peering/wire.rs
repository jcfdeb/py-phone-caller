//! # High-Density Binary Wire Protocol for Peering Datagrams
//!
//! Implements compact packed tuple serialization using [`postcard`] to guarantee single-frame
//! delivery over constrained radio links (LoRa SF11/SF12, MTU 51–64 bytes).

use crate::error::{OpenAlertError, Result};
use crate::models::{Alert, AlertSeverity, AlertSource};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Control bit: Inbound peer requests an immediate `AckPacket` reply (used on IP links).
pub const FLAG_ACK_REQ: u8 = 0x01;

/// Control bit: Designates a zero-payload canary probe used during Circuit Breaker HALF-OPEN recovery.
pub const FLAG_CANARY: u8 = 0x02;

/// Control bit: Indicates the datagram was previously spooled to SQLite storage before transmission.
pub const FLAG_SPOOLED: u8 = 0x04;

/// Control bit: Designates an emergency escape-valve failover alert triggered after primary egress collapse.
pub const FLAG_FAILOVER: u8 = 0x08;

/// Compact alert packet formatted as packed sequential primitives (~22–26 bytes plaintext).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AlertPacket {
    /// 64-bit cryptographic alert fingerprint for atomic deduplication and tracking.
    pub fp: u64,
    /// Unix Epoch timestamp in seconds (valid through year 2106).
    pub ts: u32,
    /// Severity level: 0 = Info, 1 = Warning, 2 = Critical, 3 = Emergency.
    pub lvl: u8,
    /// Control flags (`FLAG_ACK_REQ`, `FLAG_CANARY`, `FLAG_SPOOLED`, `FLAG_FAILOVER`).
    pub flags: u8,
    /// Remaining mesh hop count (decremented per forward; dropped at 0).
    pub hop: u8,
    /// Originating node identifier (e.g. "e-01").
    pub src: String,
    /// Compact alarm summary code (e.g. "PWR_DN", "BGP_FL").
    pub code: String,
}

/// Compact acknowledgment packet confirming receipt of an `AlertPacket` (~12–14 bytes plaintext).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AckPacket {
    /// 64-bit fingerprint of the acknowledged alert packet.
    pub fp: u64,
    /// Unix Epoch timestamp of acknowledgment generation.
    pub ts: u32,
}

/// Top-level peering packet discriminant enum.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PeeringPacket {
    /// Actionable alarm or event datagram.
    Alert(AlertPacket),
    /// Transport-level confirmation datagram.
    Ack(AckPacket),
}

impl PeeringPacket {
    /// Serializes the packet into a high-density postcard binary slice.
    pub fn serialize(&self) -> Result<Vec<u8>> {
        postcard::to_allocvec(self).map_err(|e| {
            OpenAlertError::Peering(format!("Failed to serialize peering packet: {}", e))
        })
    }

    /// Deserializes a postcard binary slice into a strongly-typed [`PeeringPacket`].
    pub fn deserialize(bytes: &[u8]) -> Result<Self> {
        postcard::from_bytes(bytes).map_err(|e| {
            OpenAlertError::Peering(format!("Failed to deserialize peering packet: {}", e))
        })
    }
}

impl AlertPacket {
    /// Converts a canonical internal [`Alert`] into a compact [`AlertPacket`].
    pub fn from_alert(alert: &Alert, flags: u8) -> Self {
        let lvl = match alert.severity {
            AlertSeverity::Info => 0,
            AlertSeverity::Warning => 1,
            AlertSeverity::Critical => 2,
            AlertSeverity::Emergency => 3,
        };

        let src = alert
            .node
            .as_deref()
            .or(alert.sender.as_deref())
            .unwrap_or("node")
            .to_string();

        let code = if alert.summary.len() > 32 {
            alert.summary[..32].to_string()
        } else {
            alert.summary.clone()
        };

        Self {
            fp: alert.fingerprint_u64(),
            ts: alert.starts_at.timestamp() as u32,
            lvl,
            flags,
            hop: alert.hop,
            src,
            code,
        }
    }

    /// Reconstructs a canonical internal [`Alert`] from a received [`AlertPacket`].
    pub fn into_alert(self, origin_peer: Option<String>) -> Alert {
        let severity = match self.lvl {
            0 => AlertSeverity::Info,
            1 => AlertSeverity::Warning,
            2 => AlertSeverity::Critical,
            _ => AlertSeverity::Emergency,
        };

        let alert_id = format!("peer-{}-{:016x}", self.src, self.fp);
        let starts_at = DateTime::from_timestamp(self.ts as i64, 0).unwrap_or_else(Utc::now);

        Alert {
            alert_id,
            severity,
            summary: self.code.clone(),
            description: Some(format!(
                "Federated alert from peer '{}' [Flags: 0x{:02x}, Fingerprint: 0x{:016x}]",
                self.src, self.flags, self.fp
            )),
            source: AlertSource::Peering,
            sender: Some(self.src.clone()),
            node: Some(self.src),
            starts_at,
            destinations: Vec::new(),
            origin_peer,
            hop: self.hop.saturating_sub(1),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_alert_packet_micro_footprint() {
        let packet = PeeringPacket::Alert(AlertPacket {
            fp: 0xfeedfacecafebeef,
            ts: 1789035000,
            lvl: 2,
            flags: FLAG_ACK_REQ | FLAG_FAILOVER,
            hop: 3,
            src: "e-01".to_string(),
            code: "PWR_DN".to_string(),
        });

        let encoded = packet.serialize().expect("Serialization should succeed");
        // Ensure payload is under 30 bytes for LoRa SF11/SF12 margin!
        assert!(
            encoded.len() <= 32,
            "Serialized AlertPacket size ({} bytes) exceeds 32-byte envelope",
            encoded.len()
        );

        let decoded = PeeringPacket::deserialize(&encoded).expect("Deserialization should succeed");
        assert_eq!(packet, decoded);
    }

    #[test]
    fn test_ack_packet_micro_footprint() {
        let ack = PeeringPacket::Ack(AckPacket {
            fp: 0xfeedfacecafebeef,
            ts: 1789035000,
        });

        let encoded = ack.serialize().expect("Serialization should succeed");
        assert!(
            encoded.len() <= 16,
            "Serialized AckPacket size ({} bytes) exceeds 16 bytes",
            encoded.len()
        );

        let decoded = PeeringPacket::deserialize(&encoded).expect("Deserialization should succeed");
        assert_eq!(ack, decoded);
    }
}
