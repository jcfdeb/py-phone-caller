//! # Error Types
//!
//! Provides the centralized [`OpenAlertError`] enum and [`Result`] type alias
//! covering all error scenarios across configuration, networking, cryptography, and templates.

use thiserror::Error;

/// Enumeration of error conditions encountered during daemon execution.
#[derive(Error, Debug)]
pub enum OpenAlertError {
    /// Configuration file reading, parsing, or validation error.
    #[error("Configuration error: {0}")]
    Config(String),

    /// Layered configuration builder or deserialization error.
    #[error("Configuration build error: {0}")]
    ConfigBuilder(#[from] config::ConfigError),

    /// TOML parsing or deserialization error.
    #[error("TOML decode error: {0}")]
    Toml(#[from] toml::de::Error),

    /// Tera template compilation or rendering failure.
    #[error("Template rendering error: {0}")]
    Template(#[from] tera::Error),

    /// JSON serialization or deserialization failure.
    #[error("Serialization/Deserialization error: {0}")]
    Json(#[from] serde_json::Error),

    /// HTTP client or webhook dispatch failure.
    #[error("HTTP client error: {0}")]
    HttpClient(#[from] reqwest::Error),

    /// WebSocket transport error on relay connections (boxed to minimize enum memory size).
    #[error("WebSocket error: {0}")]
    WebSocket(Box<tokio_tungstenite::tungstenite::Error>),

    /// Cryptographic signing, verification, or key derivation failure.
    #[error("Cryptography / Schnorr error: {0}")]
    Crypto(String),

    /// Standard I/O or network socket binding failure.
    #[error("Network I/O error: {0}")]
    Io(#[from] std::io::Error),

    /// Alert routing or dispatch failure.
    #[error("Dispatch routing error: {0}")]
    Routing(String),

    /// Embedded storage / SQLite database failure.
    #[error("Storage error: {0}")]
    Storage(#[from] rusqlite::Error),

    /// Federated peering transport, wire decoding, or protocol error.
    #[error("Peering protocol error: {0}")]
    Peering(String),
}

impl From<tokio_tungstenite::tungstenite::Error> for OpenAlertError {
    fn from(err: tokio_tungstenite::tungstenite::Error) -> Self {
        OpenAlertError::WebSocket(Box::new(err))
    }
}

/// Convenience type alias for standard library `Result` using [`OpenAlertError`].
pub type Result<T> = std::result::Result<T, OpenAlertError>;
