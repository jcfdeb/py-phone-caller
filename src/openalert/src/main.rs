//! # OpenAlert Daemon (`openalertd`)
//!
//! Multi-protocol alerting gateway linking local infrastructure, Nostr decentralized pub/sub relays,
//! and Bluetooth Low Energy BitChat ad-hoc mesh networks into a unified alerting pipeline.

use openalertd::bitchat::BitChatService;
use openalertd::config::AppConfig;
use openalertd::engine::AlertEngine;
use openalertd::error::Result;
use openalertd::ingress::nostr::NostrSubscriber;
use openalertd::peering::PeeringService;
use openalertd::ingress::rest::RestServer;
use std::env;
use std::sync::Arc;
use tracing::{info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    let config_path = if args.len() > 1 {
        args[1].clone()
    } else {
        "config/openalertd.toml".to_string()
    };

    let config = AppConfig::load(&config_path)?;

    // Configure logging subscriber: systemd mode (without timestamps) vs default mode (with ISO-8601 timestamps)
    let log_filter = std::env::var("RUST_LOG").unwrap_or_else(|_| {
        format!("openalertd={},tower_http=debug", config.daemon.log_level)
    });
    let env_filter = tracing_subscriber::EnvFilter::new(log_filter);

    if config.daemon.is_systemd_logging() {
        tracing_subscriber::registry()
            .with(env_filter)
            .with(tracing_subscriber::fmt::layer().without_time())
            .init();
    } else {
        tracing_subscriber::registry()
            .with(env_filter)
            .with(tracing_subscriber::fmt::layer())
            .init();
    }

    info!(
        "Starting OpenAlert Daemon (openalertd) [Config: {}, Logging: {}]",
        config_path,
        if config.daemon.is_systemd_logging() { "systemd" } else { "default" }
    );
    let engine = Arc::new(AlertEngine::new(config.clone())?);

    // If storage recovery is enabled, re-route pending alerts from previous session
    if config.storage.enabled && config.storage.recover_pending_on_startup {
        let _ = engine.recover_pending_alerts().await;
    }

    // Start background sliding-window pruning task
    if config.storage.enabled {
        engine.clone().start_background_pruning();
    }

    let nostr_sub = Arc::new(NostrSubscriber::new(config.nostr.clone(), engine.clone()));
    let _ = nostr_sub.start().await;

    let bitchat_service = Arc::new(BitChatService::new(
        config.bitchat.clone(),
        Some(engine.clone()),
    ));
    let bitchat_svc = bitchat_service.clone();
    tokio::spawn(async move {
        if let Err(e) = bitchat_svc.start().await {
            warn!("BitChat service ended: {}", e);
        }
    });

    // Start decentralized peering service if enabled
    if config.peering.enabled {
        match PeeringService::new(config.peering.clone(), engine.storage().cloned()).await {
            Ok(peering_svc) => {
                let peering_svc = Arc::new(peering_svc);
                peering_svc.set_engine(engine.clone()).await;
                engine.set_peering_service(peering_svc.clone()).await;
                peering_svc.start();
            }
            Err(e) => {
                warn!("Failed to initialize peering service: {}", e);
            }
        }
    }

    let rest_server = RestServer::new(config.rest.clone(), engine.clone());
    rest_server.run().await?;

    Ok(())
}
