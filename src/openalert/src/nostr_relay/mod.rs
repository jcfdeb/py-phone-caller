//! # Embedded Nostr Micro-Relay Server
//!
//! Provides a zero-external-dependency, in-process Nostr WebSocket server adhering to:
//! - **NIP-01**: Core WebSocket protocol (`EVENT`, `REQ`, `CLOSE`, `OK`, `EOSE`, `NOTICE`).
//! - **NIP-11**: Relay Information Document (served via HTTP GET with `Accept: application/nostr+json`).
//! - **NIP-04 / NIP-44 / NIP-59**: End-to-end encrypted direct messages and Gift Wraps passthrough.

use crate::config::NostrRelayServerConfig;
use crate::models::NostrEvent;
use crate::storage::Storage;
use axum::{
    Router,
    extract::{
        State,
        ws::{Message, WebSocket, WebSocketUpgrade},
    },
    http::{HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::sync::{RwLock, broadcast};
use tracing::{debug, error, info};

/// In-memory subscription filter representation following NIP-01.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct NostrFilter {
    #[serde(default)]
    pub ids: Option<Vec<String>>,
    #[serde(default)]
    pub authors: Option<Vec<String>>,
    #[serde(default)]
    pub kinds: Option<Vec<u64>>,
    #[serde(rename = "#e", default)]
    pub tag_e: Option<Vec<String>>,
    #[serde(rename = "#p", default)]
    pub tag_p: Option<Vec<String>>,
    #[serde(rename = "#t", default)]
    pub tag_t: Option<Vec<String>>,
    #[serde(default)]
    pub since: Option<u64>,
    #[serde(default)]
    pub until: Option<u64>,
    #[serde(default)]
    pub limit: Option<usize>,
}

impl NostrFilter {
    /// Checks if a NostrEvent satisfies this filter.
    pub fn matches(&self, event: &NostrEvent) -> bool {
        if let Some(ref ids) = self.ids
            && !ids.iter().any(|id| event.id.starts_with(id))
        {
            return false;
        }
        if let Some(ref authors) = self.authors
            && !authors.iter().any(|author| event.pubkey.starts_with(author))
        {
            return false;
        }
        if let Some(ref kinds) = self.kinds
            && !kinds.contains(&event.kind)
        {
            return false;
        }
        if let Some(since) = self.since
            && event.created_at < since
        {
            return false;
        }
        if let Some(until) = self.until
            && event.created_at > until
        {
            return false;
        }
        if let Some(ref tag_p_list) = self.tag_p {
            let matched = event.tags.iter().any(|t| {
                t.len() >= 2 && t[0] == "p" && tag_p_list.iter().any(|p| p.eq_ignore_ascii_case(&t[1]))
            });
            if !matched {
                return false;
            }
        }
        if let Some(ref tag_e_list) = self.tag_e {
            let matched = event.tags.iter().any(|t| {
                t.len() >= 2 && t[0] == "e" && tag_e_list.iter().any(|e| e.eq_ignore_ascii_case(&t[1]))
            });
            if !matched {
                return false;
            }
        }
        if let Some(ref tag_t_list) = self.tag_t {
            let matched = event.tags.iter().any(|t| {
                t.len() >= 2 && t[0] == "t" && tag_t_list.iter().any(|topic| topic.eq_ignore_ascii_case(&t[1]))
            });
            if !matched {
                return false;
            }
        }
        true
    }
}

/// Relay state shared across all WebSocket client sessions.
pub struct RelayState {
    pub config: NostrRelayServerConfig,
    pub storage: Option<Arc<Storage>>,
    pub broadcast_tx: broadcast::Sender<Arc<NostrEvent>>,
    /// In-memory cache of recent events for quick historical replay.
    pub mem_events: RwLock<Vec<Arc<NostrEvent>>>,
}

impl RelayState {
    pub fn new(config: NostrRelayServerConfig, storage: Option<Arc<Storage>>) -> Self {
        let (broadcast_tx, _) = broadcast::channel(1024);
        Self {
            config,
            storage,
            broadcast_tx,
            mem_events: RwLock::new(Vec::with_capacity(1000)),
        }
    }

    /// Stores an event in memory and optional persistent storage.
    pub async fn save_event(&self, event: NostrEvent) -> Result<bool, String> {
        let arc_ev = Arc::new(event);

        // Check if already in memory
        {
            let mut mem = self.mem_events.write().await;
            if mem.iter().any(|e| e.id == arc_ev.id) {
                return Ok(false);
            }
            if mem.len() >= self.config.max_events {
                mem.remove(0);
            }
            mem.push(arc_ev.clone());
        }

        // Persist to SQLite if enabled
        if let Some(ref storage) = self.storage {
            let _ = storage.save_nostr_event(&arc_ev).await;
        }

        // Broadcast to all active subscribers
        let _ = self.broadcast_tx.send(arc_ev);
        Ok(true)
    }

    /// Queries events from memory or SQLite storage matching a filter.
    pub async fn query_events(&self, filter: &NostrFilter) -> Vec<Arc<NostrEvent>> {
        let limit = filter.limit.unwrap_or(50).clamp(1, 500);

        if let Some(ref storage) = self.storage
            && self.config.storage_backend == "sqlite" {
                let kinds_slice = filter.kinds.as_deref();
                let authors_slice = filter.authors.as_deref();
                let tag_p_slice = filter.tag_p.as_deref();
                let tag_e_slice = filter.tag_e.as_deref();

                if let Ok(events) = storage
                    .query_nostr_events(
                        kinds_slice,
                        authors_slice,
                        filter.since,
                        filter.until,
                        tag_p_slice,
                        tag_e_slice,
                        limit,
                    )
                    .await
                {
                    return events.into_iter().map(Arc::new).collect();
                }
        }

        // Fallback to in-memory events
        let mem = self.mem_events.read().await;
        let mut matched = Vec::new();
        for ev in mem.iter().rev() {
            if filter.matches(ev) {
                matched.push(ev.clone());
                if matched.len() >= limit {
                    break;
                }
            }
        }
        matched.reverse();
        matched
    }
}

/// Primary embedded Nostr micro-relay service controller.
pub struct EmbeddedNostrRelay {
    config: NostrRelayServerConfig,
    state: Arc<RelayState>,
}

impl EmbeddedNostrRelay {
    pub fn new(config: NostrRelayServerConfig, storage: Option<Arc<Storage>>) -> Self {
        let state = Arc::new(RelayState::new(config.clone(), storage));
        Self { config, state }
    }

    /// Starts the micro-relay TCP/HTTP/WebSocket listener.
    pub async fn start(&self) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let bind_addr: SocketAddr = self.config.bind_address.parse()?;
        let state = self.state.clone();

        let app = Router::new()
            .route("/", get(handle_root_or_ws))
            .with_state(state);

        if self.config.tls.enabled {
            let _ = rustls::crypto::ring::default_provider().install_default();
            let cert_path = self.config.tls.cert_path.as_deref().ok_or_else(|| {
                std::io::Error::new(std::io::ErrorKind::InvalidInput, "Missing cert_path for native relay TLS")
            })?;
            let key_path = self.config.tls.key_path.as_deref().ok_or_else(|| {
                std::io::Error::new(std::io::ErrorKind::InvalidInput, "Missing key_path for native relay TLS")
            })?;

            let tls_config = axum_server::tls_rustls::RustlsConfig::from_pem_file(cert_path, key_path).await?;

            info!(
                "🔒 [Embedded Nostr Relay] Spawning tactical micro-relay with native TLS on wss://{} ('{}')",
                bind_addr, self.config.name
            );

            tokio::spawn(async move {
                if let Err(e) = axum_server::bind_rustls(bind_addr, tls_config)
                    .serve(app.into_make_service_with_connect_info::<SocketAddr>())
                    .await
                {
                    error!("Embedded Nostr TLS relay terminated: {}", e);
                }
            });
        } else {
            info!(
                "📡 [Embedded Nostr Relay] Spawning tactical micro-relay on ws://{} ('{}')",
                bind_addr, self.config.name
            );

            tokio::spawn(async move {
                if let Err(e) = axum_server::bind(bind_addr)
                    .serve(app.into_make_service_with_connect_info::<SocketAddr>())
                    .await
                {
                    error!("Embedded Nostr relay terminated: {}", e);
                }
            });
        }

        Ok(())
    }
}

/// Handles either NIP-11 discovery GET or WebSocket upgrade on `/`.
async fn handle_root_or_ws(
    State(state): State<Arc<RelayState>>,
    headers: HeaderMap,
    ws: Result<WebSocketUpgrade, axum::extract::ws::rejection::WebSocketUpgradeRejection>,
) -> Response {
    // 1. If client sent WebSocket upgrade header, accept it
    if let Ok(ws) = ws {
        return ws.on_upgrade(move |socket| handle_websocket(socket, state));
    }

    // 2. Otherwise check for NIP-11 discovery
    let is_nip11 = headers
        .get("accept")
        .and_then(|v| v.to_str().ok())
        .map(|v| v.contains("application/nostr+json"))
        .unwrap_or(false);

    if is_nip11 {
        let doc = serde_json::json!({
            "name": state.config.name,
            "description": state.config.description,
            "contact": state.config.contact,
            "supported_nips": [1, 4, 11, 17, 20, 44, 59],
            "software": "openalertd-embedded-relay",
            "version": env!("CARGO_PKG_VERSION"),
        });

        return (
            StatusCode::OK,
            [
                ("content-type", "application/nostr+json"),
                ("access-control-allow-origin", "*"),
            ],
            doc.to_string(),
        )
            .into_response();
    }

    // Default friendly HTTP greeting
    (
        StatusCode::OK,
        [("content-type", "text/plain; charset=utf-8")],
        format!(
            "{} is running.\nConnect using a Nostr client (like 0xChat) via WebSocket: {}://{}",
            state.config.name, if state.config.tls.enabled { "wss" } else { "ws" }, state.config.bind_address
        ),
    )
        .into_response()
}

/// Per-connection WebSocket handler processing NIP-01 frames.
async fn handle_websocket(socket: WebSocket, state: Arc<RelayState>) {
    let (mut ws_sender, mut ws_receiver) = socket.split();
    let mut subscriptions: HashMap<String, Vec<NostrFilter>> = HashMap::new();
    let mut broadcast_rx = state.broadcast_tx.subscribe();

    loop {
        tokio::select! {
            // Outbound live event broadcast to matching client subscriptions
            Ok(live_event) = broadcast_rx.recv() => {
                for (sub_id, filters) in &subscriptions {
                    if filters.iter().any(|f| f.matches(&live_event)) {
                        let msg = serde_json::json!(["EVENT", sub_id, &*live_event]);
                        if let Err(e) = ws_sender.send(Message::Text(msg.to_string().into())).await {
                            debug!("Error pushing live event to subscriber: {}", e);
                            return;
                        }
                    }
                }
            }

            // Inbound frame from WebSocket client
            maybe_msg = ws_receiver.next() => {
                let Some(msg_res) = maybe_msg else {
                    break;
                };
                let msg = match msg_res {
                    Ok(m) => m,
                    Err(e) => {
                        debug!("WebSocket frame error: {}", e);
                        break;
                    }
                };

                match msg {
                    Message::Text(text) => {
                        let parsed: serde_json::Value = match serde_json::from_str(&text) {
                            Ok(p) => p,
                            Err(_) => {
                                let notice = serde_json::json!(["NOTICE", "Error: Invalid JSON frame"]);
                                let _ = ws_sender.send(Message::Text(notice.to_string().into())).await;
                                continue;
                            }
                        };

                        let Some(arr) = parsed.as_array() else {
                            continue;
                        };
                        let Some(cmd) = arr.first().and_then(|v| v.as_str()) else {
                            continue;
                        };

                        match cmd {
                            // Client submitting an event: ["EVENT", { <event_json> }]
                            "EVENT" => {
                                if arr.len() < 2 {
                                    continue;
                                }
                                let event_val = &arr[1];
                                match serde_json::from_value::<NostrEvent>(event_val.clone()) {
                                    Ok(event) => {
                                        let event_id = event.id.clone();
                                        match state.save_event(event).await {
                                            Ok(_) => {
                                                // Send NIP-20 OK acknowledgment: ["OK", <event_id>, true, ""]
                                                let ok_msg = serde_json::json!(["OK", event_id, true, ""]);
                                                let _ = ws_sender.send(Message::Text(ok_msg.to_string().into())).await;
                                            }
                                            Err(err) => {
                                                let ok_msg = serde_json::json!(["OK", event_id, false, format!("error: {}", err)]);
                                                let _ = ws_sender.send(Message::Text(ok_msg.to_string().into())).await;
                                            }
                                        }
                                    }
                                    Err(err) => {
                                        let notice = serde_json::json!(["NOTICE", format!("Invalid EVENT payload: {}", err)]);
                                        let _ = ws_sender.send(Message::Text(notice.to_string().into())).await;
                                    }
                                }
                            }

                            // Client registering a subscription: ["REQ", <sub_id>, { <filter> }, ...]
                            "REQ" => {
                                if arr.len() < 3 {
                                    continue;
                                }
                                let Some(sub_id) = arr[1].as_str() else {
                                    continue;
                                };

                                let mut filters = Vec::new();
                                for filter_val in &arr[2..] {
                                    if let Ok(filter) = serde_json::from_value::<NostrFilter>(filter_val.clone()) {
                                        filters.push(filter);
                                    }
                                }

                                // 1. Replay matching historical events
                                for filter in &filters {
                                    let historical = state.query_events(filter).await;
                                    for ev in historical {
                                        let msg = serde_json::json!(["EVENT", sub_id, &*ev]);
                                        let _ = ws_sender.send(Message::Text(msg.to_string().into())).await;
                                    }
                                }

                                // 2. Send NIP-15 End of Stored Events: ["EOSE", <sub_id>]
                                let eose = serde_json::json!(["EOSE", sub_id]);
                                let _ = ws_sender.send(Message::Text(eose.to_string().into())).await;

                                // 3. Save subscription for live broadcasts
                                subscriptions.insert(sub_id.to_string(), filters);
                            }

                            // Client closing a subscription: ["CLOSE", <sub_id>]
                            "CLOSE" => {
                                if arr.len() >= 2 && let Some(sub_id) = arr[1].as_str() {
                                    subscriptions.remove(sub_id);
                                }
                            }

                            _ => {
                                let notice = serde_json::json!(["NOTICE", format!("Unknown Nostr command: {}", cmd)]);
                                let _ = ws_sender.send(Message::Text(notice.to_string().into())).await;
                            }
                        }
                    }
                    Message::Ping(payload) => {
                        let _ = ws_sender.send(Message::Pong(payload)).await;
                    }
                    Message::Close(_) => {
                        break;
                    }
                    _ => {}
                }
            }
        }
    }
}
