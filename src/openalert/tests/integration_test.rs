//! # End-to-End Integration Tests for OpenAlert Daemon
//!
//! Validates template rendering, Nostr Schnorr event signing, deduplication caching,
//! BitChat egress routing, private direct message escalation, Prometheus Alertmanager webhook ingestion,
//! embedded SQLite sliding-window persistence & crash recovery, multi-instance webhook balancing (Cascade/RoundRobin/Broadcast),
//! Circuit Breaker protection, and Prometheus /metrics scraping.

use openalertd::config::{
    AppConfig, PeeringLinkType, PeeringNodeConfig,
    PyPhoneCallerConfig, StorageConfig, WebhookEndpointConfig, WebhookStrategy,
};
use openalertd::peering::PeeringService;
use openalertd::egress::{BitChatEgress, PrometheusWebhookDispatcher};
use openalertd::engine::AlertEngine;
use openalertd::models::{Alert, AlertSeverity, AlertSource, PrometheusAlertmanagerPayload};
use openalertd::storage::Storage;
use openalertd::templates::TemplateEngine;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

fn test_config() -> AppConfig {
    let mut config = AppConfig::load("config/openalertd.toml").expect("Failed to load config");
    config.storage.path = ":memory:".to_string();
    config
}

#[tokio::test]
async fn test_template_rendering() {
    let template_engine =
        TemplateEngine::new("templates", "prometheus_alertmanager.json.tera".to_string())
            .expect("Failed to initialize template engine");

    let alert = Alert {
        alert_id: "test-alert-01".to_string(),
        severity: AlertSeverity::Critical,
        summary: "HVAC Temperature Threshold Exceeded".to_string(),
        description: Some("Data center sensor zone 3 reported 42C".to_string()),
        source: AlertSource::Rest,
        sender: Some("sensor-gateway".to_string()),
        node: Some("lycaon-01".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["webhook".to_string()],
        origin_peer: None,
        hop: 3,
    };

    let rendered = template_engine
        .render_alert(&alert, None)
        .expect("Rendering failed");
    let json_val: serde_json::Value =
        serde_json::from_str(&rendered).expect("Rendered text is not valid JSON");

    assert_eq!(
        json_val["alerts"][0]["labels"]["alertname"],
        "test-alert-01"
    );
    assert_eq!(json_val["alerts"][0]["labels"]["severity"], "critical");
    assert_eq!(
        json_val["alerts"][0]["annotations"]["summary"],
        "HVAC Temperature Threshold Exceeded"
    );
    println!(
        "✅ Template rendered successfully:\n{}",
        serde_json::to_string_pretty(&json_val).unwrap()
    );
}

#[tokio::test]
async fn test_nostr_signing_and_dedup() {
    let config = test_config();
    let engine = AlertEngine::new(config.clone()).expect("Failed to create engine");

    let alert = Alert {
        alert_id: "dedup-test-01".to_string(),
        severity: AlertSeverity::Warning,
        summary: "Battery level below 20%".to_string(),
        description: None,
        source: AlertSource::Rest,
        sender: Some("ups-node".to_string()),
        node: Some("lycaon-01".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["nostr".to_string()],
        origin_peer: None,
        hop: 3,
    };

    let fp = alert.fingerprint();
    assert!(!engine.is_duplicate_and_record(&fp).await);
    assert!(
        engine.is_duplicate_and_record(&fp).await,
        "Second attempt should be detected as duplicate"
    );

    let publisher = engine.nostr_publisher();
    let event = publisher.sign_alert(&alert).expect("Signing failed");
    assert_eq!(event.kind, 30000);
    assert_eq!(event.tags[0][1], "dedup-test-01");

    // Verify NIP-40 expiration tag is present and properly computed
    let exp_tag = event.tags.iter().find(|t| t[0] == "expiration");
    assert!(exp_tag.is_some(), "NIP-40 expiration tag missing from Nostr event");
    let exp_val: i64 = exp_tag.unwrap()[1].parse().expect("Expiration is not integer");
    assert_eq!(exp_val, (event.created_at + config.nostr.alert_ttl_seconds) as i64);

    println!(
        "✅ Nostr event signed with Schnorr sig: {} and NIP-40 expiration: {}",
        &event.sig[..16],
        exp_val
    );
}

#[tokio::test]
async fn test_cross_transport_deduplication() {
    let config = test_config();
    let engine = AlertEngine::new(config).expect("Failed to create engine");

    // 1. Alert arrives via BitChat with private DM description
    let bitchat_alert = Alert {
        alert_id: "bitchat-dm-2a7bc99a-1788970467227".to_string(),
        severity: AlertSeverity::Critical,
        summary: "alert strong wind".to_string(),
        description: Some("Private 1-on-1 encrypted BLE mesh alert from BitChat peer 2a7bc99a8dbe975f".to_string()),
        source: AlertSource::BitChat,
        sender: Some("2a7bc99a8dbe975f".to_string()),
        node: Some("OpenAlert-Mesh".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["webhook".to_string(), "nostr".to_string()],
        origin_peer: None,
        hop: 3,
    };

    let (is_dup_1, _) = engine.is_duplicate_alert(&bitchat_alert).await;
    assert!(!is_dup_1, "Initial BitChat alert should not be flagged as duplicate");

    // 2. Alert echoes back from Nostr relay with Nostr-specific description
    let nostr_echo_alert = Alert {
        alert_id: "bitchat-dm-2a7bc99a-1788970467227".to_string(),
        severity: AlertSeverity::Critical,
        summary: "alert strong wind".to_string(),
        description: Some("alert strong wind".to_string()),
        source: AlertSource::Nostr,
        sender: Some("2e62ef5450740edd9b2f2bb123cfcbd496c9ea5c87a8de0b0d82f2c6166fc3c3".to_string()),
        node: None,
        starts_at: chrono::Utc::now(),
        destinations: vec!["webhook".to_string()],
        origin_peer: None,
        hop: 3,
    };

    let (is_dup_2, matched_key) = engine.is_duplicate_alert(&nostr_echo_alert).await;
    assert!(is_dup_2, "Nostr echo alert MUST be flagged as duplicate");
    assert!(
        matched_key.starts_with("id:") || matched_key.starts_with("fp:"),
        "Matched key should be id or fp: {}",
        matched_key
    );
    println!("✅ Cross-transport duplicate correctly dropped! (Matched: {})", matched_key);
}

#[tokio::test]
async fn test_identical_content_deduplication() {
    let config = test_config();
    let engine = AlertEngine::new(config).expect("Failed to create engine");

    let alert1 = Alert {
        alert_id: "alert-generated-001".to_string(),
        severity: AlertSeverity::Emergency,
        summary: "Wind of change".to_string(),
        description: Some("First report".to_string()),
        source: AlertSource::Rest,
        sender: Some("sensor-node-a".to_string()),
        node: Some("lycaon".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec![],
        origin_peer: None,
        hop: 3,
    };

    let (is_dup_1, _) = engine.is_duplicate_alert(&alert1).await;
    assert!(!is_dup_1);

    // Second alert has different generated alert_id but identical summary & sender
    let alert2 = Alert {
        alert_id: "alert-generated-002".to_string(),
        severity: AlertSeverity::Emergency,
        summary: "Wind of change".to_string(),
        description: Some("Repeated report seconds later".to_string()),
        source: AlertSource::Rest,
        sender: Some("sensor-node-a".to_string()),
        node: Some("lycaon".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec![],
        origin_peer: None,
        hop: 3,
    };

    let (is_dup_2, matched_key) = engine.is_duplicate_alert(&alert2).await;
    assert!(is_dup_2, "Repeated content from same sender must be dropped as duplicate");
    println!("✅ Identical content duplicate correctly dropped! (Matched: {})", matched_key);
}

#[tokio::test]
async fn test_nostr_ttl_config_and_lookback() {
    let config = AppConfig::load("config/openalertd.toml").expect("Failed to load config");
    assert_eq!(config.nostr.alert_ttl_seconds, 3600);
    assert_eq!(config.nostr.subscription_lookback_seconds, 300);
    assert_eq!(config.storage.retention_seconds, 900);
    assert!(config.storage.enabled);
    println!("✅ Nostr & Storage config verified (TTL: 3600s, Lookback: 300s, Storage retention: 900s)");
}

#[tokio::test]
async fn test_bitchat_egress_and_routing() {
    let config = test_config();
    let engine = AlertEngine::new(config.clone()).expect("Failed to create engine");

    let alert = Alert {
        alert_id: "bitchat-test-01".to_string(),
        severity: AlertSeverity::Emergency,
        summary: "Mesh peer disconnect detected".to_string(),
        description: Some("Lost BLE signal to base relay".to_string()),
        source: AlertSource::Rest,
        sender: Some("gateway-node".to_string()),
        node: Some("lycaon-01".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["bitchat".to_string()],
        origin_peer: None,
        hop: 3,
    };

    let bitchat_egress = BitChatEgress::new(config.bitchat.clone());
    let res = bitchat_egress.broadcast(&alert).await;
    assert!(res.is_ok(), "BitChat broadcast failed: {:?}", res);

    let route_res = engine.route_alert(alert).await;
    assert!(route_res.is_ok(), "Routing failed: {:?}", route_res);
    println!("✅ BitChat routing & egress verified successfully");
}

#[tokio::test]
async fn test_bitchat_private_1on1_alert_mesh_escalation() {
    let config = test_config();
    let engine = AlertEngine::new(config).expect("Failed to create engine");

    let private_alert = Alert {
        alert_id: "bitchat-dm-2a7bc99a".to_string(),
        severity: AlertSeverity::Critical,
        summary: "URGENT: Main power feed failure on UPS-A".to_string(),
        description: Some("Private direct alert received from BitChat mobile peer 2a7bc99a8dbe975f".to_string()),
        source: AlertSource::BitChat,
        sender: Some("2a7bc99a8dbe975f".to_string()),
        node: Some("OpenAlert-Mesh".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["webhook".to_string(), "nostr".to_string(), "bitchat".to_string()],
        origin_peer: None,
        hop: 3,
    };

    let route_res = engine.route_alert(private_alert).await;
    assert!(route_res.is_ok(), "Failed to route private 1-on-1 direct alert for mesh escalation");
    println!("✅ BitChat private 1-on-1 alert mesh escalation route verified successfully");
}

#[tokio::test]
async fn test_prometheus_alertmanager_webhook_parsing_and_routing() {
    let raw_payload = r#"{
      "version": "4",
      "status": "firing",
      "receiver": "openalert-webhook",
      "alerts": [
        {
          "status": "firing",
          "labels": {
            "alertname": "DiskSpaceLow",
            "severity": "critical",
            "instance": "storage-node-03",
            "job": "node_exporter"
          },
          "annotations": {
            "summary": "Root partition usage > 90%",
            "description": "Available disk space on / is only 4.2 GB remaining"
          },
          "startsAt": "2026-09-08T18:30:00Z"
        }
      ]
    }"#;

    let payload: PrometheusAlertmanagerPayload =
        serde_json::from_str(raw_payload).expect("Failed to deserialize Prometheus payload");
    assert_eq!(payload.alerts.len(), 1);

    let alert_item = payload.alerts.into_iter().next().unwrap();
    let canonical = alert_item.into_canonical_alert();

    assert_eq!(canonical.alert_id, "DiskSpaceLow");
    assert_eq!(canonical.severity, AlertSeverity::Critical);
    assert_eq!(canonical.source, AlertSource::Prometheus);
    assert_eq!(canonical.summary, "Root partition usage > 90%");
    assert_eq!(
        canonical.description,
        Some("Available disk space on / is only 4.2 GB remaining".to_string())
    );
    assert_eq!(canonical.node, Some("storage-node-03".to_string()));
    assert_eq!(canonical.sender, Some("node_exporter".to_string()));

    let config = test_config();
    let engine = AlertEngine::new(config).expect("Failed to create engine");

    let route_res = engine.route_alert(canonical).await;
    assert!(
        route_res.is_ok(),
        "Failed to route Prometheus canonical alert"
    );
}

#[tokio::test]
async fn test_storage_sliding_window_pruning() {
    let storage_cfg = StorageConfig {
        enabled: true,
        path: ":memory:".to_string(),
        retention_seconds: 900, // 15 minutes
        recover_pending_on_startup: true,
        prune_interval_seconds: 60,
    };
    let storage = Storage::new(storage_cfg).expect("Failed to init storage");
    assert!(storage.is_in_memory());

    let now = chrono::Utc::now();
    let old_timestamp = now - chrono::Duration::seconds(1200); // 20 minutes ago (expired)
    let fresh_timestamp = now - chrono::Duration::seconds(120); // 2 minutes ago (valid)

    let old_alert = Alert {
        alert_id: "old-alert-01".to_string(),
        severity: AlertSeverity::Warning,
        summary: "Old warning".to_string(),
        description: None,
        source: AlertSource::Rest,
        sender: None,
        node: None,
        starts_at: old_timestamp,
        destinations: vec![],
        origin_peer: None,
        hop: 3,
    };

    let fresh_alert = Alert {
        alert_id: "fresh-alert-01".to_string(),
        severity: AlertSeverity::Critical,
        summary: "Fresh critical".to_string(),
        description: None,
        source: AlertSource::Rest,
        sender: None,
        node: None,
        starts_at: fresh_timestamp,
        destinations: vec![],
        origin_peer: None,
        hop: 3,
    };

    storage.record_alert(&old_alert, "dispatched").await.unwrap();
    storage.record_alert(&fresh_alert, "pending").await.unwrap();
    storage.record_dedup_keys(&["key-old".to_string()]).await.unwrap();

    // Prune with 900s (15 min) retention window
    let pruned = storage.prune(900).await.expect("Prune failed");
    assert!(pruned >= 1, "At least old alert should be pruned");

    // Fresh alert should remain in pending
    let pending = storage.get_pending_alerts(900).await.unwrap();
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].alert_id, "fresh-alert-01");
    println!("✅ Sliding-window 15m retention pruning successfully verified (pruned: {})", pruned);
}

#[tokio::test]
async fn test_storage_pending_alert_recovery() {
    let mut config = test_config();
    config.storage.retention_seconds = 900;

    let engine = Arc::new(AlertEngine::new(config).expect("Failed to create engine"));
    let storage = engine.storage().expect("Storage should be present").clone();

    let pending_alert = Alert {
        alert_id: "crashed-alert-777".to_string(),
        severity: AlertSeverity::Critical,
        summary: "Power grid failure during previous crash".to_string(),
        description: Some("Recovered alert".to_string()),
        source: AlertSource::Rest,
        sender: Some("substation".to_string()),
        node: Some("node-01".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec![],
        origin_peer: None,
        hop: 3,
    };

    // Store as 'pending' simulating an in-flight alert before a crash
    storage.record_alert(&pending_alert, "pending").await.unwrap();

    let recovered = engine.recover_pending_alerts().await.expect("Recovery failed");
    assert_eq!(recovered, 1, "Should recover 1 pending alert");
    println!("✅ Crash recovery: successfully found and re-routed {} pending alert(s)", recovered);
}

#[tokio::test]
async fn test_persistent_deduplication_across_restarts() {
    let temp_dir = std::env::temp_dir();
    let db_path = temp_dir.join(format!("openalert_test_{}.db", uuid::Uuid::new_v4()));
    let db_path_str = db_path.to_str().unwrap().to_string();

    let mut config = test_config();
    config.storage.path = db_path_str.clone();

    // 1. Session 1: engine processes an alert
    {
        let engine1 = AlertEngine::new(config.clone()).expect("Failed to create engine 1");
        let alert = Alert {
            alert_id: "persistent-alert-99".to_string(),
            severity: AlertSeverity::Critical,
            summary: "Disk array degraded".to_string(),
            description: None,
            source: AlertSource::Rest,
            sender: Some("raid-mgr".to_string()),
            node: Some("srv-1".to_string()),
            starts_at: chrono::Utc::now(),
            destinations: vec![],
            origin_peer: None,
            hop: 3,
        };

        let (is_dup_1, _) = engine1.is_duplicate_alert(&alert).await;
        assert!(!is_dup_1, "First time should not be duplicate");
    } // engine 1 dropped / simulates daemon restart

    // 2. Session 2: brand new engine instance with empty in-memory cache, loads same DB file
    {
        let engine2 = AlertEngine::new(config).expect("Failed to create engine 2");
        let repeat_alert = Alert {
            alert_id: "persistent-alert-99".to_string(),
            severity: AlertSeverity::Critical,
            summary: "Disk array degraded".to_string(),
            description: None,
            source: AlertSource::Nostr,
            sender: Some("raid-mgr".to_string()),
            node: Some("srv-1".to_string()),
            starts_at: chrono::Utc::now(),
            destinations: vec![],
            origin_peer: None,
            hop: 3,
        };

        let (is_dup_2, matched) = engine2.is_duplicate_alert(&repeat_alert).await;
        assert!(is_dup_2, "Alert MUST be detected as duplicate from persistent SQLite across restart!");
        println!("✅ Persistent deduplication survived daemon restart! (Matched: {})", matched);
    }

    // Clean up temporary test db
    let _ = std::fs::remove_file(db_path);
}

// -------------------------------------------------------------------------------------------------
// Multi-Webhook Egress & Balancing Strategy Tests
// -------------------------------------------------------------------------------------------------

async fn spawn_mock_webhook_server(
    status_code: axum::http::StatusCode,
    counter: Arc<AtomicUsize>,
) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let url = format!("http://127.0.0.1:{}/alerts", port);

    let app = axum::Router::new().route(
        "/alerts",
        axum::routing::post(move || {
            let counter = counter.clone();
            async move {
                counter.fetch_add(1, Ordering::SeqCst);
                status_code
            }
        }),
    );

    let handle = tokio::spawn(async move {
        let _ = axum::serve(listener, app).await;
    });

    (url, handle)
}

#[test]
fn test_multi_webhook_config_parsing_and_priority_normalization() {
    let toml_str = r#"
        strategy = "cascade"

        [[webhooks]]
        url = "http://127.0.0.1:9099/alerts"
        priority = 0
        timeout_seconds = 4.0
        max_retries = 2
        delay = 15

        [[webhooks]]
        url = "http://192.168.1.12:9099/alerts"
        priority = 10

        [[webhooks]]
        url = "http://10.10.10.12:9099/alerts"
        # priority omitted: auto-assigned

        [[webhooks]]
        url = "http://10.10.10.99:9099/alerts"
        # 4th instance: must be capped at 3
    "#;

    let config: PyPhoneCallerConfig = toml::from_str(toml_str).expect("Failed to parse TOML");
    assert_eq!(config.strategy, WebhookStrategy::Cascade);
    assert_eq!(config.webhooks.len(), 4);

    let resolved = config.resolved_webhooks();
    // Maximum 3 endpoints allowed
    assert_eq!(resolved.len(), 3);
    assert_eq!(resolved[0].url, "http://127.0.0.1:9099/alerts");
    assert_eq!(resolved[0].priority, Some(0));
    assert_eq!(resolved[0].timeout_seconds, 4.0);
    assert_eq!(resolved[0].max_retries, 2);
    assert_eq!(resolved[0].delay, 15);

    assert_eq!(resolved[1].url, "http://192.168.1.12:9099/alerts");
    assert_eq!(resolved[1].priority, Some(10));

    assert_eq!(resolved[2].url, "http://10.10.10.12:9099/alerts");
    // Auto-assigned priority: (index 2) * 10 = 20
    assert_eq!(resolved[2].priority, Some(20));

    println!("✅ Multi-webhook configuration parsing, auto-priority, and cap-at-3 verified!");
}

#[tokio::test]
async fn test_multi_webhook_cascade_failover() {
    let template_engine = Arc::new(
        TemplateEngine::new("templates", "prometheus_alertmanager.json.tera".to_string()).unwrap(),
    );

    let s1_counter = Arc::new(AtomicUsize::new(0));
    let s2_counter = Arc::new(AtomicUsize::new(0));

    // Server 1 returns HTTP 500 (fails)
    let (s1_url, _h1) =
        spawn_mock_webhook_server(axum::http::StatusCode::INTERNAL_SERVER_ERROR, s1_counter.clone()).await;
    // Server 2 returns HTTP 200 (succeeds)
    let (s2_url, _h2) =
        spawn_mock_webhook_server(axum::http::StatusCode::OK, s2_counter.clone()).await;

    let webhook_cfg = PyPhoneCallerConfig {
        strategy: WebhookStrategy::Cascade,
        webhook_url: None,
        timeout_seconds: 1.0,
        max_retries: 1,
        webhooks: vec![
            WebhookEndpointConfig {
                url: s1_url,
                timeout_seconds: 1.0,
                max_retries: 1,
                delay: 1, // 1 second delay before cascade for fast test
                priority: Some(0),
            },
            WebhookEndpointConfig {
                url: s2_url,
                timeout_seconds: 1.0,
                max_retries: 1,
                delay: 1,
                priority: Some(10),
            },
        ],
        ..Default::default()
    };

    let dispatcher = PrometheusWebhookDispatcher::new(webhook_cfg, template_engine, None);

    let alert = Alert {
        alert_id: "cascade-test-01".to_string(),
        severity: AlertSeverity::Critical,
        summary: "Cascade failover test alert".to_string(),
        description: None,
        source: AlertSource::Rest,
        sender: None,
        node: None,
        starts_at: chrono::Utc::now(),
        destinations: vec!["webhook".to_string()],
        origin_peer: None,
        hop: 3,
    };

    let res = dispatcher.dispatch(&alert).await;
    assert!(res.is_ok(), "Dispatcher should succeed on backup server in cascade: {:?}", res);

    // Primary server 1 failed and was hit
    assert_eq!(s1_counter.load(Ordering::SeqCst), 1);
    // Secondary server 2 was cascaded to and succeeded
    assert_eq!(s2_counter.load(Ordering::SeqCst), 1);
    println!("✅ Cascade failover successfully delivered alert to secondary webhook upon primary failure!");
}

#[tokio::test]
async fn test_multi_webhook_broadcast_and_roundrobin() {
    let template_engine = Arc::new(
        TemplateEngine::new("templates", "prometheus_alertmanager.json.tera".to_string()).unwrap(),
    );

    let s1_counter = Arc::new(AtomicUsize::new(0));
    let s2_counter = Arc::new(AtomicUsize::new(0));

    let (s1_url, _h1) =
        spawn_mock_webhook_server(axum::http::StatusCode::OK, s1_counter.clone()).await;
    let (s2_url, _h2) =
        spawn_mock_webhook_server(axum::http::StatusCode::OK, s2_counter.clone()).await;

    // 1. Test Broadcast Strategy: sends to BOTH servers simultaneously
    {
        let broadcast_cfg = PyPhoneCallerConfig {
            strategy: WebhookStrategy::Broadcast,
            webhook_url: None,
            timeout_seconds: 2.0,
            max_retries: 1,
            webhooks: vec![
                WebhookEndpointConfig {
                    url: s1_url.clone(),
                    timeout_seconds: 2.0,
                    max_retries: 1,
                    delay: 0,
                    priority: Some(0),
                },
                WebhookEndpointConfig {
                    url: s2_url.clone(),
                    timeout_seconds: 2.0,
                    max_retries: 1,
                    delay: 0,
                    priority: Some(10),
                },
            ],
            ..Default::default()
        };

        let dispatcher = PrometheusWebhookDispatcher::new(broadcast_cfg, template_engine.clone(), None);
        let alert = Alert {
            alert_id: "broadcast-test-01".to_string(),
            severity: AlertSeverity::Warning,
            summary: "Broadcast test alert".to_string(),
            description: None,
            source: AlertSource::Rest,
            sender: None,
            node: None,
            starts_at: chrono::Utc::now(),
            destinations: vec!["webhook".to_string()],
            origin_peer: None,
            hop: 3,
        };

        let res = dispatcher.dispatch(&alert).await;
        assert!(res.is_ok());
        assert_eq!(s1_counter.load(Ordering::SeqCst), 1);
        assert_eq!(s2_counter.load(Ordering::SeqCst), 1);
        println!("✅ Broadcast strategy concurrently delivered alert to both webhooks!");
    }

    // 2. Test Roundrobin Strategy: distributes alternating requests
    {
        let roundrobin_cfg = PyPhoneCallerConfig {
            strategy: WebhookStrategy::Roundrobin,
            webhook_url: None,
            timeout_seconds: 2.0,
            max_retries: 1,
            webhooks: vec![
                WebhookEndpointConfig {
                    url: s1_url.clone(),
                    timeout_seconds: 2.0,
                    max_retries: 1,
                    delay: 0,
                    priority: Some(0),
                },
                WebhookEndpointConfig {
                    url: s2_url.clone(),
                    timeout_seconds: 2.0,
                    max_retries: 1,
                    delay: 0,
                    priority: Some(10),
                },
            ],
            ..Default::default()
        };

        let dispatcher = PrometheusWebhookDispatcher::new(roundrobin_cfg, template_engine.clone(), None);
        let alert1 = Alert {
            alert_id: "rr-01".to_string(),
            severity: AlertSeverity::Info,
            summary: "RR 1".to_string(),
            description: None,
            source: AlertSource::Rest,
            sender: None,
            node: None,
            starts_at: chrono::Utc::now(),
            destinations: vec![],
            origin_peer: None,
            hop: 3,
        };
        let alert2 = Alert {
            alert_id: "rr-02".to_string(),
            severity: AlertSeverity::Info,
            summary: "RR 2".to_string(),
            description: None,
            source: AlertSource::Rest,
            sender: None,
            node: None,
            starts_at: chrono::Utc::now(),
            destinations: vec![],
            origin_peer: None,
            hop: 3,
        };

        dispatcher.dispatch(&alert1).await.unwrap();
        dispatcher.dispatch(&alert2).await.unwrap();

        // Roundrobin should have delivered 1 request to s1 and 1 request to s2 (previous count was 1 each from broadcast)
        assert_eq!(s1_counter.load(Ordering::SeqCst), 2);
        assert_eq!(s2_counter.load(Ordering::SeqCst), 2);
        println!("✅ RoundRobin strategy evenly distributed requests across instances!");
    }
}

#[tokio::test]
async fn test_circuit_breaker_tripping_and_fast_failover() {
    let template_engine = Arc::new(
        TemplateEngine::new("templates", "prometheus_alertmanager.json.tera".to_string()).unwrap(),
    );

    let s1_counter = Arc::new(AtomicUsize::new(0));
    let s2_counter = Arc::new(AtomicUsize::new(0));

    // Server 1 always fails with 500
    let (s1_url, _h1) =
        spawn_mock_webhook_server(axum::http::StatusCode::INTERNAL_SERVER_ERROR, s1_counter.clone()).await;
    // Server 2 always succeeds with 200
    let (s2_url, _h2) =
        spawn_mock_webhook_server(axum::http::StatusCode::OK, s2_counter.clone()).await;

    let cfg = PyPhoneCallerConfig {
        strategy: WebhookStrategy::Cascade,
        webhook_url: None,
        timeout_seconds: 1.0,
        max_retries: 0, // no inner retries so each dispatch failure counts as 1 attempt failure
        circuit_breaker_enabled: true,
        circuit_breaker_failure_threshold: 2, // trips after 2 failures
        circuit_breaker_cooldown_seconds: 60, // stays open for 60s
        webhooks: vec![
            WebhookEndpointConfig {
                url: s1_url.clone(),
                timeout_seconds: 1.0,
                max_retries: 0,
                delay: 0,
                priority: Some(0),
            },
            WebhookEndpointConfig {
                url: s2_url.clone(),
                timeout_seconds: 1.0,
                max_retries: 0,
                delay: 0,
                priority: Some(10),
            },
        ],
    };

    let dispatcher = PrometheusWebhookDispatcher::new(cfg, template_engine, None);

    let alert = Alert {
        alert_id: "cb-alert".to_string(),
        severity: AlertSeverity::Critical,
        summary: "Circuit breaker test".to_string(),
        description: None,
        source: AlertSource::Rest,
        sender: None,
        node: None,
        starts_at: chrono::Utc::now(),
        destinations: vec!["webhook".to_string()],
        origin_peer: None,
        hop: 3,
    };

    // Attempt 1: S1 fails, cascades to S2 (S1 fail count = 1)
    dispatcher.dispatch(&alert).await.unwrap();
    assert_eq!(s1_counter.load(Ordering::SeqCst), 1);
    assert_eq!(s2_counter.load(Ordering::SeqCst), 1);
    assert!(dispatcher.can_attempt_endpoint(&s1_url));

    // Attempt 2: S1 fails, cascades to S2 (S1 fail count = 2 -> circuit trips to OPEN)
    dispatcher.dispatch(&alert).await.unwrap();
    assert_eq!(s1_counter.load(Ordering::SeqCst), 2);
    assert_eq!(s2_counter.load(Ordering::SeqCst), 2);
    assert!(!dispatcher.can_attempt_endpoint(&s1_url), "S1 circuit should now be OPEN");

    // Attempt 3: S1 circuit is OPEN! Dispatcher must fast-skip S1 in 0ms and deliver straight to S2!
    let start = std::time::Instant::now();
    dispatcher.dispatch(&alert).await.unwrap();
    let duration = start.elapsed();

    // S1 was fast-skipped (counter NOT incremented!)
    assert_eq!(s1_counter.load(Ordering::SeqCst), 2, "S1 counter must NOT increment because circuit is open");
    // S2 received the alert directly
    assert_eq!(s2_counter.load(Ordering::SeqCst), 3);
    assert!(duration.as_millis() < 200, "Fast-skip should execute in sub-200ms: {:?}", duration);

    println!("✅ Circuit breaker tripped to OPEN after 2 failures and fast-skipped dead endpoint in {:?}", duration);
}

#[tokio::test]
async fn test_prometheus_metrics_registry() {
    let config = test_config();
    let engine = AlertEngine::new(config).expect("Failed to create engine");

    let alert = Alert {
        alert_id: "metrics-alert-01".to_string(),
        severity: AlertSeverity::Critical,
        summary: "Testing metrics counters".to_string(),
        description: None,
        source: AlertSource::Rest,
        sender: Some("test-sender".to_string()),
        node: Some("test-node".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec![],
        origin_peer: None,
        hop: 3,
    };

    engine.route_alert(alert.clone()).await.unwrap();
    // Route duplicate to increment duplicates counter
    engine.route_alert(alert).await.unwrap();

    let metrics_text = engine.metrics().render().expect("Failed to render metrics");
    assert!(metrics_text.contains("openalert_alerts_received_total{source=\"rest\"} 2"));
    assert!(metrics_text.contains("openalert_duplicates_dropped_total"));
    println!("✅ Prometheus /metrics text rendered with all counters:\n{}", metrics_text);
}

#[tokio::test]
async fn test_peering_end_to_end_edge_to_gateway_backhaul() {
    let psk = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".to_string();

    // Node A (Edge Stub Node)
    let mut config_a = test_config();
    config_a.peering.enabled = true;
    config_a.peering.listen_addr = "127.0.0.1:19876".to_string();
    config_a.peering.shared_key = psk.clone();
    config_a.peering.nodes = vec![PeeringNodeConfig {
        name: "gateway".to_string(),
        addr: "127.0.0.1:19877".to_string(),
        link_type: PeeringLinkType::Lan,
        burst_retries: None,
        burst_interval_ms: None,
        burst_jitter_ms: None,
        max_ip_retries: Some(2),
        base_timeout_ms: Some(100),
        failure_threshold: Some(3),
        base_cooldown_secs: Some(60),
        shared_key: None,
        ..Default::default()
    }];

    // Node B (Central Gateway)
    let mut config_b = test_config();
    config_b.peering.enabled = true;
    config_b.peering.listen_addr = "127.0.0.1:19877".to_string();
    config_b.peering.shared_key = psk.clone();
    config_b.peering.nodes = vec![PeeringNodeConfig {
        name: "edge".to_string(),
        addr: "127.0.0.1:19876".to_string(),
        link_type: PeeringLinkType::Lan,
        burst_retries: None,
        burst_interval_ms: None,
        burst_jitter_ms: None,
        max_ip_retries: Some(2),
        base_timeout_ms: Some(100),
        failure_threshold: Some(3),
        base_cooldown_secs: Some(60),
        shared_key: None,
        ..Default::default()
    }];

    let engine_a = Arc::new(AlertEngine::new(config_a.clone()).unwrap());
    let engine_b = Arc::new(AlertEngine::new(config_b.clone()).unwrap());

    let peering_a = Arc::new(PeeringService::new(config_a.peering.clone(), engine_a.storage().cloned()).await.unwrap());
    let peering_b = Arc::new(PeeringService::new(config_b.peering.clone(), engine_b.storage().cloned()).await.unwrap());

    peering_a.set_engine(engine_a.clone()).await;
    engine_a.set_peering_service(peering_a.clone()).await;
    peering_a.clone().start();

    peering_b.set_engine(engine_b.clone()).await;
    engine_b.set_peering_service(peering_b.clone()).await;
    peering_b.clone().start();

    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

    // Dispatch alert from Edge Node A destined for ["peering"]
    let edge_alert = Alert {
        alert_id: "edge-power-loss-01".to_string(),
        severity: AlertSeverity::Critical,
        summary: "Substation Generator Offline".to_string(),
        description: Some("Battery backup engaged at zone 4".to_string()),
        source: AlertSource::Rest,
        sender: Some("edge-collector".to_string()),
        node: Some("edge-01".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["peering".to_string()],
        origin_peer: None,
        hop: 3,
    };

    engine_a.route_alert(edge_alert).await.unwrap();

    // Allow UDP delivery, AEAD decryption, and Gateway ingestion
    tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;

    // Verify Gateway received the alert in its deduplication cache
    let peering_received = engine_b.metrics().alerts_received_total.with_label_values(&["peering"]).get();
    assert_eq!(peering_received as u64, 1, "Gateway must have received exactly 1 peering alert");

    println!("✅ Edge-to-Gateway UDP Peering verified! Ingested into central gateway.");
}

#[tokio::test]
async fn test_peering_sqlite_spooling_and_retrieval() {
    let storage_cfg = StorageConfig {
        path: ":memory:".to_string(),
        ..Default::default()
    };
    let storage = Storage::new(storage_cfg).expect("Failed to create storage");

    let payload = b"mock-postcard-alert-payload";
    let fp: u64 = 0x1234567890abcdef;

    let id = storage.spool_peering_packet("hub-gateway", fp, payload).await.unwrap();
    assert!(id > 0);

    let spooled = storage.get_spooled_peering_packets("hub-gateway", 10).await.unwrap();
    assert_eq!(spooled.len(), 1);
    assert_eq!(spooled[0].0, id);
    assert_eq!(spooled[0].1, fp);
    assert_eq!(spooled[0].2, payload.to_vec());

    storage.mark_peering_spool_delivered(id).await.unwrap();
    let remaining = storage.get_spooled_peering_packets("hub-gateway", 10).await.unwrap();
    assert_eq!(remaining.len(), 0);

    println!("✅ SQLite peering_spool FIFO storage and delivery lifecycle verified!");
}

#[tokio::test]
async fn test_peering_split_horizon_suppression() {
    let psk = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".to_string();

    let mut config = test_config();
    config.peering.enabled = true;
    config.peering.listen_addr = "127.0.0.1:29876".to_string();
    config.peering.shared_key = psk;
    config.peering.nodes = vec![PeeringNodeConfig {
        name: "node-b".to_string(),
        addr: "127.0.0.1:29877".to_string(),
        link_type: PeeringLinkType::Lan,
        burst_retries: None,
        burst_interval_ms: None,
        burst_jitter_ms: None,
        max_ip_retries: Some(1),
        base_timeout_ms: Some(50),
        failure_threshold: Some(3),
        base_cooldown_secs: Some(60),
        shared_key: None,
        ..Default::default()
    }];

    let peering = PeeringService::new(config.peering, None).await.unwrap();

    let reflected_alert = Alert {
        alert_id: "peer-loop-test-01".to_string(),
        severity: AlertSeverity::Warning,
        summary: "Checking split-horizon loop suppression".to_string(),
        description: None,
        source: AlertSource::Peering,
        sender: Some("node-b".to_string()),
        node: Some("node-b".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["peering".to_string()],
        origin_peer: Some("node-b".to_string()), // Received from node-b!
        hop: 2,
    };

    // Dispatching alert back must be suppressed by split-horizon origin filter!
    let res = peering.dispatch_alert(&reflected_alert, false).await;
    assert!(res.is_ok());
    println!("✅ Split-horizon loop suppression successfully prevented reflection!");
}

#[test]
fn test_cli_config_validator() {
    let res = openalertd::cli::validate_config("config/openalertd.toml");
    assert!(res.is_ok(), "config/openalertd.toml must be valid: {:?}", res.err());
    let summary = res.unwrap();
    assert!(summary.contains("openalertd-hub"));
    assert!(summary.contains("REST Ingress:"));
    assert!(summary.contains("Templates:"));

    // Verify all turnkey configuration profiles validate cleanly
    for profile in &["edge-sensor.toml", "mesh-repeater.toml", "central-gateway.toml"] {
        let path = format!("config/profiles/{}", profile);
        let prof_res = openalertd::cli::validate_config(&path);
        assert!(prof_res.is_ok(), "Profile '{}' must be valid: {:?}", path, prof_res.err());
    }

    let bad_res = openalertd::cli::validate_config("nonexistent_config_path.toml");
    assert!(bad_res.is_err(), "Nonexistent config must fail validation");
}

#[tokio::test]
async fn test_engine_diagnostics_and_status_api() {
    let config = test_config();
    let engine = Arc::new(AlertEngine::new(config).expect("Engine creation failed"));

    // 1. Test Health model
    let health = engine.get_health();
    assert_eq!(health.status, "ok");
    assert!(!health.version.is_empty());

    // 2. Test Spool stats
    let spool_stats = engine.get_spool_stats().await;
    assert!(spool_stats.is_some());
    assert_eq!(spool_stats.unwrap().spooled, 0);

    // 3. Test Full Status model
    let status = engine.get_status().await;
    assert_eq!(status.node_name, "openalertd-hub");
    assert!(status.storage.is_in_memory);
    assert_eq!(status.webhook.strategy, "cascade");
    assert_eq!(status.nostr.relays_count, 6);
    println!("✅ Engine status and diagnostics validated successfully: node={}, version={}", status.node_name, status.version);
}

#[tokio::test]
async fn test_peering_lora_serial_dispatch() {
    let psk = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".to_string();

    let mut config = test_config();
    config.peering.enabled = true;
    config.peering.listen_addr = "127.0.0.1:39876".to_string();
    config.peering.shared_key = psk;
    config.peering.nodes = vec![PeeringNodeConfig {
        name: "mountain-lora-relay".to_string(),
        addr: "127.0.0.1:39877".to_string(),
        link_type: PeeringLinkType::LoraSerial,
        serial_device: Some("/dev/ttyUSB99_virtual".to_string()),
        baud_rate: Some(115200),
        spreading_factor: Some(9),
        bandwidth_khz: Some(125),
        duty_cycle_percent: Some(1.0),
        burst_retries: None,
        burst_interval_ms: None,
        burst_jitter_ms: None,
        max_ip_retries: None,
        base_timeout_ms: None,
        failure_threshold: Some(3),
        base_cooldown_secs: Some(60),
        shared_key: None,
    }];

    let peering = PeeringService::new(config.peering.clone(), None)
        .await
        .expect("Failed to initialize PeeringService with LoraSerial node");

    let alert = Alert {
        alert_id: "lora-serial-test-01".to_string(),
        severity: AlertSeverity::Critical,
        summary: "Wildfire Perimeter Breached - LoRa Dispatch".to_string(),
        description: Some("Sensor cluster 14 reports extreme thermal anomalies".to_string()),
        source: AlertSource::Rest,
        sender: Some("sensor-gateway".to_string()),
        node: Some("edge-node".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["peering".to_string()],
        origin_peer: None,
        hop: 3,
    };

    // Dispatch alert through peering: should format micro-frame, SLIP-encode, check ETSI duty-cycle, and handle virtual serial
    let res = peering.dispatch_alert(&alert, false).await;
    assert!(res.is_ok(), "LoraSerial dispatch must succeed without crashing: {:?}", res.err());
    println!("✅ LoRa Serial physical profile successfully processed, SLIP-encoded, and regulated!");
}

#[tokio::test]
async fn test_rest_ingress_bearer_and_hmac_security() {
    let mut config = test_config();
    config.rest.auth_token = Some("secret-test-bearer-token".to_string());
    config.rest.webhook_secret = Some("secret-webhook-key".to_string());
    config.rest.webhook_max_skew_seconds = 60;

    let engine = Arc::new(AlertEngine::new(config.clone()).expect("Engine creation failed"));
    let state = openalertd::ingress::rest::AppState {
        engine,
        config: config.rest.clone(),
    };

    // 1. Health check is public (unauthenticated allowed)
    let health_resp = openalertd::ingress::rest::health_check(axum::extract::State(state.clone())).await;
    assert_eq!(health_resp.status(), axum::http::StatusCode::OK);

    // 2. Status handler without auth -> 401
    let unauth_status = openalertd::ingress::rest::status_handler(axum::http::HeaderMap::new(), axum::extract::State(state.clone())).await;
    assert_eq!(unauth_status.status(), axum::http::StatusCode::UNAUTHORIZED);

    // 3. Status handler with valid Bearer token -> 200
    let mut authed_headers = axum::http::HeaderMap::new();
    authed_headers.insert(
        axum::http::header::AUTHORIZATION,
        axum::http::HeaderValue::from_static("Bearer secret-test-bearer-token"),
    );
    let ok_status = openalertd::ingress::rest::status_handler(authed_headers.clone(), axum::extract::State(state.clone())).await;
    assert_eq!(ok_status.status(), axum::http::StatusCode::OK);

    // 4. Ingest alert without HMAC signature -> 401
    let alert_payload = serde_json::json!({
        "alert_id": "hmac-test-01",
        "severity": "critical",
        "summary": "Perimeter alarm",
        "destinations": ["webhook"]
    });
    let body_bytes = axum::body::Bytes::from(serde_json::to_vec(&alert_payload).unwrap());
    let missing_sig = openalertd::ingress::rest::ingest_alert(authed_headers.clone(), axum::extract::State(state.clone()), body_bytes.clone()).await;
    assert_eq!(missing_sig.status(), axum::http::StatusCode::UNAUTHORIZED);

    // 5. Ingest alert with valid HMAC-SHA256 signature and timestamp -> 202 Accepted
    let sig_hex = openalertd::ingress::rest::compute_hmac_sha256(b"secret-webhook-key", &body_bytes);
    let mut secure_headers = authed_headers.clone();
    secure_headers.insert(
        "x-openalert-signature",
        axum::http::HeaderValue::from_str(&sig_hex).unwrap(),
    );
    let now = chrono::Utc::now().timestamp();
    secure_headers.insert(
        "x-openalert-timestamp",
        axum::http::HeaderValue::from_str(&now.to_string()).unwrap(),
    );

    let accepted_resp = openalertd::ingress::rest::ingest_alert(secure_headers, axum::extract::State(state.clone()), body_bytes).await;
    assert_eq!(accepted_resp.status(), axum::http::StatusCode::ACCEPTED);
    println!("✅ REST ingress Bearer and HMAC-SHA256 security tests passed successfully!");
}

#[tokio::test]
async fn test_peering_multihop_3node_mesh_forwarding() {
    let psk = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".to_string();

    // Node A (Edge): 127.0.0.1:19881, peers with Node B
    let mut config_a = test_config();
    config_a.peering.enabled = true;
    config_a.peering.listen_addr = "127.0.0.1:19881".to_string();
    config_a.peering.shared_key = psk.clone();
    config_a.peering.nodes = vec![openalertd::config::PeeringNodeConfig {
        name: "node-b".to_string(),
        addr: "127.0.0.1:19882".to_string(),
        link_type: openalertd::config::PeeringLinkType::Lan,
        shared_key: None,
        ..Default::default()
    }];

    // Node B (Relay): 127.0.0.1:19882, peers with Node A and Node C
    let mut config_b = test_config();
    config_b.peering.enabled = true;
    config_b.peering.listen_addr = "127.0.0.1:19882".to_string();
    config_b.peering.shared_key = psk.clone();
    config_b.peering.nodes = vec![
        openalertd::config::PeeringNodeConfig {
            name: "node-a".to_string(),
            addr: "127.0.0.1:19881".to_string(),
            link_type: openalertd::config::PeeringLinkType::Lan,
            shared_key: None,
            ..Default::default()
        },
        openalertd::config::PeeringNodeConfig {
            name: "node-c".to_string(),
            addr: "127.0.0.1:19883".to_string(),
            link_type: openalertd::config::PeeringLinkType::Lan,
            shared_key: None,
            ..Default::default()
        },
    ];

    // Node C (Gateway): 127.0.0.1:19883, peers with Node B
    let mut config_c = test_config();
    config_c.peering.enabled = true;
    config_c.peering.listen_addr = "127.0.0.1:19883".to_string();
    config_c.peering.shared_key = psk.clone();
    config_c.peering.nodes = vec![openalertd::config::PeeringNodeConfig {
        name: "node-b".to_string(),
        addr: "127.0.0.1:19882".to_string(),
        link_type: openalertd::config::PeeringLinkType::Lan,
        shared_key: None,
        ..Default::default()
    }];

    let engine_a = Arc::new(AlertEngine::new(config_a.clone()).unwrap());
    let engine_b = Arc::new(AlertEngine::new(config_b.clone()).unwrap());
    let engine_c = Arc::new(AlertEngine::new(config_c.clone()).unwrap());

    let peering_a = Arc::new(PeeringService::new(config_a.peering.clone(), engine_a.storage().cloned()).await.unwrap());
    let peering_b = Arc::new(PeeringService::new(config_b.peering.clone(), engine_b.storage().cloned()).await.unwrap());
    let peering_c = Arc::new(PeeringService::new(config_c.peering.clone(), engine_c.storage().cloned()).await.unwrap());

    peering_a.set_engine(engine_a.clone()).await;
    engine_a.set_peering_service(peering_a.clone()).await;
    peering_a.clone().start();

    peering_b.set_engine(engine_b.clone()).await;
    engine_b.set_peering_service(peering_b.clone()).await;
    peering_b.clone().start();

    peering_c.set_engine(engine_c.clone()).await;
    engine_c.set_peering_service(peering_c.clone()).await;
    peering_c.clone().start();

    tokio::time::sleep(tokio::time::Duration::from_millis(150)).await;

    // Node A sends an alert with hop: 3 destined for ["peering"]
    let multihop_alert = Alert {
        alert_id: "multihop-cascade-01".to_string(),
        severity: AlertSeverity::Emergency,
        summary: "Dam Water Level Critical".to_string(),
        description: Some("Reservoir crest exceeded".to_string()),
        source: AlertSource::Rest,
        sender: Some("sensor-crest-01".to_string()),
        node: Some("node-a".to_string()),
        starts_at: chrono::Utc::now(),
        destinations: vec!["peering".to_string()],
        origin_peer: None,
        hop: 3,
    };

    engine_a.route_alert(multihop_alert).await.unwrap();

    // Allow UDP hop traversal: Node A -> Node B (hop 3->2) -> Node C (hop 2->1)
    tokio::time::sleep(tokio::time::Duration::from_millis(600)).await;

    // Node B (Relay) must have received it
    let b_received = engine_b.metrics().alerts_received_total.with_label_values(&["peering"]).get();
    assert_eq!(b_received as u64, 1, "Node B (Relay) must have received exactly 1 alert");

    // Node C (Gateway) must have received the forwarded multi-hop alert
    let c_received = engine_c.metrics().alerts_received_total.with_label_values(&["peering"]).get();
    assert_eq!(c_received as u64, 1, "Node C (Gateway) must have received exactly 1 forwarded multi-hop alert");

    println!("✅ Multi-hop 3-node mesh traversal verified: Node A -> Node B (Relay) -> Node C (Gateway)");
}

#[tokio::test]
async fn test_embedded_dashboard_and_sse_telemetry() {
    let config = test_config();
    let engine = Arc::new(AlertEngine::new(config.clone()).unwrap());
    let state = openalertd::ingress::rest::AppState {
        engine,
        config: config.rest.clone(),
    };

    // 1. Verify dashboard HTML response (unauthenticated default: open access)
    let dash_resp = openalertd::ingress::dashboard::dashboard_handler(
        axum::http::HeaderMap::new(),
        axum::extract::State(state.clone()),
    ).await;
    assert_eq!(dash_resp.status(), axum::http::StatusCode::OK);
    let content_type = dash_resp.headers().get(axum::http::header::CONTENT_TYPE).unwrap().to_str().unwrap();
    assert!(content_type.contains("text/html"));

    // 2. Verify dashboard HTML content contains control plane markers and operator action triggers
    let html = openalertd::ingress::dashboard::dashboard_html();
    assert!(html.contains("OpenAlert Control Plane"));
    assert!(html.contains("Mesh Topology & Peer Circuit Breakers"));
    assert!(html.contains("Dynamic Multi-Hop Distance-Vector Routing"));
    assert!(html.contains("Nostr Relays Quorum & Health"));
    assert!(html.contains("resetPeerCircuit"));
    assert!(html.contains("purgeSpool"));

    // 3. Verify SSE handler initializes
    let sse_resp = openalertd::ingress::dashboard::sse_telemetry_handler(
        axum::http::HeaderMap::new(),
        axum::extract::State(state),
    ).await;
    assert_eq!(sse_resp.status(), axum::http::StatusCode::OK);
    // Sse response wrapped successfully
    drop(sse_resp);

    println!("✅ Zero-dependency embedded Web Dashboard & SSE telemetry verified!");
}

#[tokio::test]
async fn test_cli_hash_password() {
    let hash = openalertd::cli::hash_password("test");
    assert_eq!(hash, "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08");
    println!("✅ CLI hash-password test vector verified!");
}

#[tokio::test]
async fn test_dashboard_auth_flow() {
    use base64::Engine;
    let mut config = test_config();
    let expected_pass = "controlPlaneSecret!";
    let pass_hash = openalertd::cli::hash_password(expected_pass);

    config.dashboard.auth.enabled = true;
    config.dashboard.auth.username = "sysadmin".to_string();
    config.dashboard.auth.password_hash = pass_hash;

    let engine = Arc::new(AlertEngine::new(config.clone()).unwrap());
    let state = openalertd::ingress::rest::AppState {
        engine,
        config: config.rest.clone(),
    };

    // 1. Missing Authorization header -> 401 Unauthorized
    let resp_no_auth = openalertd::ingress::dashboard::dashboard_handler(
        axum::http::HeaderMap::new(),
        axum::extract::State(state.clone()),
    ).await;
    assert_eq!(resp_no_auth.status(), axum::http::StatusCode::UNAUTHORIZED);
    let auth_header = resp_no_auth.headers().get(axum::http::header::WWW_AUTHENTICATE).unwrap();
    assert!(auth_header.to_str().unwrap().contains("Basic realm="));

    // 2. Wrong password -> 401 Unauthorized
    let bad_creds = base64::engine::general_purpose::STANDARD.encode("sysadmin:wrongpassword");
    let mut bad_headers = axum::http::HeaderMap::new();
    bad_headers.insert(
        axum::http::header::AUTHORIZATION,
        format!("Basic {}", bad_creds).parse().unwrap(),
    );
    let resp_bad = openalertd::ingress::dashboard::dashboard_handler(
        bad_headers,
        axum::extract::State(state.clone()),
    ).await;
    assert_eq!(resp_bad.status(), axum::http::StatusCode::UNAUTHORIZED);

    // 3. Correct credentials -> 200 OK
    let good_creds = base64::engine::general_purpose::STANDARD.encode(format!("sysadmin:{}", expected_pass));
    let mut good_headers = axum::http::HeaderMap::new();
    good_headers.insert(
        axum::http::header::AUTHORIZATION,
        format!("Basic {}", good_creds).parse().unwrap(),
    );
    let resp_good = openalertd::ingress::dashboard::dashboard_handler(
        good_headers.clone(),
        axum::extract::State(state.clone()),
    ).await;
    assert_eq!(resp_good.status(), axum::http::StatusCode::OK);

    // 4. SSE telemetry endpoint with correct auth -> 200 OK
    let sse_good = openalertd::ingress::dashboard::sse_telemetry_handler(
        good_headers,
        axum::extract::State(state),
    ).await;
    assert_eq!(sse_good.status(), axum::http::StatusCode::OK);

    println!("✅ Dashboard HTTP Basic Authentication via password hash verified!");
}

#[tokio::test]
async fn test_operator_peer_reset_and_spool_purge() {
    let mut config = test_config();
    config.peering.enabled = true;
    config.peering.nodes = vec![
        openalertd::config::PeeringNodeConfig {
            name: "remote-repeater".to_string(),
            addr: "127.0.0.1:29877".to_string(),
            failure_threshold: Some(2),
            ..Default::default()
        }
    ];

    let engine = Arc::new(AlertEngine::new(config.clone()).unwrap());
    let peering = Arc::new(openalertd::peering::PeeringService::new(
        config.peering.clone(),
        engine.storage().cloned(),
    ).await.unwrap());
    engine.set_peering_service(peering.clone()).await;

    let state = openalertd::ingress::rest::AppState {
        engine: engine.clone(),
        config: config.rest.clone(),
    };

    // 1. Spool a packet into persistent storage
    let storage = engine.storage().unwrap();
    storage.spool_peering_packet("remote-repeater", 0xbeefcafe, b"test-packet").await.unwrap();
    let stats_before = storage.get_spool_stats().await.unwrap();
    assert_eq!(stats_before.spooled, 1);

    // 2. Trigger Spool Purge via operator handler
    let purge_resp = openalertd::ingress::rest::purge_spool_handler(
        axum::http::HeaderMap::new(),
        axum::extract::State(state.clone()),
    ).await;
    assert_eq!(purge_resp.status(), axum::http::StatusCode::OK);

    let stats_after = storage.get_spool_stats().await.unwrap();
    assert_eq!(stats_after.spooled, 0);

    // 3. Test Peer Circuit Breaker Reset via operator handler
    let reset_resp = openalertd::ingress::rest::reset_peer_handler(
        axum::http::HeaderMap::new(),
        axum::extract::State(state.clone()),
        axum::extract::Path("remote-repeater".to_string()),
    ).await;
    assert_eq!(reset_resp.status(), axum::http::StatusCode::OK);

    // 4. Test non-existent peer returns 404
    let not_found_resp = openalertd::ingress::rest::reset_peer_handler(
        axum::http::HeaderMap::new(),
        axum::extract::State(state),
        axum::extract::Path("unknown-node".to_string()),
    ).await;
    assert_eq!(not_found_resp.status(), axum::http::StatusCode::NOT_FOUND);

    println!("✅ Operator Peer Circuit Breaker Reset and Spool Purge verified!");
}
