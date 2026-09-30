//! # Template Engine
//!
//! Compiles and renders Jinja2/Tera templates to dynamically construct outbound JSON payloads
//! for HTTP webhooks, ensuring decoupling between internal alert models and external API schemas.

use crate::error::{OpenAlertError, Result};
use crate::models::Alert;
use std::path::Path;
use tera::{Context, Tera};
use tracing::info;

/// Manages compiled Tera templates for rendering alert payloads.
pub struct TemplateEngine {
    tera: Tera,
    default_template: String,
}

impl TemplateEngine {
    /// Loads and parses all `.tera` template files within the specified directory.
    pub fn new<P: AsRef<Path>>(template_dir: P, default_template: String) -> Result<Self> {
        let dir_pattern = format!("{}/**/*.tera", template_dir.as_ref().display());
        let tera = Tera::new(&dir_pattern).map_err(OpenAlertError::Template)?;

        info!(
            "Loaded {} alert templates from {}",
            tera.get_template_names().count(),
            template_dir.as_ref().display()
        );

        Ok(Self {
            tera,
            default_template,
        })
    }

    /// Renders an alert using either a specified template name or the default template.
    pub fn render_alert(&self, alert: &Alert, template_override: Option<&str>) -> Result<String> {
        let template_name = template_override.unwrap_or(&self.default_template);

        let mut ctx = Context::new();
        ctx.insert("alert_id", &alert.alert_id);
        ctx.insert("severity", &format!("{:?}", alert.severity).to_lowercase());
        ctx.insert("summary", &alert.summary);
        ctx.insert(
            "description",
            alert.description.as_deref().unwrap_or(&alert.summary),
        );
        ctx.insert("source", &format!("{:?}", alert.source).to_lowercase());
        ctx.insert(
            "sender",
            alert.sender.as_deref().unwrap_or("openalert-node"),
        );
        ctx.insert("node", alert.node.as_deref().unwrap_or("openalertd-hub"));
        ctx.insert("starts_at", &alert.starts_at.to_rfc3339());
        ctx.insert("status", "firing");
        ctx.insert(
            "generator_url",
            &format!("openalert://hub/{}", alert.alert_id),
        );

        self.tera
            .render(template_name, &ctx)
            .map_err(OpenAlertError::Template)
    }
}
