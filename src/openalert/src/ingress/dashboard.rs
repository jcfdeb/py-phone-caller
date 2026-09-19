//! # Zero-Dependency Ultra-Modern Embedded Web Dashboard
//!
//! Provides a responsive, glassmorphic Network Operations Center (NOC) control plane
//! compiled directly into the binary. Features animated SVG mesh topology packet flows,
//! live circuit breaker telemetry, distance-vector routing tables, Nostr relay quorum
//! health meters, an interactive test dispatcher, and Server-Sent Events (SSE).

use crate::ingress::rest::AppState;
use axum::{
    extract::State,
    http::{header, HeaderMap, StatusCode},
    response::{
        sse::{Event, KeepAlive, Sse},
        IntoResponse, Response,
    },
};
use futures_util::stream;
use std::convert::Infallible;
use std::time::Duration;

/// Returns the embedded HTML5/CSS3/JavaScript single-page application.
pub fn dashboard_html() -> &'static str {
    r##"<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OpenAlert Control Plane — NOC Dashboard</title>
  <style>
    :root {
      --bg: #070a13;
      --card-bg: rgba(15, 23, 42, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --border-focus: rgba(99, 102, 241, 0.5);
      --text: #e2e8f0;
      --text-muted: #94a3b8;
      --primary: #6366f1;
      --primary-glow: rgba(99, 102, 241, 0.35);
      --cyan: #06b6d4;
      --cyan-glow: rgba(6, 182, 212, 0.35);
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.3);
      --warning: #f59e0b;
      --warning-glow: rgba(245, 158, 11, 0.3);
      --danger: #f43f5e;
      --danger-glow: rgba(244, 63, 94, 0.3);
      --font: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, Helvetica, Arial, sans-serif;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      background-image: 
        radial-gradient(circle at 15% 15%, rgba(99, 102, 241, 0.08) 0%, transparent 40%),
        radial-gradient(circle at 85% 85%, rgba(6, 182, 212, 0.06) 0%, transparent 40%);
      color: var(--text);
      font-family: var(--font);
      padding: 1.5rem;
      min-height: 100vh;
      line-height: 1.5;
    }

    /* Glassmorphism containers */
    .glass-panel {
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
    }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 1rem 1.5rem;
      margin-bottom: 1.5rem;
      flex-wrap: wrap;
      gap: 1rem;
    }
    .logo-area { display: flex; align-items: center; gap: 0.75rem; }
    .logo-icon {
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, var(--primary), var(--cyan));
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 0 16px var(--primary-glow);
    }
    h1 { font-size: 1.35rem; font-weight: 700; letter-spacing: -0.02em; color: #fff; }
    .subtitle { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; }

    .header-actions { display: flex; align-items: center; gap: 0.75rem; }
    .btn {
      padding: 0.5rem 1rem;
      border-radius: 8px;
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      border: 1px solid transparent;
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
    }
    .btn-primary {
      background: var(--primary);
      color: #fff;
      box-shadow: 0 0 12px var(--primary-glow);
    }
    .btn-primary:hover {
      background: #4f46e5;
      transform: translateY(-1px);
    }

    .badge {
      font-size: 0.72rem;
      padding: 0.25rem 0.65rem;
      border-radius: 9999px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
    }
    .badge-success { background: rgba(16, 185, 129, 0.15); color: var(--success); border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-warning { background: rgba(245, 158, 11, 0.15); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge-danger { background: rgba(244, 63, 94, 0.15); color: var(--danger); border: 1px solid rgba(244, 63, 94, 0.3); }
    .badge-primary { background: rgba(99, 102, 241, 0.15); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.3); }
    .badge-cyan { background: rgba(6, 182, 212, 0.15); color: var(--cyan); border: 1px solid rgba(6, 182, 212, 0.3); }

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

    /* Hero Grid Stats */
    .grid-stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }
    .stat-card {
      padding: 1.25rem;
      position: relative;
      overflow: hidden;
    }
    .stat-title {
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      font-weight: 600;
      letter-spacing: 0.05em;
      margin-bottom: 0.4rem;
    }
    .stat-value {
      font-size: 1.75rem;
      font-weight: 700;
      color: #fff;
      display: flex;
      align-items: baseline;
      gap: 0.4rem;
    }
    .stat-meta {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 0.4rem;
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
      background: linear-gradient(90deg, transparent, var(--primary), transparent);
    }

    /* Tabs */
    .tab-bar {
      display: flex;
      gap: 0.5rem;
      border-bottom: 1px solid var(--card-border);
      margin-bottom: 1.5rem;
      padding-bottom: 0.5rem;
      overflow-x: auto;
    }
    .tab-btn {
      background: transparent;
      border: none;
      color: var(--text-muted);
      font-family: inherit;
      font-size: 0.85rem;
      font-weight: 600;
      padding: 0.5rem 1rem;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s ease;
      white-space: nowrap;
    }
    .tab-btn.active, .tab-btn:hover {
      background: rgba(255, 255, 255, 0.06);
      color: #fff;
    }
    .tab-btn.active {
      background: rgba(99, 102, 241, 0.15);
      color: #818cf8;
      border-bottom: 2px solid var(--primary);
    }

    /* Layout Columns */
    .layout-cols {
      display: grid;
      grid-template-columns: 2fr 1fr;
      gap: 1.5rem;
    }
    @media (max-width: 1024px) {
      .layout-cols { grid-template-columns: 1fr; }
    }

    .card {
      padding: 1.25rem;
      margin-bottom: 1.5rem;
    }
    .card-title {
      font-size: 1rem;
      font-weight: 600;
      color: #fff;
      margin-bottom: 1rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    /* SVG Topology Map */
    .topology-wrap {
      width: 100%;
      height: 240px;
      background: #04060b;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      position: relative;
      overflow: hidden;
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

    /* Tables */
    table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
    th, td { text-align: left; padding: 0.65rem 0.85rem; border-bottom: 1px solid var(--card-border); }
    th { color: var(--text-muted); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; }
    tr:hover { background: rgba(255, 255, 255, 0.02); }
    tr:last-child td { border-bottom: none; }

    /* Live Feed */
    .event-feed {
      max-height: 380px;
      overflow-y: auto;
      font-size: 0.8rem;
    }
    .event-card {
      padding: 0.65rem 0.75rem;
      border-bottom: 1px solid var(--card-border);
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
      transition: background 0.15s ease;
    }
    .event-card:hover { background: rgba(255, 255, 255, 0.03); }
    .event-header { display: flex; justify-content: space-between; align-items: center; }
    .event-summary { color: #f8fafc; font-weight: 500; font-size: 0.85rem; }
    .event-meta { font-size: 0.72rem; color: var(--text-muted); display: flex; gap: 0.5rem; }

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
    }
    .modal-overlay.active { display: flex; }
    .modal-box {
      width: 90%;
      max-width: 480px;
      padding: 1.5rem;
    }
    .form-group { margin-bottom: 1rem; }
    .form-group label { display: block; font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600; margin-bottom: 0.35rem; }
    .form-control {
      width: 100%;
      padding: 0.6rem 0.8rem;
      background: #0b0f19;
      border: 1px solid var(--card-border);
      border-radius: 6px;
      color: #fff;
      font-family: inherit;
      font-size: 0.85rem;
    }
    .form-control:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 8px var(--primary-glow); }
    .modal-footer { display: flex; justify-content: flex-end; gap: 0.5rem; margin-top: 1.25rem; }
  </style>
</head>
<body>

  <!-- Top Glassmorphic Navigation -->
  <header class="glass-panel">
    <div class="logo-area">
      <div class="logo-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
        </svg>
      </div>
      <div>
        <h1 id="node-title">OpenAlert Control Plane</h1>
        <div class="subtitle">Distributed Emergency Control Plane</div>
      </div>
    </div>
    <div class="header-actions">
      <div id="live-indicator" class="badge badge-success">
        <div class="pulse-dot"></div>
        <span>Connected (Live SSE)</span>
      </div>
      <button class="btn btn-primary" onclick="openTestModal()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        Dispatch Test Alert
      </button>
    </div>
  </header>

  <!-- Key Metrics Hero Bar -->
  <div class="grid-stats">
    <div class="glass-panel stat-card">
      <div class="stat-glow-bar" style="background: linear-gradient(90deg, transparent, var(--success), transparent)"></div>
      <div class="stat-title">Daemon State</div>
      <div id="stat-status" class="stat-value" style="color: var(--success);">ONLINE</div>
      <div class="stat-meta">
        <span>Uptime:</span>
        <strong id="stat-uptime" style="color: #fff;">--</strong>
      </div>
    </div>

    <div class="glass-panel stat-card">
      <div class="stat-glow-bar" style="background: linear-gradient(90deg, transparent, var(--cyan), transparent)"></div>
      <div class="stat-title">Peering Mesh</div>
      <div class="stat-value">
        <span id="stat-peers-count">0</span>
        <span style="font-size: 0.9rem; color: var(--text-muted); font-weight: 400;">active peers</span>
      </div>
      <div class="stat-meta">
        <span class="badge badge-cyan" id="stat-peers-healthy">All Healthy</span>
      </div>
    </div>

    <div class="glass-panel stat-card">
      <div class="stat-glow-bar" style="background: linear-gradient(90deg, transparent, var(--warning), transparent)"></div>
      <div class="stat-title" style="display: flex; justify-content: space-between; align-items: center;">
        <span>Persistent Spool</span>
        <button class="btn" style="font-size: 0.65rem; padding: 0.15rem 0.5rem; background: rgba(244,63,94,0.2); border: 1px solid rgba(244,63,94,0.4); color: #fda4af; cursor: pointer;" onclick="purgeSpool()">Purge</button>
      </div>
      <div class="stat-value">
        <span id="stat-spool-count">0</span>
        <span style="font-size: 0.9rem; color: var(--text-muted); font-weight: 400;">queued</span>
      </div>
      <div class="stat-meta">SQLite Flash Buffer Ready</div>
    </div>

    <div class="glass-panel stat-card">
      <div class="stat-glow-bar" style="background: linear-gradient(90deg, transparent, var(--primary), transparent)"></div>
      <div class="stat-title">LoRa Radio Duty-Cycle</div>
      <div class="stat-value">
        <span id="stat-duty-cycle">0.00%</span>
        <span style="font-size: 0.9rem; color: var(--text-muted); font-weight: 400;">/ 1.0%</span>
      </div>
      <div class="stat-meta">ETSI EN 300 220 Sub-GHz Cap</div>
    </div>
  </div>

  <!-- Navigation Tab Bar -->
  <div class="tab-bar">
    <button class="tab-btn active" onclick="switchTab('overview')">Overview & Topology</button>
    <button class="tab-btn" onclick="switchTab('peers')">Peer Links & Circuit Breakers</button>
    <button class="tab-btn" onclick="switchTab('routes')">Dynamic Distance-Vector Routes</button>
    <button class="tab-btn" onclick="switchTab('nostr')">Nostr Quorum & Relays</button>
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
              <!-- Definitions for arrows and glow effects -->
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

      <div>
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
  </div>

  <!-- Tab 2: Peers & Circuit Breakers -->
  <div id="tab-peers" class="tab-content" style="display: none;">
    <div class="glass-panel card">
      <div class="card-title">
        <span>Federated Peer Nodes & Circuit Breaker Telemetry</span>
        <span class="badge badge-cyan">Self-Healing ARQ</span>
      </div>
      <table id="full-peers-table">
        <thead>
          <tr>
            <th>Peer Identifier</th>
            <th>Socket / Device</th>
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

  <!-- Tab 3: Dynamic Distance-Vector Routes -->
  <div id="tab-routes" class="tab-content" style="display: none;">
    <div class="glass-panel card">
      <div class="card-title">
        <span>Dynamic Multi-Hop Distance-Vector Routing</span>
        <span class="badge badge-primary">Split-Horizon Enforced</span>
      </div>
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

  <!-- Tab 4: Nostr Quorum & Relays -->
  <div id="tab-nostr" class="tab-content" style="display: none;">
    <div class="glass-panel card">
      <div class="card-title">
        <span>Nostr Relays Quorum & Health</span>
        <span class="badge badge-primary">M-of-N Consensus</span>
      </div>
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

  <!-- Modal: Test Alert Dispatcher -->
  <div id="test-modal" class="modal-overlay">
    <div class="glass-panel modal-box">
      <div class="card-title">
        <span>Dispatch Test Alert</span>
        <span style="cursor: pointer; font-size: 1.2rem;" onclick="closeTestModal()">&times;</span>
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
        </select>
      </div>
      <div class="modal-footer">
        <button class="btn" style="background: rgba(255,255,255,0.1); color: #fff;" onclick="closeTestModal()">Cancel</button>
        <button class="btn btn-primary" onclick="sendTestAlert()">Dispatch Alert Now</button>
      </div>
    </div>
  </div>

  <script>
    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
      event.target.classList.add('active');
      const target = document.getElementById('tab-' + tabId);
      if (target) target.style.display = 'block';
    }

    async function resetPeerCircuit(peerName) {
      if (!confirm(`Reset circuit breaker for peer '${peerName}' to CLOSED?`)) return;
      try {
        const res = await fetch(`/api/v1/peers/${encodeURIComponent(peerName)}/reset`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
          alert(`✅ ${data.message || 'Circuit reset successfully'}`);
        } else {
          alert(`❌ ${data.message || 'Failed to reset circuit'}`);
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
        } else {
          alert(`❌ ${data.message || 'Failed to purge spool'}`);
        }
      } catch (err) {
        alert(`❌ Error connecting to server: ${err}`);
      }
    }

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
        } else {
          alert('Failed to dispatch alert: ' + res.statusText);
        }
      } catch (err) {
        alert('Error dispatching alert: ' + err);
      }
    }

    function addEventToFeed(alert) {
      const feed = document.getElementById('event-feed');
      const card = document.createElement('div');
      card.className = 'event-card';
      const sevClass = alert.severity === 'emergency' ? 'danger' : alert.severity === 'critical' ? 'danger' : alert.severity === 'warning' ? 'warning' : 'primary';
      card.innerHTML = `
        <div class="event-header">
          <span class="badge badge-${sevClass}">${alert.severity.toUpperCase()}</span>
          <span class="ts" style="color: var(--text-muted); font-size: 0.7rem;">${new Date().toLocaleTimeString()}</span>
        </div>
        <div class="event-summary">${alert.summary}</div>
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
    }

    function renderPeers(peers) {
      const obody = document.querySelector('#overview-peers-table tbody');
      const fbody = document.querySelector('#full-peers-table tbody');

      if (peers.length === 0) {
        obody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No peer nodes configured</td></tr>`;
        fbody.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">No peer nodes configured</td></tr>`;
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

      obody.innerHTML = rows;

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
      fbody.innerHTML = fullRows;
    }

    function renderRoutes(routes) {
      const tbody = document.querySelector('#routes-table tbody');
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

    // Connect to SSE stream
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
      ind.className = 'badge badge-warning';
      ind.innerHTML = '<div class="pulse-dot" style="background: var(--warning)"></div><span>Reconnecting...</span>';
    };
    eventSource.onopen = function() {
      const ind = document.getElementById('live-indicator');
      ind.className = 'badge badge-success';
      ind.innerHTML = '<div class="pulse-dot"></div><span>Connected (Live SSE)</span>';
    };
  </script>
</body>
</html>"##
}

/// HTTP handler serving the embedded dashboard.
pub async fn dashboard_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
) -> Response {
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
pub async fn sse_telemetry_handler(
    headers: HeaderMap,
    State(state): State<AppState>,
) -> Response {
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

        let payload = serde_json::json!({
            "status": health.status,
            "version": health.version,
            "uptime_seconds": health.uptime_seconds,
            "node_name": state.engine.config().daemon.name,
            "peers": peering.map(|p| p.peers).unwrap_or_default(),
            "routes": routes,
            "spool": spool.map(|s| s.spooled).unwrap_or(0),
            "nostr_relays": nostr_relays,
        });

        let event = Event::default().data(payload.to_string());
        Some((Ok::<Event, Infallible>(event), state))
    });

    Sse::new(stream).keep_alive(KeepAlive::default()).into_response()
}
