//! # Per-Peer Actor Tasks & Link-Aware Delivery Workers
//!
//! Implements independent Tokio worker tasks for each remote peer:
//! - **Profile A (LoRa):** Proactive jittered bursts ($N \le 3$) without ACKs (1% duty cycle).
//! - **Profile B (LAN/VPN):** Stop-and-wait ARQ with exponential backoff and full jitter.
//! - **Asymmetric Circuit Breaker & SQLite Spool Draining:** Automatic fault isolation and FIFO recovery.

use crate::config::{PeeringLinkType, PeeringNodeConfig};
use crate::error::Result;
use crate::models::Alert;
use crate::peering::circuit_breaker::{CircuitState, PeeringCircuitBreaker};
use crate::peering::crypto::encrypt_datagram;
use crate::peering::wire::{
    AlertPacket, PeeringPacket, FLAG_ACK_REQ, FLAG_CANARY, FLAG_FAILOVER, FLAG_SPOOLED,
};
use crate::storage::Storage;
use rand::Rng;
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;
use tokio::net::UdpSocket;
use tokio::sync::{mpsc, oneshot, Mutex};
use tokio::time::sleep;
use tracing::{debug, error, info, warn};

/// Inbound request to route an alert to a specific peer.
#[derive(Debug, Clone)]
pub struct OutboundAlertRequest {
    pub alert: Alert,
    pub is_failover: bool,
}

/// Shared registry of in-flight ARQ acknowledgment waiters keyed by alert fingerprint.
pub type AckWaiters = Arc<Mutex<HashMap<u64, oneshot::Sender<()>>>>;

/// Actor handle for dispatching alerts to a peer worker task.
#[derive(Clone)]
pub struct PeerWorkerHandle {
    name: String,
    tx: mpsc::Sender<OutboundAlertRequest>,
}

impl PeerWorkerHandle {
    pub fn name(&self) -> &str {
        &self.name
    }

    pub async fn dispatch(&self, req: OutboundAlertRequest) -> Result<()> {
        let _ = self.tx.send(req).await;
        Ok(())
    }
}

/// Spawns a dedicated actor worker task for a configured peer.
#[allow(clippy::too_many_arguments)]
pub fn spawn_peer_worker(
    node: PeeringNodeConfig,
    key: [u8; 32],
    socket: Arc<UdpSocket>,
    ack_waiters: AckWaiters,
    storage: Option<Arc<Storage>>,
    default_max_ip_retries: u32,
    default_base_timeout_ms: u64,
    default_max_timeout_ms: u64,
    default_failure_threshold: u32,
    default_base_cooldown_secs: u64,
    default_max_cooldown_secs: u64,
    default_canary_timeout_ms: u64,
) -> PeerWorkerHandle {
    let (tx, rx) = mpsc::channel::<OutboundAlertRequest>(128);
    let name = node.name.clone();

    let worker = PeerWorker {
        node,
        key,
        socket,
        ack_waiters,
        storage,
        rx,
        max_ip_retries: default_max_ip_retries,
        base_timeout_ms: default_base_timeout_ms,
        max_timeout_ms: default_max_timeout_ms,
        cb: PeeringCircuitBreaker::new(
            name.clone(),
            PeeringLinkType::Lan, // replaced below
            default_failure_threshold,
            default_base_cooldown_secs,
            default_max_cooldown_secs,
            default_canary_timeout_ms,
        ),
    };

    tokio::spawn(async move {
        worker.run().await;
    });

    PeerWorkerHandle { name, tx }
}

struct PeerWorker {
    node: PeeringNodeConfig,
    key: [u8; 32],
    socket: Arc<UdpSocket>,
    ack_waiters: AckWaiters,
    storage: Option<Arc<Storage>>,
    rx: mpsc::Receiver<OutboundAlertRequest>,
    max_ip_retries: u32,
    base_timeout_ms: u64,
    max_timeout_ms: u64,
    cb: PeeringCircuitBreaker,
}

impl PeerWorker {
    async fn resolve_target_addr(&self) -> Option<SocketAddr> {
        if let Ok(addr) = self.node.addr.parse::<SocketAddr>() {
            return Some(addr);
        }
        match tokio::net::lookup_host(&self.node.addr).await {
            Ok(mut addrs) => addrs.next(),
            Err(_) => None,
        }
    }

    async fn run(mut self) {
        let mut resolved = None;
        for _ in 0..10 {
            if let Some(addr) = self.resolve_target_addr().await {
                resolved = Some(addr);
                break;
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }

        let target_addr: SocketAddr = match resolved {
            Some(addr) => addr,
            None => {
                error!(
                    "❌ Peering node '{}' could not resolve address '{}'",
                    self.node.name, self.node.addr
                );
                return;
            }
        };

        let link_type = self.node.link_type;
        let failure_threshold = self.node.failure_threshold.unwrap_or(3);
        let base_cooldown_secs = self.node.base_cooldown_secs.unwrap_or(60);

        self.cb = PeeringCircuitBreaker::new(
            self.node.name.clone(),
            link_type,
            failure_threshold,
            base_cooldown_secs,
            1800,
            3500,
        );

        if let Some(r) = self.node.max_ip_retries {
            self.max_ip_retries = r;
        }
        if let Some(t) = self.node.base_timeout_ms {
            self.base_timeout_ms = t;
        }

        info!(
            "🚀 Initialized Peering Worker for '{}' [{:?}] -> {} (Circuit Breaker: threshold={})",
            self.node.name, link_type, target_addr, failure_threshold
        );

        // Periodic maintenance timer for Half-Open canary probes and spool drainage
        let mut maintenance_interval = tokio::time::interval(Duration::from_secs(5));

        loop {
            tokio::select! {
                Some(req) = self.rx.recv() => {
                    self.handle_outbound_alert(req, target_addr).await;
                }
                _ = maintenance_interval.tick() => {
                    self.perform_maintenance(target_addr).await;
                }
            }
        }
    }

    async fn handle_outbound_alert(&mut self, req: OutboundAlertRequest, target_addr: SocketAddr) {
        let mut flags = 0u8;
        if req.is_failover {
            flags |= FLAG_FAILOVER;
        }

        // Check if circuit breaker allows transmission
        if !self.cb.can_send() {
            warn!(
                "🛑 Peering link '{}' is OPEN. Spooling alert [{}] to SQLite storage",
                self.node.name, req.alert.alert_id
            );
            self.spool_alert(&req.alert).await;
            return;
        }

        match self.node.link_type {
            PeeringLinkType::Lora => {
                self.send_lora_burst(&req.alert, flags, target_addr).await;
            }
            PeeringLinkType::Lan | PeeringLinkType::Vpn => {
                flags |= FLAG_ACK_REQ;
                self.send_ip_arq(&req.alert, flags, target_addr).await;
            }
        }
    }

    async fn send_lora_burst(&mut self, alert: &Alert, flags: u8, target_addr: SocketAddr) {
        let burst_count = self.node.burst_retries.unwrap_or(3);
        let base_interval = self.node.burst_interval_ms.unwrap_or(500);
        let max_jitter = self.node.burst_jitter_ms.unwrap_or(150);

        let packet = PeeringPacket::Alert(AlertPacket::from_alert(alert, flags));
        let serialized = match packet.serialize() {
            Ok(s) => s,
            Err(e) => {
                error!("Failed to serialize LoRa alert packet: {}", e);
                return;
            }
        };

        let datagram = match encrypt_datagram(&self.key, &serialized) {
            Ok(d) => d,
            Err(e) => {
                error!("Failed to encrypt LoRa datagram: {}", e);
                return;
            }
        };

        debug!(
            "📻 [LoRa Burst] Emitting {} burst transmissions to {} (datagram: {}B)",
            burst_count, target_addr, datagram.len()
        );

        let mut burst_succeeded = false;
        for attempt in 0..burst_count {
            match self.socket.send_to(&datagram, target_addr).await {
                Ok(_) => {
                    burst_succeeded = true;
                }
                Err(e) => {
                    warn!(
                        "⚠️ LoRa send_to failure on attempt {}/{}: {}",
                        attempt + 1, burst_count, e
                    );
                    self.cb.record_failure();
                    self.spool_alert(alert).await;
                    return;
                }
            }

            if attempt + 1 < burst_count {
                let jitter: u64 = if max_jitter > 0 {
                    rand::rng().random_range(0..=max_jitter)
                } else {
                    0
                };
                sleep(Duration::from_millis(base_interval + jitter)).await;
            }
        }

        if burst_succeeded {
            self.cb.record_success();
        }
    }

    async fn send_ip_arq(&mut self, alert: &Alert, flags: u8, target_addr: SocketAddr) {
        let fp = alert.fingerprint_u64();
        let packet = PeeringPacket::Alert(AlertPacket::from_alert(alert, flags));
        let serialized = match packet.serialize() {
            Ok(s) => s,
            Err(e) => {
                error!("Failed to serialize ARQ alert packet: {}", e);
                return;
            }
        };

        let datagram = match encrypt_datagram(&self.key, &serialized) {
            Ok(d) => d,
            Err(e) => {
                error!("Failed to encrypt ARQ datagram: {}", e);
                return;
            }
        };

        let max_attempts = self.max_ip_retries;
        let mut delivered = false;

        for attempt in 0..=max_attempts {
            // Register oneshot channel for incoming ACK
            let (ack_tx, ack_rx) = oneshot::channel();
            {
                let mut waiters = self.ack_waiters.lock().await;
                waiters.insert(fp, ack_tx);
            }

            if let Err(e) = self.socket.send_to(&datagram, target_addr).await {
                warn!(
                    "⚠️ UDP send error to '{}' (attempt {}): {}",
                    self.node.name, attempt + 1, e
                );
                let mut waiters = self.ack_waiters.lock().await;
                waiters.remove(&fp);
                self.cb.record_failure();
                break;
            }

            // Exponential backoff with full jitter
            let backoff_limit = std::cmp::min(
                self.max_timeout_ms,
                self.base_timeout_ms * (1 << attempt.min(5)),
            );
            let timeout_ms = rand::rng().random_range((self.base_timeout_ms / 2)..=backoff_limit);

            match tokio::time::timeout(Duration::from_millis(timeout_ms), ack_rx).await {
                Ok(Ok(())) => {
                    debug!(
                        "✅ [ARQ Verified] Received ACK from '{}' for fingerprint 0x{:016x} on attempt {}",
                        self.node.name, fp, attempt + 1
                    );
                    delivered = true;
                    self.cb.record_success();
                    break;
                }
                _ => {
                    warn!(
                        "⏱️ [ARQ Timeout] No ACK from '{}' for alert [{}] (attempt {}/{})",
                        self.node.name, alert.alert_id, attempt + 1, max_attempts + 1
                    );
                    let mut waiters = self.ack_waiters.lock().await;
                    waiters.remove(&fp);
                }
            }
        }

        if !delivered {
            warn!(
                "🚨 ARQ exhausted all {} retries to '{}'. Spooling alert [{}]",
                max_attempts + 1, self.node.name, alert.alert_id
            );
            self.cb.record_failure();
            self.spool_alert(alert).await;
        }
    }

    async fn spool_alert(&self, alert: &Alert) {
        if let Some(ref storage) = self.storage {
            let fp = alert.fingerprint_u64();
            let packet = PeeringPacket::Alert(AlertPacket::from_alert(alert, FLAG_SPOOLED));
            if let Ok(serialized) = packet.serialize()
                && let Ok(id) = storage.spool_peering_packet(&self.node.name, fp, &serialized).await {
                    info!(
                        "💾 Spooled alert [{}] to SQLite peering_spool (id: {}, peer: '{}')",
                        alert.alert_id, id, self.node.name
                    );
            }
        }
    }

    async fn perform_maintenance(&mut self, target_addr: SocketAddr) {
        // 1. If Circuit Breaker is HalfOpen, test channel recovery
        if self.cb.state() == CircuitState::HalfOpen {
            self.probe_half_open(target_addr).await;
        }

        // 2. If Circuit Breaker is Closed, drain spooled records
        if self.cb.state() == CircuitState::Closed {
            self.drain_spool(target_addr).await;
        }
    }

    async fn probe_half_open(&mut self, target_addr: SocketAddr) {
        match self.node.link_type {
            PeeringLinkType::Lora => {
                // Radio Optimistic probe: verify socket accepts a minimal datagram
                let canary = PeeringPacket::Alert(AlertPacket {
                    fp: 0,
                    ts: 0,
                    lvl: 0,
                    flags: FLAG_CANARY,
                    hop: 1,
                    src: "canary".to_string(),
                    code: "PING".to_string(),
                });
                if let Ok(ser) = canary.serialize()
                    && let Ok(datagram) = encrypt_datagram(&self.key, &ser) {
                        match self.socket.send_to(&datagram, target_addr).await {
                            Ok(_) => {
                                info!(
                                    "✅ [Radio Optimistic Check] Local interface accepted canary packet for '{}'. Restoring CLOSED",
                                    self.node.name
                                );
                                self.cb.record_success();
                            }
                            Err(e) => {
                                warn!("⚠️ [Radio Optimistic Check] Socket error for '{}': {}", self.node.name, e);
                                self.cb.record_failure();
                            }
                        }
                    }
            }
            PeeringLinkType::Lan | PeeringLinkType::Vpn => {
                // Canary ARQ probe
                let canary_fp = rand::rng().random::<u64>();
                let canary = PeeringPacket::Alert(AlertPacket {
                    fp: canary_fp,
                    ts: 0,
                    lvl: 0,
                    flags: FLAG_CANARY | FLAG_ACK_REQ,
                    hop: 1,
                    src: "canary".to_string(),
                    code: "PING".to_string(),
                });

                if let Ok(ser) = canary.serialize()
                    && let Ok(datagram) = encrypt_datagram(&self.key, &ser) {
                        self.cb.mark_canary_dispatched();
                        let (ack_tx, ack_rx) = oneshot::channel();
                        {
                            let mut waiters = self.ack_waiters.lock().await;
                            waiters.insert(canary_fp, ack_tx);
                        }

                        if self.socket.send_to(&datagram, target_addr).await.is_ok() {
                            match tokio::time::timeout(self.cb.canary_timeout(), ack_rx).await {
                                Ok(Ok(())) => {
                                    info!(
                                        "✅ [Canary ARQ Success] Peer '{}' acknowledged probe! Circuit RESTORED to CLOSED",
                                        self.node.name
                                    );
                                    self.cb.record_success();
                                }
                                _ => {
                                    warn!(
                                        "🛑 [Canary ARQ Timeout] Peer '{}' failed to ACK canary probe",
                                        self.node.name
                                    );
                                    let mut waiters = self.ack_waiters.lock().await;
                                    waiters.remove(&canary_fp);
                                    self.cb.record_failure();
                                }
                            }
                        } else {
                            let mut waiters = self.ack_waiters.lock().await;
                            waiters.remove(&canary_fp);
                            self.cb.record_failure();
                        }
                    }
            }
        }
    }

    async fn drain_spool(&mut self, target_addr: SocketAddr) {
        let Some(ref storage) = self.storage else {
            return;
        };

        if let Ok(spooled) = storage.get_spooled_peering_packets(&self.node.name, 5).await {
            if spooled.is_empty() {
                return;
            }

            info!(
                "📦 Draining {} spooled peering packet(s) for recovering peer '{}'...",
                spooled.len(), self.node.name
            );

            for (id, _fp, payload) in spooled {
                if let Ok(datagram) = encrypt_datagram(&self.key, &payload) {
                    if self.socket.send_to(&datagram, target_addr).await.is_ok() {
                        let _ = storage.mark_peering_spool_delivered(id).await;
                        debug!("✅ Spool packet id {} delivered to '{}'", id, self.node.name);
                    } else {
                        let _ = storage.increment_peering_spool_retry(id).await;
                        break;
                    }
                }
                sleep(Duration::from_millis(100)).await;
            }
        }
    }
}
