//! # Zero-Dependency Ultra-Modern Embedded Web Dashboard
//!
//! Provides a responsive, glassmorphic Network Operations Center (NOC) control plane
//! compiled directly into the binary. Features animated SVG mesh topology packet flows,
//! live circuit breaker telemetry, distance-vector routing tables, Nostr relay quorum
//! health meters, an interactive test dispatcher, and Server-Sent Events (SSE).

use crate::ingress::rest::AppState;
use axum::{
    extract::{Query, State},
    http::{HeaderMap, StatusCode, header},
    response::{
        IntoResponse, Response,
        sse::{Event, KeepAlive, Sse},
    },
};
use std::collections::HashMap;

/// Master transparent OpenAlert logo (Midnight / dark theme).
pub static LOGO_PNG: &[u8] = include_bytes!("../../../../docs/openalert/openalert-logo.png");

/// Pre-adapted high-contrast tactical sapphire OpenAlert logo (Day / sunlight theme).
pub static LOGO_DAY_PNG: &[u8] = include_bytes!("../../../../docs/openalert/openalert-logo-day.png");

/// HTTP handler serving the embedded logo asset with day/night adaptation.
pub async fn logo_handler(
    Query(params): Query<HashMap<String, String>>,
) -> Response {
    let is_day = params
        .get("theme")
        .map(|t| t == "light" || t == "day")
        .unwrap_or(false);
    let bytes = if is_day { LOGO_DAY_PNG } else { LOGO_PNG };
    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "image/png"),
            (header::CACHE_CONTROL, "public, max-age=86400"),
        ],
        bytes,
    )
        .into_response()
}
use futures_util::stream;
use std::convert::Infallible;
use std::time::Duration;

/// Returns the embedded HTML5/CSS3/JavaScript single-page application.
pub fn dashboard_html() -> &'static str {
    r##"<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
  <title>OpenAlert Control Plane — Mission Control NOC</title>
  <link rel="icon" type="image/png" href="/api/v1/logo">
  <style>
    :root {
      --bg: #070a13;
      --bg-gradient-1: rgba(99, 102, 241, 0.08);
      --bg-gradient-2: rgba(6, 182, 212, 0.06);
      --card-bg: rgba(15, 23, 42, 0.78);
      --card-border: rgba(255, 255, 255, 0.09);
      --border-focus: rgba(99, 102, 241, 0.6);
      --text: #e2e8f0;
      --text-heading: #ffffff;
      --text-muted: #94a3b8;
      --primary: #6366f1;
      --primary-hover: #4f46e5;
      --primary-glow: rgba(99, 102, 241, 0.35);
      --cyan: #06b6d4;
      --cyan-glow: rgba(6, 182, 212, 0.35);
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.3);
      --warning: #f59e0b;
      --warning-glow: rgba(245, 158, 11, 0.3);
      --danger: #f43f5e;
      --danger-glow: rgba(244, 63, 94, 0.3);
      --input-bg: #0b0f19;
      --table-hover: rgba(255, 255, 255, 0.025);
      --topo-bg: #04060b;
      --console-bg: #030712;
      --shadow-main: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, Helvetica, Arial, sans-serif;
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }

    [data-theme="light"] {
      --bg: #f1f5f9;
      --bg-gradient-1: rgba(99, 102, 241, 0.05);
      --bg-gradient-2: rgba(6, 182, 212, 0.05);
      --card-bg: rgba(255, 255, 255, 0.95);
      --card-border: rgba(15, 23, 42, 0.12);
      --border-focus: rgba(79, 70, 229, 0.6);
      --text: #1e293b;
      --text-heading: #0f172a;
      --text-muted: #64748b;
      --primary: #4f46e5;
      --primary-hover: #4338ca;
      --primary-glow: rgba(79, 70, 229, 0.25);
      --cyan: #0891b2;
      --cyan-glow: rgba(8, 145, 178, 0.25);
      --success: #059669;
      --success-glow: rgba(5, 150, 105, 0.2);
      --warning: #d97706;
      --warning-glow: rgba(217, 119, 6, 0.2);
      --danger: #e11d48;
      --danger-glow: rgba(225, 29, 72, 0.2);
      --input-bg: #f8fafc;
      --table-hover: rgba(15, 23, 42, 0.03);
      --topo-bg: #e2e8f0;
      --console-bg: #0f172a;
      --shadow-main: 0 4px 20px 0 rgba(15, 23, 42, 0.08);
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      background-image:
        radial-gradient(circle at 15% 15%, var(--bg-gradient-1) 0%, transparent 45%),
        radial-gradient(circle at 85% 85%, var(--bg-gradient-2) 0%, transparent 45%);
      color: var(--text);
      font-family: var(--font);
      padding: 1.25rem;
      min-height: 100vh;
      line-height: 1.5;
      transition: background 0.25s ease, color 0.25s ease;
    }

    /* Glassmorphic Precision Containers */
    .glass-panel {
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      box-shadow: var(--shadow-main);
      transition: all 0.25s ease;
    }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.85rem 1.25rem;
      margin-bottom: 1rem;
      flex-wrap: wrap;
      gap: 0.75rem;
    }
    .logo-area { display: flex; align-items: center; gap: 0.85rem; }
    .brand-logo-wrap {
      display: flex;
      align-items: center;
      justify-content: center;
      height: 48px;
      padding: 3px 8px;
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--card-border);
      transition: all 0.25s ease;
      flex-shrink: 0;
    }
    [data-theme="light"] .brand-logo-wrap {
      background: rgba(15, 23, 42, 0.04);
      border-color: rgba(15, 23, 42, 0.12);
      box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
    }
    .brand-logo {
      height: 40px;
      width: auto;
      max-width: 140px;
      object-fit: contain;
      display: block;
      transition: filter 0.25s ease, transform 0.2s ease;
    }
    .brand-logo:hover {
      transform: scale(1.05);
    }
    [data-theme="dark"] .brand-logo {
      filter: drop-shadow(0 0 10px rgba(6, 182, 212, 0.5));
    }
    [data-theme="light"] .brand-logo {
      filter: drop-shadow(0 2px 4px rgba(15, 23, 42, 0.14));
    }
    h1 { font-size: 1.25rem; font-weight: 700; letter-spacing: -0.02em; color: var(--text-heading); }
    .subtitle { font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600; }

    .header-actions { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
    .btn {
      padding: 0.45rem 0.85rem;
      border-radius: 8px;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.35rem;
      user-select: none;
    }
    .btn-primary {
      background: var(--primary);
      color: #fff;
      box-shadow: 0 0 12px var(--primary-glow);
    }
    .btn-primary:hover {
      background: var(--primary-hover);
      transform: translateY(-1px);
    }
    .btn-secondary {
      background: rgba(255, 255, 255, 0.08);
      color: var(--text);
      border: 1px solid var(--card-border);
    }
    .btn-secondary:hover {
      background: rgba(255, 255, 255, 0.15);
    }
    [data-theme="light"] .btn-secondary {
      background: rgba(15, 23, 42, 0.06);
      border-color: rgba(15, 23, 42, 0.15);
    }
    [data-theme="light"] .btn-secondary:hover {
      background: rgba(15, 23, 42, 0.1);
    }

    .badge {
      font-size: 0.7rem;
      padding: 0.22rem 0.55rem;
      border-radius: 9999px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }
    .badge-success { background: rgba(16, 185, 129, 0.15); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.35); }
    .badge-warning { background: rgba(245, 158, 11, 0.15); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.35); }
    .badge-danger { background: rgba(244, 63, 94, 0.15); color: var(--danger); border: 1px solid rgba(244, 63, 94, 0.35); }
    .badge-primary { background: rgba(99, 102, 241, 0.15); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.35); }
    .badge-cyan { background: rgba(6, 182, 212, 0.15); color: var(--cyan); border: 1px solid rgba(6, 182, 212, 0.35); }

    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--success);
      box-shadow: 0 0 8px var(--success);
      animation: pulse-glow 2s infinite;
    }
    @keyframes pulse-glow {
      0% { opacity: 0.6; transform: scale(0.95); }
      50% { opacity: 1; transform: scale(1.15); box-shadow: 0 0 12px var(--success); }
      100% { opacity: 0.6; transform: scale(0.95); }
    }

    /* Active Incident Emergency Strobe Banner */
    .incident-banner {
      display: none;
      padding: 0.85rem 1.25rem;
      margin-bottom: 1rem;
      border-radius: 10px;
      background: rgba(244, 63, 94, 0.15);
      border: 1px solid var(--danger);
      box-shadow: 0 0 20px rgba(244, 63, 94, 0.3);
      animation: alert-strobe 1.6s infinite alternate;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      flex-wrap: wrap;
    }
    @keyframes alert-strobe {
      0% { border-color: var(--danger); box-shadow: 0 0 10px rgba(244, 63, 94, 0.2); }
      100% { border-color: #fda4af; box-shadow: 0 0 24px rgba(244, 63, 94, 0.55); }
    }
    .incident-info { display: flex; align-items: center; gap: 0.75rem; flex: 1; min-width: 260px; }
    .incident-title { font-size: 0.9rem; font-weight: 700; color: #fff; }
    [data-theme="light"] .incident-title { color: #9f1239; }
    .incident-sub { font-size: 0.75rem; color: #fecdd3; }
    [data-theme="light"] .incident-sub { color: #be123c; }

    /* Hero Grid Stats */
    .grid-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 0.85rem;
      margin-bottom: 1.25rem;
    }
    .stat-card {
      padding: 1rem 1.15rem;
      position: relative;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 110px;
    }
    .stat-title {
      font-size: 0.72rem;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 600;
      letter-spacing: 0.05em;
      margin-bottom: 0.3rem;
    }
    .stat-value {
      font-size: 1.55rem;
      font-weight: 700;
      color: var(--text-heading);
      display: flex;
      align-items: baseline;
      gap: 0.4rem;
    }
    .stat-meta {
      font-size: 0.72rem;
      color: var(--text-muted);
      margin-top: 0.35rem;
      display: flex;
      align-items: center;
      gap: 0.35rem;
    }
    .stat-glow-bar {
      position: absolute;
      top: 0;
      left: 0;
      height: 3px;
      width: 100%;
    }

    /* LoRa Duty Cycle Mini Progress Meter */
    .duty-meter-bar {
      width: 100%;
      height: 6px;
      background: rgba(255, 255, 255, 0.08);
      border-radius: 4px;
      overflow: hidden;
      margin-top: 0.35rem;
    }
    [data-theme="light"] .duty-meter-bar { background: rgba(15, 23, 42, 0.1); }
    .duty-meter-fill {
      height: 100%;
      width: 0%;
      background: var(--success);
      border-radius: 4px;
      transition: width 0.4s ease, background 0.4s ease;
    }

    /* BitChat Radar Animations */
    @keyframes radar-sweep {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    @keyframes ble-ripple-1 {
      0% { r: 16px; opacity: 0.85; stroke-width: 2px; }
      100% { r: 125px; opacity: 0; stroke-width: 0.5px; }
    }
    @keyframes ble-ripple-2 {
      0% { r: 16px; opacity: 0.85; stroke-width: 2px; }
      100% { r: 125px; opacity: 0; stroke-width: 0.5px; }
    }
    .radar-scanner { animation: radar-sweep 6s linear infinite; }
    .radar-ripple-1 { animation: ble-ripple-1 3.2s cubic-bezier(0.1, 0.8, 0.3, 1) infinite; }
    .radar-ripple-2 { animation: ble-ripple-2 3.2s cubic-bezier(0.1, 0.8, 0.3, 1) 1.6s infinite; }
    .bitchat-peer-chip {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.35rem 0.75rem;
      background: rgba(56, 189, 248, 0.08);
      border: 1px solid rgba(56, 189, 248, 0.25);
      border-radius: 8px;
      font-size: 0.75rem;
      transition: all 0.2s ease;
      cursor: pointer;
    }
    .bitchat-peer-chip:hover {
      background: rgba(56, 189, 248, 0.18);
      border-color: rgba(56, 189, 248, 0.5);
      transform: translateY(-1px);
    }

    /* Navigation Tab Bar */
    .tab-bar-wrap {
      position: relative;
      margin-bottom: 1.25rem;
    }
    .tab-bar {
      display: flex;
      gap: 0.35rem;
      border-bottom: 1px solid var(--card-border);
      padding-bottom: 0.4rem;
      overflow-x: auto;
      scrollbar-width: none;
      -webkit-overflow-scrolling: touch;
    }
    .tab-bar::-webkit-scrollbar { display: none; }
    .tab-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-family: inherit;
      font-size: 0.82rem;
      font-weight: 600;
      padding: 0.5rem 0.85rem;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s ease;
      white-space: nowrap;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }
    .tab-btn:hover {
      background: rgba(255, 255, 255, 0.06);
      color: var(--text-heading);
    }
    .tab-btn.active {
      background: rgba(99, 102, 241, 0.16);
      color: var(--primary);
      border-bottom: 2px solid var(--primary);
    }

    /* Layout Columns */
    .layout-cols {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 1.25rem;
      align-items: start;
    }
    .layout-cols-equal {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.25rem;
      align-items: start;
    }
    @media (max-width: 1024px) {
      .layout-cols, .layout-cols-equal { grid-template-columns: 1fr; }
    }

    .card {
      padding: 1.25rem;
      margin-bottom: 1.25rem;
    }
    .card-title {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--text-heading);
      margin-bottom: 0.85rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
    }

    /* SVG Topology Map */
    .topology-wrap {
      width: 100%;
      height: 230px;
      background: var(--topo-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      overflow: hidden;
      transition: background 0.25s ease;
    }
    .svg-node { cursor: pointer; transition: all 0.3s ease; }
    .svg-node:hover circle { filter: drop-shadow(0 0 10px var(--cyan)); }
    .flow-line {
      stroke-dasharray: 6, 6;
      animation: packet-flow 1.5s linear infinite;
    }
    @keyframes packet-flow {
      from { stroke-dashoffset: 24; }
      to { stroke-dashoffset: 0; }
    }

    /* Responsive Tables */
    .table-responsive {
      width: 100%;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }
    table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
    th, td { text-align: left; padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--card-border); }
    th { color: var(--text-muted); font-weight: 600; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.04em; white-space: nowrap; }
    tr:hover { background: var(--table-hover); }
    tr:last-child td { border-bottom: none; }

    /* Live Feed */
    .event-feed {
      max-height: 380px;
      overflow-y: auto;
      font-size: 0.8rem;
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
    }
    .event-card {
      padding: 0.65rem 0.75rem;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid var(--card-border);
      border-radius: 6px;
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
      transition: background 0.15s ease;
    }
    [data-theme="light"] .event-card { background: rgba(15, 23, 42, 0.02); }
    .event-card:hover { background: var(--table-hover); }
    .event-header { display: flex; justify-content: space-between; align-items: center; }
    .event-summary { color: var(--text-heading); font-weight: 500; font-size: 0.83rem; }
    .event-meta { font-size: 0.7rem; color: var(--text-muted); display: flex; gap: 0.5rem; flex-wrap: wrap; }

    /* Console Terminal View */
    .console-pane {
      background: var(--console-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      color: #94a3b8;
      height: 440px;
      overflow-y: auto;
      padding: 0.85rem;
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
      line-height: 1.45;
    }
    .console-line { display: flex; gap: 0.5rem; word-break: break-all; }
    .console-ts { color: var(--text-muted); flex-shrink: 0; }
    .console-tag-info { color: #38bdf8; font-weight: 600; flex-shrink: 0; }
    .console-tag-warn { color: #fbbf24; font-weight: 600; flex-shrink: 0; }
    .console-tag-error { color: #f43f5e; font-weight: 600; flex-shrink: 0; }
    .console-tag-ack { color: #34d399; font-weight: 600; flex-shrink: 0; }
    .console-msg { color: #e2e8f0; }

    /* Modal */
    .modal-overlay {
      position: fixed;
      top: 0; left: 0; width: 100vw; height: 100vh;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(6px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 999;
      padding: 1rem;
    }
    .modal-overlay.active { display: flex; }
    .modal-box {
      width: 100%;
      max-width: 480px;
      padding: 1.5rem;
    }
    .form-group { margin-bottom: 0.9rem; }
    .form-group label { display: block; font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600; margin-bottom: 0.3rem; }
    .form-control {
      width: 100%;
      padding: 0.55rem 0.75rem;
      background: var(--input-bg);
      border: 1px solid var(--card-border);
      border-radius: 6px;
      color: var(--text-heading);
      font-family: inherit;
      font-size: 0.82rem;
      transition: all 0.2s ease;
    }
    .form-control:focus { outline: none; border-color: var(--border-focus); box-shadow: 0 0 8px var(--primary-glow); }
    .modal-footer { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1.2rem; }

    /* Mobile Media Tweaks */
    @media (max-width: 640px) {
      body { padding: 0.65rem; }
      header { padding: 0.75rem 0.85rem; }
      h1 { font-size: 1.1rem; }
      .grid-stats { grid-template-columns: repeat(2, 1fr); gap: 0.5rem; }
      .stat-card { padding: 0.75rem; min-height: 95px; }
      .stat-value { font-size: 1.3rem; }
      .btn { padding: 0.4rem 0.65rem; font-size: 0.72rem; }
    }
    @media (max-width: 400px) {
      .grid-stats { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>

  <!-- Top Glassmorphic Navigation -->
  <header class="glass-panel">
    <div class="logo-area">
      <div class="brand-logo-wrap">
        <img id="brand-logo-img" src="/api/v1/logo" alt="OpenAlert Logo" class="brand-logo">
      </div>
      <div>
        <h1 id="node-title">OpenAlert Control Plane</h1>
        <div class="subtitle">Distributed Emergency Control Plane</div>
      </div>
    </div>
    <div class="header-actions">
      <!-- Live SSE Indicator -->
      <div id="live-indicator" class="badge badge-success">
        <div class="pulse-dot"></div>
        <span>Connected (Live SSE)</span>
      </div>

      <!-- Audio Alarm Toggle (Disabled / Muted by Default) -->
      <button id="btn-audio-toggle" class="btn btn-secondary" onclick="toggleAudioAlarm()" title="Emergency Audio Alarm (Disabled by default)">
        <span id="audio-icon">🔇</span>
        <span id="audio-text">Audio Muted</span>
      </button>

      <!-- Day / Night Theme Switcher -->
      <button id="btn-theme-toggle" class="btn btn-secondary" onclick="toggleTheme()" title="Toggle Day/Night Mode">
        <span id="theme-icon">🌙</span>
        <span id="theme-text">Night</span>
      </button>

      <!-- Dispatch Test Alert Action Trigger -->
      <button class="btn btn-primary" onclick="openTestModal()">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Dispatch Test Alert
      </button>
    </div>
  </header>

  <!-- High-Severity Incident Active Strobe Banner -->
  <div id="incident-banner" class="incident-banner">
    <div class="incident-info">
      <span class="badge badge-danger" id="incident-badge" style="font-size: 0.75rem; padding: 0.3rem 0.6rem;">🚨 CRITICAL ALARM</span>
      <div>
        <div class="incident-title" id="incident-summary">Active Incident Detected</div>
        <div class="incident-sub" id="incident-meta">Node: -- | ID: --</div>
      </div>
    </div>
    <div style="display: flex; gap: 0.5rem; align-items: center;">
      <button class="btn btn-primary" style="background: #e11d48; border-color: #f43f5e;" onclick="acknowledgeActiveIncident()">
        ✋ Acknowledge &amp; Silence
      </button>
      <button class="btn btn-secondary" onclick="dismissIncidentBanner()">Dismiss</button>
    </div>
  </div>

  <!-- Key Metrics Hero Bar -->
  <div class="grid-stats">
    <!-- Stat 1: Daemon Status -->
    <div class="glass-panel stat-card">
      <div class="stat-glow-bar" style="background: linear-gradient(90deg, transparent, var(--success), transparent)"></div>
      <div class="stat-title">Daemon State</div>
      <div id="stat-status" class="stat-value" style="color: var(--success);">ONLINE</div>
      <div class="stat-meta">
        <span>Uptime:</span>
        <strong id="stat-uptime" style="color: var(--text-heading);">--</strong>
      </div>
    </div>

    <!-- Stat 2: Mesh Peering Links -->
    <div class="glass-panel stat-card">
      <div class="stat-glow-bar" style="background: linear-gradient(90deg, transparent, var(--cyan), transparent)"></div>
      <div class="stat-title">Peering Mesh</div>
      <div class="stat-value">
        <span id="stat-peers-count">0</span>
        <span style="font-size: 0.85rem; color: var(--text-muted); font-weight: 400;">active peers</span>
      </div>
      <div class="stat-meta">
        <span class="badge badge-cyan" id="stat-peers-healthy">All Healthy</span>
      </div>
    </div>

    <!-- Stat 3: Spool Backlog -->
    <div class="glass-panel stat-card">
      <div class="stat-glow-bar" style="background: linear-gradient(90deg, transparent, var(--warning), transparent)"></div>
      <div class="stat-title" style="display: flex; justify-content: space-between; align-items: center;">
        <span>Persistent Spool</span>
        <button class="btn" style="font-size: 0.65rem; padding: 0.15rem 0.45rem; background: rgba(244,63,94,0.2); border: 1px solid rgba(244,63,94,0.4); color: #fda4af;" onclick="purgeSpool()">Purge</button>
      </div>
      <div class="stat-value">
        <span id="stat-spool-count">0</span>
        <span style="font-size: 0.85rem; color: var(--text-muted); font-weight: 400;">queued</span>
      </div>
      <div class="stat-meta">SQLite Flash Buffer Ready</div>
    </div>

    <!-- Stat 4: LoRa Duty Cycle with Visual Progress Meter -->
    <div class="glass-panel stat-card">
      <div class="stat-glow-bar" style="background: linear-gradient(90deg, transparent, var(--primary), transparent)"></div>
      <div class="stat-title">LoRa Radio Duty-Cycle</div>
      <div class="stat-value">
        <span id="stat-duty-cycle">0.00%</span>
        <span style="font-size: 0.85rem; color: var(--text-muted); font-weight: 400;">/ 1.0%</span>
      </div>
      <div class="duty-meter-bar">
        <div id="duty-meter-fill" class="duty-meter-fill"></div>
      </div>
      <div class="stat-meta" style="margin-top: 0.25rem;">ETSI EN 300 220 Sub-GHz Cap</div>
    </div>

    <!-- Stat 5: BitChat BLE Mesh -->
    <div class="glass-panel stat-card" style="cursor: pointer;" onclick="switchTab('bitchat')">
      <div class="stat-glow-bar" style="background: linear-gradient(90deg, transparent, #38bdf8, transparent)"></div>
      <div class="stat-title" style="display: flex; justify-content: space-between; align-items: center;">
        <span>BitChat BLE Mesh</span>
        <span id="stat-bitchat-pulse" class="pulse-dot" style="background: #38bdf8; box-shadow: 0 0 8px #38bdf8;"></span>
      </div>
      <div class="stat-value">
        <span id="stat-bitchat-peers-count">0</span>
        <span style="font-size: 0.85rem; color: var(--text-muted); font-weight: 400;">peers</span>
      </div>
      <div class="stat-meta">
        <span class="badge" id="stat-bitchat-badge" style="background: rgba(56,189,248,0.15); color: #38bdf8; border: 1px solid rgba(56,189,248,0.3);">BLE Active</span>
      </div>
    </div>
  </div>

  <!-- Navigation Tab Bar -->
  <div class="tab-bar-wrap">
    <div class="tab-bar">
      <button class="tab-btn active" onclick="switchTab('overview')">Overview &amp; Topology</button>
      <button class="tab-btn" onclick="switchTab('peers')">Peer Links &amp; Circuit Breakers</button>
      <button class="tab-btn" onclick="switchTab('routes')">Dynamic Distance-Vector Routes</button>
      <button class="tab-btn" onclick="switchTab('nostr')">Nostr Quorum &amp; Relays</button>
      <button class="tab-btn" onclick="switchTab('sms')">Cellular GSM / SMS</button>
      <button class="tab-btn" onclick="switchTab('bitchat')">Bluetooth &amp; BitChat Mesh</button>
      <button class="tab-btn" onclick="switchTab('tools')">🛠️ Tools</button>
      <button class="tab-btn" onclick="switchTab('config')">⚙️ Configuration</button>
      <button class="tab-btn" onclick="switchTab('console')">💻 Console &amp; Logs</button>
    </div>
  </div>

  <!-- Tab 1: Overview & Topology -->
  <div id="tab-overview" class="tab-content">
    <div class="layout-cols">
      <div>
        <div class="glass-panel card">
          <div class="card-title">
            <span>Mesh Topology & Peer Circuit Breakers</span>
            <span class="badge badge-primary">Distance-Vector Real-Time Flow</span>
          </div>
          <div class="topology-wrap">
            <svg width="100%" height="100%" viewBox="0 0 600 220">
              <defs>
                <linearGradient id="linkGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stop-color="#06b6d4" stop-opacity="0.8"/>
                  <stop offset="100%" stop-color="#10b981" stop-opacity="0.8"/>
                </linearGradient>
                <filter id="glow">
                  <feGaussianBlur stdDeviation="3" result="coloredBlur"/>
                  <feMerge>
                    <feMergeNode in="coloredBlur"/>
                    <feMergeNode in="SourceGraphic"/>
                  </feMerge>
                </filter>
              </defs>

              <!-- Link 1: Edge to Relay (LoRa/LAN) -->
              <line x1="120" y1="110" x2="300" y2="110" stroke="#1e293b" stroke-width="4"/>
              <line class="flow-line" x1="120" y1="110" x2="300" y2="110" stroke="url(#linkGrad)" stroke-width="3"/>
              
              <!-- Link 2: Relay to Central Gateway (VPN/IP) -->
              <line x1="300" y1="110" x2="480" y2="110" stroke="#1e293b" stroke-width="4"/>
              <line class="flow-line" x1="300" y1="110" x2="480" y2="110" stroke="url(#linkGrad)" stroke-width="3"/>

              <!-- Link 3: Gateway to Egress Cloud -->
              <path d="M 480 110 Q 530 50 560 30" fill="none" stroke="#1e293b" stroke-width="3"/>
              <path class="flow-line" d="M 480 110 Q 530 50 560 30" fill="none" stroke="#8b5cf6" stroke-width="2"/>

              <!-- EDGE NODE -->
              <g class="svg-node" transform="translate(120, 110)">
                <circle r="30" fill="#0f172a" stroke="#06b6d4" stroke-width="3" filter="url(#glow)"/>
                <text y="4" fill="#fff" font-size="10" font-weight="700" text-anchor="middle">EDGE</text>
                <text y="46" fill="#94a3b8" font-size="9" text-anchor="middle">Off-Grid Node</text>
              </g>

              <!-- RELAY MESH NODE -->
              <g class="svg-node" transform="translate(300, 110)">
                <circle r="32" fill="#0f172a" stroke="#10b981" stroke-width="3" filter="url(#glow)"/>
                <text y="4" fill="#fff" font-size="10" font-weight="700" text-anchor="middle">RELAY</text>
                <text y="46" fill="#94a3b8" font-size="9" text-anchor="middle">Multi-Hop Router</text>
              </g>

              <!-- CENTRAL GATEWAY NODE -->
              <g class="svg-node" transform="translate(480, 110)">
                <circle r="30" fill="#0f172a" stroke="#6366f1" stroke-width="3" filter="url(#glow)"/>
                <text y="4" fill="#fff" font-size="10" font-weight="700" text-anchor="middle">GATEWAY</text>
                <text y="46" fill="#94a3b8" font-size="9" text-anchor="middle">Core DC Hub</text>
              </g>

              <!-- Physical link badges in SVG -->
              <rect x="180" y="80" width="60" height="18" rx="4" fill="#0b0f19" stroke="rgba(6,182,212,0.3)"/>
              <text x="210" y="93" fill="#06b6d4" font-size="9" text-anchor="middle">LoRa / LAN</text>

              <rect x="360" y="80" width="60" height="18" rx="4" fill="#0b0f19" stroke="rgba(16,185,129,0.3)"/>
              <text x="390" y="93" fill="#10b981" font-size="9" text-anchor="middle">VPN / WireG</text>
            </svg>
          </div>

          <div style="margin-top: 1.25rem;">
            <div class="card-title">Peer Circuit Breaker States</div>
            <div class="table-responsive">
              <table id="overview-peers-table">
                <thead>
                  <tr>
                    <th>Node</th>
                    <th>Transport</th>
                    <th>Circuit State</th>
                    <th>Failures</th>
                    <th>Backlog</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">Synchronizing link states...</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <div>
        <!-- Live Alert Feed Card -->
        <div class="glass-panel card">
          <div class="card-title">
            <span>Live Alert Feed</span>
            <span class="badge badge-success" id="feed-count">Streaming</span>
          </div>
          <div id="event-feed" class="event-feed">
            <div class="event-card">
              <div class="event-header">
                <span class="badge badge-primary">SYSTEM</span>
                <span class="ts" style="color: var(--text-muted); font-size: 0.7rem;">Live</span>
              </div>
              <div class="event-summary">Subscribed to daemon Server-Sent Events (SSE) stream.</div>
              <div class="event-meta">
                <span>Ingress: REST / Peering / Nostr</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Overview BitChat Mesh Live Radar Card -->
    <div class="glass-panel card" style="margin-top: 0.5rem;">
      <div class="card-title">
        <div style="display: flex; align-items: center; gap: 0.6rem;">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.2"><path d="m7 7 10 10-5 5V2l5 5L7 17"/></svg>
          <span>Bluetooth BLE &amp; BitChat Ad-Hoc Mesh Radar</span>
        </div>
        <div style="display: flex; align-items: center; gap: 0.5rem;">
          <span class="badge" style="background: rgba(56,189,248,0.15); color: #38bdf8; border: 1px solid rgba(56,189,248,0.3);" id="overview-bitchat-status">Active (BLE GATT)</span>
          <button class="btn btn-primary" style="font-size: 0.72rem; padding: 0.25rem 0.65rem;" onclick="switchTab('bitchat')">
            Manage Mesh &rarr;
          </button>
        </div>
      </div>
      <div style="display: grid; grid-template-columns: minmax(240px, 280px) 1fr; gap: 1.25rem; align-items: center;">
        <div style="position: relative; width: 240px; height: 240px; margin: 0 auto; display: flex; align-items: center; justify-content: center;">
          <svg width="240" height="240" viewBox="0 0 260 260" id="overview-radar-svg">
            <defs>
              <radialGradient id="radarScanGrad" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.35"/>
                <stop offset="60%" stop-color="#38bdf8" stop-opacity="0.1"/>
                <stop offset="100%" stop-color="#38bdf8" stop-opacity="0"/>
              </radialGradient>
              <linearGradient id="sweepBeam" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.8"/>
                <stop offset="100%" stop-color="#0284c7" stop-opacity="0"/>
              </linearGradient>
            </defs>
            <circle cx="130" cy="130" r="120" stroke="rgba(56, 189, 248, 0.25)" stroke-width="1.5" fill="rgba(15, 23, 42, 0.75)"/>
            <circle cx="130" cy="130" r="85" stroke="rgba(56, 189, 248, 0.18)" stroke-width="1" fill="none" stroke-dasharray="3,3"/>
            <circle cx="130" cy="130" r="50" stroke="rgba(56, 189, 248, 0.22)" stroke-width="1" fill="none"/>
            <line x1="10" y1="130" x2="250" y2="130" stroke="rgba(56, 189, 248, 0.12)" stroke-width="1"/>
            <line x1="130" y1="10" x2="130" y2="250" stroke="rgba(56, 189, 248, 0.12)" stroke-width="1"/>
            <circle cx="130" cy="130" r="20" stroke="#38bdf8" fill="none" class="radar-ripple-1"/>
            <circle cx="130" cy="130" r="20" stroke="#38bdf8" fill="none" class="radar-ripple-2"/>
            <g class="radar-scanner" style="transform-origin: 130px 130px;">
              <path d="M 130 130 L 250 130 A 120 120 0 0 0 214.85 45.15 Z" fill="url(#radarScanGrad)"/>
              <line x1="130" y1="130" x2="250" y2="130" stroke="url(#sweepBeam)" stroke-width="2"/>
            </g>
            <circle cx="130" cy="130" r="14" fill="#0284c7" stroke="#38bdf8" stroke-width="2"/>
            <path d="M127 125 L133 131 L130 134 L130 122 L133 125 L127 131" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
            <g id="overview-radar-peers"></g>
          </svg>
        </div>
        <div style="display: flex; flex-direction: column; gap: 0.85rem;">
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.75rem;">
            <div style="padding: 0.75rem; background: rgba(56,189,248,0.06); border: 1px solid rgba(56,189,248,0.18); border-radius: 8px;">
              <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Local BLE Identity</div>
              <div style="font-weight: 600; color: var(--text-heading); font-size: 0.88rem;" id="overview-bitchat-nodename">OpenAlert-Mesh</div>
              <div style="font-size: 0.72rem; color: #38bdf8; font-family: monospace; display: flex; align-items: center; gap: 0.3rem; margin-top: 0.2rem;">
                <span id="overview-bitchat-senderid">--</span>
              </div>
            </div>
            <div style="padding: 0.75rem; background: rgba(56,189,248,0.06); border: 1px solid rgba(56,189,248,0.18); border-radius: 8px;">
              <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">GATT Service UUID</div>
              <div style="font-weight: 500; font-family: monospace; color: var(--text-muted); font-size: 0.72rem; margin-top: 0.2rem; word-break: break-all;" id="overview-bitchat-uuid">
                f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5c
              </div>
            </div>
          </div>
          <div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem;">
              <span style="font-size: 0.75rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em;">Discovered BLE Mesh Nodes</span>
              <span class="badge" style="background: rgba(56,189,248,0.12); color: #38bdf8; font-size: 0.65rem;" id="overview-bitchat-peer-count-badge">0 Active</span>
            </div>
            <div id="overview-bitchat-peers-list" style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
              <span style="color: var(--text-muted); font-size: 0.8rem; font-style: italic;">Listening for BitChat BLE broadcast announcements...</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Tab 2: Peer Links & Circuit Breakers -->
  <div id="tab-peers" class="tab-content" style="display: none;">
    <div class="glass-panel card">
      <div class="card-title">
        <span>Active Peering Links &amp; Failover Circuits</span>
        <span class="badge badge-success">Automated Fault Isolation</span>
      </div>
      <div class="table-responsive">
        <table id="full-peers-table">
          <thead>
            <tr>
              <th>Node Identifier</th>
              <th>Network Endpoint</th>
              <th>Transport Type</th>
              <th>Circuit Breaker</th>
              <th>Consecutive Failures</th>
              <th>Spooled Buffer</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            <tr><td colspan="7" style="text-align: center; color: var(--text-muted);">Loading peer data...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Tab 3: Dynamic Distance-Vector Routes -->
  <div id="tab-routes" class="tab-content" style="display: none;">
    <div class="glass-panel card">
      <div class="card-title">
        <span>Dynamic Multi-Hop Distance-Vector Routing</span>
        <span class="badge badge-primary">Split-Horizon Enforced</span>
      </div>
      <div class="table-responsive">
        <table id="routes-table">
          <thead>
            <tr>
              <th>Destination Node</th>
              <th>Next-Hop Peer</th>
              <th>Path Metric</th>
              <th>Hops</th>
              <th>Link Classification</th>
            </tr>
          </thead>
          <tbody>
            <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Evaluating shortest mesh paths...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Tab 4: Nostr Quorum & Relays -->
  <div id="tab-nostr" class="tab-content" style="display: none;">
    <div class="glass-panel card">
      <div class="card-title">
        <span>Nostr Relays Quorum & Health</span>
        <span class="badge badge-primary">M-of-N Consensus</span>
      </div>
      <div class="table-responsive">
        <table id="nostr-table">
          <thead>
            <tr>
              <th>Relay WebSocket URI</th>
              <th>Health Score</th>
              <th>Success / Failure</th>
              <th>Last Latency (ms)</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">Probing configured Nostr relays...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Tab 5: Cellular GSM / SMS -->
  <div id="tab-sms" class="tab-content" style="display: none;">
    <div class="layout-cols">
      <div>
        <div class="glass-panel card">
          <div class="card-title">
            <span>Cellular Modem Telemetry</span>
            <span id="sms-status-badge" class="badge badge-warning">Checking Modem...</span>
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 0.75rem; margin-bottom: 1rem;">
            <div style="padding: 0.65rem; background: rgba(255,255,255,0.02); border: 1px solid var(--card-border); border-radius: 6px;">
              <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Subsystem</div>
              <strong id="sms-enabled-text" style="font-size: 0.85rem; color: var(--text-heading);">--</strong>
            </div>
            <div style="padding: 0.65rem; background: rgba(255,255,255,0.02); border: 1px solid var(--card-border); border-radius: 6px;">
              <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Serial Port</div>
              <strong id="sms-port-text" style="font-size: 0.85rem; color: var(--text-heading);">--</strong>
            </div>
            <div style="padding: 0.65rem; background: rgba(255,255,255,0.02); border: 1px solid var(--card-border); border-radius: 6px;">
              <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Baud Rate</div>
              <strong id="sms-baud-text" style="font-size: 0.85rem; color: var(--text-heading);">--</strong>
            </div>
            <div style="padding: 0.65rem; background: rgba(255,255,255,0.02); border: 1px solid var(--card-border); border-radius: 6px;">
              <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Poll Interval</div>
              <strong id="sms-poll-text" style="font-size: 0.85rem; color: var(--text-heading);">--</strong>
            </div>
            <div style="padding: 0.65rem; background: rgba(255,255,255,0.02); border: 1px solid var(--card-border); border-radius: 6px;">
              <div style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Storage TTL</div>
              <strong id="sms-ttl-text" style="font-size: 0.85rem; color: var(--text-heading);">--</strong>
            </div>
          </div>
          <div id="sms-error-box" style="display: none; padding: 0.65rem 0.85rem; border-radius: 6px; background: rgba(244,63,94,0.15); border: 1px solid var(--danger); color: #fda4af; font-size: 0.8rem; margin-bottom: 1rem;"></div>

          <div class="card-title" style="margin-top: 1rem;">Cellular SMS Transmission Log</div>
          <div class="table-responsive">
            <table id="sms-history-table">
              <thead>
                <tr>
                  <th>Direction</th>
                  <th>Phone Number</th>
                  <th>Message Body</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr><td colspan="4" style="text-align: center; color: var(--text-muted);">Fetching SMS history...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div>
        <!-- Send Manual SMS Card -->
        <div class="glass-panel card">
          <div class="card-title">
            <span>Send Direct Cellular SMS</span>
            <span class="badge badge-primary">GSM AT Command</span>
          </div>
          <div class="form-group">
            <label>Recipient Phone Number (+E.164)</label>
            <input type="text" id="sms-manual-phone" class="form-control" placeholder="+393349246425">
          </div>
          <div class="form-group">
            <label>Message Content (UCS-2 / ASCII)</label>
            <textarea id="sms-manual-msg" class="form-control" rows="3" placeholder="Test notification from OpenAlert NOC..."></textarea>
          </div>
          <button class="btn btn-primary" style="width: 100%; justify-content: center;" onclick="sendManualSms()">
            Dispatch SMS Now
          </button>
        </div>

        <!-- Hot Reload SMS ACL Card -->
        <div class="glass-panel card">
          <div class="card-title">
            <span>SMS Access Control Lists</span>
            <span class="badge badge-cyan">SQLite Persisted</span>
          </div>
          <div class="form-group">
            <label>Outbound Emergency Alert Recipients (newline separated)</label>
            <textarea id="sms-recipients-input" class="form-control" rows="3" placeholder="+393349246425"></textarea>
          </div>
          <div class="form-group">
            <label>Authorized Inbound Senders (newline separated)</label>
            <textarea id="sms-senders-input" class="form-control" rows="3" placeholder="+393349246425"></textarea>
          </div>
          <button class="btn btn-primary" style="width: 100%; justify-content: center;" onclick="saveSmsConfig()">
            Save &amp; Hot-Reload SMS Config
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Tab 6: Bluetooth & BitChat Mesh -->
  <div id="tab-bitchat" class="tab-content" style="display: none;">
    <div class="layout-cols">
      <div>
        <div class="glass-panel card">
          <div class="card-title">
            <div style="display: flex; align-items: center; gap: 0.6rem;">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.2"><path d="m7 7 10 10-5 5V2l5 5L7 17"/></svg>
              <span>BitChat Bluetooth LE Mesh Tactical Radar</span>
            </div>
            <span class="badge" style="background: rgba(56,189,248,0.15); color: #38bdf8; border: 1px solid rgba(56,189,248,0.3);" id="bitchat-tab-status">Active (BLE GATT)</span>
          </div>
          <div style="position: relative; width: 280px; height: 280px; margin: 0 auto; display: flex; align-items: center; justify-content: center;">
            <svg width="280" height="280" viewBox="0 0 300 300" id="tab-radar-svg">
              <defs>
                <radialGradient id="tabRadarGrad" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.38"/>
                  <stop offset="60%" stop-color="#38bdf8" stop-opacity="0.1"/>
                  <stop offset="100%" stop-color="#38bdf8" stop-opacity="0"/>
                </radialGradient>
                <linearGradient id="tabSweepBeam" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.9"/>
                  <stop offset="100%" stop-color="#0284c7" stop-opacity="0"/>
                </linearGradient>
              </defs>
              <circle cx="150" cy="150" r="135" stroke="rgba(56, 189, 248, 0.25)" stroke-width="1.5" fill="rgba(15, 23, 42, 0.75)"/>
              <circle cx="150" cy="150" r="95" stroke="rgba(56, 189, 248, 0.18)" stroke-width="1" fill="none" stroke-dasharray="3,3"/>
              <circle cx="150" cy="150" r="55" stroke="rgba(56, 189, 248, 0.22)" stroke-width="1" fill="none"/>
              <line x1="15" y1="150" x2="285" y2="150" stroke="rgba(56, 189, 248, 0.12)" stroke-width="1"/>
              <line x1="150" y1="15" x2="150" y2="285" stroke="rgba(56, 189, 248, 0.12)" stroke-width="1"/>
              <circle cx="150" cy="150" r="22" stroke="#38bdf8" fill="none" class="radar-ripple-1"/>
              <circle cx="150" cy="150" r="22" stroke="#38bdf8" fill="none" class="radar-ripple-2"/>
              <g class="radar-scanner" style="transform-origin: 150px 150px;">
                <path d="M 150 150 L 285 150 A 135 135 0 0 0 245.45 54.55 Z" fill="url(#tabRadarGrad)"/>
                <line x1="150" y1="150" x2="285" y2="150" stroke="url(#tabSweepBeam)" stroke-width="2.5"/>
              </g>
              <circle cx="150" cy="150" r="16" fill="#0284c7" stroke="#38bdf8" stroke-width="2"/>
              <path d="M147 145 L153 151 L150 154 L150 142 L153 145 L147 151" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
              <g id="tab-radar-peers"></g>
            </svg>
          </div>
          <div style="text-align: center; margin-top: 0.5rem; font-size: 0.8rem; color: var(--text-muted);" id="tab-radar-peer-count">0 Peers Online</div>
        </div>

        <div class="glass-panel card">
          <div class="card-title">
            <span>Discovered BitChat Mesh Nodes</span>
            <span class="badge badge-cyan">Ed25519 Verified</span>
          </div>
          <div class="table-responsive">
            <table id="bitchat-peers-table">
              <thead>
                <tr>
                  <th>Nickname</th>
                  <th>Sender ID</th>
                  <th>Session State</th>
                  <th>Verification</th>
                  <th>Traffic</th>
                  <th>Last Seen</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                <tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No active BitChat peers detected</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div>
        <div class="glass-panel card">
          <div class="card-title">
            <span>BitChat Node Metadata</span>
            <span class="badge badge-cyan">Linux BlueZ GATT</span>
          </div>
          <div class="form-group">
            <label>Advertised Node Nickname</label>
            <input type="text" id="bitchat-tab-nodename" class="form-control" readonly value="OpenAlert-Mesh">
          </div>
          <div class="form-group">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
              <label style="margin: 0; font-size: 0.72rem;">Local Sender ID (Blake3 Pubkey Hash)</label>
              <button class="btn" style="font-size: 0.65rem; padding: 0.1rem 0.4rem; background: rgba(255,255,255,0.08); color: var(--text-heading);" onclick="copySenderId()">Copy</button>
            </div>
            <div id="bitchat-tab-senderid" style="font-family: monospace; font-size: 0.8rem; color: #38bdf8; word-break: break-all; padding: 0.5rem 0.75rem; background: var(--input-bg); border: 1px solid var(--card-border); border-radius: 6px;">--</div>
          </div>
          <div class="form-group">
            <label>Service UUID</label>
            <div id="bitchat-tab-uuid" style="font-family: monospace; font-size: 0.75rem; color: var(--text-muted); word-break: break-all; padding: 0.5rem 0.75rem; background: var(--input-bg); border: 1px solid var(--card-border); border-radius: 6px;">
              f47b5e2d-4a9e-4c5a-9b3f-8e1d2c3a4b5c
            </div>
          </div>
        </div>

        <div class="glass-panel card">
          <div class="card-title">
            <span>Broadcast BLE Mesh Alert</span>
            <span class="badge badge-primary">E2EE Flooding</span>
          </div>
          <div class="form-group">
            <label>Alert Severity</label>
            <select id="bitchat-broadcast-sev" class="form-control">
              <option value="warning">Warning</option>
              <option value="critical">Critical</option>
              <option value="emergency">Emergency</option>
            </select>
          </div>
          <div class="form-group">
            <label>Notification Text</label>
            <textarea id="bitchat-broadcast-msg" class="form-control" rows="3" placeholder="Evacuation advisory or critical notice for nearby mobile nodes..."></textarea>
          </div>
          <div id="bitchat-broadcast-feedback" style="font-size: 0.78rem; margin-bottom: 0.5rem; color: #38bdf8;"></div>
          <button class="btn btn-primary" style="width: 100%; justify-content: center;" onclick="sendBitChatBroadcast()">
            Broadcast to BitChat Mesh
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Tab 7: Operational Tools & Conversions -->
  <div id="tab-tools" class="tab-content" style="display: none;">
    <div class="layout-cols-equal">
      <!-- Left Column: Nostr Keypair Generator & Converter -->
      <div>
        <div class="glass-panel card">
          <div class="card-title">
            <span>🔑 Nostr Secp256k1 Keypair Generator</span>
            <button class="btn btn-primary" style="font-size: 0.72rem; padding: 0.25rem 0.7rem;" onclick="generateNostrKeypair()">Generate Fresh Keypair</button>
          </div>
          <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.85rem;">
            Generates standard BIP-340 Schnorr Secp256k1 keys compatible with Nostr relays, NIP-17 0xChat, Coracle, and Damus.
          </p>
          <div class="form-group">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
              <label style="margin: 0; font-size: 0.72rem;">Public Key (npub1...)</label>
              <button class="btn" style="font-size: 0.65rem; padding: 0.1rem 0.4rem; background: rgba(255,255,255,0.08); color: var(--text-heading);" onclick="copyText('tool-gen-npub')">Copy npub</button>
            </div>
            <input type="text" id="tool-gen-npub" class="form-control" readonly placeholder="Click 'Generate Fresh Keypair' above">
          </div>
          <div class="form-group">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
              <label style="margin: 0; font-size: 0.72rem;">Public Key (Hex 64-char)</label>
              <button class="btn" style="font-size: 0.65rem; padding: 0.1rem 0.4rem; background: rgba(255,255,255,0.08); color: var(--text-heading);" onclick="copyText('tool-gen-pubhex')">Copy Hex</button>
            </div>
            <input type="text" id="tool-gen-pubhex" class="form-control" readonly placeholder="--">
          </div>
          <div class="form-group">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
              <label style="margin: 0; font-size: 0.72rem; color: #fda4af;">Secret Private Key (nsec1... - NEVER SHARE)</label>
              <button class="btn" style="font-size: 0.65rem; padding: 0.1rem 0.4rem; background: rgba(244,63,94,0.15); color: #fda4af;" onclick="copyText('tool-gen-nsec')">Copy nsec</button>
            </div>
            <input type="password" id="tool-gen-nsec" class="form-control" readonly placeholder="--">
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
              <label style="margin: 0; font-size: 0.72rem; color: #fda4af;">Secret Private Key (Hex 64-char)</label>
              <button class="btn" style="font-size: 0.65rem; padding: 0.1rem 0.4rem; background: rgba(244,63,94,0.15); color: #fda4af;" onclick="copyText('tool-gen-privhex')">Copy PrivHex</button>
            </div>
            <input type="password" id="tool-gen-privhex" class="form-control" readonly placeholder="--">
          </div>
        </div>

        <div class="glass-panel card">
          <div class="card-title">
            <span>🔄 Nostr Key Converter &amp; Deriver</span>
            <span class="badge badge-cyan">Bech32 &harr; Hex &bull; BIP-340</span>
          </div>
          <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.85rem;">
            Paste any <code>npub1...</code>, <code>nsec1...</code>, or 64-character hex key. Decodes Bech32 format, verifies checksums, and derives public keys from private keys.
          </p>
          <div class="form-group">
            <label>Input Key (npub1, nsec1, or 64-char Hex)</label>
            <div style="display: flex; gap: 0.5rem;">
              <input type="text" id="tool-conv-input" class="form-control" placeholder="e.g. npub1uvtjer4wn7y2qpe4clvqd7qz7x483pthpngewqddc03xes39uq3sw9p5u6">
              <button class="btn btn-primary" onclick="convertNostrKey()">Convert</button>
            </div>
          </div>
          <div id="tool-conv-result" style="display: none; padding: 0.75rem; border-radius: 8px; background: rgba(255,255,255,0.03); border: 1px solid var(--card-border); margin-top: 0.5rem;">
            <div style="display: grid; grid-template-columns: 100px 1fr; gap: 0.5rem; font-size: 0.8rem; align-items: center;">
              <span style="color: var(--text-muted);">Detected:</span>
              <strong id="tool-conv-format" style="color: var(--text-heading);">--</strong>
              <span style="color: var(--text-muted);">Hex (64):</span>
              <div style="display: flex; align-items: center; gap: 0.3rem;">
                <code id="tool-conv-hex" style="word-break: break-all; color: var(--cyan);">--</code>
                <button class="btn" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;" onclick="copyText('tool-conv-hex')">Copy</button>
              </div>
              <span style="color: var(--text-muted);">Bech32:</span>
              <div style="display: flex; align-items: center; gap: 0.3rem;">
                <code id="tool-conv-bech32" style="word-break: break-all; color: #a5b4fc;">--</code>
                <button class="btn" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;" onclick="copyText('tool-conv-bech32')">Copy</button>
              </div>
              <span id="tool-conv-derived-label" style="color: var(--text-muted); display: none;">Derived Pub:</span>
              <div id="tool-conv-derived-box" style="display: none;">
                <div style="display: flex; align-items: center; gap: 0.3rem; margin-bottom: 0.2rem;">
                  <code id="tool-conv-derived-hex" style="word-break: break-all; color: var(--success);">--</code>
                  <button class="btn" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;" onclick="copyText('tool-conv-derived-hex')">Copy</button>
                </div>
                <div style="display: flex; align-items: center; gap: 0.3rem;">
                  <code id="tool-conv-derived-npub" style="word-break: break-all; color: #38bdf8;">--</code>
                  <button class="btn" style="font-size: 0.6rem; padding: 0.1rem 0.3rem;" onclick="copyText('tool-conv-derived-npub')">Copy</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column: SMS Codec & Cryptographic Generators -->
      <div>
        <div class="glass-panel card">
          <div class="card-title">
            <span>📱 Cellular SMS UCS-2 Hex Codec</span>
            <span class="badge badge-primary">GSM 03.38 &bull; UCS-2 16-Bit</span>
          </div>
          <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.85rem;">
            Bi-directional cellular modem text codec. Converts UTF-8 (accents, emojis) to UCS-2 Big-Endian Hex, or translates raw modem hex dumps back to UTF-8.
          </p>
          <div class="form-group">
            <label>Input Text (UTF-8) OR Modem Hex String</label>
            <textarea id="tool-sms-input" class="form-control" rows="3" placeholder="Enter text (e.g. Allarme critico! 🚨) or hex (0041006c...)"></textarea>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.65rem;">
            <span id="tool-sms-op-badge" class="badge badge-cyan" style="display: none;">--</span>
            <button class="btn btn-primary" onclick="convertSmsCodec()">Translate / Encode</button>
          </div>
          <div class="form-group" style="margin-bottom: 0;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
              <label style="margin: 0; font-size: 0.72rem;">Result</label>
              <button class="btn" style="font-size: 0.65rem; padding: 0.1rem 0.4rem; background: rgba(255,255,255,0.08); color: var(--text-heading);" onclick="copyText('tool-sms-output')">Copy Result</button>
            </div>
            <textarea id="tool-sms-output" class="form-control" rows="3" readonly placeholder="Translated result will appear here"></textarea>
          </div>
        </div>

        <div class="glass-panel card">
          <div class="card-title">
            <span>🛡️ Privacy &amp; Security Tools</span>
          </div>

          <!-- Password Hasher -->
          <div style="margin-bottom: 1.15rem;">
            <div style="font-size: 0.82rem; font-weight: 600; color: var(--text-heading); margin-bottom: 0.2rem;">Dashboard Password Hasher (SHA-256)</div>
            <p style="font-size: 0.74rem; color: var(--text-muted); margin-bottom: 0.45rem;">Computes the cryptographic SHA-256 hash for <code>[dashboard.auth] password_hash</code>.</p>
            <div style="display: flex; gap: 0.5rem; margin-bottom: 0.35rem;">
              <input type="password" id="tool-pwd-input" class="form-control" placeholder="Enter password to hash...">
              <button class="btn btn-secondary" onclick="hashPassword()">Hash</button>
            </div>
            <div style="display: flex; align-items: center; gap: 0.3rem;">
              <input type="text" id="tool-pwd-output" class="form-control" readonly placeholder="Generated SHA-256 hash" style="font-size: 0.75rem;">
              <button class="btn" style="font-size: 0.65rem; padding: 0.2rem 0.5rem;" onclick="copyText('tool-pwd-output')">Copy</button>
            </div>
          </div>

          <hr style="border: 0; border-top: 1px solid var(--card-border); margin: 0.85rem 0;">

          <!-- 256-Bit Cryptographic Hex Generator -->
          <div>
            <div style="font-size: 0.82rem; font-weight: 600; color: var(--text-heading); margin-bottom: 0.2rem;">256-Bit Cryptographic Pre-Shared Key Generator</div>
            <p style="font-size: 0.74rem; color: var(--text-muted); margin-bottom: 0.45rem;">Generates 32-byte OsRng random hex for Peering PSKs (AEAD ChaCha20-Poly1305) and Webhook secrets.</p>
            <div style="display: flex; gap: 0.5rem; align-items: center;">
              <input type="text" id="tool-psk-output" class="form-control" readonly placeholder="Click 'Generate Key' ->" style="font-size: 0.75rem;">
              <button class="btn btn-primary" style="font-size: 0.72rem; padding: 0.3rem 0.6rem; white-space: nowrap;" onclick="generateCryptoKey()">Generate Key</button>
              <button class="btn" style="font-size: 0.72rem; padding: 0.3rem 0.5rem;" onclick="copyText('tool-psk-output')">Copy</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Tab 8: Configuration Management & ACL Editor -->
  <div id="tab-config" class="tab-content" style="display: none;">
    <div class="layout-cols-equal">
      <!-- Left Column: Visual Access Control Lists -->
      <div>
        <div class="glass-panel card">
          <div class="card-title">
            <span>📡 Nostr &amp; 0xChat Operators (ACL)</span>
            <span class="badge badge-primary">NIP-17 / Kind 1 &bull; Hot-Reload</span>
          </div>
          <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.85rem;">
            Manage authorized operators permitted to send remote C2 commands (<code>ping</code>, <code>status</code>, <code>ack</code>, <code>mesh</code>, <code>sms</code>) and receive private encrypted alert DMs.
          </p>

          <div class="form-group">
            <label>Add Operator (Paste npub1... or 64-char Hex)</label>
            <div style="display: flex; gap: 0.5rem;">
              <input type="text" id="config-oxchat-new-op" class="form-control" placeholder="npub1... or hex public key">
              <button class="btn btn-primary" onclick="addNostrOperator()">+ Add</button>
            </div>
          </div>

          <div style="margin-bottom: 0.85rem;">
            <div style="font-size: 0.72rem; color: var(--text-muted); margin-bottom: 0.4rem;">Configured 0xChat C2 Authorized Operators:</div>
            <div id="config-oxchat-ops-list" style="display: flex; flex-direction: column; gap: 0.35rem; max-height: 160px; overflow-y: auto;">
              <span style="color: var(--text-muted); font-size: 0.75rem; font-style: italic;">Loading operator list...</span>
            </div>
          </div>

          <div style="margin-bottom: 0.85rem;">
            <div style="font-size: 0.72rem; color: var(--text-muted); margin-bottom: 0.4rem;">Configured 0xChat Alert DM Recipients:</div>
            <div id="config-oxchat-recipients-list" style="display: flex; flex-direction: column; gap: 0.35rem; max-height: 160px; overflow-y: auto;">
              <span style="color: var(--text-muted); font-size: 0.75rem; font-style: italic;">Loading recipients list...</span>
            </div>
          </div>

          <div style="display: flex; justify-content: flex-end; gap: 0.5rem;">
            <button class="btn btn-primary" onclick="saveNostrAcl()">Save Nostr Access Control</button>
          </div>
        </div>

        <div class="glass-panel card">
          <div class="card-title">
            <span>📱 Cellular SMS Authorized Senders &amp; Recipients</span>
            <span class="badge badge-cyan">GSM AT &bull; SQLite Persisted</span>
          </div>
          <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.85rem;">
            Configure inbound phone numbers authorized to execute remote SMS commands and outbound numbers receiving emergency SMS dispatches.
          </p>
          <div class="form-group">
            <label>Outbound Emergency SMS Recipients (+E.164, newline separated)</label>
            <textarea id="config-sms-recipients-text" class="form-control" rows="3" placeholder="+393349246425"></textarea>
          </div>
          <div class="form-group">
            <label>Authorized Inbound Senders (+E.164, newline separated; empty = all permitted)</label>
            <textarea id="config-sms-senders-text" class="form-control" rows="3" placeholder="+393349246425"></textarea>
          </div>
          <div style="display: flex; justify-content: flex-end;">
            <button class="btn btn-primary" onclick="saveSmsAclFromConfigTab()">Save SMS Access Control</button>
          </div>
        </div>
      </div>

      <!-- Right Column: Interactive Raw TOML Configuration Editor -->
      <div>
        <div class="glass-panel card">
          <div class="card-title">
            <span>📝 Daemon Configuration Editor (openalertd.toml)</span>
            <button class="btn btn-secondary" style="font-size: 0.7rem; padding: 0.2rem 0.55rem;" onclick="loadConfigFile()">Reload File</button>
          </div>
          <p style="font-size: 0.78rem; color: var(--text-muted); margin-bottom: 0.65rem;">
            Directly edit the live configuration file on disk (<code id="config-file-path-badge" style="color: var(--cyan);">config/openalertd.toml</code>). Built-in dry-run validation ensures no broken config is ever saved.
          </p>

          <div id="config-validation-banner" style="display: none; padding: 0.6rem 0.75rem; border-radius: 6px; font-size: 0.78rem; margin-bottom: 0.65rem;"></div>

          <div class="form-group" style="margin-bottom: 0.65rem;">
            <textarea id="config-toml-editor" class="form-control" rows="22" style="font-family: var(--font-mono); font-size: 0.8rem; line-height: 1.4; tab-size: 4; white-space: pre;" spellcheck="false" placeholder="Loading daemon configuration..."></textarea>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
            <button class="btn btn-secondary" style="color: var(--cyan); border-color: rgba(6,182,212,0.3);" onclick="validateTomlConfig()">Validate Syntax</button>
            <div style="display: flex; gap: 0.5rem;">
              <button class="btn btn-secondary" onclick="loadConfigFile()">Discard Changes</button>
              <button class="btn btn-primary" onclick="saveTomlConfig()">Backup &amp; Save Config</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Tab 9: Live Console & Event Log Stream (New!) -->
  <div id="tab-console" class="tab-content" style="display: none;">
    <div class="glass-panel card">
      <div class="card-title">
        <div style="display: flex; align-items: center; gap: 0.6rem;">
          <span>💻 Live Daemon Interactive Console</span>
          <span class="badge badge-success" id="console-stream-badge">Streaming</span>
        </div>
        <div style="display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;">
          <input type="text" id="console-filter-input" class="form-control" style="width: 160px; padding: 0.25rem 0.5rem; font-size: 0.75rem;" placeholder="Filter logs..." oninput="filterConsoleLogs()">
          <select id="console-level-select" class="form-control" style="width: 110px; padding: 0.25rem 0.5rem; font-size: 0.75rem;" onchange="filterConsoleLogs()">
            <option value="all">All Levels</option>
            <option value="info">INFO</option>
            <option value="warn">WARN</option>
            <option value="error">ERROR / ALERT</option>
          </select>
          <label style="display: flex; align-items: center; gap: 0.3rem; font-size: 0.75rem; color: var(--text-muted); cursor: pointer; user-select: none;">
            <input type="checkbox" id="console-autoscroll" checked> Auto-scroll
          </label>
          <button class="btn btn-secondary" style="font-size: 0.7rem; padding: 0.25rem 0.55rem;" onclick="copyConsoleLogs()">📋 Copy</button>
          <button class="btn btn-secondary" style="font-size: 0.7rem; padding: 0.25rem 0.55rem;" onclick="clearConsoleLogs()">🧹 Clear</button>
        </div>
      </div>
      <div id="console-pane" class="console-pane">
        <div class="console-line" data-level="info">
          <span class="console-ts">[SYSTEM BOOT]</span>
          <span class="console-tag-info">[INFO]</span>
          <span class="console-msg">OpenAlert Control Plane interactive terminal initialized.</span>
        </div>
      </div>
    </div>
  </div>

  <!-- Modal: Test Alert Dispatcher -->
  <div id="test-modal" class="modal-overlay">
    <div class="glass-panel modal-box">
      <div class="card-title">
        <span>Dispatch Test Alert</span>
        <span style="cursor: pointer; font-size: 1.2rem; color: var(--text-muted);" onclick="closeTestModal()">&times;</span>
      </div>
      <div class="form-group">
        <label>Summary / Code</label>
        <input type="text" id="alert-summary" class="form-control" value="Substation Power Grid Anomaly">
      </div>
      <div class="form-group">
        <label>Severity Level</label>
        <select id="alert-severity" class="form-control">
          <option value="critical">Critical</option>
          <option value="emergency">Emergency</option>
          <option value="warning">Warning</option>
          <option value="info">Info</option>
        </select>
      </div>
      <div class="form-group">
        <label>Egress Target Destination</label>
        <select id="alert-dest" class="form-control">
          <option value="peering">Peering Mesh (LoRa / UDP)</option>
          <option value="py-phone-caller">py-phone-caller Telephony</option>
          <option value="nostr">Nostr Relay Mesh</option>
          <option value="bitchat">BitChat BLE Mesh</option>
          <option value="sms">Cellular GSM / SMS Alert</option>
        </select>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="closeTestModal()">Cancel</button>
        <button class="btn btn-primary" onclick="sendTestAlert()">Dispatch Alert Now</button>
      </div>
    </div>
  </div>

  <script>
    // --- THEME ENGINE (DAY / NIGHT) ---
    let currentTheme = localStorage.getItem('openalert-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', currentTheme);
    updateThemeControls(currentTheme);

    function toggleTheme() {
      currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', currentTheme);
      localStorage.setItem('openalert-theme', currentTheme);
      updateThemeControls(currentTheme);
      logToConsole('info', 'UI', `Switched theme to ${currentTheme.toUpperCase()} mode`);
    }

    function updateThemeControls(t) {
      const icon = document.getElementById('theme-icon');
      const text = document.getElementById('theme-text');
      const logo = document.getElementById('brand-logo-img');
      if (t === 'light') {
        if (icon) icon.innerText = '☀️';
        if (text) text.innerText = 'Day';
        if (logo) logo.src = '/api/v1/logo?theme=day';
      } else {
        if (icon) icon.innerText = '🌙';
        if (text) text.innerText = 'Night';
        if (logo) logo.src = '/api/v1/logo?theme=night';
      }
    }

    // --- SYNTHESIZED WEB AUDIO API ALARMS (Disabled / Muted by Default) ---
    let audioEnabled = localStorage.getItem('openalert-audio') === 'true'; // Default is false!
    let audioCtx = null;
    let activeAlarmOscillators = [];

    function initAudioContext() {
      if (!audioCtx) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (AudioContext) {
          audioCtx = new AudioContext();
        }
      }
      if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume();
      }
    }

    function toggleAudioAlarm() {
      initAudioContext();
      audioEnabled = !audioEnabled;
      localStorage.setItem('openalert-audio', audioEnabled);
      updateAudioControls();
      if (audioEnabled) {
        playTone(587, 0.1, 'sine');
        setTimeout(() => playTone(880, 0.15, 'sine'), 120);
        logToConsole('info', 'AUDIO', 'Acoustic alarm cues enabled by operator');
      } else {
        stopActiveAlarmSound();
        logToConsole('warn', 'AUDIO', 'Acoustic alarm cues muted');
      }
    }

    function updateAudioControls() {
      const icon = document.getElementById('audio-icon');
      const text = document.getElementById('audio-text');
      const btn = document.getElementById('btn-audio-toggle');
      if (audioEnabled) {
        if (icon) icon.innerText = '🔊';
        if (text) text.innerText = 'Sound ON';
        if (btn) {
          btn.style.background = 'rgba(16, 185, 129, 0.18)';
          btn.style.borderColor = 'rgba(16, 185, 129, 0.4)';
          btn.style.color = '#34d399';
        }
      } else {
        if (icon) icon.innerText = '🔇';
        if (text) text.innerText = 'Sound Muted';
        if (btn) {
          btn.style.background = '';
          btn.style.borderColor = '';
          btn.style.color = '';
        }
      }
    }
    updateAudioControls();

    function playTone(freq, duration, type = 'sine') {
      if (!audioEnabled || !audioCtx) return;
      try {
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = type;
        osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
        gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
        osc.connect(gain);
        gain.connect(audioCtx.destination);
        osc.start();
        osc.stop(audioCtx.currentTime + duration);
      } catch (err) {
        console.warn('Audio synthesis notice:', err);
      }
    }

    function triggerAlarmSiren(sev) {
      if (!audioEnabled) return;
      initAudioContext();
      stopActiveAlarmSound();

      if (sev === 'critical' || sev === 'emergency') {
        let count = 0;
        const interval = setInterval(() => {
          if (!audioEnabled || count >= 6) {
            clearInterval(interval);
            return;
          }
          const freq = count % 2 === 0 ? 880 : 587;
          playTone(freq, 0.22, 'sawtooth');
          count++;
        }, 260);
        activeAlarmOscillators.push(interval);
      } else if (sev === 'warning') {
        playTone(659, 0.18, 'triangle');
        setTimeout(() => playTone(880, 0.22, 'triangle'), 190);
      } else {
        playTone(523, 0.15, 'sine');
      }
    }

    function stopActiveAlarmSound() {
      activeAlarmOscillators.forEach(id => clearInterval(id));
      activeAlarmOscillators = [];
    }

    // --- ACTIVE INCIDENT BANNER & ACK ---
    let latestCriticalIncident = null;

    function showIncidentBanner(alert) {
      latestCriticalIncident = alert;
      const banner = document.getElementById('incident-banner');
      if (!banner) return;
      banner.style.display = 'flex';

      const badge = document.getElementById('incident-badge');
      if (badge) badge.innerText = `🚨 ${(alert.severity || 'CRITICAL').toUpperCase()} ALARM`;
      const sumEl = document.getElementById('incident-summary');
      if (sumEl) sumEl.innerText = alert.summary || 'Unspecified emergency incident';
      const metaEl = document.getElementById('incident-meta');
      if (metaEl) metaEl.innerText = `ID: ${alert.alert_id} | Node: ${alert.node || 'Local'} | Egress: [${(alert.destinations || []).join(', ')}]`;

      triggerAlarmSiren(alert.severity);
    }

    function acknowledgeActiveIncident() {
      stopActiveAlarmSound();
      const badge = document.getElementById('incident-badge');
      if (badge) {
        badge.className = 'badge badge-success';
        badge.innerText = '✅ ACKNOWLEDGED';
      }
      if (latestCriticalIncident) {
        logToConsole('ack', 'C2', `Alert ${latestCriticalIncident.alert_id} acknowledged by operator`);
        addEventToFeed({
          alert_id: 'ack-' + Date.now().toString(16),
          severity: 'info',
          summary: `✅ Acknowledged: ${latestCriticalIncident.summary} [${latestCriticalIncident.alert_id}]`,
          destinations: ['control-plane']
        });
      }
      setTimeout(() => dismissIncidentBanner(), 3500);
    }

    function dismissIncidentBanner() {
      stopActiveAlarmSound();
      const banner = document.getElementById('incident-banner');
      if (banner) banner.style.display = 'none';
    }

    // --- LIVE CONSOLE LOG STREAM ---
    function logToConsole(level, tag, msg) {
      const pane = document.getElementById('console-pane');
      if (!pane) return;
      const ts = new Date().toISOString().replace('T', ' ').slice(0, 19);

      const div = document.createElement('div');
      div.className = 'console-line';
      div.setAttribute('data-level', level);

      let tagClass = 'console-tag-info';
      if (level === 'warn') tagClass = 'console-tag-warn';
      else if (level === 'error') tagClass = 'console-tag-error';
      else if (level === 'ack') tagClass = 'console-tag-ack';

      div.innerHTML = `
        <span class="console-ts">[${ts}]</span>
        <span class="${tagClass}">[${level.toUpperCase()}]</span>
        <span style="color: var(--cyan); font-weight: 500;">[${tag}]</span>
        <span class="console-msg">${escapeHtml(msg)}</span>
      `;
      pane.appendChild(div);

      const autoscroll = document.getElementById('console-autoscroll');
      if (autoscroll && autoscroll.checked) {
        pane.scrollTop = pane.scrollHeight;
      }
    }

    function filterConsoleLogs() {
      const term = (document.getElementById('console-filter-input').value || '').toLowerCase();
      const level = document.getElementById('console-level-select').value;
      const lines = document.querySelectorAll('.console-line');

      lines.forEach(l => {
        const text = l.innerText.toLowerCase();
        const lLevel = l.getAttribute('data-level') || 'info';
        const matchText = !term || text.includes(term);
        const matchLevel = level === 'all' || lLevel === level || (level === 'error' && (lLevel === 'error' || lLevel === 'emergency' || lLevel === 'critical'));
        l.style.display = matchText && matchLevel ? 'flex' : 'none';
      });
    }

    function copyConsoleLogs() {
      const pane = document.getElementById('console-pane');
      if (!pane) return;
      navigator.clipboard.writeText(pane.innerText).then(() => {
        alert('Console logs copied to clipboard!');
      }).catch(() => prompt('Copy logs:', pane.innerText));
    }

    function clearConsoleLogs() {
      const pane = document.getElementById('console-pane');
      if (pane) pane.innerHTML = '';
      logToConsole('info', 'SYS', 'Console buffer cleared.');
    }

    function escapeHtml(str) {
      return (str || '').replace(/[&<>"']/g, m => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      })[m]);
    }

    // --- NAVIGATION TABS ---
    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
      if (window.event && window.event.target && window.event.target.classList) {
        window.event.target.classList.add('active');
      }
      const target = document.getElementById('tab-' + tabId);
      if (target) target.style.display = 'block';

      if (tabId === 'sms') {
        loadSmsStatus();
        loadSmsHistory();
      }
      if (tabId === 'bitchat') {
        loadBitChatStatus();
      }
      if (tabId === 'config') {
        loadConfigFile();
      }
      logToConsole('info', 'NAV', `Switched active tab to '${tabId}'`);
    }

    // --- PEER & SPOOL ACTIONS ---
    async function resetPeerCircuit(peerName) {
      if (!confirm(`Reset circuit breaker for peer '${peerName}' to CLOSED?`)) return;
      try {
        const res = await fetch(`/api/v1/peers/${encodeURIComponent(peerName)}/reset`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          alert(`✅ ${data.message || 'Circuit reset successfully'}`);
          logToConsole('ack', 'PEER', `Reset circuit breaker for peer ${peerName}`);
        } else {
          alert(`❌ ${data.message || 'Failed to reset circuit'}`);
          logToConsole('error', 'PEER', `Failed to reset peer ${peerName}: ${data.message}`);
        }
      } catch (err) {
        alert(`❌ Error connecting to server: ${err}`);
      }
    }

    async function purgeSpool() {
      if (!confirm("Are you sure you want to PURGE all spooled packets from the persistent database?")) return;
      try {
        const res = await fetch('/api/v1/spool/purge', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          alert(`✅ ${data.message || 'Spool purged successfully'}`);
          document.getElementById('stat-spool-count').innerText = '0';
          logToConsole('warn', 'STORAGE', 'Persistent spool purged by operator');
        } else {
          alert(`❌ ${data.message || 'Failed to purge spool'}`);
        }
      } catch (err) {
        alert(`❌ Error connecting to server: ${err}`);
      }
    }

    // --- TEST MODAL & ALERT DISPATCH ---
    function openTestModal() {
      document.getElementById('test-modal').classList.add('active');
    }
    function closeTestModal() {
      document.getElementById('test-modal').classList.remove('active');
    }

    async function sendTestAlert() {
      const summary = document.getElementById('alert-summary').value;
      const severity = document.getElementById('alert-severity').value;
      const dest = document.getElementById('alert-dest').value;

      const payload = {
        alert_id: "test-" + Date.now().toString(16),
        severity: severity,
        summary: summary,
        source: "rest",
        destinations: [dest]
      };

      try {
        const res = await fetch('/api/v1/alerts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          addEventToFeed(payload);
          closeTestModal();
          logToConsole(severity === 'critical' || severity === 'emergency' ? 'error' : 'info', 'DISPATCH', `Dispatched alert [ID: ${payload.alert_id}] (${severity}): ${summary}`);
          if (severity === 'critical' || severity === 'emergency') {
            showIncidentBanner(payload);
          }
        } else {
          alert('Failed to dispatch alert: ' + res.statusText);
        }
      } catch (err) {
        alert('Error dispatching alert: ' + err);
      }
    }

    function addEventToFeed(alert) {
      const feed = document.getElementById('event-feed');
      if (!feed) return;
      const card = document.createElement('div');
      card.className = 'event-card';
      const sevClass = alert.severity === 'emergency' ? 'danger' : alert.severity === 'critical' ? 'danger' : alert.severity === 'warning' ? 'warning' : 'primary';
      card.innerHTML = `
        <div class="event-header">
          <span class="badge badge-${sevClass}">${alert.severity.toUpperCase()}</span>
          <span class="ts" style="color: var(--text-muted); font-size: 0.7rem;">${new Date().toLocaleTimeString()}</span>
        </div>
        <div class="event-summary">${escapeHtml(alert.summary)}</div>
        <div class="event-meta">
          <span>Target: [${(alert.destinations || []).join(', ')}]</span>
          <span>ID: ${alert.alert_id}</span>
        </div>
      `;
      feed.prepend(card);
    }

    function updateDashboard(data) {
      if (!data) return;
      if (data.status) {
        document.getElementById('stat-status').innerText = data.status.toUpperCase();
      }
      if (data.node_name) {
        document.getElementById('node-title').innerText = data.node_name;
      }
      if (data.uptime_seconds !== undefined) {
        const h = Math.floor(data.uptime_seconds / 3600);
        const m = Math.floor((data.uptime_seconds % 3600) / 60);
        const s = data.uptime_seconds % 60;
        document.getElementById('stat-uptime').innerText = `${h}h ${m}m ${s}s`;
      }
      if (data.spool !== undefined) {
        document.getElementById('stat-spool-count').innerText = data.spool;
      }
      if (data.peers) {
        document.getElementById('stat-peers-count').innerText = data.peers.length;
        renderPeers(data.peers);
      }
      if (data.routes) {
        renderRoutes(data.routes);
      }
      if (data.nostr_relays) {
        renderNostr(data.nostr_relays);
      }
      if (data.sms) {
        renderSmsStatus(data.sms);
      }
      if (data.bitchat) {
        renderBitChat(data.bitchat);
      }
    }

    // --- TELEMETRY RENDERERS ---
    function renderPeers(peers) {
      const obody = document.querySelector('#overview-peers-table tbody');
      const fbody = document.querySelector('#full-peers-table tbody');

      if (!peers || peers.length === 0) {
        if (obody) obody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No peer nodes configured</td></tr>`;
        if (fbody) fbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No peer nodes configured</td></tr>`;
        return;
      }

      const rows = peers.map(p => {
        const stateClass = p.circuit_state === 'Closed' ? 'success' : p.circuit_state === 'HalfOpen' ? 'warning' : 'danger';
        return `
          <tr>
            <td><strong>${p.name}</strong></td>
            <td><span class="badge badge-cyan">${p.link_type}</span></td>
            <td><span class="badge badge-${stateClass}">${p.circuit_state}</span></td>
            <td>${p.consecutive_failures || 0}</td>
            <td>${p.spooled_count || 0} msgs</td>
            <td><button class="btn" style="font-size: 0.65rem; padding: 0.15rem 0.5rem; background: rgba(99,102,241,0.2); border: 1px solid rgba(99,102,241,0.4); color: #a5b4fc; cursor: pointer;" onclick="resetPeerCircuit('${p.name}')">Reset</button></td>
          </tr>
        `;
      }).join('');

      if (obody) obody.innerHTML = rows;

      const fullRows = peers.map(p => {
        const stateClass = p.circuit_state === 'Closed' ? 'success' : p.circuit_state === 'HalfOpen' ? 'warning' : 'danger';
        return `
          <tr>
            <td><strong>${p.name}</strong></td>
            <td><code>${p.addr || 'serial'}</code></td>
            <td><span class="badge badge-cyan">${p.link_type}</span></td>
            <td><span class="badge badge-${stateClass}">${p.circuit_state}</span></td>
            <td>${p.consecutive_failures || 0}</td>
            <td>${p.spooled_count || 0}</td>
            <td><button class="btn" style="font-size: 0.65rem; padding: 0.15rem 0.5rem; background: rgba(99,102,241,0.2); border: 1px solid rgba(99,102,241,0.4); color: #a5b4fc; cursor: pointer;" onclick="resetPeerCircuit('${p.name}')">Reset</button></td>
          </tr>
        `;
      }).join('');
      if (fbody) fbody.innerHTML = fullRows;
    }

    function renderRoutes(routes) {
      const tbody = document.querySelector('#routes-table tbody');
      if (!tbody) return;
      if (!routes || routes.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No remote mesh routes discovered</td></tr>`;
        return;
      }
      tbody.innerHTML = routes.map(r => `
        <tr>
          <td><strong>${r.destination}</strong></td>
          <td><code>${r.next_hop}</code></td>
          <td><span class="badge badge-primary">${r.metric}</span></td>
          <td>${r.hops}</td>
          <td><span class="badge badge-cyan">${r.metric < 200 ? 'Fast LAN/VPN' : 'Sub-GHz LoRa'}</span></td>
        </tr>
      `).join('');
    }

    function renderNostr(relays) {
      const tbody = document.querySelector('#nostr-table tbody');
      if (!tbody) return;
      if (!relays || relays.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">No Nostr relays active</td></tr>`;
        return;
      }
      tbody.innerHTML = relays.map(r => {
        const pct = Math.round((r.score || 1.0) * 100);
        const scoreClass = pct > 80 ? 'success' : pct > 50 ? 'warning' : 'danger';
        return `
          <tr>
            <td><code>${r.url}</code></td>
            <td><span class="badge badge-${scoreClass}">${pct}%</span></td>
            <td>${r.successes || 0} / ${r.failures || 0}</td>
            <td>${r.last_latency_ms ? r.last_latency_ms + ' ms' : '--'}</td>
            <td><span class="badge badge-${scoreClass}">${pct > 50 ? 'Healthy' : 'Degraded'}</span></td>
          </tr>
        `;
      }).join('');
    }

    // --- BITCHAT BLE MESH ---
    function copySenderId() {
      const code = document.getElementById('bitchat-tab-senderid').innerText.trim();
      if (!code || code === '--') return;
      navigator.clipboard.writeText(code).then(() => {
        alert('Copied BitChat Sender ID: ' + code);
      });
    }

    async function loadBitChatStatus() {
      try {
        const res = await fetch('/api/v1/bitchat/status');
        if (!res.ok) return;
        const data = await res.json();
        renderBitChat(data);
      } catch (err) {
        console.error('Error fetching BitChat status', err);
      }
    }

    async function sendBitChatBroadcast() {
      const msg = document.getElementById('bitchat-broadcast-msg').value.trim();
      const sev = document.getElementById('bitchat-broadcast-sev').value;
      const fb = document.getElementById('bitchat-broadcast-feedback');
      if (!msg) {
        alert('Please enter a message to broadcast across the BitChat mesh');
        return;
      }
      if (fb) fb.innerText = 'Transmitting across Bluetooth mesh...';
      try {
        const res = await fetch('/api/v1/bitchat/broadcast', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: msg, severity: sev })
        });
        const data = await res.json();
        if (res.ok) {
          if (fb) fb.innerText = '✅ Broadcast dispatched!';
          document.getElementById('bitchat-broadcast-msg').value = '';
          logToConsole('info', 'BITCHAT', `Broadcast dispatched to BLE mesh (${sev}): ${msg}`);
          setTimeout(() => { if (fb) fb.innerText = ''; }, 4000);
        } else {
          if (fb) fb.innerText = '❌ Failed: ' + (data.message || res.statusText);
        }
      } catch (err) {
        if (fb) fb.innerText = '❌ Error: ' + err;
      }
    }

    function renderBitChat(bc) {
      if (!bc) return;

      const pCount = (bc.peers || []).length;
      const countEl = document.getElementById('stat-bitchat-peers-count');
      if (countEl) countEl.innerText = pCount;
      const badgeEl = document.getElementById('stat-bitchat-badge');
      if (badgeEl) {
        badgeEl.innerText = !bc.enabled ? 'Disabled' : (bc.status || 'Active (BLE GATT)');
      }

      const ovNode = document.getElementById('overview-bitchat-nodename');
      if (ovNode) ovNode.innerText = bc.node_name || 'OpenAlert-Mesh';
      const ovId = document.getElementById('overview-bitchat-senderid');
      if (ovId) ovId.innerText = bc.sender_id || '--';
      const ovUuid = document.getElementById('overview-bitchat-uuid');
      if (ovUuid && bc.service_uuid) ovUuid.innerText = bc.service_uuid;
      const ovStatus = document.getElementById('overview-bitchat-status');
      if (ovStatus) ovStatus.innerText = !bc.enabled ? 'Disabled' : (bc.status || 'Active (BLE GATT)');

      const ovPeerBadge = document.getElementById('overview-bitchat-peer-count-badge');
      if (ovPeerBadge) ovPeerBadge.innerText = `${pCount} Discovered`;

      const ovPeerList = document.getElementById('overview-bitchat-peers-list');
      if (ovPeerList) {
        if (!bc.peers || bc.peers.length === 0) {
          ovPeerList.innerHTML = '<span style="color: var(--text-muted); font-size: 0.8rem; font-style: italic;">Listening for BitChat BLE broadcast announcements...</span>';
        } else {
          ovPeerList.innerHTML = bc.peers.map(p => {
            const isEst = p.session_state && p.session_state.includes('Established');
            const dotCol = isEst ? '#10b981' : '#38bdf8';
            return `
              <div class="bitchat-peer-chip" onclick="switchTab('bitchat')" title="Sender ID: ${p.sender_id}">
                <span style="width: 8px; height: 8px; border-radius: 50%; background: ${dotCol}; box-shadow: 0 0 6px ${dotCol};"></span>
                <strong>${escapeHtml(p.nickname || 'Peer')}</strong>
                <span style="color: var(--text-muted); font-family: monospace; font-size: 0.7rem;">${p.sender_id.slice(0, 6)}...</span>
                <span style="font-size: 0.68rem; color: #38bdf8;">${isEst ? '🔒 E2EE' : '📡 Discovered'}</span>
              </div>
            `;
          }).join('');
        }
      }

      const tabNode = document.getElementById('bitchat-tab-nodename');
      if (tabNode) tabNode.value = bc.node_name || 'OpenAlert-Mesh';
      const tabId = document.getElementById('bitchat-tab-senderid');
      if (tabId) tabId.innerText = bc.sender_id || '--';
      const tabUuid = document.getElementById('bitchat-tab-uuid');
      if (tabUuid && bc.service_uuid) tabUuid.innerText = bc.service_uuid;
      const tabStatus = document.getElementById('bitchat-tab-status');
      if (tabStatus) tabStatus.innerText = !bc.enabled ? 'Disabled' : (bc.status || 'Active');
      const tabCount = document.getElementById('tab-radar-peer-count');
      if (tabCount) tabCount.innerText = `${pCount} Peers Online`;

      const tbody = document.querySelector('#bitchat-peers-table tbody');
      if (tbody) {
        if (!bc.peers || bc.peers.length === 0) {
          tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No active BitChat peers detected in BLE range</td></tr>';
        } else {
          tbody.innerHTML = bc.peers.map(p => {
            const isEst = p.session_state && p.session_state.includes('Established');
            const stBadge = isEst ? 'badge-success' : 'badge-primary';
            const verBadge = p.verified ? '<span class="badge badge-success" style="font-size: 0.65rem;">✅ Valid Ed25519</span>' : '<span class="badge badge-warning" style="font-size: 0.65rem;">⚠️ Unverified</span>';
            const timeStr = p.last_seen_seconds_ago < 5 ? 'Just now' : `${p.last_seen_seconds_ago}s ago`;
            return `
              <tr>
                <td><strong>${escapeHtml(p.nickname || 'Peer')}</strong></td>
                <td><code style="color: #38bdf8;">${p.sender_id}</code></td>
                <td><span class="badge ${stBadge}" style="font-size: 0.68rem;">${p.session_state}</span></td>
                <td>${verBadge}</td>
                <td style="font-size: 0.75rem;">RX: ${p.messages_received || 0} | TX: ${p.messages_sent || 0}</td>
                <td style="font-size: 0.75rem; color: var(--text-muted);">${timeStr}</td>
                <td>
                  <button class="btn" style="font-size: 0.65rem; padding: 0.15rem 0.5rem; background: rgba(56,189,248,0.2); border: 1px solid rgba(56,189,248,0.4); color: #38bdf8; cursor: pointer;" onclick="document.getElementById('bitchat-broadcast-msg').value = 'Direct notification to ${p.nickname}: '; switchTab('bitchat');">Alert</button>
                </td>
              </tr>
            `;
          }).join('');
        }
      }

      drawRadarPeers('overview-radar-peers', bc.peers || [], 130, 130, 100);
      drawRadarPeers('tab-radar-peers', bc.peers || [], 150, 150, 120);
    }

    function drawRadarPeers(groupId, peers, cx, cy, maxR) {
      const g = document.getElementById(groupId);
      if (!g) return;

      if (!peers || peers.length === 0) {
        g.innerHTML = '';
        return;
      }

      let html = '';
      peers.forEach((p, idx) => {
        const count = peers.length;
        const angle = (idx / count) * (2 * Math.PI) + 0.6;
        const dist = 45 + (idx % 3) * 28;
        const px = cx + dist * Math.cos(angle);
        const py = cy + dist * Math.sin(angle);
        const isEst = p.session_state && p.session_state.includes('Established');
        const fillCol = isEst ? '#10b981' : '#38bdf8';

        html += `<line x1="${cx}" y1="${cy}" x2="${px}" y2="${py}" stroke="${fillCol}" stroke-width="1.2" stroke-dasharray="2,2" stroke-opacity="0.6"/>`;
        html += `<circle cx="${px}" cy="${py}" r="7" fill="${fillCol}" stroke="#fff" stroke-width="1.5" style="filter: drop-shadow(0 0 4px ${fillCol}); cursor: pointer;" onclick="switchTab('bitchat')"/>`;
        html += `<text x="${px}" y="${py - 10}" fill="var(--text-heading)" font-size="10" font-weight="600" text-anchor="middle" font-family="sans-serif">${escapeHtml(p.nickname || 'Peer')}</text>`;
      });
      g.innerHTML = html;
    }

    // --- CELLULAR SMS ---
    function renderSmsStatus(data) {
      if (!data) return;
      const badge = document.getElementById('sms-status-badge');
      if (badge) {
        let isConnected = data.modem_status && (data.modem_status.includes('Registered') || data.modem_status.includes('Connected') || data.modem_status.includes('Responsive'));
        badge.className = !data.enabled ? 'badge badge-warning' : (isConnected ? 'badge badge-success' : 'badge badge-danger');
        badge.innerText = !data.enabled ? 'Disabled' : data.modem_status;
      }
      const enabledText = document.getElementById('sms-enabled-text');
      if (enabledText) enabledText.innerText = data.enabled ? 'Active / Enabled' : 'Disabled';
      const portText = document.getElementById('sms-port-text');
      if (portText) portText.innerText = data.port || '--';
      const baudText = document.getElementById('sms-baud-text');
      if (baudText) baudText.innerText = data.baud_rate ? data.baud_rate + ' bps' : '--';
      const pollText = document.getElementById('sms-poll-text');
      if (pollText) pollText.innerText = data.poll_interval_seconds ? data.poll_interval_seconds + 's' : '--';
      const ttlText = document.getElementById('sms-ttl-text');
      if (ttlText) ttlText.innerText = data.ttl_minutes === 0 ? 'Never Deleted (0)' : (data.ttl_minutes + ' min');

      const errBox = document.getElementById('sms-error-box');
      if (errBox) {
        if (data.last_error) {
          errBox.style.display = 'block';
          errBox.innerText = '⚠️ Modem Notice: ' + data.last_error;
        } else {
          errBox.style.display = 'none';
        }
      }

      const recInput = document.getElementById('sms-recipients-input');
      if (recInput && document.activeElement !== recInput) {
        recInput.value = (data.recipients || []).join('\n');
      }
      const sendersInput = document.getElementById('sms-senders-input');
      if (sendersInput && document.activeElement !== sendersInput) {
        sendersInput.value = (data.authorized_senders || []).join('\n');
      }
    }

    async function loadSmsStatus() {
      try {
        const res = await fetch('/api/v1/sms/status');
        if (!res.ok) return;
        const data = await res.json();
        renderSmsStatus(data);
      } catch (err) {
        console.error('Error fetching SMS status', err);
      }
    }

    async function saveSmsConfig() {
      const recRaw = document.getElementById('sms-recipients-input').value;
      const sendRaw = document.getElementById('sms-senders-input').value;
      const recipients = recRaw.split(/[\n,]+/).map(s => s.trim()).filter(s => s.length > 0);
      const authorized_senders = sendRaw.split(/[\n,]+/).map(s => s.trim()).filter(s => s.length > 0);

      try {
        const res = await fetch('/api/v1/sms/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recipients, authorized_senders })
        });
        const data = await res.json();
        if (res.ok) {
          alert('✅ SMS configuration saved and hot-reloaded successfully!');
          renderSmsStatus(data);
          logToConsole('ack', 'SMS', `Updated SMS configuration: ${recipients.length} recipients, ${authorized_senders.length} senders`);
        } else {
          alert('❌ Failed to save SMS configuration: ' + (data.message || res.statusText));
        }
      } catch (err) {
        alert('❌ Error saving SMS configuration: ' + err);
      }
    }

    async function sendManualSms() {
      const phone = document.getElementById('sms-manual-phone').value.trim();
      const message = document.getElementById('sms-manual-msg').value.trim();
      if (!phone || !message) {
        alert('Please specify recipient phone and message text');
        return;
      }

      try {
        const res = await fetch('/api/v1/sms/send', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ phone_number: phone, message: message })
        });
        const data = await res.json();
        if (res.ok) {
          alert('✅ ' + data.message);
          loadSmsHistory();
          logToConsole('info', 'SMS', `Sent manual SMS to ${phone}: ${message}`);
        } else {
          alert('❌ ' + (data.message || 'SMS send failed'));
        }
      } catch (err) {
        alert('❌ Error dispatching SMS: ' + err);
      }
    }

    async function loadSmsHistory() {
      try {
        const res = await fetch('/api/v1/sms/history');
        if (!res.ok) return;
        const list = await res.json();
        const tbody = document.querySelector('#sms-history-table tbody');
        if (!tbody) return;

        if (!list || list.length === 0) {
          tbody.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted);">No SMS history recorded</td></tr>';
          return;
        }

        tbody.innerHTML = list.map(item => {
          const dirIcon = item.direction === 'inbound' ? '📥 IN' : '📤 OUT';
          const dirClass = item.direction === 'inbound' ? 'badge-cyan' : 'badge-primary';
          const stClass = item.status === 'sent' || item.status === 'received' ? 'badge-success' : 'badge-danger';
          const dateStr = new Date(item.created_at * 1000).toLocaleTimeString();
          return `
            <tr>
              <td><span class="badge ${dirClass}" style="font-size: 0.65rem;">${dirIcon}</span></td>
              <td><code>${item.phone_number}</code><div style="font-size: 0.65rem; color: var(--text-muted);">${dateStr}</div></td>
              <td style="font-size: 0.8rem; word-break: break-word;">${escapeHtml(item.message)}</td>
              <td><span class="badge ${stClass}" style="font-size: 0.65rem;">${item.status}</span></td>
            </tr>
          `;
        }).join('');
      } catch (err) {
        console.error('Error fetching SMS history', err);
      }
    }

    // --- OPERATIONAL TOOLS ---
    function copyText(elementId) {
      const el = document.getElementById(elementId);
      if (!el) return;
      const val = el.value || el.innerText || '';
      if (!val) return;
      navigator.clipboard.writeText(val).then(() => {
        alert('Copied to clipboard: ' + (val.length > 32 ? val.substring(0, 32) + '...' : val));
      }).catch(() => prompt('Copy to clipboard (Ctrl+C):', val));
    }

    async function generateNostrKeypair() {
      try {
        const res = await fetch('/api/v1/tools/generate-keypair', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          document.getElementById('tool-gen-npub').value = data.npub;
          document.getElementById('tool-gen-pubhex').value = data.pub_hex;
          document.getElementById('tool-gen-nsec').value = data.nsec;
          document.getElementById('tool-gen-privhex').value = data.priv_hex;
          logToConsole('info', 'TOOLS', `Generated Secp256k1 keypair [${data.npub.slice(0, 16)}...]`);
        } else {
          alert('Failed to generate keypair: ' + (data.message || res.statusText));
        }
      } catch (err) {
        alert('Error generating keypair: ' + err);
      }
    }

    async function convertNostrKey() {
      const input = document.getElementById('tool-conv-input').value.trim();
      if (!input) {
        alert('Please enter an npub, nsec, or hex key to convert');
        return;
      }
      try {
        const res = await fetch('/api/v1/tools/convert-key', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: input })
        });
        const data = await res.json();
        const box = document.getElementById('tool-conv-result');
        if (res.ok) {
          box.style.display = 'block';
          document.getElementById('tool-conv-format').innerText = data.input_format;
          document.getElementById('tool-conv-hex').innerText = data.hex_value;
          document.getElementById('tool-conv-bech32').innerText = data.bech32_value;

          const derLabel = document.getElementById('tool-conv-derived-label');
          const derBox = document.getElementById('tool-conv-derived-box');
          if (data.derived_public) {
            derLabel.style.display = 'block';
            derBox.style.display = 'block';
            document.getElementById('tool-conv-derived-hex').innerText = data.derived_public.hex;
            document.getElementById('tool-conv-derived-npub').innerText = data.derived_public.npub;
          } else {
            derLabel.style.display = 'none';
            derBox.style.display = 'none';
          }
          logToConsole('info', 'TOOLS', `Converted ${data.input_format} key successfully`);
        } else {
          box.style.display = 'none';
          alert('Conversion failed: ' + (data.message || res.statusText));
        }
      } catch (err) {
        alert('Error converting key: ' + err);
      }
    }

    async function convertSmsCodec() {
      const payload = document.getElementById('tool-sms-input').value.trim();
      if (!payload) {
        alert('Please enter text or hex string to convert');
        return;
      }
      try {
        const res = await fetch('/api/v1/tools/convert-sms', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ payload })
        });
        const data = await res.json();
        if (res.ok) {
          const badge = document.getElementById('tool-sms-op-badge');
          badge.style.display = 'inline-block';
          badge.innerText = data.operation;
          document.getElementById('tool-sms-output').value = data.result;
          logToConsole('info', 'TOOLS', `Executed SMS codec operation: ${data.operation}`);
        } else {
          alert('SMS codec error: ' + (data.message || res.statusText));
        }
      } catch (err) {
        alert('Error in SMS codec: ' + err);
      }
    }

    async function hashPassword() {
      const pwd = document.getElementById('tool-pwd-input').value;
      if (!pwd) {
        alert('Please enter a password');
        return;
      }
      try {
        const res = await fetch('/api/v1/tools/hash-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: pwd })
        });
        const data = await res.json();
        if (res.ok) {
          document.getElementById('tool-pwd-output').value = data.hash;
          logToConsole('info', 'TOOLS', 'Computed SHA-256 dashboard password hash');
        } else {
          alert('Password hashing failed: ' + (data.message || res.statusText));
        }
      } catch (err) {
        alert('Error hashing password: ' + err);
      }
    }

    async function generateCryptoKey() {
      try {
        const res = await fetch('/api/v1/tools/generate-key', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          document.getElementById('tool-psk-output').value = data.key;
          logToConsole('info', 'TOOLS', 'Generated 256-bit OsRng cryptographic pre-shared key');
        } else {
          alert('Failed to generate key: ' + (data.message || res.statusText));
        }
      } catch (err) {
        alert('Error generating key: ' + err);
      }
    }

    // --- CONFIGURATION & ACL MANAGEMENT ---
    let currentConfigObj = null;

    async function loadConfigFile() {
      try {
        const res = await fetch('/api/v1/config');
        if (!res.ok) {
          console.error('Failed to load config', res.statusText);
          return;
        }
        const data = await res.json();
        currentConfigObj = data.config;

        const pathEl = document.getElementById('config-file-path-badge');
        if (pathEl) pathEl.innerText = data.config_path;

        const editor = document.getElementById('config-toml-editor');
        if (editor) editor.value = data.toml_content;

        renderNostrAclLists(data.config);
        renderSmsAclFields(data.config);
        logToConsole('info', 'CONFIG', `Loaded configuration from ${data.config_path}`);
      } catch (err) {
        console.error('Error fetching config file', err);
      }
    }

    function renderNostrAclLists(cfg) {
      if (!cfg || !cfg.nostr || !cfg.nostr.oxchat) return;

      const ops = cfg.nostr.oxchat.c2_authorized_operators || [];
      const recs = cfg.nostr.oxchat.recipients || [];

      const opsList = document.getElementById('config-oxchat-ops-list');
      if (opsList) {
        if (ops.length === 0) {
          opsList.innerHTML = '<span style="color: var(--text-muted); font-size: 0.75rem; font-style: italic;">No operators configured</span>';
        } else {
          opsList.innerHTML = ops.map((op, idx) => `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.35rem 0.5rem; background: rgba(255,255,255,0.03); border: 1px solid var(--card-border); border-radius: 4px; font-size: 0.75rem;">
              <code style="color: #38bdf8;">${op}</code>
              <button class="btn" style="font-size: 0.65rem; padding: 0.1rem 0.4rem; background: rgba(244,63,94,0.15); color: #fda4af;" onclick="removeNostrOperator(${idx})">&times; Remove</button>
            </div>
          `).join('');
        }
      }

      const recsList = document.getElementById('config-oxchat-recipients-list');
      if (recsList) {
        if (recs.length === 0) {
          recsList.innerHTML = '<span style="color: var(--text-muted); font-size: 0.75rem; font-style: italic;">No recipients configured</span>';
        } else {
          recsList.innerHTML = recs.map((r, idx) => `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.35rem 0.5rem; background: rgba(255,255,255,0.03); border: 1px solid var(--card-border); border-radius: 4px; font-size: 0.75rem;">
              <code style="color: var(--cyan);">${r}</code>
              <button class="btn" style="font-size: 0.65rem; padding: 0.1rem 0.4rem; background: rgba(244,63,94,0.15); color: #fda4af;" onclick="removeNostrRecipient(${idx})">&times; Remove</button>
            </div>
          `).join('');
        }
      }
    }

    function renderSmsAclFields(cfg) {
      if (!cfg || !cfg.sms) return;
      const recText = document.getElementById('config-sms-recipients-text');
      if (recText) recText.value = (cfg.sms.recipients || []).join('\n');
      const sendText = document.getElementById('config-sms-senders-text');
      if (sendText) sendText.value = (cfg.sms.authorized_senders || []).join('\n');
    }

    async function addNostrOperator() {
      const input = document.getElementById('config-oxchat-new-op');
      let val = input.value.trim();
      if (!val) return;

      if (val.startsWith('npub1')) {
        try {
          const cRes = await fetch('/api/v1/tools/convert-key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key: val })
          });
          const cData = await cRes.json();
          if (cRes.ok && cData.hex_value) {
            val = cData.hex_value;
          } else {
            alert('Invalid npub key: ' + (cData.message || 'conversion failed'));
            return;
          }
        } catch (err) {
          alert('Error resolving npub: ' + err);
          return;
        }
      }

      if (val.length !== 64) {
        alert('Operator public key must be a 64-character hex string or valid npub1...');
        return;
      }

      if (!currentConfigObj) currentConfigObj = { nostr: { oxchat: { c2_authorized_operators: [], recipients: [] } } };
      if (!currentConfigObj.nostr) currentConfigObj.nostr = {};
      if (!currentConfigObj.nostr.oxchat) currentConfigObj.nostr.oxchat = { c2_authorized_operators: [], recipients: [] };

      const ops = currentConfigObj.nostr.oxchat.c2_authorized_operators || [];
      const recs = currentConfigObj.nostr.oxchat.recipients || [];

      if (!ops.includes(val)) ops.push(val);
      if (!recs.includes(val)) recs.push(val);

      currentConfigObj.nostr.oxchat.c2_authorized_operators = ops;
      currentConfigObj.nostr.oxchat.recipients = recs;

      input.value = '';
      renderNostrAclLists(currentConfigObj);
    }

    function removeNostrOperator(idx) {
      if (!currentConfigObj || !currentConfigObj.nostr || !currentConfigObj.nostr.oxchat) return;
      currentConfigObj.nostr.oxchat.c2_authorized_operators.splice(idx, 1);
      renderNostrAclLists(currentConfigObj);
    }

    function removeNostrRecipient(idx) {
      if (!currentConfigObj || !currentConfigObj.nostr || !currentConfigObj.nostr.oxchat) return;
      currentConfigObj.nostr.oxchat.recipients.splice(idx, 1);
      renderNostrAclLists(currentConfigObj);
    }

    async function saveNostrAcl() {
      if (!currentConfigObj || !currentConfigObj.nostr || !currentConfigObj.nostr.oxchat) return;
      const ops = currentConfigObj.nostr.oxchat.c2_authorized_operators || [];
      const recs = currentConfigObj.nostr.oxchat.recipients || [];

      try {
        const res = await fetch('/api/v1/nostr/oxchat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            recipients: recs,
            c2_authorized_operators: ops
          })
        });
        const data = await res.json();
        if (res.ok) {
          alert('✅ Nostr 0xChat Access Control list updated and saved to config file!');
          loadConfigFile();
          logToConsole('ack', 'NOSTR', `Updated Nostr 0xChat ACL: ${ops.length} operators, ${recs.length} recipients`);
        } else {
          alert('❌ Failed to update Nostr ACL: ' + (data.message || res.statusText));
        }
      } catch (err) {
        alert('❌ Error saving Nostr ACL: ' + err);
      }
    }

    async function saveSmsAclFromConfigTab() {
      const recRaw = document.getElementById('config-sms-recipients-text').value;
      const sendRaw = document.getElementById('config-sms-senders-text').value;
      const recipients = recRaw.split(/[\n,]+/).map(s => s.trim()).filter(s => s.length > 0);
      const authorized_senders = sendRaw.split(/[\n,]+/).map(s => s.trim()).filter(s => s.length > 0);

      try {
        const res = await fetch('/api/v1/sms/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ recipients, authorized_senders })
        });
        const data = await res.json();
        if (res.ok) {
          alert('✅ Cellular SMS ACL saved and hot-reloaded successfully!');
          renderSmsStatus(data);
          logToConsole('ack', 'SMS', `Updated SMS ACL: ${recipients.length} recipients, ${authorized_senders.length} senders`);
        } else {
          alert('❌ Failed to save SMS ACL: ' + (data.message || res.statusText));
        }
      } catch (err) {
        alert('❌ Error saving SMS ACL: ' + err);
      }
    }

    async function validateTomlConfig() {
      const editor = document.getElementById('config-toml-editor');
      const banner = document.getElementById('config-validation-banner');
      const tomlContent = editor.value;

      try {
        const res = await fetch('/api/v1/config/validate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ toml_content: tomlContent })
        });
        const data = await res.json();
        banner.style.display = 'block';
        if (res.ok) {
          banner.style.background = 'rgba(16, 185, 129, 0.15)';
          banner.style.border = '1px solid var(--success)';
          banner.style.color = '#34d399';
          banner.innerText = '✅ ' + data.message + ` (Node: ${data.node_name}, Relays: ${data.relays_count}, 0xChat: ${data.oxchat_recipients_count}, SMS: ${data.sms_recipients_count})`;
          logToConsole('info', 'CONFIG', 'Configuration syntax validation passed');
        } else {
          banner.style.background = 'rgba(244, 63, 94, 0.15)';
          banner.style.border = '1px solid var(--danger)';
          banner.style.color = '#fda4af';
          banner.innerText = '❌ ' + (data.message || 'Validation error');
          logToConsole('error', 'CONFIG', `Validation error: ${data.message}`);
        }
      } catch (err) {
        banner.style.display = 'block';
        banner.style.background = 'rgba(244, 63, 94, 0.15)';
        banner.style.border = '1px solid var(--danger)';
        banner.style.color = '#fda4af';
        banner.innerText = '❌ Validation request failed: ' + err;
      }
    }

    async function saveTomlConfig() {
      const editor = document.getElementById('config-toml-editor');
      const banner = document.getElementById('config-validation-banner');
      const tomlContent = editor.value;

      if (!confirm('Save this configuration? A timestamped .bak copy will be automatically created on disk.')) {
        return;
      }

      try {
        const res = await fetch('/api/v1/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ toml_content: tomlContent, reload: true })
        });
        const data = await res.json();
        banner.style.display = 'block';
        if (res.ok) {
          banner.style.background = 'rgba(16, 185, 129, 0.15)';
          banner.style.border = '1px solid var(--success)';
          banner.style.color = '#34d399';
          banner.innerText = '✅ ' + data.message;
          alert('✅ ' + data.message);
          loadConfigFile();
          logToConsole('ack', 'CONFIG', 'Configuration written and backed up successfully');
        } else {
          banner.style.background = 'rgba(244, 63, 94, 0.15)';
          banner.style.border = '1px solid var(--danger)';
          banner.style.color = '#fda4af';
          banner.innerText = '❌ ' + (data.message || 'Save error');
          alert('❌ Save failed: ' + (data.message || res.statusText));
          logToConsole('error', 'CONFIG', `Save error: ${data.message}`);
        }
      } catch (err) {
        alert('❌ Error saving configuration: ' + err);
      }
    }

    // --- CONNECT SSE TELEMETRY STREAM ---
    const eventSource = new EventSource('/api/v1/events/live');
    eventSource.onmessage = function(e) {
      try {
        const data = JSON.parse(e.data);
        updateDashboard(data);
      } catch (err) {
        console.error('SSE parse error', err);
      }
    };
    eventSource.onerror = function() {
      const ind = document.getElementById('live-indicator');
      if (ind) {
        ind.className = 'badge badge-warning';
        ind.innerHTML = '<div class="pulse-dot" style="background: var(--warning)"></div><span>Reconnecting...</span>';
      }
    };
    eventSource.onopen = function() {
      const ind = document.getElementById('live-indicator');
      if (ind) {
        ind.className = 'badge badge-success';
        ind.innerHTML = '<div class="pulse-dot"></div><span>Connected (Live SSE)</span>';
      }
      logToConsole('info', 'SSE', 'Connected to real-time Server-Sent Events control plane stream');
    };
  </script>
</body>
</html>"##
}

/// HTTP handler serving the embedded dashboard.
pub async fn dashboard_handler(headers: HeaderMap, State(state): State<AppState>) -> Response {
    if let Err(resp) = crate::ingress::rest::check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }
    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/html; charset=utf-8")],
        dashboard_html(),
    )
        .into_response()
}

/// SSE handler streaming live daemon diagnostics, link states, routing tables, and spool metrics every 2s.
pub async fn sse_telemetry_handler(headers: HeaderMap, State(state): State<AppState>) -> Response {
    if let Err(resp) = crate::ingress::rest::check_dashboard_auth(&headers, state.engine.config()) {
        return *resp;
    }
    let stream = stream::unfold(state, |state| async move {
        tokio::time::sleep(Duration::from_secs(2)).await;

        let health = state.engine.get_health();
        let peering = state.engine.get_peering_diagnostics().await;
        let routes = state.engine.get_routes().await;
        let spool = state.engine.get_spool_stats().await;
        let nostr_relays = state.engine.nostr_publisher().get_relay_health().await;

        let sms_status = if let Some(sms) = state.engine.sms_service().await {
            Some(sms.get_status().await)
        } else {
            None
        };

        let bitchat_status = if let Some(bc) = state.engine.bitchat_service().await {
            Some(bc.get_status().await)
        } else {
            let (_, _, my_sender_id) = crate::bitchat::BitChatService::derive_keys(
                &state.engine.config().bitchat.node_name,
            );
            Some(crate::models::BitChatStatusReport {
                enabled: state.engine.config().bitchat.enabled,
                node_name: state.engine.config().bitchat.node_name.clone(),
                sender_id: hex::encode(my_sender_id),
                service_uuid: crate::bitchat::DEFAULT_BITCHAT_SERVICE_UUID.to_string(),
                status: if state.engine.config().bitchat.enabled {
                    "Active (BLE GATT)".to_string()
                } else {
                    "Disabled".to_string()
                },
                peers_count: 0,
                active_sessions_count: 0,
                peers: Vec::new(),
            })
        };

        let payload = serde_json::json!({
            "status": health.status,
            "version": health.version,
            "uptime_seconds": health.uptime_seconds,
            "node_name": state.engine.config().daemon.name,
            "peers": peering.map(|p| p.peers).unwrap_or_default(),
            "routes": routes,
            "spool": spool.map(|s| s.spooled).unwrap_or(0),
            "nostr_relays": nostr_relays,
            "sms": sms_status,
            "bitchat": bitchat_status,
        });

        let event = Event::default().data(payload.to_string());
        Some((Ok::<Event, Infallible>(event), state))
    });

    Sse::new(stream)
        .keep_alive(KeepAlive::default())
        .into_response()
}
