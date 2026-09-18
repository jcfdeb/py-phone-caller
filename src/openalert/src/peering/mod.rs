//! # Decentralized UDP Peering, Radio Backhaul & Emergency Failover Subsystem
//!
//! Provides a resilient, transport-agnostic datagram federation layer for:
//! 1. **Topology 1 (Stub Node / Asymmetric Uplink):** Isolated edge nodes forwarding alerts to an upstream gateway.
//! 2. **Topology 2 (Emergency Escape Valve):** Out-of-band failover when primary local egress channels collapse.
//!
//! Key properties:
//! - Sub-64-byte wire datagrams via packed tuple serialization (`postcard`).
//! - Stateless `XChaCha20-Poly1305` AEAD with 24-byte random nonces and per-peer PSKs.
//! - Radio link compliance (zero ACKs, proactive jittered bursts).
//! - Split-horizon egress loop suppression and clock-skew tolerance.

pub mod circuit_breaker;
pub mod crypto;
pub mod wire;
pub mod worker;

use crate::config::PeeringConfig;
use crate::engine::AlertEngine;
use crate::error::{OpenAlertError, Result};
use crate::models::Alert;
use crate::peering::crypto::{encrypt_datagram, KeyRegistry};
use crate::peering::wire::{AckPacket, PeeringPacket, FLAG_ACK_REQ, FLAG_CANARY};
use crate::peering::worker::{spawn_peer_worker, AckWaiters, OutboundAlertRequest, PeerWorkerHandle};
use crate::storage::Storage;
use chrono::Utc;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::net::UdpSocket;
use tokio::sync::{Mutex, RwLock};
use tracing::{debug, error, info, warn};

/// Central peering manager orchestrating UDP sockets, crypto, actor workers, and inbound routing.
pub struct PeeringService {
    config: PeeringConfig,
    socket: Arc<UdpSocket>,
    key_registry: Arc<KeyRegistry>,
    workers: Arc<HashMap<String, PeerWorkerHandle>>,
    ack_waiters: AckWaiters,
    dedup_cache: Arc<Mutex<HashMap<u64, Instant>>>,
    engine: Arc<RwLock<Option<Arc<AlertEngine>>>>,
}

impl PeeringService {
    /// Initializes the peering service and binds the listening UDP socket.
    pub async fn new(config: PeeringConfig, storage: Option<Arc<Storage>>) -> Result<Self> {
        let socket = UdpSocket::bind(&config.listen_addr)
            .await
            .map_err(|e| OpenAlertError::Peering(format!("Failed to bind peering UDP socket on {}: {}", config.listen_addr, e)))?;
        let socket = Arc::new(socket);

        let peer_overrides: Vec<(String, Option<String>)> = config
            .nodes
            .iter()
            .map(|n| (n.name.clone(), n.shared_key.clone()))
            .collect();

        let key_registry = Arc::new(KeyRegistry::new(&config.shared_key, &peer_overrides)?);
        let ack_waiters: AckWaiters = Arc::new(Mutex::new(HashMap::new()));
        let mut workers = HashMap::new();

        for node in &config.nodes {
            let key = *key_registry
                .get_key_for_peer(&node.name)
                .unwrap_or(&[0u8; 32]);

            let handle = spawn_peer_worker(
                node.clone(),
                key,
                socket.clone(),
                ack_waiters.clone(),
                storage.clone(),
                config.retry.max_ip_retries,
                config.retry.base_timeout_ms,
                config.retry.max_timeout_ms,
                config.circuit_breaker.failure_threshold,
                config.circuit_breaker.base_cooldown_secs,
                config.circuit_breaker.max_cooldown_secs,
                config.circuit_breaker.canary_timeout_ms,
            );
            workers.insert(node.name.clone(), handle);
        }

        info!(
            "🛰️ Initialized Peering Subsystem on UDP {} [{} peer node(s) configured]",
            config.listen_addr,
            workers.len()
        );

        Ok(Self {
            config,
            socket,
            key_registry,
            workers: Arc::new(workers),
            ack_waiters,
            dedup_cache: Arc::new(Mutex::new(HashMap::new())),
            engine: Arc::new(RwLock::new(None)),
        })
    }

    /// Links the central routing engine to receive verified inbound peering alerts.
    pub async fn set_engine(&self, engine: Arc<AlertEngine>) {
        let mut eng = self.engine.write().await;
        *eng = Some(engine);
    }

    /// Starts the background UDP receiver task.
    pub fn start(self: Arc<Self>) {
        tokio::spawn(async move {
            self.run_rx_loop().await;
        });
    }

    /// Dispatches an alert to all configured peers with split-horizon origin filtering.
    pub async fn dispatch_alert(&self, alert: &Alert, is_failover: bool) -> Result<()> {
        if alert.hop == 0 {
            debug!(
                "🛑 Dropping alert [{}] with hop_count=0 to prevent broadcast storm",
                alert.alert_id
            );
            return Ok(());
        }

        let origin_peer = alert.origin_peer.as_deref();

        for (name, worker) in self.workers.iter() {
            // Split-horizon rule: Never reflect an alert back to the peer that sent it!
            if let Some(origin) = origin_peer
                && origin == name {
                    debug!(
                        "🔄 [Split-Horizon] Suppressing alert [{}] reflection back to origin peer '{}'",
                        alert.alert_id, name
                    );
                    continue;
            }

            let req = OutboundAlertRequest {
                alert: alert.clone(),
                is_failover,
            };
            if let Err(e) = worker.dispatch(req).await {
                warn!("Failed to dispatch alert to peer worker '{}': {}", name, e);
            }
        }

        Ok(())
    }

    async fn run_rx_loop(&self) {
        let mut buf = [0u8; 1024];
        let dedup_window = Duration::from_secs(self.config.dedup_ttl_secs);

        loop {
            let (len, src_addr) = match self.socket.recv_from(&mut buf).await {
                Ok(res) => res,
                Err(e) => {
                    error!("Peering UDP recv_from error: {}", e);
                    tokio::time::sleep(Duration::from_millis(50)).await;
                    continue;
                }
            };

            let datagram = &buf[..len];

            // 1. Decrypt and authenticate using XChaCha20-Poly1305
            let (plaintext, matched_peer) = match self.key_registry.try_decrypt_any(datagram) {
                Some(res) => res,
                None => {
                    // Silently drop unauthenticated / corrupt bytes
                    debug!("⚠️ Discarded unauthenticated peering datagram ({} bytes) from {}", len, src_addr);
                    continue;
                }
            };

            // 2. Deserialize packed tuple binary payload
            let packet = match PeeringPacket::deserialize(&plaintext) {
                Ok(p) => p,
                Err(e) => {
                    debug!("Failed to deserialize valid AEAD datagram from {}: {}", src_addr, e);
                    continue;
                }
            };

            // 3. Process packet variants
            match packet {
                PeeringPacket::Ack(ack) => {
                    let mut waiters = self.ack_waiters.lock().await;
                    if let Some(tx) = waiters.remove(&ack.fp) {
                        let _ = tx.send(());
                    }
                }
                PeeringPacket::Alert(alert_pkt) => {
                    // Check if canary probe
                    if alert_pkt.flags & FLAG_CANARY != 0 {
                        if alert_pkt.flags & FLAG_ACK_REQ != 0 {
                            self.send_ack(alert_pkt.fp, src_addr, matched_peer.as_deref()).await;
                        }
                        continue;
                    }

                    // Clock skew validation (relaxed for off-grid edge nodes)
                    if alert_pkt.ts > 0 {
                        let now_ts = Utc::now().timestamp() as u32;
                        let skew_tolerance = self.config.clock_skew_tolerance_secs as u32;
                        let is_skewed = if now_ts > alert_pkt.ts {
                            (now_ts - alert_pkt.ts) > skew_tolerance
                        } else {
                            (alert_pkt.ts - now_ts) > skew_tolerance
                        };

                        if is_skewed {
                            warn!(
                                "⏱️ Discarded peering alert 0x{:016x} due to excessive clock skew (pkt_ts: {}, now: {}, tolerance: {}s)",
                                alert_pkt.fp, alert_pkt.ts, now_ts, skew_tolerance
                            );
                            continue;
                        }
                    }

                    // Sliding-window deduplication check
                    {
                        let mut cache = self.dedup_cache.lock().await;
                        let now = Instant::now();
                        cache.retain(|_, seen_at| now.duration_since(*seen_at) < dedup_window);

                        if cache.contains_key(&alert_pkt.fp) {
                            debug!("🛑 Dropped duplicate peering alert 0x{:016x} from {}", alert_pkt.fp, src_addr);
                            if alert_pkt.flags & FLAG_ACK_REQ != 0 {
                                self.send_ack(alert_pkt.fp, src_addr, matched_peer.as_deref()).await;
                            }
                            continue;
                        }
                        cache.insert(alert_pkt.fp, now);
                    }

                    // Respond with ACK if requested (Profile B on IP links)
                    if alert_pkt.flags & FLAG_ACK_REQ != 0 {
                        self.send_ack(alert_pkt.fp, src_addr, matched_peer.as_deref()).await;
                    }

                    // Convert to canonical Alert and route through daemon core
                    let origin_name = matched_peer.clone().unwrap_or_else(|| alert_pkt.src.clone());
                    let alert = alert_pkt.into_alert(Some(origin_name));

                    info!(
                        "📥 [Peering Ingress] Ingested alert [{}] from '{}' via UDP (Severity: {:?}, Summary: \"{}\")",
                        alert.alert_id, alert.sender.as_deref().unwrap_or("unknown"), alert.severity, alert.summary
                    );

                    let eng_guard = self.engine.read().await;
                    if let Some(ref eng) = *eng_guard {
                        let eng_clone = eng.clone();
                        tokio::spawn(async move {
                            if let Err(e) = eng_clone.route_alert(alert).await {
                                warn!("Failed to route peering ingress alert: {}", e);
                            }
                        });
                    }
                }
            }
        }
    }

    async fn send_ack(&self, fp: u64, dest: std::net::SocketAddr, peer_name: Option<&str>) {
        let ack_pkt = PeeringPacket::Ack(AckPacket {
            fp,
            ts: Utc::now().timestamp() as u32,
        });

        if let Ok(serialized) = ack_pkt.serialize() {
            let key = peer_name
                .and_then(|n| self.key_registry.get_key_for_peer(n))
                .or_else(|| self.key_registry.get_key_for_peer(""))
                .unwrap_or(&[0u8; 32]);

            if let Ok(datagram) = encrypt_datagram(key, &serialized) {
                let _ = self.socket.send_to(&datagram, dest).await;
            }
        }
    }
}
