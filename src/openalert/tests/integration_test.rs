//! # End-to-End Integration Tests for OpenAlert Daemon
//!
//! Validates template rendering, Nostr Schnorr event signing, deduplication caching,
//! BitChat egress routing, private direct message escalation, and Prometheus Alertmanager webhook ingestion.

use openalertd::config::AppConfig;
use openalertd::egress::BitChatEgress;
use openalertd::engine::AlertEngine;
use openalertd::models::{Alert, AlertSeverity, AlertSource, PrometheusAlertmanagerPayload};
use openalertd::templates::TemplateEngine;

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
    let config = AppConfig::load("config/openalertd.toml").expect("Failed to load config");
    let engine = AlertEngine::new(config).expect("Failed to create engine");

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
    println!(
        "✅ Nostr event signed with Schnorr sig: {}",
        &event.sig[..16]
    );
}

#[tokio::test]
async fn test_bitchat_egress_and_routing() {
    let config = AppConfig::load("config/openalertd.toml").expect("Failed to load config");
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
    let config = AppConfig::load("config/openalertd.toml").expect("Failed to load config");
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

    let config = AppConfig::load("config/openalertd.toml").expect("Failed to load config");
    let engine = AlertEngine::new(config).expect("Failed to create engine");

    let route_res = engine.route_alert(canonical).await;
    assert!(
        route_res.is_ok(),
        "Failed to route Prometheus canonical alert"
    );
}
