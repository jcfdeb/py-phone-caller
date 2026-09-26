# OpenAlert Configuration Guide: Multi-Layered Architecture

Development of OpenAlert is supported by a grant from the **Human Rights Foundation (HRF) Bitcoin Development Fund**.

OpenAlert (`openalertd`) features an enterprise-grade, cloud-native configuration engine implemented in Rust using the [`config`](https://docs.rs/config/latest/config/) crate and [`serde`](https://serde.rs/). 

Designed for strict parity with `py-phone-caller`'s Python [Dynaconf](https://www.dynaconf.com/) ecosystem, OpenAlert supports seamless configuration through on-disk **TOML files**, **turnkey deployment profiles**, **12-Factor App environment variables**, and **dynamic web-based hot-reloading**.

---

## 1. Layered Precedence Hierarchy

When `openalertd` launches, it resolves configuration by layering multiple tiers in order of increasing precedence. Values defined in higher layers cleanly override those in lower layers:

```
┌────────────────────────────────────────────────────────┐
│  Tier 4: Live Web UI & REST API Hot-Reloads (Runtime)  │  (Highest Priority)
├────────────────────────────────────────────────────────┤
│  Tier 3: Environment Variables (OPENALERT_<SEC>__<KEY>)│  (12-Factor App Overrides)
├────────────────────────────────────────────────────────┤
│  Tier 2: On-Disk TOML File (or Turnkey Profile)        │  (Static File Configuration)
├────────────────────────────────────────────────────────┤
│  Tier 1: Built-in Compiled Defaults                    │  (Lowest / Fallback Base)
└────────────────────────────────────────────────────────┘
```

1. **Compiled Defaults:** Sensible production defaults are built into every subsystem struct (e.g., node name `openalertd-hub`, REST port `8090`, TTLs, retries).
2. **TOML Configuration File:** If a file is supplied (default `config/openalertd.toml` or via CLI argument), values in this file overwrite compiled defaults.
3. **Environment Variables:** Any environment variable prefixed with `OPENALERT_` (or alias `OPENALERTD_`) using double underscore `__` for nested sections overrides the corresponding setting from the TOML file.
4. **Runtime In-Process API:** Operators can validate and hot-reload parameters through the authenticated Web UI Mission Control or the REST API (`/api/v1/config`).

---

## 2. Configuration Method 1: TOML Files

The standard deployment method utilizes a TOML file. By default, `openalertd` looks for `config/openalertd.toml` in the working directory:

```bash
# Launch with default config/openalertd.toml
openalertd run

# Launch with an explicit custom TOML file
openalertd run /etc/openalertd/production.toml
```

### Turnkey Deployment Profiles
Pre-tuned profiles are available in `config/profiles/` for specific field deployment topologies:

| Profile | Target Hardware / Topology | Key Characteristics |
| :--- | :--- | :--- |
| [`edge-sensor.toml`](file:///home/jcf/Workspace/PyCharm/py-phone-caller_release-github/src/openalert/config/profiles/edge-sensor.toml) | Solar/Battery Edge Nodes | Minimal footprint, RF LoRa + BLE only, REST on localhost `127.0.0.1:8091`. |
| [`mesh-repeater.toml`](file:///home/jcf/Workspace/PyCharm/py-phone-caller_release-github/src/openalert/config/profiles/mesh-repeater.toml) | Hilltop Towers / Relay Pods | Bridges RF LoRa clusters to LAN Ethernet / VPN backhaul routers. |
| [`central-gateway.toml`](file:///home/jcf/Workspace/PyCharm/py-phone-caller_release-github/src/openalert/config/profiles/central-gateway.toml) | NOC / Datacenter Servers | Web UI Mission Control, Asterisk telephony egress, Nostr quorum, WireGuard VPN. |

```bash
# Launch using a specific turnkey profile
openalertd config/profiles/central-gateway.toml
```

---

## 3. Configuration Method 2: Dynaconf-Style Environment Variables

For cloud, container, and automated CI/CD deployments, any configuration setting can be overridden using environment variables without modifying files on disk.

### Double Underscore (`__`) Section Mapping
Following the Dynaconf standard used in `py-phone-caller`:
* Prefix: `OPENALERT_` (or `OPENALERTD_`)
* Section delimiter: `__` (double underscore)
* Key name: uppercase field name
* Data types: numbers, booleans (`true`/`false`), strings, and JSON arrays are automatically parsed.

```
TOML Section & Field              Environment Variable Override
─────────────────────             ──────────────────────────────
[daemon] log_level = "info"   ──> OPENALERT_DAEMON__LOG_LEVEL=debug
[rest] listen_port = 8090     ──> OPENALERT_REST__LISTEN_PORT=9099
[rest] enable_cors = true     ──> OPENALERT_REST__ENABLE_CORS=false
[storage] path = "..."        ──> OPENALERT_STORAGE__PATH="/mnt/data/alerts.db"
[nostr] kind = 30000          ──> OPENALERT_NOSTR__KIND=30001
[bitchat] enabled = false     ──> OPENALERT_BITCHAT__ENABLED=true
[peering] enabled = false     ──> OPENALERT_PEERING__ENABLED=true
```

### Pure Container Execution (Zero Disk Files)
In ephemeral container environments, `openalertd` can operate **without any TOML file mounted**. When no file is present at `config/openalertd.toml`, the daemon cleanly initializes from compiled defaults and injects environment variables:

```bash
export OPENALERT_DAEMON__NAME="cloud-gateway-us-east-1"
export OPENALERT_REST__LISTEN_PORT="8080"
export OPENALERT_STORAGE__PATH=":memory:"
export OPENALERT_ROUTING__DEFAULT_DESTINATIONS='["nostr"]'

openalertd run
```

---

## 4. Container & Orchestration Examples

### Docker CLI
```bash
docker run -d \
  --name openalertd \
  -p 8080:8080 \
  -p 8088:8088 \
  -e OPENALERT_DAEMON__NAME="docker-hub" \
  -e OPENALERT_REST__LISTEN_PORT=8080 \
  -e OPENALERT_DAEMON__LOG_LEVEL=info \
  -e OPENALERT_STORAGE__PATH="/data/openalert.db" \
  -v openalert-data:/data \
  ghcr.io/openalert/openalertd:v0.1.0
```

### Docker Compose
```yaml
version: "3.8"

services:
  openalertd:
    image: ghcr.io/openalert/openalertd:v0.1.0
    restart: unless-stopped
    ports:
      - "8090:8090"
      - "8088:8088"
    environment:
      - OPENALERT_DAEMON__NAME=prod-gateway-01
      - OPENALERT_DAEMON__LOG_LEVEL=info
      - OPENALERT_REST__LISTEN_HOST=0.0.0.0
      - OPENALERT_REST__LISTEN_PORT=8090
      - OPENALERT_REST__ENABLE_CORS=true
      - OPENALERT_STORAGE__PATH=/var/lib/openalert/openalert.db
      - OPENALERT_STORAGE__RETENTION_DAYS=30
      - OPENALERT_DASHBOARD__AUTH__ENABLED=true
      - OPENALERT_DASHBOARD__AUTH__USERNAME=admin
      - OPENALERT_DASHBOARD__AUTH__PASSWORD_HASH=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08
    volumes:
      - openalert_storage:/var/lib/openalert

volumes:
  openalert_storage:
```

### Kubernetes Pod Manifest (ConfigMap + Secret)
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: openalertd
  namespace: monitoring
spec:
  replicas: 1
  template:
    metadata:
      labels:
        app: openalertd
    spec:
      containers:
        - name: openalertd
          image: ghcr.io/openalert/openalertd:v0.1.0
          ports:
            - containerPort: 8090
              name: rest-api
            - containerPort: 8088
              name: nostr-relay
          env:
            # Overrides from ConfigMap
            - name: OPENALERT_DAEMON__NAME
              value: "k8s-cluster-router"
            - name: OPENALERT_REST__LISTEN_PORT
              value: "8090"
            - name: OPENALERT_DAEMON__LOG_LEVEL
              value: "info"
            # Overrides from Kubernetes Secret
            - name: OPENALERT_NOSTR__PRIVATE_KEY
              valueFrom:
                secretKeyRef:
                  name: openalert-secrets
                  key: nostr-nsec
            - name: OPENALERT_REST__AUTH__PASSWORD_HASH
              valueFrom:
                secretKeyRef:
                  name: openalert-secrets
                  key: rest-ingress-hash
```

---

## 5. Configuration Method 3: Inbound & Outbound Credential Security

OpenAlert guarantees **Zero Plaintext Secrets in TOML files**:

### Inbound REST Ingress (`[rest.auth]`)
Incoming alerts and operator management APIs are guarded by SHA-256 password or token hashes. The plaintext password is never stored on disk:

```toml
[rest.auth]
type = "basic"
username = "operator"
password_hash = "sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
```
Or via environment:
```bash
export OPENALERT_REST__AUTH__TYPE="basic"
export OPENALERT_REST__AUTH__USERNAME="operator"
export OPENALERT_REST__AUTH__PASSWORD_HASH="sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
```

### Outbound Webhook Egress (`[py_phone_caller.webhooks.auth]`)
Outbound HTTP POST requests dispatched to `py-phone-caller` support dynamic `${ENV_VAR}` secret expansion:

```toml
[[py_phone_caller.webhooks]]
url = "http://127.0.0.1:9099/alerts"
priority = 0

[py_phone_caller.webhooks.auth]
type = "basic"
username = "admin"
password = "${CALLER_WEBHOOK_PASSWORD}"
```

At runtime, `openalertd` dynamically resolves `${CALLER_WEBHOOK_PASSWORD}` from the process environment, formats the HTTP `Authorization: Basic ...` header, and POSTs the alert safely.

---

## 6. Configuration Method 4: Dynamic Web UI Mission Control

For bare-metal and VM installations, operators can inspect and modify configuration through the embedded Web Dashboard at `http://<node-ip>:8090/`:

1. **Visual Editing:** Navigate to **Configuration** in the sidebar.
2. **Syntax Validation:** The editor performs automated TOML syntax and schema validation before any write takes place.
3. **Automatic Backups:** Every save generates a timestamped `.bak` copy (e.g. `openalertd.toml.20260926-212000.bak`) preventing accidental misconfigurations.
4. **Zero-Downtime Hot-Reload:** Configuration changes take effect immediately without requiring service restarts.

---

## 7. Configuration Reference Table

| TOML Parameter | Environment Variable Override | Type | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `daemon.name` | `OPENALERT_DAEMON__NAME` | String | `"openalertd-hub"` | Node identity identifier |
| `daemon.log_level` | `OPENALERT_DAEMON__LOG_LEVEL` | String | `"info"` | Tracing level (`trace`, `debug`, `info`, `warn`, `error`) |
| `daemon.logging` | `OPENALERT_DAEMON__LOGGING` | String | `"default"` | Format (`default` with timestamps or `systemd` journald mode) |
| `rest.listen_host` | `OPENALERT_REST__LISTEN_HOST` | String | `"0.0.0.0"` | Network interface to bind HTTP listeners |
| `rest.listen_port` | `OPENALERT_REST__LISTEN_PORT` | u16 | `8090` | Ingress HTTP port |
| `rest.enable_cors` | `OPENALERT_REST__ENABLE_CORS` | Bool | `true` | Cross-Origin Resource Sharing |
| `rest.webhook_secret` | `OPENALERT_REST__WEBHOOK_SECRET` | String | `None` | HMAC-SHA256 inbound signature secret |
| `storage.path` | `OPENALERT_STORAGE__PATH` | String | `"data/openalert.db"` | Path to SQLite database (`:memory:` for ephemeral RAM) |
| `storage.retention_days` | `OPENALERT_STORAGE__RETENTION_DAYS` | u32 | `30` | Sliding window alert retention |
| `routing.default_destinations` | `OPENALERT_ROUTING__DEFAULT_DESTINATIONS` | Array | `["nostr"]` | Default destinations (`nostr`, `py_phone_caller`, `bitchat`, `peering`, `sms`) |
| `routing.dedup_cache_size` | `OPENALERT_ROUTING__DEDUP_CACHE_SIZE` | usize | `1000` | Max alert signatures in LRU cache |
| `routing.dedup_ttl_seconds` | `OPENALERT_ROUTING__DEDUP_TTL_SECONDS` | u64 | `3600` | De-duplication time window |
| `nostr.kind` | `OPENALERT_NOSTR__KIND` | u64 | `30000` | Default event kind |
| `nostr.alert_ttl_seconds` | `OPENALERT_NOSTR__ALERT_TTL_SECONDS` | u64 | `3600` | NIP-40 alert expiration window |
| `nostr.relay_server.enabled` | `OPENALERT_NOSTR__RELAY_SERVER__ENABLED` | Bool | `false` | Embedded micro-relay server |
| `nostr.relay_server.bind_address`| `OPENALERT_NOSTR__RELAY_SERVER__BIND_ADDRESS` | String | `"0.0.0.0:8088"` | Embedded relay bind socket |
| `bitchat.enabled` | `OPENALERT_BITCHAT__ENABLED` | Bool | `false` | BitChat BLE mesh engine |
| `peering.enabled` | `OPENALERT_PEERING__ENABLED` | Bool | `false` | Heterogeneous peering engine |
| `sms.enabled` | `OPENALERT_SMS__ENABLED` | Bool | `false` | Cellular SMS gateway subsystem |
| `dashboard.auth.enabled` | `OPENALERT_DASHBOARD__AUTH__ENABLED` | Bool | `false` | Web Dashboard authentication |

---

## 8. CLI Configuration Validation

Before restarting or applying configurations to production clusters, validate syntax and directories:

```bash
# Validate TOML file syntax and profile settings
openalertd check-config config/openalertd.toml

# Generate secure password hash for auth configurations
openalertd hash-password "MyMasterPassword"
```
