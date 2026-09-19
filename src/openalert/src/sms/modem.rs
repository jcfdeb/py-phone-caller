//! # Cellular GSM/LTE Serial AT Modem Driver
//!
//! Provides asynchronous serial communication (`tokio-serial`) with standard GSM/LTE
//! baseband modems (e.g., SIMCom SIM7100/SIM7600, Quectel, Huawei, Option).
//!
//! Guarantees non-crashing behavior: if a device is disconnected, loose, or returns errors,
//! the driver returns safe `Result::Err` values and never panics.

use super::codec;
use std::time::Duration;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::time::sleep;
use tokio_serial::{SerialPortBuilderExt, SerialStream};
use tracing::debug;

/// Parsed inbound SMS message retrieved from modem SIM storage.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InboundSms {
    pub index: u32,
    pub status: String,
    pub sender: String,
    pub body: String,
}

/// Serial AT Modem controller.
#[derive(Debug, Clone)]
pub struct ModemDriver {
    pub port_path: String,
    pub baud_rate: u32,
}

impl ModemDriver {
    /// Creates a new driver instance for the designated serial port.
    pub fn new(port_path: impl Into<String>, baud_rate: u32) -> Self {
        Self {
            port_path: port_path.into(),
            baud_rate,
        }
    }

    /// Resolves the effective serial port path.
    /// If the configured path exists and is accessible, it is returned.
    /// If missing or disconnected, attempts auto-discovery of known persistent AT endpoints:
    /// 1. `/dev/ttySMS` (OpenAlert udev rule)
    /// 2. `/dev/simcom-at` (OpenAlert udev rule)
    /// 3. Any `/dev/serial/by-id/*SimTech*if02*` (Hardware AT Interface 02)
    /// 4. `/dev/ttyUSB2` (Standard primary AT tty)
    pub fn resolve_port(&self) -> String {
        let configured = std::path::Path::new(&self.port_path);
        if configured.exists() {
            return self.port_path.clone();
        }

        // Only fall back to hardware discovery if the configured port was a modem device pattern
        let is_modem_pattern = self.port_path.starts_with("/dev/ttyUSB")
            || self.port_path.starts_with("/dev/serial/")
            || self.port_path == "/dev/ttySMS"
            || self.port_path == "/dev/simcom-at";

        if !is_modem_pattern {
            return self.port_path.clone();
        }

        if std::path::Path::new("/dev/ttySMS").exists() {
            return "/dev/ttySMS".to_string();
        }

        if std::path::Path::new("/dev/simcom-at").exists() {
            return "/dev/simcom-at".to_string();
        }

        if let Ok(entries) = std::fs::read_dir("/dev/serial/by-id") {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if name.contains("SimTech") && name.contains("if02") {
                    return format!("/dev/serial/by-id/{}", name);
                }
            }
        }

        if std::path::Path::new("/dev/ttyUSB2").exists() {
            return "/dev/ttyUSB2".to_string();
        }

        self.port_path.clone()
    }

    /// Attempts to open the serial port asynchronously.
    /// Returns `Err` if the device file is missing, permission is denied, or port is busy.
    pub fn open_port(&self) -> Result<SerialStream, String> {
        let actual_port = self.resolve_port();
        let mut builder = tokio_serial::new(&actual_port, self.baud_rate);
        builder = builder.data_bits(tokio_serial::DataBits::Eight);
        builder = builder.stop_bits(tokio_serial::StopBits::One);
        builder = builder.parity(tokio_serial::Parity::None);
        builder = builder.flow_control(tokio_serial::FlowControl::None);

        builder.open_native_async().map_err(|e| {
            format!(
                "Serial port '{}' (resolved: '{}') could not be opened: {}",
                self.port_path, actual_port, e
            )
        })
    }

    /// Reads all pending bytes from the serial buffer until silence or standard terminator.
    async fn drain_serial(&self, port: &mut SerialStream, timeout_ms: u64) -> String {
        let mut response = String::new();
        let mut buffer = [0u8; 1024];
        let max_wait = Duration::from_millis(timeout_ms);
        let start = tokio::time::Instant::now();

        while start.elapsed() < max_wait {
            match tokio::time::timeout(Duration::from_millis(150), port.read(&mut buffer)).await {
                Ok(Ok(n)) if n > 0 => {
                    response.push_str(&String::from_utf8_lossy(&buffer[..n]));
                    if response.contains("OK\r")
                        || response.contains("ERROR\r")
                        || response.contains('>')
                    {
                        break;
                    }
                }
                _ => {
                    if !response.is_empty() {
                        break;
                    }
                }
            }
        }
        response
    }

    /// Sends an AT command string and reads the response within timeout.
    async fn send_command(
        &self,
        port: &mut SerialStream,
        cmd: &str,
        timeout_ms: u64,
    ) -> Result<String, String> {
        port.write_all(cmd.as_bytes())
            .await
            .map_err(|e| format!("Failed to write command '{}': {}", cmd.trim(), e))?;
        port.flush()
            .await
            .map_err(|e| format!("Failed to flush command '{}': {}", cmd.trim(), e))?;

        let response = self.drain_serial(port, timeout_ms).await;
        Ok(response)
    }

    /// Checks basic AT responsiveness and network registration status.
    pub async fn check_status(&self) -> Result<String, String> {
        let mut port = self.open_port()?;

        // Send ESC to break any pending interactive SMS prompt
        let _ = port.write_all(&[0x1b]).await;
        let _ = port.flush().await;
        sleep(Duration::from_millis(200)).await;
        let _ = self.drain_serial(&mut port, 300).await;

        // Verify basic AT ping
        let mut alive = false;
        for _ in 0..3 {
            let resp = self.send_command(&mut port, "AT\r", 1000).await?;
            if resp.contains("OK") {
                alive = true;
                break;
            }
            sleep(Duration::from_millis(200)).await;
        }

        if !alive {
            return Err("Modem did not respond to AT probe".to_string());
        }

        // Check network registration (CREG or CEREG)
        let creg_resp = self.send_command(&mut port, "AT+CREG?\r", 1500).await.unwrap_or_default();
        let cereg_resp = self.send_command(&mut port, "AT+CEREG?\r", 1500).await.unwrap_or_default();

        let registered = creg_resp.contains(",1")
            || creg_resp.contains(",5")
            || cereg_resp.contains(",1")
            || cereg_resp.contains(",5");

        if registered {
            Ok("Registered / Connected".to_string())
        } else {
            Ok("Modem Responsive (Searching for Cell Network)".to_string())
        }
    }

    /// Sends an SMS message to a specific recipient phone number.
    /// Handles UTF-8 to UCS-2 / GSM7 transparent transcoding.
    pub async fn send_sms(&self, phone: &str, message: &str) -> Result<(), String> {
        let clean_phone = phone.trim();
        let clean_msg = message.trim();
        if clean_phone.is_empty() {
            return Err("Recipient phone number cannot be empty".to_string());
        }
        if clean_msg.is_empty() {
            return Err("SMS body cannot be empty".to_string());
        }

        let mut port = self.open_port()?;

        // Clean slate: ESC
        let _ = port.write_all(&[0x1b]).await;
        let _ = port.flush().await;
        sleep(Duration::from_millis(200)).await;
        let _ = self.drain_serial(&mut port, 300).await;

        // Disable echo
        let _ = self.send_command(&mut port, "ATE0\r", 1000).await;

        // Set SMS Text Mode
        let mode_resp = self.send_command(&mut port, "AT+CMGF=1\r", 2000).await?;
        if !mode_resp.contains("OK") {
            return Err(format!("Failed to set SMS text mode: {}", mode_resp.trim()));
        }

        let use_unicode = !codec::is_pure_ascii(clean_msg);
        let (target_number, target_body) = if use_unicode {
            let _ = self.send_command(&mut port, "AT+CSCS=\"UCS2\"\r", 1500).await;
            let _ = self.send_command(&mut port, "AT+CSMP=17,167,0,8\r", 1500).await;
            (codec::to_ucs2_hex(clean_phone), codec::to_ucs2_hex(clean_msg))
        } else {
            let _ = self.send_command(&mut port, "AT+CSCS=\"GSM\"\r", 1500).await;
            let _ = self.send_command(&mut port, "AT+CSMP=17,167,0,0\r", 1500).await;
            (clean_phone.to_string(), clean_msg.to_string())
        };

        // Initiate SMS dispatch
        let cmgs_cmd = format!("AT+CMGS=\"{}\"\r", target_number);
        port.write_all(cmgs_cmd.as_bytes())
            .await
            .map_err(|e| format!("Failed to send CMGS command: {}", e))?;
        port.flush()
            .await
            .map_err(|e| format!("Failed to flush CMGS command: {}", e))?;

        // Wait for prompt '>'
        let mut got_prompt = false;
        let prompt_start = tokio::time::Instant::now();
        let mut prompt_buf = [0u8; 256];
        let mut prompt_acc = String::new();

        while prompt_start.elapsed() < Duration::from_millis(3500) {
            match tokio::time::timeout(Duration::from_millis(150), port.read(&mut prompt_buf)).await {
                Ok(Ok(n)) if n > 0 => {
                    prompt_acc.push_str(&String::from_utf8_lossy(&prompt_buf[..n]));
                    if prompt_acc.contains('>') {
                        got_prompt = true;
                        break;
                    }
                    if prompt_acc.contains("ERROR") {
                        break;
                    }
                }
                _ => {}
            }
        }

        if !got_prompt {
            // Cancel with ESC
            let _ = port.write_all(&[0x1b]).await;
            let _ = port.flush().await;
            return Err(format!(
                "Modem did not present prompt '>' for CMGS: {}",
                prompt_acc.trim()
            ));
        }

        // Send payload followed by Ctrl+Z (0x1A)
        port.write_all(target_body.as_bytes())
            .await
            .map_err(|e| format!("Failed to write SMS payload: {}", e))?;
        port.write_all(&[0x1a])
            .await
            .map_err(|e| format!("Failed to write Ctrl+Z terminator: {}", e))?;
        port.flush()
            .await
            .map_err(|e| format!("Failed to flush SMS payload: {}", e))?;

        // Wait for final response (+CMGS: <mr> and OK)
        let resp_start = tokio::time::Instant::now();
        let mut resp_acc = String::new();
        let mut resp_buf = [0u8; 1024];

        while resp_start.elapsed() < Duration::from_secs(20) {
            match tokio::time::timeout(Duration::from_millis(300), port.read(&mut resp_buf)).await {
                Ok(Ok(n)) if n > 0 => {
                    resp_acc.push_str(&String::from_utf8_lossy(&resp_buf[..n]));
                    if resp_acc.contains("OK\r") {
                        return Ok(());
                    }
                    if resp_acc.contains("ERROR")
                        || resp_acc.contains("+CMS ERROR")
                        || resp_acc.contains("+CME ERROR")
                    {
                        return Err(format!("Modem dispatch rejected: {}", resp_acc.trim()));
                    }
                }
                _ => {}
            }
        }

        if resp_acc.contains("OK") {
            Ok(())
        } else {
            Err(format!(
                "Timeout awaiting SMS delivery confirmation: {}",
                resp_acc.trim()
            ))
        }
    }

    /// Reads and deletes incoming SMS messages from the SIM card.
    pub async fn read_and_delete_inbound(&self) -> Result<Vec<InboundSms>, String> {
        let mut port = self.open_port()?;

        // Clean slate: ESC
        let _ = port.write_all(&[0x1b]).await;
        let _ = port.flush().await;
        sleep(Duration::from_millis(150)).await;
        let _ = self.drain_serial(&mut port, 200).await;

        // Set SMS Text Mode
        let _ = self.send_command(&mut port, "AT+CMGF=1\r", 1500).await;

        // List all stored SMS messages
        let raw_list = self.send_command(&mut port, "AT+CMGL=\"ALL\"\r", 5000).await?;
        let parsed = parse_cmgl_response(&raw_list);

        // Delete processed messages so SIM card buffer does not exhaust
        for msg in &parsed {
            let del_cmd = format!("AT+CMGD={}\r", msg.index);
            let _ = self.send_command(&mut port, &del_cmd, 1500).await;
            debug!("Deleted processed SMS #{} from SIM storage", msg.index);
        }

        Ok(parsed)
    }
}

/// Parses the multi-line text response of an `AT+CMGL` query into structured [`InboundSms`] items.
pub fn parse_cmgl_response(raw: &str) -> Vec<InboundSms> {
    let mut results = Vec::new();
    let mut current_index: Option<u32> = None;
    let mut current_status = String::new();
    let mut current_sender = String::new();
    let mut current_body_lines: Vec<String> = Vec::new();

    for line in raw.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        if trimmed.starts_with("+CMGL:") {
            // Commit previous message if any
            if let Some(idx) = current_index {
                let body = current_body_lines.join("\n");
                let decoded_sender = codec::normalize_inbound_text(&current_sender);
                let decoded_body = codec::normalize_inbound_text(&body);
                results.push(InboundSms {
                    index: idx,
                    status: current_status.clone(),
                    sender: decoded_sender,
                    body: decoded_body,
                });
                current_body_lines.clear();
            }

            // Format: +CMGL: <index>,"<status>","<sender>",[...],...
            // e.g. +CMGL: 1,"REC UNREAD","+393349246425",,"2026/09/19 14:30:00+08"
            let after_cmgl = trimmed.trim_start_matches("+CMGL:").trim();
            let parts: Vec<&str> = after_cmgl.split(',').collect();

            if let Some(first) = parts.first() {
                current_index = first.trim().parse::<u32>().ok();
            } else {
                current_index = None;
            }

            current_status = parts
                .get(1)
                .map(|s| s.trim().trim_matches('"').to_string())
                .unwrap_or_default();

            current_sender = parts
                .get(2)
                .map(|s| s.trim().trim_matches('"').to_string())
                .unwrap_or_default();
        } else if trimmed == "OK" || trimmed == "ERROR" {
            break;
        } else if current_index.is_some() {
            current_body_lines.push(trimmed.to_string());
        }
    }

    // Commit final message in buffer
    if let Some(idx) = current_index {
        let body = current_body_lines.join("\n");
        let decoded_sender = codec::normalize_inbound_text(&current_sender);
        let decoded_body = codec::normalize_inbound_text(&body);
        results.push(InboundSms {
            index: idx,
            status: current_status,
            sender: decoded_sender,
            body: decoded_body,
        });
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_cmgl_plain_ascii() {
        let raw = r#"
+CMGL: 1,"REC UNREAD","+393349246425",,"2026/09/19 14:30:00+08"
CRITICAL: Water pump failure at plant 4
+CMGL: 2,"REC READ","+391234567890",,"2026/09/19 14:32:00+08"
System OK
OK
"#;
        let msgs = parse_cmgl_response(raw);
        assert_eq!(msgs.len(), 2);
        assert_eq!(msgs[0].index, 1);
        assert_eq!(msgs[0].sender, "+393349246425");
        assert_eq!(msgs[0].body, "CRITICAL: Water pump failure at plant 4");
        assert_eq!(msgs[1].index, 2);
        assert_eq!(msgs[1].body, "System OK");
    }

    #[test]
    fn test_parse_cmgl_ucs2() {
        // "004F004B" is "OK" in UCS-2 HEX
        let raw = r#"
+CMGL: 3,"REC UNREAD","002B003300390033003300340039003200340036003400320035",,"2026/09/19 14:30:00+08"
004F004B
OK
"#;
        let msgs = parse_cmgl_response(raw);
        assert_eq!(msgs.len(), 1);
        assert_eq!(msgs[0].index, 3);
        assert_eq!(msgs[0].sender, "+393349246425");
        assert_eq!(msgs[0].body, "OK");
    }
}
