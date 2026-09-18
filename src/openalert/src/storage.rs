//! # Embedded Alert Storage & Sliding-Window Persistence
//!
//! Provides a lean, zero-external-dependency embedded database layer using SQLite (bundled `rusqlite`).
//! Supports automatic fallback to RAM (`:memory:`) on read-only filesystems, sliding-window retention pruning,
//! cross-restart deduplication, and pending alert recovery after daemon restarts.

use crate::config::StorageConfig;
use crate::error::{OpenAlertError, Result};
use crate::models::{Alert, AlertSeverity, AlertSource};
use chrono::{DateTime, Utc};
use rusqlite::{params, Connection};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{info, warn};

/// Embedded storage manager coordinating SQLite connections, schema, and pruning.
pub struct Storage {
    config: StorageConfig,
    conn: Arc<Mutex<Connection>>,
    in_memory: AtomicBool,
}

impl Storage {
    /// Initializes SQLite storage from configuration with automatic read-only/RAM fallback.
    pub fn new(config: StorageConfig) -> Result<Self> {
        let is_explicit_memory = config.path == ":memory:";
        let mut in_memory = is_explicit_memory;

        let conn_res = if is_explicit_memory {
            info!("💾 Initializing in-memory SQLite database (:memory:)");
            Connection::open_in_memory()
        } else {
            // Attempt to prepare directory for disk database
            let db_path = Path::new(&config.path);
            if let Some(parent) = db_path.parent()
                && !parent.as_os_str().is_empty()
                && let Err(e) = std::fs::create_dir_all(parent) {
                warn!(
                    "⚠️ Cannot create directory for DB path '{}': {}. Falling back to in-memory SQLite (:memory:)",
                    config.path, e
                );
                in_memory = true;
            }

            if in_memory {
                Connection::open_in_memory()
            } else {
                match Connection::open(&config.path) {
                    Ok(conn) => {
                        info!("💾 Opened persistent SQLite database at: {}", config.path);
                        Ok(conn)
                    }
                    Err(e) => {
                        warn!(
                            "⚠️ Failed to open persistent DB at '{}': {}. Filesystem may be read-only. Falling back to (:memory:)",
                            config.path, e
                        );
                        in_memory = true;
                        Connection::open_in_memory()
                    }
                }
            }
        };

        let conn = conn_res.map_err(OpenAlertError::Storage)?;

        // Configure performance and disk footprint pragmas
        if !in_memory {
            let _ = conn.execute_batch(
                "PRAGMA journal_mode = WAL;
                 PRAGMA synchronous = NORMAL;
                 PRAGMA auto_vacuum = INCREMENTAL;",
            );
        }

        // Initialize schema
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS alerts (
                alert_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                summary TEXT NOT NULL,
                description TEXT,
                severity TEXT NOT NULL,
                source TEXT NOT NULL,
                sender TEXT,
                node TEXT,
                destinations TEXT NOT NULL,
                status TEXT NOT NULL, -- 'pending', 'dispatched'
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_fingerprint ON alerts(fingerprint);
            CREATE INDEX IF NOT EXISTS idx_alerts_created_at ON alerts(created_at);
            CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

            CREATE TABLE IF NOT EXISTS dedup_records (
                key TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dedup_created_at ON dedup_records(created_at);

            CREATE TABLE IF NOT EXISTS peering_spool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                peer_name TEXT NOT NULL,
                fingerprint INTEGER NOT NULL,
                payload BLOB NOT NULL,
                created_at INTEGER NOT NULL,
                retry_count INTEGER DEFAULT 0,
                status TEXT CHECK(status IN ('spooled', 'draining', 'delivered')) NOT NULL DEFAULT 'spooled'
            );
            CREATE INDEX IF NOT EXISTS idx_peering_spool_peer ON peering_spool(peer_name, status);
            CREATE INDEX IF NOT EXISTS idx_peering_spool_fp ON peering_spool(fingerprint);",
        )
        .map_err(OpenAlertError::Storage)?;

        Ok(Self {
            config,
            conn: Arc::new(Mutex::new(conn)),
            in_memory: AtomicBool::new(in_memory),
        })
    }

    /// Whether the database is currently running purely in RAM (ephemeral).
    pub fn is_in_memory(&self) -> bool {
        self.in_memory.load(Ordering::Relaxed)
    }

    /// Returns a reference to the active storage configuration.
    pub fn config(&self) -> &StorageConfig {
        &self.config
    }

    /// Checks if any of the provided candidate deduplication keys have been seen within the TTL window.
    pub async fn is_duplicate(&self, keys: &[String], dedup_ttl_seconds: u64) -> Result<(bool, Option<String>)> {
        let conn = self.conn.lock().await;
        let now = Utc::now().timestamp();
        let cutoff = now.saturating_sub(dedup_ttl_seconds as i64);

        for key in keys {
            let mut stmt = conn
                .prepare_cached("SELECT key FROM dedup_records WHERE key = ?1 AND created_at >= ?2 LIMIT 1")
                .map_err(OpenAlertError::Storage)?;

            let exists = stmt
                .query_row(params![key, cutoff], |row| row.get::<_, String>(0))
                .ok();

            if let Some(matched) = exists {
                return Ok((true, Some(matched)));
            }
        }

        Ok((false, None))
    }

    /// Records candidate deduplication keys into the persistent storage.
    pub async fn record_dedup_keys(&self, keys: &[String]) -> Result<()> {
        let conn = self.conn.lock().await;
        let now = Utc::now().timestamp();

        for key in keys {
            conn.execute(
                "INSERT OR REPLACE INTO dedup_records (key, created_at) VALUES (?1, ?2)",
                params![key, now],
            )
            .map_err(OpenAlertError::Storage)?;
        }

        Ok(())
    }

    /// Inserts or updates an alert record with initial status (e.g. 'pending').
    pub async fn record_alert(&self, alert: &Alert, status: &str) -> Result<()> {
        let conn = self.conn.lock().await;
        let destinations_json = serde_json::to_string(&alert.destinations)
            .unwrap_or_else(|_| "[]".to_string());
        let severity_str = format!("{:?}", alert.severity).to_lowercase();
        let source_str = format!("{:?}", alert.source).to_lowercase();
        let created_at = alert.starts_at.timestamp();

        conn.execute(
            "INSERT OR REPLACE INTO alerts (
                alert_id, fingerprint, summary, description, severity,
                source, sender, node, destinations, status, created_at
            ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11)",
            params![
                alert.alert_id,
                alert.fingerprint(),
                alert.summary,
                alert.description,
                severity_str,
                source_str,
                alert.sender,
                alert.node,
                destinations_json,
                status,
                created_at,
            ],
        )
        .map_err(OpenAlertError::Storage)?;

        Ok(())
    }

    /// Marks an alert as successfully dispatched across all egress drivers.
    pub async fn mark_dispatched(&self, alert_id: &str) -> Result<()> {
        let conn = self.conn.lock().await;
        conn.execute(
            "UPDATE alerts SET status = 'dispatched' WHERE alert_id = ?1",
            params![alert_id],
        )
        .map_err(OpenAlertError::Storage)?;

        Ok(())
    }

    /// Retrieves all unacknowledged / pending alerts within the retention sliding window.
    pub async fn get_pending_alerts(&self, retention_seconds: u64) -> Result<Vec<Alert>> {
        let conn = self.conn.lock().await;
        let now = Utc::now().timestamp();
        let cutoff = now.saturating_sub(retention_seconds as i64);

        let mut stmt = conn
            .prepare_cached(
                "SELECT alert_id, summary, description, severity, source, sender, node, destinations, created_at
                 FROM alerts
                 WHERE status = 'pending' AND created_at >= ?1
                 ORDER BY created_at ASC",
            )
            .map_err(OpenAlertError::Storage)?;

        let rows = stmt
            .query_map(params![cutoff], |row| {
                let alert_id: String = row.get(0)?;
                let summary: String = row.get(1)?;
                let description: Option<String> = row.get(2)?;
                let severity_str: String = row.get(3)?;
                let _source_str: String = row.get(4)?;
                let sender: Option<String> = row.get(5)?;
                let node: Option<String> = row.get(6)?;
                let destinations_json: String = row.get(7)?;
                let created_at: i64 = row.get(8)?;

                let severity = AlertSeverity::parse_str(&severity_str);
                let destinations: Vec<String> = serde_json::from_str(&destinations_json).unwrap_or_default();
                let starts_at = DateTime::from_timestamp(created_at, 0).unwrap_or_else(Utc::now);

                Ok(Alert {
                    alert_id,
                    severity,
                    summary,
                    description,
                    source: AlertSource::Rest, // recover as managed ingress
                    sender,
                    node,
                    starts_at,
                    destinations,
                    origin_peer: None,
                    hop: 3,
                })
            })
            .map_err(OpenAlertError::Storage)?;

        let mut alerts = Vec::new();
        for alert in rows.flatten() {
            alerts.push(alert);
        }

        Ok(alerts)
    }

    /// Prunes expired alerts and deduplication records older than the sliding window retention.
    pub async fn prune(&self, retention_seconds: u64) -> Result<usize> {
        let conn = self.conn.lock().await;
        let now = Utc::now().timestamp();
        let cutoff = now.saturating_sub(retention_seconds as i64);

        let deleted_alerts = conn
            .execute("DELETE FROM alerts WHERE created_at < ?1", params![cutoff])
            .map_err(OpenAlertError::Storage)?;

        let deleted_dedup = conn
            .execute("DELETE FROM dedup_records WHERE created_at < ?1", params![cutoff])
            .map_err(OpenAlertError::Storage)?;

        let deleted_spool = conn
            .execute(
                "DELETE FROM peering_spool WHERE (status = 'delivered' AND created_at < ?1) OR created_at < ?2",
                params![cutoff, cutoff.saturating_sub(retention_seconds as i64 * 3)],
            )
            .unwrap_or(0);

        let total_pruned = deleted_alerts + deleted_dedup + deleted_spool;
        if total_pruned > 0 && !self.is_in_memory() {
            let _ = conn.execute("PRAGMA incremental_vacuum(50);", []);
        }

        Ok(total_pruned)
    }

    /// Spools an outbound peering packet for a specific peer when link is down or circuit is open.
    pub async fn spool_peering_packet(
        &self,
        peer_name: &str,
        fingerprint: u64,
        payload: &[u8],
    ) -> Result<i64> {
        let conn = self.conn.lock().await;
        let now = Utc::now().timestamp();
        conn.execute(
            "INSERT INTO peering_spool (peer_name, fingerprint, payload, created_at, status)
             VALUES (?1, ?2, ?3, ?4, 'spooled')",
            params![peer_name, fingerprint as i64, payload, now],
        )
        .map_err(OpenAlertError::Storage)?;
        Ok(conn.last_insert_rowid())
    }

    /// Fetches spooled peering packets for a peer in chronological FIFO order.
    pub async fn get_spooled_peering_packets(
        &self,
        peer_name: &str,
        limit: usize,
    ) -> Result<Vec<(i64, u64, Vec<u8>)>> {
        let conn = self.conn.lock().await;
        let mut stmt = conn
            .prepare(
                "SELECT id, fingerprint, payload FROM peering_spool
                 WHERE peer_name = ?1 AND status = 'spooled'
                 ORDER BY id ASC LIMIT ?2",
            )
            .map_err(OpenAlertError::Storage)?;

        let rows = stmt
            .query_map(params![peer_name, limit as i64], |row| {
                let id: i64 = row.get(0)?;
                let fp_i64: i64 = row.get(1)?;
                let payload: Vec<u8> = row.get(2)?;
                Ok((id, fp_i64 as u64, payload))
            })
            .map_err(OpenAlertError::Storage)?;

        let mut results = Vec::new();
        for r in rows.flatten() {
            results.push(r);
        }
        Ok(results)
    }

    /// Marks a spooled peering packet as delivered or permanently resolved.
    pub async fn mark_peering_spool_delivered(&self, id: i64) -> Result<()> {
        let conn = self.conn.lock().await;
        conn.execute(
            "UPDATE peering_spool SET status = 'delivered' WHERE id = ?1",
            params![id],
        )
        .map_err(OpenAlertError::Storage)?;
        Ok(())
    }

    /// Increments retry count on a spooled peering packet.
    pub async fn increment_peering_spool_retry(&self, id: i64) -> Result<()> {
        let conn = self.conn.lock().await;
        conn.execute(
            "UPDATE peering_spool SET retry_count = retry_count + 1 WHERE id = ?1",
            params![id],
        )
        .map_err(OpenAlertError::Storage)?;
        Ok(())
    }
}
