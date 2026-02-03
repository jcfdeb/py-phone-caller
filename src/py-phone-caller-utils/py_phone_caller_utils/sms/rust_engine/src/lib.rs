//! High‑availability on‑premise SMS engine.
//!
//! This crate powers the `on_premise` SMS backend for `py-phone-caller`.
//! It exposes a minimal Python API via pyo3:
//! - `enqueue_sms(db_path, number, msg) -> Awaitable[str]`: enqueue a message
//!   into an SQLite queue with de‑duplication.
//! - `start_engine(db_path, modems_json, strategy, retry_limit) -> Awaitable[str]`:
//!   starts a background Tokio task which drains the queue and sends SMSs using
//!   one or more serial GSM modems with configurable strategies:
//!   failover | single_carrier | round_robin.
//!
//! Internals:
//! - SQLite queue schema: `sms_queue` with status (0=queued,1=processing,2=sent,3=failed)
//! - AT command driver over `tokio-serial` with GSM7/UCS2 handling.
//! - HA strategies implemented in Rust; Python only provides configuration.
//!
//! Only documentation and comment cleanup; logic unchanged.

use log::{error, info, warn};
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use sqlx::sqlite::{SqliteConnectOptions, SqliteJournalMode, SqlitePool};
use sqlx::FromRow;
use std::fs;
use std::path::Path;
use std::str::FromStr;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::time::sleep;
use tokio_serial::{SerialPort, SerialPortBuilderExt, SerialStream};


#[derive(FromRow)]
struct SmsRow {
    id: i64,
    phone_number: String,
    message: String,
    retries: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ModemConfig {
    id: String,
    port: String,
    baud_rate: u32,
    priority: u8,
}

// Enum per definire le 3 strategie supportate
#[derive(Debug, Clone, Copy, PartialEq)]
enum SmsStrategy {
    Failover,
    SingleCarrier,
    RoundRobin,
}

#[derive(Clone)]
struct ModemManager {
    modems: Vec<ModemConfig>,
    strategy: SmsStrategy,
}


async fn connect_db(db_path: &str) -> Result<SqlitePool, Box<dyn std::error::Error + Send + Sync>> {
    info!("Connecting to database at: {}", db_path);

    // Extract file path from sqlite:// URI if present
    let file_path = if db_path.starts_with("sqlite://") {
        &db_path[8..]
    } else if db_path.starts_with("sqlite:") {
        &db_path[7..]
    } else {
        db_path
    };

    let file_path = file_path.split('?').next().unwrap_or(file_path);

    if let Some(parent) = Path::new(file_path).parent() {
        if !parent.as_os_str().is_empty() && !parent.exists() {
            info!("Creating database directory: {:?}", parent);
            fs::create_dir_all(parent)?;
        }
    }

    let options = SqliteConnectOptions::from_str(db_path)?
        .create_if_missing(true)
        .journal_mode(SqliteJournalMode::Wal);

    let pool = SqlitePool::connect_with(options).await?;
    Ok(pool)
}

/// Enqueue an SMS into the SQLite-backed queue with simple de-duplication.
///
/// Parameters:
/// - `db_path`: SQLite connection string (e.g. `sqlite:///data/sms.db`) or file path.
/// - `number`: Recipient phone number.
/// - `msg`: Message body (GSM7/Unicode handled at send time).
///
/// Returns:
/// - Python awaitable resolving to `"QUEUED"` or `"DUPLICATE_IGNORED"`.
#[pyfunction]
fn enqueue_sms(py: Python<'_>, db_path: String, number: String, msg: String) -> PyResult<&PyAny> {
    pyo3_asyncio::tokio::future_into_py(py, async move {
        let pool = connect_db(&db_path)
            .await
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        // Deduplication logic
        let result = sqlx::query(
            "INSERT INTO sms_queue (phone_number, message, status, retries)
             SELECT ?, ?, 0, 0
             WHERE NOT EXISTS (
                 SELECT 1 FROM sms_queue 
                 WHERE phone_number = ? AND message = ? AND status IN (0, 1, 3)
             )",
        )
        .bind(&number)
        .bind(&msg)
        .bind(&number)
        .bind(&msg)
        .execute(&pool)
        .await
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        if result.rows_affected() == 0 {
            Ok("DUPLICATE_IGNORED".to_string())
        } else {
            Ok("QUEUED".to_string())
        }
    })
}


async fn background_worker(pool: SqlitePool, manager: ModemManager, retry_limit: i32) {
    loop {
        // Atomic pick next message
        let row = match pick_next_message(&pool, retry_limit).await {
            Ok(Some(row)) => Some(row),
            Ok(None) => None,
            Err(e) => {
                error!("Database error picking next message: {}", e);
                None
            }
        };

        if let Some(row) = row {
            info!(
                "🚀 [ID:{}] Processing SMS to {} (Attempt {}/10) | Strategy: {:?}",
                row.id,
                row.phone_number,
                row.retries + 1,
                manager.strategy
            );

            match send_with_manager(&manager, &row.phone_number, &row.message, row.id).await {
                Ok(used_modem_id) => {
                    info!(
                        "✅ [ID:{}] SUCCESS: SMS delivered via '{}' to {}...",
                        row.id,
                        used_modem_id,
                        row.phone_number
                    );
                    if let Err(e) = sqlx::query("UPDATE sms_queue SET status = 2, last_error = NULL WHERE id = ?")
                        .bind(row.id)
                        .execute(&pool)
                        .await {
                            error!("❌ [ID:{}] Failed to mark as SENT in DB: {}", row.id, e);
                        }
                }
                Err(e) => {
                    warn!(
                        "❌ [ID:{}] FATAL: Failed to send SMS to {}: {}",
                        row.id, row.phone_number, e
                    );
                    if let Err(update_err) = sqlx::query(
                        "UPDATE sms_queue SET status = 3, retries = retries + 1, last_error = ? WHERE id = ?",
                    )
                    .bind(e)
                    .bind(row.id)
                    .execute(&pool)
                    .await {
                        error!("❌ [ID:{}] Failed to update FAILED status in DB: {}", row.id, update_err);
                    }
                }
            }
        }
        
        sleep(Duration::from_secs(5)).await;
    }
}

async fn pick_next_message(pool: &SqlitePool, retry_limit: i32) -> Result<Option<SmsRow>, sqlx::Error> {
    if retry_limit > 0 {
        sqlx::query_as::<_, SmsRow>(
            "UPDATE sms_queue 
             SET status = 1, last_attempt_at = CURRENT_TIMESTAMP 
             WHERE id = (
                 SELECT id FROM sms_queue 
                 WHERE status = 0 
                 OR (
                     id IN (
                         SELECT id FROM sms_queue 
                         WHERE status = 3 AND retries < 10 
                         ORDER BY id DESC 
                         LIMIT ?
                     )
                     AND (last_attempt_at IS NULL OR last_attempt_at < datetime('now', '-5 minutes'))
                 )
                 ORDER BY created_at LIMIT 1
             )
             RETURNING id, phone_number, message, retries",
        )
        .bind(retry_limit)
        .fetch_optional(pool)
        .await
    } else {
        sqlx::query_as::<_, SmsRow>(
            "UPDATE sms_queue 
             SET status = 1, last_attempt_at = CURRENT_TIMESTAMP 
             WHERE id = (
                 SELECT id FROM sms_queue 
                 WHERE status = 0 
                 ORDER BY created_at LIMIT 1
             )
             RETURNING id, phone_number, message, retries",
        )
        .fetch_optional(pool)
        .await
    }
}


async fn drain_serial_to_string(port: &mut SerialStream) -> String {
    let mut response = String::new();
    let mut buffer = [0u8; 1024];
    loop {
        match tokio::time::timeout(Duration::from_millis(200), port.read(&mut buffer)).await {
            Ok(Ok(n)) if n > 0 => {
                response.push_str(&String::from_utf8_lossy(&buffer[..n]));
                if response.contains("OK") || response.contains("ERROR") || response.contains('>') {
                    break;
                }
            }
            _ => break,
        }
    }
    response
}

fn is_gsm7_compatible(message: &str) -> bool {
    let gsm7_basic = "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà";
    let gsm7_ext = "^{}\\[~]|€";
    for c in message.chars() {
        if !gsm7_basic.contains(c) && !gsm7_ext.contains(c) {
            return false;
        }
    }
    true
}

fn to_ucs2_hex(s: &str) -> String {
    s.encode_utf16()
        .map(|v| format!("{:04X}", v))
        .collect()
}


async fn send_single_modem(modem: &ModemConfig, number: &str, message: &str, id: i64) -> Result<(), String> {
    let mut builder = tokio_serial::new(&modem.port, modem.baud_rate);
    builder = builder.data_bits(tokio_serial::DataBits::Eight);
    builder = builder.stop_bits(tokio_serial::StopBits::One);
    builder = builder.parity(tokio_serial::Parity::None);
    builder = builder.flow_control(tokio_serial::FlowControl::None);

    match builder.open_native_async() {
        Ok(mut port) => {
            let _ = port.clear(tokio_serial::ClearBuffer::All);
            sleep(Duration::from_millis(200)).await;

            let _ = port.write_all(&[0x1b]).await;
            let _ = port.flush().await;
            sleep(Duration::from_millis(500)).await;
            let _ = drain_serial_to_string(&mut port).await;

            let mut alive = false;
            for _ in 0..3 {
                let _ = port.write_all(b"AT\r").await;
                let _ = port.flush().await;
                sleep(Duration::from_millis(500)).await;
                let resp = drain_serial_to_string(&mut port).await;
                if resp.contains("OK") {
                    alive = true;
                    break;
                }
            }
            
            if !alive {
                let _ = port.write_all(b"ATE0\r").await;
                let _ = port.flush().await;
                sleep(Duration::from_millis(500)).await;
                if drain_serial_to_string(&mut port).await.contains("OK") {
                    alive = true;
                }
            }

            if !alive {
                return Err(format!("Modem {} not responding (AT check failed)", modem.id));
            }

            let mut registered = false;
            for _ in 0..5 {
                for cmd in &["AT+CREG?\r", "AT+CEREG?\r", "AT+CGREG?\r"] {
                    let _ = port.write_all(cmd.as_bytes()).await.map_err(|e| e.to_string())?;
                    let _ = port.flush().await.map_err(|e| e.to_string())?;
                    sleep(Duration::from_millis(800)).await;
                    let resp = drain_serial_to_string(&mut port).await;
                    if resp.contains(",1") || resp.contains(",5") {
                        registered = true;
                        break;
                    }
                }
                if registered { break; }
                sleep(Duration::from_millis(1500)).await;
            }

            if !registered {
                return Err(format!("Modem {} not registered to network.", modem.id));
            }

            let use_unicode = !is_gsm7_compatible(message);
            
            if use_unicode {
                let _ = port.write_all(b"AT+CSCS=\"UCS2\"\r").await.map_err(|e| e.to_string())?;
                let _ = port.flush().await.map_err(|e| e.to_string())?;
                sleep(Duration::from_millis(300)).await;
                let _ = drain_serial_to_string(&mut port).await;

                let _ = port.write_all(b"AT+CSMP=17,167,0,8\r").await.map_err(|e| e.to_string())?;
                let _ = port.flush().await.map_err(|e| e.to_string())?;
                sleep(Duration::from_millis(300)).await;
                let _ = drain_serial_to_string(&mut port).await;
            } else {
                let _ = port.write_all(b"AT+CSCS=\"GSM\"\r").await.map_err(|e| e.to_string())?;
                let _ = port.flush().await.map_err(|e| e.to_string())?;
                sleep(Duration::from_millis(300)).await;
                let _ = drain_serial_to_string(&mut port).await;

                let _ = port.write_all(b"AT+CSMP=17,167,0,0\r").await.map_err(|e| e.to_string())?;
                let _ = port.flush().await.map_err(|e| e.to_string())?;
                sleep(Duration::from_millis(300)).await;
                let _ = drain_serial_to_string(&mut port).await;
            }

            let _ = port.write_all(b"AT+CMGF=1\r").await.map_err(|e| e.to_string())?;
            let _ = port.flush().await.map_err(|e| e.to_string())?;
            sleep(Duration::from_millis(300)).await;
            let _ = drain_serial_to_string(&mut port).await;

            let target_number = if use_unicode { to_ucs2_hex(number) } else { number.to_string() };
            let cmd = format!("AT+CMGS=\"{}\"\r", target_number);
            let _ = port.write_all(cmd.as_bytes()).await.map_err(|e| e.to_string())?;
            let _ = port.flush().await.map_err(|e| e.to_string())?;
            
            sleep(Duration::from_millis(1500)).await;
            let resp = drain_serial_to_string(&mut port).await;
            if !resp.contains('>') {
                warn!("[ID:{}] Carrier {}: No '>' prompt seen, proceeding anyway...", id, modem.id);
            }
            
            let content = if use_unicode { to_ucs2_hex(message) } else { message.to_string() };
            let _ = port.write_all(content.as_bytes()).await.map_err(|e| e.to_string())?;
            let _ = port.write_all(&[0x1a]).await.map_err(|e| e.to_string())?;
            let _ = port.flush().await.map_err(|e| e.to_string())?;
            
            sleep(Duration::from_secs(5)).await;
            let resp = drain_serial_to_string(&mut port).await;
            
            if resp.contains("OK") {
                Ok(())
            } else if resp.contains("ERROR") {
                Err(format!("Modem {} returned ERROR: {}", modem.id, resp.trim()))
            } else {
                if resp.is_empty() {
                    warn!("[ID:{}] Carrier {}: No final response, assuming sent.", id, modem.id);
                    Ok(())
                } else {
                    info!("[ID:{}] Carrier {}: response: {}", id, modem.id, resp.trim());
                    Ok(())
                }
            }
        }
        Err(e) => Err(format!("Failed to open serial port {} ({}): {}", modem.port, modem.id, e)),
    }
}


async fn send_with_manager(manager: &ModemManager, number: &str, message: &str, id: i64) -> Result<String, String> {
    let mut sorted_modems = manager.modems.clone();
    
    sorted_modems.sort_by_key(|m| m.priority);

    match manager.strategy {
        SmsStrategy::SingleCarrier => {
            if sorted_modems.len() > 1 {
                info!("[ID:{}] Strategy 'SingleCarrier'. Using ONLY primary '{}'.", id, sorted_modems[0].id);
                sorted_modems.truncate(1);
            }
        },
        SmsStrategy::RoundRobin => {
            let count = sorted_modems.len();
            if count > 1 {
                let rotation = (id as usize) % count;
                sorted_modems.rotate_left(rotation);
                info!("[ID:{}] Strategy 'RoundRobin'. Order rotated by {}. First attempt: '{}'", id, rotation, sorted_modems[0].id);
            }
        },
        SmsStrategy::Failover => {
            info!("[ID:{}] Strategy 'Failover'. Using priority order. First attempt: '{}'", id, sorted_modems[0].id);
        }
    }

    let mut errors_log = String::new();

    for modem in sorted_modems {
        info!("🔄 [ID:{}] Attempting via carrier '{}' ({})", id, modem.id, modem.port);

        match send_single_modem(&modem, number, message, id).await {
            Ok(_) => {
                return Ok(modem.id);
            }
            Err(e) => {
                let err_msg = format!("[{}: {}]", modem.id, e);
                warn!("⚠️ [ID:{}] Carrier '{}' failed. Error: {}", id, modem.id, e);
                errors_log.push_str(&err_msg);
                errors_log.push_str("; ");
                
            }
        }
        sleep(Duration::from_millis(500)).await;
    }

    Err(format!("All allowed carriers failed. Trace: {}", errors_log))
}

/// Start the background SMS engine and return immediately.
///
/// Spawns a Tokio task that continuously drains the queue and sends SMS through
/// the configured serial modems. Strategy determines modem selection:
/// - `failover` (default)
/// - `single_carrier`
/// - `round_robin`
///
/// Parameters:
/// - `db_path`: SQLite connection string or path.
/// - `modems_config_json`: JSON array of modem objects `{id, port, baud_rate, priority}`.
/// - `sms_strategy_str`: One of `failover`, `single_carrier`, `round_robin`.
/// - `retry_limit`: Extra pool of failed records to retry in each cycle (0 disables).
#[pyfunction]
fn start_engine(
    py: Python<'_>,
    db_path: String,
    modems_config_json: String,
    sms_strategy_str: String,
    retry_limit: i32,
) -> PyResult<&PyAny> {
    pyo3_asyncio::tokio::future_into_py(py, async move {
        let _ = env_logger::builder()
            .filter_level(log::LevelFilter::Info)
            .parse_default_env()
            .try_init();

        let pool = connect_db(&db_path)
            .await
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        sqlx::query("CREATE TABLE IF NOT EXISTS sms_queue (id INTEGER PRIMARY KEY AUTOINCREMENT, phone_number TEXT NOT NULL, message TEXT NOT NULL, status INTEGER DEFAULT 0, retries INTEGER DEFAULT 0, last_attempt_at DATETIME, last_error TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)")
            .execute(&pool)
            .await
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

        let _ = sqlx::query("ALTER TABLE sms_queue ADD COLUMN last_attempt_at DATETIME").execute(&pool).await;
        let _ = sqlx::query("ALTER TABLE sms_queue ADD COLUMN last_error TEXT").execute(&pool).await;
        
        if let Err(e) = sqlx::query("UPDATE sms_queue SET status = 3, last_attempt_at = NULL, last_error = 'Interrupted by system restart' WHERE status = 1").execute(&pool).await {
            warn!("Failed to reset stuck processing messages: {}", e);
        }

        let modems: Vec<ModemConfig> = serde_json::from_str(&modems_config_json)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("Invalid Modem Config JSON: {}", e)))?;

        if modems.is_empty() {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>("No modems defined in config!"));
        }

        let strategy = match sms_strategy_str.as_str() {
            "single_carrier" => SmsStrategy::SingleCarrier,
            "round_robin" => SmsStrategy::RoundRobin,
            _ => SmsStrategy::Failover,
        };

        info!("Starting engine with {} modem(s). Strategy: {:?}", modems.len(), strategy);

        let manager = ModemManager { modems, strategy };

        tokio::spawn(async move {
            background_worker(pool, manager, retry_limit).await;
        });
        Ok("ENGINE_STARTED_WITH_HA")
    })
}

#[pymodule]
fn rust_engine(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(enqueue_sms, m)?)?;
    m.add_function(wrap_pyfunction!(start_engine, m)?)?;
    Ok(())
}