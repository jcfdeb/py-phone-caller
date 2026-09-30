//! # BitChat Mesh Egress Handler
//!
//! Formats outbound alerts into compact BitChat text representations and broadcasts them
//! over the local Bluetooth Low Energy mesh characteristic.

use crate::bitchat::{BITCHAT_BROADCAST_RECIPIENT, BitChatService};
use crate::config::BitChatConfig;
use crate::error::Result;
use crate::models::Alert;
use ed25519_dalek::SigningKey;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{Mutex, broadcast};
use tokio::time::sleep;
use tracing::info;

/// Egress handler for broadcasting alerts to BitChat mesh peers.
pub struct BitChatEgress {
    pub config: BitChatConfig,
    sender: Arc<Mutex<Option<broadcast::Sender<Vec<u8>>>>>,
    signing_key: Arc<SigningKey>,
    sender_id: [u8; 8],
}

impl BitChatEgress {
    /// Creates a new BitChat egress driver with cryptographic signing identity.
    pub fn new(config: BitChatConfig) -> Self {
        let (signing_key, _, sender_id) = BitChatService::derive_keys(&config.node_name);
        Self {
            config,
            sender: Arc::new(Mutex::new(None)),
            signing_key: Arc::new(signing_key),
            sender_id,
        }
    }

    /// Associates an active broadcast channel from the GATT server loop for live packet transmission.
    pub async fn attach_broadcast_sender(&self, tx: broadcast::Sender<Vec<u8>>) {
        let mut guard = self.sender.lock().await;
        *guard = Some(tx);
    }

    /// Formats and broadcasts an alert to connected BitChat mesh peers.
    pub async fn broadcast(&self, alert: &Alert) -> Result<()> {
        if !self.config.enabled {
            return Ok(());
        }

        let formatted_text = if alert.alert_id.starts_with("bitchat-dm-") {
            format!(
                "🚨 [{}] BLE Mesh Alert: {}",
                format!("{:?}", alert.severity).to_uppercase(),
                alert.summary
            )
        } else {
            format!(
                "🚨 [{}] {}: {}",
                format!("{:?}", alert.severity).to_uppercase(),
                alert.alert_id,
                alert.summary
            )
        };

        info!(
            "📡 [BitChat BLE Egress] Broadcasting alert to Bluetooth mesh: \"{}\"",
            formatted_text
        );

        let guard = self.sender.lock().await;
        if let Some(ref tx) = *guard {
            let packet = BitChatService::build_chat_message_packet(
                &self.sender_id,
                Some(&BITCHAT_BROADCAST_RECIPIENT),
                &formatted_text,
                &self.signing_key,
            );
            // Send initial broadcast notification
            let _ = tx.send(packet.clone());

            // In lossy BLE radio environments, send a redundant follow-up after pacing to guarantee mesh delivery
            let tx_followup = tx.clone();
            tokio::spawn(async move {
                sleep(Duration::from_millis(300)).await;
                let _ = tx_followup.send(packet);
            });
        }

        Ok(())
    }
}
