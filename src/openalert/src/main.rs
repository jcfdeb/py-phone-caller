//! # OpenAlert Daemon (`openalertd`)
//!
//! Entrypoint for the high-availability incident response routing daemon.
//! Initializes configuration, Nostr subscribers, BitChat BLE mesh listeners,
//! and the Prometheus Alertmanager REST API server.

use openalertd::bitchat::BitChatService;
use openalertd::config::AppConfig;
use openalertd::engine::AlertEngine;
use openalertd::ingress::{NostrSubscriber, RestServer};
use std::env;
use std::sync::Arc;
use tracing::info;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| EnvFilter::new("info,openalertd=debug")),
        )
        .init();

    let args: Vec<String> = env::args().collect();
    let config_path = if args.len() > 1 {
        args[1].clone()
    } else {
        "config/openalertd.toml".to_string()
    };

    info!(
        "Starting OpenAlert Daemon (openalertd) [Config: {}]",
        config_path
    );

    let config = AppConfig::load(&config_path)?;
    let engine = Arc::new(AlertEngine::new(config.clone())?);

    let nostr_sub = Arc::new(NostrSubscriber::new(config.nostr.clone(), engine.clone()));
    nostr_sub.start().await;

    let bitchat_service = Arc::new(BitChatService::new(
        config.bitchat.clone(),
        Some(engine.clone()),
    ));
    let _ = bitchat_service.start().await;

    let rest_server = RestServer::new(config.rest.clone(), engine.clone());
    rest_server.run().await?;

    Ok(())
}
