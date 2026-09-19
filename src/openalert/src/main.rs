//! # OpenAlert Daemon (`openalertd`)
//!
//! Multi-protocol alerting gateway linking local infrastructure, Nostr decentralized pub/sub relays,
//! and Bluetooth Low Energy BitChat ad-hoc mesh networks into a unified alerting pipeline.

use openalertd::bitchat::BitChatService;
use openalertd::cli;
use openalertd::config::AppConfig;
use openalertd::engine::AlertEngine;
use openalertd::error::Result;
use openalertd::ingress::nostr::NostrSubscriber;
use openalertd::ingress::rest::RestServer;
use openalertd::peering::PeeringService;
use openalertd::{SmsService, Storage};
use std::env;
use std::sync::Arc;
use tracing::{info, warn};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

fn print_usage() {
    println!("OpenAlert Daemon (openalertd) - Mission-Critical Alert Router");
    println!();
    println!("USAGE:");
    println!("    openalertd [COMMAND] [OPTIONS]");
    println!();
    println!("COMMANDS:");
    println!("    check [config_path]       Validate syntax & consistency of configuration file (alias: check-config)");
    println!("    status [--url <api_url>]  Query live operational status from running daemon");
    println!("    peers  [--url <api_url>]  Query live peering link states and circuit breakers");
    println!("    spool  [--url <api_url>]  Query persistent peering spool backlog count");
    println!("    hash-password <password>  Generate SHA-256 hash for dashboard configuration (alias: hash)");
    println!("    generate-key              Generate 256-bit hex key for peering or Nostr encryption (alias: gen-key)");
    println!("    run   [config_path]       Explicitly start daemon in foreground (default)");
    println!("    help                      Display this help information");
    println!();
    println!("OPTIONS:");
    println!("    --url <api_url>           Base URL of daemon REST API (default: http://127.0.0.1:8090)");
    println!();
    println!("DEFAULT BEHAVIOR:");
    println!("    Running 'openalertd' without subcommands boots the daemon with config/openalertd.toml");
}

fn extract_url(args: &[String]) -> String {
    for i in 0..args.len() {
        if args[i] == "--url" && i + 1 < args.len() {
            return args[i + 1].clone();
        }
        if args[i].starts_with("--url=") {
            return args[i].trim_start_matches("--url=").to_string();
        }
    }
    "http://127.0.0.1:8090".to_string()
}

#[tokio::main]
async fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    let subcommand = args.get(1).map(|s| s.as_str()).unwrap_or("");

    match subcommand {
        "help" | "--help" | "-h" => {
            print_usage();
            return Ok(());
        }
        "check" | "check-config" => {
            let config_path = args.get(2).map(|s| s.as_str()).unwrap_or("config/openalertd.toml");
            match cli::validate_config(config_path) {
                Ok(summary) => {
                    println!("✅ Configuration file '{}' is VALID:\n{}", config_path, summary);
                    std::process::exit(0);
                }
                Err(e) => {
                    eprintln!("❌ Configuration check failed:\n{}", e);
                    std::process::exit(1);
                }
            }
        }
        "status" => {
            let url = extract_url(&args[2..]);
            match cli::query_status(&url).await {
                Ok(status) => {
                    cli::print_status(&status);
                    std::process::exit(0);
                }
                Err(e) => {
                    eprintln!("❌ {}", e);
                    std::process::exit(1);
                }
            }
        }
        "peers" => {
            let url = extract_url(&args[2..]);
            match cli::query_peers(&url).await {
                Ok(peers) => {
                    cli::print_peers(&peers);
                    std::process::exit(0);
                }
                Err(e) => {
                    eprintln!("❌ {}", e);
                    std::process::exit(1);
                }
            }
        }
        "spool" => {
            let url = extract_url(&args[2..]);
            match cli::query_spool(&url).await {
                Ok(spool) => {
                    cli::print_spool(&spool);
                    std::process::exit(0);
                }
                Err(e) => {
                    eprintln!("❌ {}", e);
                    std::process::exit(1);
                }
            }
        }
        "generate-key" | "gen-key" => {
            let key = cli::generate_key();
            println!("============================================================");
            println!(" 🔑 OpenAlert Cryptographic 256-Bit Hex Key");
            println!("============================================================");
            println!("Key: {}", key);
            println!();
            println!("For Nostr Group Encryption, paste into config/openalertd.toml:");
            println!();
            println!("[nostr.privacy]");
            println!("mode = \"encrypted\"");
            println!("shared_key = \"{}\"", key);
            println!("============================================================");
            std::process::exit(0);
        }
        "hash-password" | "hash" => {
            let password = args.get(2).map(|s| s.as_str()).unwrap_or("");
            if password.is_empty() {
                eprintln!("❌ Error: Missing password argument.");
                println!("Usage: openalertd hash-password <password>");
                std::process::exit(1);
            }
            let hash = cli::hash_password(password);
            println!("============================================================");
            println!(" 🔑 OpenAlert Dashboard Authentication Hash");
            println!("============================================================");
            println!("Password Hash:  {}", hash);
            println!();
            println!("Paste the following block into your config/openalertd.toml:");
            println!();
            println!("[dashboard.auth]");
            println!("enabled = true");
            println!("username = \"admin\"");
            println!("password_hash = \"{}\"", hash);
            println!("============================================================");
            std::process::exit(0);
        }
        _ => {}
    }

    let config_path = if subcommand == "run" {
        args.get(2).cloned().unwrap_or_else(|| "config/openalertd.toml".to_string())
    } else if !subcommand.is_empty() && !subcommand.starts_with('-') {
        subcommand.to_string()
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
    engine.set_bitchat_service(bitchat_service.clone()).await;
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

    // Initialize cellular GSM/LTE SMS gateway service
    let storage_for_sms = engine.storage().cloned().unwrap_or_else(|| {
        Arc::new(
            Storage::new(openalertd::config::StorageConfig {
                enabled: true,
                path: ":memory:".to_string(),
                ..Default::default()
            })
            .expect("in-memory storage fallback"),
        )
    });
    let sms_service = Arc::new(
        SmsService::new(
            config.sms.clone(),
            storage_for_sms,
            Arc::downgrade(&engine),
        )
        .await,
    );
    engine.set_sms_service(sms_service.clone()).await;
    sms_service.start_worker();

    let rest_server = RestServer::new(config.rest.clone(), engine.clone());
    let bitchat_teardown = bitchat_service.clone();

    tokio::select! {
        res = rest_server.run() => {
            if let Err(e) = res {
                tracing::error!("REST server terminated with error: {}", e);
            }
        }
        _ = tokio::signal::ctrl_c() => {
            info!("🛑 Received shutdown signal (SIGINT/Ctrl+C). Initiating clean teardown...");
        }
    }

    info!("Unregistering BitChat BLE GATT applications...");
    bitchat_teardown.stop();
    tokio::time::sleep(tokio::time::Duration::from_millis(300)).await;
    info!("OpenAlert Daemon terminated cleanly.");

    Ok(())
}
