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
//! - 3-Tier Off-Grid Authenticated LoRa Time Synchronization (`TimeSyncReq`, `TimeSyncResp`, `TimeBeacon`, and zero-air-time piggybacking).

pub mod circuit_breaker;
pub mod crypto;
pub mod lora;
pub mod routing;
pub mod wire;
pub mod worker;

pub use routing::{RouteEntry, RoutingTable};

use crate::config::{PeeringConfig, PeeringLinkType};
use crate::engine::AlertEngine;
use crate::error::{OpenAlertError, Result};
use crate::models::{Alert, PeeringStatusReport};
use crate::peering::crypto::{KeyRegistry, encrypt_datagram};
use crate::peering::lora::{LoraModulation, slip_encode};
use crate::peering::wire::{
    AckPacket, FLAG_ACK_REQ, FLAG_CANARY, PeeringPacket, RouteAdvPacket, TimeBeaconPacket,
    TimeSyncReqPacket, TimeSyncRespPacket,
};
use crate::peering::worker::{
    AckWaiters, OutboundAlertRequest, PeerWorkerHandle, spawn_peer_worker,
};
use crate::storage::Storage;
use rand::Rng;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::net::UdpSocket;
use tokio::sync::{Mutex, RwLock, mpsc};
use tracing::{debug, error, info, warn};

type LoraPendingReceivers = Arc<Mutex<HashMap<String, (u32, mpsc::Receiver<Vec<u8>>)>>>;

const SQLITE_TIME_SYNC_KEY: &str = "time_sync_last_verified_ms";

/// Central peering manager orchestrating UDP sockets, crypto, actor workers, and inbound routing.
pub struct PeeringService {
    config: PeeringConfig,
    socket: Arc<UdpSocket>,
    key_registry: Arc<KeyRegistry>,
    workers: Arc<HashMap<String, PeerWorkerHandle>>,
    ack_waiters: AckWaiters,
    dedup_cache: Arc<Mutex<HashMap<u64, Instant>>>,
    routing_table: Arc<RwLock<RoutingTable>>,
    engine: Arc<RwLock<Option<Arc<AlertEngine>>>>,
    storage: Option<Arc<Storage>>,
    lora_transmitters: Arc<HashMap<String, mpsc::Sender<Vec<u8>>>>,
    lora_pending_receivers: LoraPendingReceivers,
    pending_time_sync_nonce: Arc<Mutex<Option<(u64, Instant)>>>,
    last_opportunistic_beacon: Arc<Mutex<Option<Instant>>>,
}

impl PeeringService {
    /// Initializes the peering service and binds the listening UDP socket.
    pub async fn new(config: PeeringConfig, storage: Option<Arc<Storage>>) -> Result<Self> {
        let socket = UdpSocket::bind(&config.listen_addr).await.map_err(|e| {
            OpenAlertError::Peering(format!(
                "Failed to bind peering UDP socket on {}: {}",
                config.listen_addr, e
            ))
        })?;
        let socket = Arc::new(socket);

        // Seed monotonic timestamp floor from SQLite on cold boot if available
        if config.time_sync.enabled
            && let Some(ref st) = storage
            && let Ok(Some(saved_ms_str)) = st.get_sms_setting(SQLITE_TIME_SYNC_KEY).await
            && let Ok(saved_ms) = saved_ms_str.trim().parse::<i64>()
        {
            crate::time_sync::seed_persisted_timestamp_floor(saved_ms);
        }

        let peer_overrides: Vec<(String, Option<String>)> = config
            .nodes
            .iter()
            .map(|n| (n.name.clone(), n.shared_key.clone()))
            .collect();

        let key_registry = Arc::new(KeyRegistry::new(&config.shared_key, &peer_overrides)?);
        let ack_waiters: AckWaiters = Arc::new(Mutex::new(HashMap::new()));
        let engine: Arc<RwLock<Option<Arc<AlertEngine>>>> = Arc::new(RwLock::new(None));
        let mut workers = HashMap::new();

        let mut lora_tx_map = HashMap::new();
        let mut lora_rx_map = HashMap::new();

        for node in &config.nodes {
            if node.link_type == PeeringLinkType::LoraSerial {
                let dev = node
                    .serial_device
                    .clone()
                    .unwrap_or_else(|| "/dev/ttyUSB0".to_string());
                let baud = node.baud_rate.unwrap_or(115200);

                if !lora_tx_map.contains_key(&dev) {
                    let (tx, rx) = mpsc::channel::<Vec<u8>>(128);
                    lora_tx_map.insert(dev.clone(), tx);
                    lora_rx_map.insert(dev, (baud, rx));
                }
            }
        }

        let lora_transmitters = Arc::new(lora_tx_map);

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
                lora_transmitters.clone(),
                engine.clone(),
            );
            workers.insert(node.name.clone(), handle);
        }

        info!(
            "🛰️ Initialized Peering Subsystem on UDP {} [{} peer node(s) configured, time_sync: {} ({})]",
            config.listen_addr,
            workers.len(),
            if config.time_sync.enabled { "enabled" } else { "disabled" },
            config.time_sync.role
        );

        Ok(Self {
            config,
            socket,
            key_registry,
            workers: Arc::new(workers),
            ack_waiters,
            dedup_cache: Arc::new(Mutex::new(HashMap::new())),
            routing_table: Arc::new(RwLock::new(RoutingTable::new())),
            engine,
            storage,
            lora_transmitters,
            lora_pending_receivers: Arc::new(Mutex::new(lora_rx_map)),
            pending_time_sync_nonce: Arc::new(Mutex::new(None)),
            last_opportunistic_beacon: Arc::new(Mutex::new(None)),
        })
    }

    /// Resolves the effective time synchronization role ("server", "client", or "disabled").
    pub fn effective_time_sync_role(&self) -> &'static str {
        if !self.config.time_sync.enabled {
            return "disabled";
        }
        match self.config.time_sync.role.trim().to_lowercase().as_str() {
            "server" => "server",
            "client" => "client",
            _ => {
                let has_explicit_time_source = self
                    .config
                    .nodes
                    .iter()
                    .any(|n| n.time_source == Some(true));
                if has_explicit_time_source || !crate::time_sync::is_os_clock_ntp_synced() {
                    "client"
                } else {
                    "server"
                }
            }
        }
    }

    /// Returns the active clock skew tolerance in seconds, tightening to `synced_clock_skew_tolerance_secs` once synchronized.
    pub fn effective_skew_tolerance_secs(&self) -> u64 {
        if self.config.time_sync.enabled && crate::time_sync::is_synchronized() {
            self.config.time_sync.synced_clock_skew_tolerance_secs
        } else {
            self.config.clock_skew_tolerance_secs
        }
    }

    /// Checks whether a given peer is authorized to act as an upstream time reference for this node.
    fn is_peer_authorized_time_source(&self, peer_name: Option<&str>) -> bool {
        if !self.config.time_sync.enabled || self.effective_time_sync_role() == "server" {
            return false;
        }
        if let Some(name) = peer_name {
            for node in &self.config.nodes {
                if node.name == name {
                    return node.time_source.unwrap_or(true);
                }
            }
        }
        true
    }

    /// Estimates the one-way physical transmission air-time (in milliseconds) for a peer frame of size `datagram_len`.
    fn estimate_peer_air_time_ms(&self, peer_name: Option<&str>, datagram_len: usize) -> f64 {
        let peer_node = peer_name
            .and_then(|name| self.config.nodes.iter().find(|n| n.name == name))
            .or_else(|| {
                self.config
                    .nodes
                    .iter()
                    .find(|n| n.link_type == PeeringLinkType::LoraSerial)
            });

        if let Some(node) = peer_node {
            match node.link_type {
                PeeringLinkType::LoraSerial | PeeringLinkType::Lora => {
                    let mod_params = LoraModulation {
                        spreading_factor: node.spreading_factor.unwrap_or(7),
                        bandwidth_khz: node.bandwidth_khz.unwrap_or(125),
                        ..Default::default()
                    };
                    mod_params.calculate_air_time_ms(datagram_len)
                }
                PeeringLinkType::Lan | PeeringLinkType::Vpn => 2.0,
            }
        } else {
            50.0
        }
    }

    /// Applies a verified gateway timestamp and persists the latest synchronized floor into SQLite.
    async fn apply_and_persist_time_sync(
        &self,
        gateway_utc_ms: i64,
        datagram_len: usize,
        peer_name: Option<&str>,
        is_challenge_response: bool,
    ) {
        let src_peer = peer_name.unwrap_or("lora-gateway");
        let air_time_ms = self.estimate_peer_air_time_ms(peer_name, datagram_len);

        if crate::time_sync::apply_verified_gateway_time(
            gateway_utc_ms,
            air_time_ms,
            src_peer,
            self.config.time_sync.step_system_clock,
            is_challenge_response,
        )
        .is_some()
            && let Some(ref st) = self.storage
        {
            let now_ms_str = crate::time_sync::now_utc_ms().to_string();
            let _ = st.set_sms_setting(SQLITE_TIME_SYNC_KEY, &now_ms_str).await;
        }
    }

    /// Transmits an encrypted control packet (`TimeSyncReq`, `TimeSyncResp`, or `TimeBeacon`) to a peer.
    async fn send_control_packet(
        &self,
        pkt: &PeeringPacket,
        peer_name: Option<&str>,
        udp_addr: Option<std::net::SocketAddr>,
    ) {
        let Ok(serialized) = pkt.serialize() else {
            return;
        };

        let key = peer_name
            .and_then(|n| self.key_registry.get_key_for_peer(n))
            .or_else(|| self.key_registry.get_key_for_peer(""))
            .unwrap_or(&[0u8; 32]);

        let Ok(datagram) = encrypt_datagram(key, &serialized) else {
            return;
        };

        let peer_node = peer_name
            .and_then(|name| self.config.nodes.iter().find(|n| n.name == name))
            .or_else(|| {
                if udp_addr.is_none() {
                    self.config
                        .nodes
                        .iter()
                        .find(|n| n.link_type == PeeringLinkType::LoraSerial)
                } else {
                    None
                }
            });

        if let Some(node) = peer_node
            && node.link_type == PeeringLinkType::LoraSerial
        {
            let dev_path = node.serial_device.as_deref().unwrap_or("/dev/ttyUSB0");
            if let Some(tx) = self.lora_transmitters.get(dev_path) {
                let framed = slip_encode(&datagram);
                let _ = tx.send(framed).await;
            }
            return;
        }

        if let Some(dest) = udp_addr.or_else(|| peer_node.and_then(|n| n.addr.parse().ok())) {
            let _ = self.socket.send_to(&datagram, dest).await;
        }
    }

    /// Links the central routing engine to receive verified inbound peering alerts.
    pub async fn set_engine(&self, engine: Arc<AlertEngine>) {
        let mut eng = self.engine.write().await;
        *eng = Some(engine);
    }

    /// Returns current active dynamic routing table entries.
    pub async fn get_routes(&self) -> Vec<RouteEntry> {
        let rt = self.routing_table.read().await;
        rt.get_routes(Duration::from_secs(300))
    }

    /// Returns live diagnostics across all configured peering workers, circuit breakers, and LoRa time sync.
    pub async fn get_diagnostics(&self) -> PeeringStatusReport {
        let rt = self.routing_table.read().await;
        let mut peers = Vec::new();
        for worker in self.workers.values() {
            let mut diag = worker.get_diagnostics(self.storage.as_deref()).await;
            diag.last_seen_seconds_ago = rt.get_peer_last_seen_secs(&diag.name);
            if let Some(rf) = rt.get_peer_rf_telemetry(&diag.name) {
                diag.rssi_dbm = Some(rf.avg_rssi_dbm);
                diag.snr_db = Some(rf.avg_snr_db);
                diag.rf_penalty = Some(rf.penalty);
            }
            peers.push(diag);
        }
        peers.sort_by(|a, b| a.name.cmp(&b.name));
        let time_sync = Some(crate::time_sync::get_status_report(
            self.config.time_sync.enabled,
            self.effective_time_sync_role(),
            self.effective_skew_tolerance_secs(),
        ));
        PeeringStatusReport {
            enabled: self.config.enabled,
            listen_addr: self.config.listen_addr.clone(),
            peers,
            time_sync,
        }
    }

    /// Manually resets a specific peer's circuit breaker to CLOSED.
    pub async fn reset_peer_circuit_breaker(&self, peer_name: &str) -> bool {
        if let Some(worker) = self.workers.get(peer_name) {
            worker.reset_circuit_breaker().await;
            true
        } else {
            false
        }
    }

    /// Starts the background UDP receiver, LoRa Serial physical duplex tasks, and 3-tier TimeSync + Heartbeat tasks.
    pub fn start(self: Arc<Self>) {
        let self_udp = self.clone();
        tokio::spawn(async move {
            self_udp.run_rx_loop().await;
        });

        // Spawn LoRa Serial duplex loops for any configured LoraSerial nodes
        let self_lora = self.clone();
        tokio::spawn(async move {
            let receivers = {
                let mut guard = self_lora.lora_pending_receivers.lock().await;
                std::mem::take(&mut *guard)
            };
            for (dev, (baud, rx)) in receivers {
                let s = self_lora.clone();
                tokio::spawn(async move {
                    s.run_lora_serial_duplex_loop(dev, baud, rx).await;
                });
            }
        });

        // Tier 2a & Periodic Client Heartbeat: Cold-Boot TimeSyncReq + periodic LoRa link heartbeat
        if self.config.time_sync.enabled && self.effective_time_sync_role() == "client" {
            let self_req = self.clone();
            let request_on_boot = self.config.time_sync.request_on_boot;
            let heartbeat_mins = self.config.time_sync.heartbeat_interval_minutes;

            tokio::spawn(async move {
                // Allow serial/UDP interfaces 2s to initialize on startup
                tokio::time::sleep(Duration::from_secs(2)).await;

                if request_on_boot {
                    let retry_delays_secs = [15u64, 30u64, 60u64];
                    for (attempt, delay_secs) in retry_delays_secs.iter().enumerate() {
                        if attempt > 0 && crate::time_sync::is_synchronized() {
                            break;
                        }

                        let nonce: u64 = rand::rng().random();
                        {
                            let mut guard = self_req.pending_time_sync_nonce.lock().await;
                            *guard = Some((nonce, Instant::now()));
                        }

                        let pkt = PeeringPacket::TimeSyncReq(TimeSyncReqPacket {
                            client_nonce: nonce,
                            client_ts_ms: crate::time_sync::now_utc_ms(),
                            src: "fog-client".to_string(),
                        });

                        for node in &self_req.config.nodes {
                            if node.time_source.unwrap_or(true) {
                                info!(
                                    "⏳ [LoRa TimeSync] Emitting cold-boot TimeSyncReq (attempt {}/{}, nonce: 0x{:016x}) to peer '{}'",
                                    attempt + 1,
                                    retry_delays_secs.len(),
                                    nonce,
                                    node.name
                                );
                                self_req
                                    .send_control_packet(&pkt, Some(&node.name), None)
                                    .await;
                            }
                        }

                        tokio::time::sleep(Duration::from_secs(*delay_secs)).await;
                        if crate::time_sync::is_synchronized() {
                            break;
                        }
                    }
                }

                // Periodic bidirectional LoRa heartbeat + clock drift compensation loop
                if heartbeat_mins > 0 {
                    let base_secs = heartbeat_mins.saturating_mul(60);
                    loop {
                        let jitter_secs: u64 = rand::rng().random_range(0..=15);
                        tokio::time::sleep(Duration::from_secs(base_secs + jitter_secs)).await;

                        let nonce: u64 = rand::rng().random();
                        {
                            let mut guard = self_req.pending_time_sync_nonce.lock().await;
                            *guard = Some((nonce, Instant::now()));
                        }

                        let pkt = PeeringPacket::TimeSyncReq(TimeSyncReqPacket {
                            client_nonce: nonce,
                            client_ts_ms: crate::time_sync::now_utc_ms(),
                            src: "fog-client".to_string(),
                        });

                        for node in &self_req.config.nodes {
                            if node.time_source.unwrap_or(true) {
                                info!(
                                    "💓 [LoRa Heartbeat] Emitting periodic TimeSyncReq heartbeat (nonce: 0x{:016x}) to peer '{}'",
                                    nonce, node.name
                                );
                                self_req
                                    .send_control_packet(&pkt, Some(&node.name), None)
                                    .await;
                            }
                        }
                    }
                }
            });
        }

        // Tier 2b: Periodic TimeBeacon loop for NTP-backed server nodes (configurable in minutes or hours)
        let beacon_interval_secs = self.config.time_sync.effective_beacon_interval_secs();
        if self.config.time_sync.enabled
            && beacon_interval_secs > 0
            && self.effective_time_sync_role() == "server"
        {
            let self_beacon = self.clone();
            tokio::spawn(async move {
                // Emit an initial startup TimeBeacon after 6s so listening FOG nodes lock immediately
                tokio::time::sleep(Duration::from_secs(6)).await;
                loop {
                    if crate::time_sync::is_synchronized() {
                        let pkt = PeeringPacket::TimeBeacon(TimeBeaconPacket {
                            server_utc_ms: crate::time_sync::now_utc_ms(),
                            src: "gateway".to_string(),
                        });
                        for node in &self_beacon.config.nodes {
                            if matches!(
                                node.link_type,
                                PeeringLinkType::LoraSerial | PeeringLinkType::Lora
                            ) {
                                info!(
                                    "🕰️ [LoRa TimeSync] Broadcasting authoritative TimeBeacon to LoRa peer '{}' (utc_ms: {}, interval: {}s)",
                                    node.name,
                                    crate::time_sync::now_utc_ms(),
                                    beacon_interval_secs
                                );
                                self_beacon
                                    .send_control_packet(&pkt, Some(&node.name), None)
                                    .await;
                            }
                        }
                    }

                    let jitter_secs: u64 = rand::rng().random_range(0..=15);
                    let sleep_secs = beacon_interval_secs.saturating_add(jitter_secs);
                    tokio::time::sleep(Duration::from_secs(sleep_secs)).await;
                }
            });
        }
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
                && origin == name
            {
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
            let src_desc = format!("udp:{}", src_addr);
            self.process_inbound_datagram(datagram, &src_desc, Some(src_addr))
                .await;
        }
    }

    async fn run_lora_serial_duplex_loop(
        self: Arc<Self>,
        dev_path: String,
        baud_rate: u32,
        mut tx_rx: mpsc::Receiver<Vec<u8>>,
    ) {
        use crate::peering::lora::SlipDecoder;
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        use tokio_serial::SerialPortBuilderExt;

        let mut decoder = SlipDecoder::new();
        let mut read_buf = [0u8; 256];
        let mut supervisor = crate::watchdog::UsbPortSupervisor::new(&dev_path, 3);

        loop {
            let port = match tokio_serial::new(&dev_path, baud_rate).open_native_async() {
                Ok(p) => {
                    info!(
                        "📻 [LoRa Serial Duplex] Actively opened {} at {} baud",
                        dev_path, baud_rate
                    );
                    supervisor.record_success();
                    p
                }
                Err(e) => {
                    debug!(
                        "LoRa serial port '{}' not currently available ({}). Retrying in 5s...",
                        dev_path, e
                    );
                    if let Ok(true) = supervisor.record_failure() {
                        info!("🔌 Triggered autonomous USB reset for '{}'; waiting 2s for kernel re-enumeration", dev_path);
                        tokio::time::sleep(Duration::from_secs(2)).await;
                    }
                    tokio::time::sleep(Duration::from_secs(5)).await;
                    continue;
                }
            };

            let (mut reader, mut writer) = tokio::io::split(port);

            loop {
                tokio::select! {
                    read_res = reader.read(&mut read_buf) => {
                        match read_res {
                            Ok(0) => {
                                warn!(
                                    "LoRa serial port '{}' read 0 bytes (disconnected). Reconnecting...",
                                    dev_path
                                );
                                if let Ok(true) = supervisor.record_failure() {
                                    info!("🔌 Triggered autonomous USB reset for '{}'; waiting 2s for kernel re-enumeration", dev_path);
                                    tokio::time::sleep(Duration::from_secs(2)).await;
                                }
                                tokio::time::sleep(Duration::from_secs(3)).await;
                                break;
                            }
                            Ok(n) => {
                                supervisor.record_success();
                                let frames = decoder.decode_chunk(&read_buf[..n]);
                                for frame in frames {
                                    let src_desc = format!("lora:{}", dev_path);
                                    self.process_inbound_datagram(&frame, &src_desc, None).await;
                                }
                            }
                            Err(e) => {
                                debug!(
                                    "LoRa serial read interrupted on '{}' ({}). Re-opening port...",
                                    dev_path, e
                                );
                                if let Ok(true) = supervisor.record_failure() {
                                    info!("🔌 Triggered autonomous USB reset for '{}'; waiting 2s for kernel re-enumeration", dev_path);
                                    tokio::time::sleep(Duration::from_secs(2)).await;
                                }
                                tokio::time::sleep(Duration::from_secs(2)).await;
                                break;
                            }
                        }
                    }
                    outbound = tx_rx.recv() => {
                        match outbound {
                            Some(packet) => {
                                if let Err(e) = writer.write_all(&packet).await {
                                    warn!("LoRa serial write_all error on '{}': {}", dev_path, e);
                                    if let Ok(true) = supervisor.record_failure() {
                                        info!("🔌 Triggered autonomous USB reset for '{}'; waiting 2s for kernel re-enumeration", dev_path);
                                        tokio::time::sleep(Duration::from_secs(2)).await;
                                    }
                                    break;
                                }
                                if let Err(e) = writer.flush().await {
                                    warn!("LoRa serial flush error on '{}': {}", dev_path, e);
                                    if let Ok(true) = supervisor.record_failure() {
                                        info!("🔌 Triggered autonomous USB reset for '{}'; waiting 2s for kernel re-enumeration", dev_path);
                                        tokio::time::sleep(Duration::from_secs(2)).await;
                                    }
                                    break;
                                }
                                supervisor.record_success();
                            }
                            None => {
                                return;
                            }
                        }
                    }
                }
            }
        }
    }

    async fn process_inbound_datagram(
        &self,
        datagram: &[u8],
        src_desc: &str,
        udp_addr: Option<std::net::SocketAddr>,
    ) {
        let dedup_window = Duration::from_secs(self.config.dedup_ttl_secs);

        // 1. Decrypt and authenticate using XChaCha20-Poly1305 (with optional LoRa RF trailer)
        let (actual_decrypted, rf_telemetry) = match self.key_registry.try_decrypt_any(datagram) {
            Some(res) => (res, None),
            None => {
                let (stripped, telem) = crate::peering::lora::strip_lora_rf_trailer(datagram);
                match self.key_registry.try_decrypt_any(stripped) {
                    Some(res) => (res, telem),
                    None => {
                        debug!(
                            "⚠️ Discarded unauthenticated peering datagram ({} bytes) from {}",
                            datagram.len(),
                            src_desc
                        );
                        return;
                    }
                }
            }
        };

        let (plaintext, mut matched_peer) = actual_decrypted;

        // Match peer identity: from UDP address or LoRa serial node definition
        if matched_peer.is_none() {
            if let Some(src_addr) = udp_addr {
                for peer_node in &self.config.nodes {
                    if let Ok(target_addr) = peer_node.addr.parse::<std::net::SocketAddr>()
                        && (target_addr == src_addr
                            || (target_addr.ip() == src_addr.ip()
                                && target_addr.port() == src_addr.port()))
                    {
                        matched_peer = Some(peer_node.name.clone());
                        break;
                    }
                }
            } else {
                for peer_node in &self.config.nodes {
                    if peer_node.link_type == PeeringLinkType::LoraSerial {
                        matched_peer = Some(peer_node.name.clone());
                        break;
                    }
                }
            }
        }

        if let Some(ref peer_name) = matched_peer {
            self.routing_table.write().await.record_peer_seen(peer_name);
            if let Some(telem) = rf_telemetry {
                let penalty = self.routing_table.write().await.update_peer_rf_telemetry(
                    peer_name,
                    telem.rssi_dbm,
                    telem.snr_db,
                );
                let eng_guard = self.engine.read().await;
                if let Some(ref eng) = *eng_guard {
                    eng.metrics()
                        .peering_rf_rssi_dbm
                        .with_label_values(&[peer_name])
                        .set(telem.rssi_dbm as f64);
                    eng.metrics()
                        .peering_rf_snr_db
                        .with_label_values(&[peer_name])
                        .set(telem.snr_db as f64);
                    eng.metrics()
                        .peering_rf_penalty_points
                        .with_label_values(&[peer_name])
                        .set(penalty as f64);
                }
            }
        }

        // 2. Deserialize packed tuple binary payload
        let packet = match PeeringPacket::deserialize(&plaintext) {
            Ok(p) => p,
            Err(e) => {
                debug!(
                    "Failed to deserialize valid AEAD datagram from {}: {}",
                    src_desc, e
                );
                return;
            }
        };

        // 3. Process packet variants
        match packet {
            PeeringPacket::TimeSyncReq(req) => {
                if self.config.time_sync.enabled
                    && (self.effective_time_sync_role() == "server"
                        || crate::time_sync::is_os_clock_ntp_synced())
                {
                    let resp = PeeringPacket::TimeSyncResp(TimeSyncRespPacket {
                        client_nonce: req.client_nonce,
                        server_utc_ms: crate::time_sync::now_utc_ms(),
                        src: "gateway".to_string(),
                    });
                    info!(
                        "⏱️ [LoRa TimeSync] Responding to TimeSyncReq (nonce: 0x{:016x}) from '{}' ({}) with UTC {}ms",
                        req.client_nonce,
                        matched_peer.as_deref().unwrap_or(&req.src),
                        src_desc,
                        crate::time_sync::now_utc_ms()
                    );
                    self.send_control_packet(&resp, matched_peer.as_deref(), udp_addr)
                        .await;
                }
            }
            PeeringPacket::TimeSyncResp(resp) => {
                if self.config.time_sync.enabled && self.effective_time_sync_role() != "server" {
                    let nonce_valid = {
                        let mut guard = self.pending_time_sync_nonce.lock().await;
                        if let Some((expected_nonce, sent_at)) = *guard {
                            if expected_nonce == resp.client_nonce
                                && sent_at.elapsed() < Duration::from_secs(30)
                            {
                                *guard = None;
                                true
                            } else {
                                false
                            }
                        } else {
                            false
                        }
                    };

                    if nonce_valid {
                        let src_peer = matched_peer.as_deref().or(Some(resp.src.as_str()));
                        self.apply_and_persist_time_sync(
                            resp.server_utc_ms,
                            datagram.len(),
                            src_peer,
                            true,
                        )
                        .await;
                    } else {
                        warn!(
                            "🛑 [LoRa TimeSync] Ignored TimeSyncResp with unmatched or expired nonce 0x{:016x} from {}",
                            resp.client_nonce, src_desc
                        );
                    }
                }
            }
            PeeringPacket::TimeBeacon(beacon) => {
                if self.is_peer_authorized_time_source(matched_peer.as_deref()) {
                    let src_peer = matched_peer.as_deref().or(Some(beacon.src.as_str()));
                    self.apply_and_persist_time_sync(
                        beacon.server_utc_ms,
                        datagram.len(),
                        src_peer,
                        false,
                    )
                    .await;

                    // Reply with a lightweight RouteAdv heartbeat after a short half-duplex turnaround delay
                    // so the upstream gateway also updates its last_seen & RF telemetry for this client node.
                    let local_node_name = {
                        let eng = self.engine.read().await;
                        eng.as_ref()
                            .map(|e| e.config().daemon.name.clone())
                            .unwrap_or_else(|| "fog-client".to_string())
                    };
                    let peer_clone = matched_peer.clone();
                    let adv = PeeringPacket::RouteAdv(RouteAdvPacket {
                        src: local_node_name.clone(),
                        ts: crate::time_sync::now_utc_secs() as u32,
                        dst: local_node_name,
                        metric: 100,
                        hops: 1,
                    });
                    let turnaround_ms: u64 = rand::rng().random_range(1500..=2500);
                    info!(
                        "🕰️ [LoRa TimeSync] Received authoritative TimeBeacon from '{}' (utc_ms: {}); replying with RouteAdv heartbeat in {}ms",
                        src_peer.unwrap_or("gateway"),
                        beacon.server_utc_ms,
                        turnaround_ms
                    );
                    tokio::time::sleep(Duration::from_millis(turnaround_ms)).await;
                    self.send_control_packet(&adv, peer_clone.as_deref(), udp_addr)
                        .await;
                }
            }
            PeeringPacket::RouteAdv(adv) => {
                if adv.ts > 0 && self.is_peer_authorized_time_source(matched_peer.as_deref()) {
                    self.apply_and_persist_time_sync(
                        (adv.ts as i64) * 1000,
                        datagram.len(),
                        matched_peer.as_deref().or(Some(adv.src.as_str())),
                        false,
                    )
                    .await;
                }
                let mut rt = self.routing_table.write().await;
                let via_peer = matched_peer.as_deref().unwrap_or(&adv.src);
                rt.update_route(&adv.dst, via_peer, adv.metric, adv.hops);
                info!(
                    "💓 [LoRa Heartbeat] Received RouteAdv heartbeat from '{}' (route: '{}', metric: {}, hops: {})",
                    via_peer, adv.dst, adv.metric, adv.hops
                );
            }
            PeeringPacket::Ack(ack) => {
                // Tier 1: Zero-air-time piggybacked clock synchronization from authenticated Ack
                if ack.ts > 0 && self.is_peer_authorized_time_source(matched_peer.as_deref()) {
                    self.apply_and_persist_time_sync(
                        (ack.ts as i64) * 1000,
                        datagram.len(),
                        matched_peer.as_deref(),
                        false,
                    )
                    .await;
                }
                let mut waiters = self.ack_waiters.lock().await;
                if let Some(tx) = waiters.remove(&ack.fp) {
                    let _ = tx.send(());
                }
            }
            PeeringPacket::Alert(alert_pkt) => {
                // Tier 1: Zero-air-time piggybacked clock synchronization from authenticated Gateway Alert
                if alert_pkt.ts > 0 && self.is_peer_authorized_time_source(matched_peer.as_deref())
                {
                    self.apply_and_persist_time_sync(
                        (alert_pkt.ts as i64) * 1000,
                        datagram.len(),
                        matched_peer.as_deref().or(Some(alert_pkt.src.as_str())),
                        false,
                    )
                    .await;
                }

                // Check if canary probe
                if alert_pkt.flags & FLAG_CANARY != 0 {
                    if alert_pkt.flags & FLAG_ACK_REQ != 0 {
                        self.send_ack(alert_pkt.fp, udp_addr, matched_peer.as_deref())
                            .await;
                    }
                    return;
                }

                // Clock skew validation (with opportunistic server TimeBeacon correction for skewed clients)
                if alert_pkt.ts > 0 {
                    let now_ts = crate::time_sync::now_utc_secs() as u32;
                    let skew_tolerance = self.effective_skew_tolerance_secs() as u32;
                    let skew_diff = now_ts.abs_diff(alert_pkt.ts);
                    let is_skewed = skew_diff > skew_tolerance;

                    // If we are an authoritative time server and the client's alert timestamp is skewed by >10s,
                    // opportunistically emit a TimeBeacon (rate-limited to 1 per 60s) so the client heals its clock!
                    if self.config.time_sync.enabled
                        && self.effective_time_sync_role() == "server"
                        && skew_diff > 10
                    {
                        let should_emit = {
                            let mut guard = self.last_opportunistic_beacon.lock().await;
                            match *guard {
                                Some(last) if last.elapsed() < Duration::from_secs(60) => false,
                                _ => {
                                    *guard = Some(Instant::now());
                                    true
                                }
                            }
                        };
                        if should_emit {
                            let beacon = PeeringPacket::TimeBeacon(TimeBeaconPacket {
                                server_utc_ms: crate::time_sync::now_utc_ms(),
                                src: "gateway".to_string(),
                            });
                            info!(
                                "🕰️ [LoRa TimeSync] Peer '{}' alert clock skewed by {}s; emitting opportunistic TimeBeacon",
                                matched_peer.as_deref().unwrap_or(&alert_pkt.src),
                                skew_diff
                            );
                            self.send_control_packet(&beacon, matched_peer.as_deref(), udp_addr)
                                .await;
                        }
                    }

                    if is_skewed {
                        warn!(
                            "⏱️ Discarded peering alert 0x{:016x} due to excessive clock skew (pkt_ts: {}, now: {}, tolerance: {}s)",
                            alert_pkt.fp, alert_pkt.ts, now_ts, skew_tolerance
                        );
                        return;
                    }
                }

                // Sliding-window deduplication check
                {
                    let mut cache = self.dedup_cache.lock().await;
                    let now = Instant::now();
                    cache.retain(|_, seen_at| now.duration_since(*seen_at) < dedup_window);

                    if cache.contains_key(&alert_pkt.fp) {
                        debug!(
                            "🛑 Dropped duplicate peering alert 0x{:016x} from {}",
                            alert_pkt.fp, src_desc
                        );
                        if alert_pkt.flags & FLAG_ACK_REQ != 0 {
                            self.send_ack(alert_pkt.fp, udp_addr, matched_peer.as_deref())
                                .await;
                        }
                        return;
                    }
                    cache.insert(alert_pkt.fp, now);
                }

                // Respond with ACK if requested (IP links and half-duplex LoRa Serial ARQ)
                if alert_pkt.flags & FLAG_ACK_REQ != 0 {
                    self.send_ack(alert_pkt.fp, udp_addr, matched_peer.as_deref())
                        .await;
                }

                // Convert to canonical Alert and route through daemon core
                let origin_name = matched_peer
                    .clone()
                    .unwrap_or_else(|| alert_pkt.src.clone());
                let alert = alert_pkt.clone().into_alert(Some(origin_name.clone()));

                info!(
                    "📥 [Peering Ingress] Ingested alert [{}] from '{}' via {} (Severity: {:?}, Summary: \"{}\")",
                    alert.alert_id,
                    alert.node.as_deref().or(alert.sender.as_deref()).unwrap_or("unknown"),
                    src_desc,
                    alert.severity,
                    alert.summary
                );

                // Dynamic route learning for alert sender
                {
                    let mut rt = self.routing_table.write().await;
                    let via_peer = matched_peer.as_deref().unwrap_or(&alert_pkt.src);
                    rt.update_route(&alert_pkt.src, via_peer, 20, 1);
                }

                // Multi-hop dynamic mesh forwarding
                if alert_pkt.hop > 1 {
                    let mut fwd_alert = alert.clone();
                    fwd_alert.hop = alert_pkt.hop - 1;
                    fwd_alert.origin_peer = Some(origin_name.clone());

                    for (peer_name, worker) in self.workers.iter() {
                        if peer_name == &origin_name
                            || peer_name == &alert_pkt.src
                            || Some(peer_name.as_str()) == alert.sender.as_deref()
                            || Some(peer_name.as_str()) == alert.node.as_deref()
                            || matched_peer.as_deref() == Some(peer_name.as_str())
                        {
                            // Strict Split-Horizon loop suppression
                            continue;
                        }
                        let req = OutboundAlertRequest {
                            alert: fwd_alert.clone(),
                            is_failover: false,
                        };
                        let _ = worker.dispatch(req).await;
                    }
                }

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

    async fn send_ack(
        &self,
        fp: u64,
        udp_addr: Option<std::net::SocketAddr>,
        peer_name: Option<&str>,
    ) {
        let ack_pkt = PeeringPacket::Ack(AckPacket {
            fp,
            ts: crate::time_sync::now_utc_secs() as u32,
        });

        if udp_addr.is_none() {
            // Half-duplex LoRa Serial turnaround delay so sender SX1262 transitions from TX to RX
            tokio::time::sleep(Duration::from_millis(180)).await;
        }

        self.send_control_packet(&ack_pkt, peer_name, udp_addr)
            .await;
    }
}
