# 🔌 py-phone-caller Services & Endpoints Reference

This document is the authoritative API and microservices reference for **py-phone-caller** (and its optional **OpenAlert `openalertd`** mesh bridge). Every route below matches the default configuration in [`src/config/settings.toml`](../src/config/settings.toml) and each service's `routes.py`.

---

## 📑 Table of Contents

1. [Microservices Overview & Port Allocations](#1-microservices-overview--port-allocations)
2. [Standardized Telemetry, Probes & OpenAPI Docs](#2-standardized-telemetry-probes--openapi-docs)
3. [Microservices Detailed Specification](#3-microservices-detailed-specification)
   - [3.1 asterisk_caller (Port 8081)](#31-asterisk_caller-port-8081)
   - [3.2 generate_audio (Port 8082)](#32-generate_audio-port-8082)
   - [3.3 caller_register (Port 8083)](#33-caller_register-port-8083)
   - [3.4 caller_prometheus_webhook (Port 8084)](#34-caller_prometheus_webhook-port-8084)
   - [3.5 caller_sms (Port 8085)](#35-caller_sms-port-8085)
   - [3.6 caller_scheduler (Port 8086)](#36-caller_scheduler-port-8086)
   - [3.7 caller_address_book (Port 8087)](#37-caller_address_book-port-8087)
   - [3.8 py_phone_caller_ui (Port 5000)](#38-py_phone_caller_ui-port-5000)
   - [3.9 asterisk_ws_monitor (WebSocket Daemon)](#39-asterisk_ws_monitor-websocket-daemon)
   - [3.10 asterisk_recaller (Background Retry Daemon)](#310-asterisk_recaller-background-retry-daemon)
   - [3.11 celery_worker (Background Task Consumer)](#311-celery_worker-background-task-consumer)
   - [3.12 openalertd (Ports 8090 / 8088, Optional Mesh Bridge)](#312-openalertd-ports-8090--8088-optional-mesh-bridge)
   - [3.13 apache_apisix (Port 9080 / 9443, Dashboard 9001)](#313-apache_apisix-port-9080--9443-dashboard-9001)
   - [3.14 keycloak (Port 8180 / 8443, Management 9009)](#314-keycloak-port-8180--8443-management-9009)
4. [Shared Library: `py_phone_caller_utils`](#4-shared-library-py_phone_caller_utils)
5. [Database Models & Schemas (Piccolo ORM)](#5-database-models--schemas-piccolo-orm)

---

## 1. Microservices Overview & Port Allocations

| Service Name | Default Port | Protocol / Type | Primary Responsibility |
| :--- | :---: | :--- | :--- |
| **`asterisk_caller`** | `8081` | HTTP (aiohttp) | Originates Asterisk ARI calls, manages call queue, plays audio, ARI Circuit Breaker |
| **`generate_audio`** | `8082` | HTTP (aiohttp) | Strategy-pattern multi-engine TTS synthesis (Kokoro, Silero, Piper, MMS, Polly, gTTS) |
| **`caller_register`** | `8083` | HTTP (aiohttp) | Central call registry, DTMF state tracker, and Piccolo ORM migrations |
| **`caller_prometheus_webhook`** | `8084` | HTTP (aiohttp) | Alertmanager & OpenAlert webhook receiver with M2M JWT auth & coalescing |
| **`caller_sms`** | `8085` | HTTP (aiohttp) | Dual-channel SMS & RFC 3428 SIP `MESSAGE` gateway (`on_premise`, `asterisk_sip`, `twilio`) |
| **`caller_scheduler`** | `8086` | HTTP (aiohttp) | Delayed call scheduling via Celery and Redis |
| **`caller_address_book`** | `8087` | HTTP (aiohttp) | Dual-channel contact directory (`phone_number` + `sms_phone_number`), on-call rotation, CSV tools |
| **`py_phone_caller_ui`** | `5000` | HTTP (Flask/Gunicorn) | Multilingual (Flask-Babel RTL) web console, dashboard, diagnostics, OIDC/local auth |
| **`asterisk_ws_monitor`** | *N/A* | WebSocket Client | Listens to Asterisk ARI events, triggers audio generation, playback & DTMF handling |
| **`asterisk_recaller`** | *N/A* | Background Daemon | Distributed-lock polling loop for retrying unacknowledged calls & backup escalation |
| **`celery_worker`** | *N/A* | Redis Task Consumer | Priority queue execution worker (`p0_emergency`, `default`, `telephony.dlq`) |
| **`openalertd`** *(optional)* | `8090` / `8088` | Rust Daemon (HTTP/WS) | LoRa RF, BitChat BLE, `/sos` Captive Portal, Nostr (`NIP-ALERT`), Embedded Relay (`:8088`) |
| **`apache_apisix`** *(enterprise)* | `9080` / `9443` | HTTP / HTTPS Gateway | Unified API gateway routing ingress to UI, Keycloak, and microservices |
| **`apisix_dashboard`** *(enterprise)* | `9001` | HTTP (Manager API) | Visual dashboard and Manager API for APISIX routes and upstreams |
| **`keycloak`** *(enterprise)* | `8180` / `8443` | OIDC / OAuth2 IAM | Enterprise identity provider, OpenID Connect SSO, and 3-tier RBAC |

---

## 2. Standardized Telemetry, Probes & OpenAPI Docs

All HTTP microservices automatically register uniform liveness, readiness, service catalog, Swagger/OpenAPI, and Prometheus metrics endpoints via `py_phone_caller_utils.telemetry` and `py_phone_caller_utils.web`:

### Liveness Probes (`GET /health`, `GET /healthz`, `GET /live`)
- **Response (`200 OK`)**:
  ```json
  {
    "status": "healthy",
    "service": "asterisk_caller",
    "version": "1.1.0"
  }
  ```

### Dependency Readiness Probe (`GET /ready`)
- Evaluates live downstream dependencies (`ReadinessRegistry`) such as PostgreSQL connection pools (`caller_register`, `caller_address_book`, `caller_sms`), Redis broker (`caller_scheduler`), or Asterisk ARI + PJSIP trunk (`asterisk_caller`).
- Returns `200 OK` when ready, or `503 Service Unavailable` with per-dependency diagnostic JSON when degraded.

### Service Catalog & OpenAPI Specification (`GET /`, `GET /docs`, `GET /docs/swagger.json`, `GET /api/docs`)
- `GET /`: Returns a JSON service catalog listing active endpoints and metadata.
- `GET /docs`: Serves interactive Swagger UI HTML (or static same-origin OpenAPI JSON links with zero external CDN requests when `PPC_OFFLINE=1`).
- `GET /docs/swagger.json`: Returns the OpenAPI 3.0.3 JSON specification for that service.
- `GET /api/docs` (on `py_phone_caller_ui`): Unified OpenAPI portal aggregating the Web UI and all 7 internal microservices over the single HTTPS origin via `GET /api/v1/<service>/docs/swagger.json` (`alerts`, `telephony`, `sms`, `contacts`, `schedules`, `audio`, `registry`), keeping internal ports `8081`–`8087` strictly private.

### Prometheus Metrics (`GET /metrics`)
- **Format**: `text/plain; version=0.0.4; charset=utf-8`
- Exposes Python process metrics, GC statistics, CPU/memory usage, and HTTP request counters.

### Health & Documentation Access Matrix (Edge vs Loopback)

In `standard` and `airgapped` topologies, Caddy exposes only the single HTTPS origin (`https://<domain>`) while internal microservices (`8081`–`8087`) stay bound to `127.0.0.1`:

| Endpoint | Origin | Auth Required | Purpose |
| :--- | :--- | :--- | :--- |
| `GET /health`, `GET /ready` | Public HTTPS (`https://<domain>`) | No | Unauthenticated liveness & readiness probes for `py_phone_caller_ui` and load balancers |
| `GET /api/cluster_health` | Public HTTPS (`https://<domain>`) | Yes (Session / JWT) | Full-stack health JSON probing PostgreSQL, Redis, Asterisk ARI/WS, SMS engine, Gateway, and IAM |
| `GET /api/docs` | Public HTTPS (`https://<domain>`) | No | Unified OpenAPI Developer Portal (static zero-CDN same-origin links when `PPC_OFFLINE=1`) |
| `GET /docs/swagger.json` | Public HTTPS (`https://<domain>`) | No | Complete OpenAPI 3.0.3 JSON spec for `py_phone_caller_ui` |
| `GET /api/v1/<service>/docs/swagger.json` | Public HTTPS (`https://<domain>`) | No | Read-only allowlisted BFF proxy (`alerts`, `telephony`, `sms`, `contacts`, `schedules`, `audio`, `registry`); returns `404` for unknown slugs |
| `GET http://127.0.0.1:808{1..7}/health` & `/ready` | Loopback only (host / SSH) | No | Direct per-microservice liveness and dependency readiness probes |

---

## 3. Microservices Detailed Specification

### 3.1 `asterisk_caller` (Port 8081)

Interfaces directly with Asterisk ARI to originate outbound calls and manage audio playback. Includes an integrated **ARI Circuit Breaker** (returns HTTP `503` when open) and `oncall` lookup against `caller_address_book`.

#### `POST /call_to_queue`
Enqueues a phone call into the internal async worker queue. **Recommended endpoint for monitoring integrations (Nagios, Zabbix).**
- **Query / Form / JSON Parameters**:
  - `phone` (string, required): Destination phone number (e.g. `00393341234567`, local SIP extension `1000`, or the reserved alias `oncall`).
  - `message` (string, required): The alert message to be synthesized to speech.
  - `lang` / `language` (string, optional): Override TTS language code for this call.
- **Behavior**: If `phone=oncall`, resolves the active on-call contact's `phone_number` from `caller_address_book`. If no contact is available, logs an operational warning and returns HTTP `400` without crashing.

#### `POST /place_call`
Directly and synchronously initiates an outbound call via Asterisk ARI without queueing.
- **Query / Form / JSON Parameters**:
  - `phone` (string, required): Phone number, SIP extension, or `oncall`.
  - `message` (string, required): Alert message.
  - `backup_callee` (boolean, optional, default: `false`): Indicates an automated backup retry from `asterisk_recaller`.
  - `lang` / `language` (string, optional): Override TTS language code.
- **Response**: `200 OK` (`{"status": 200}`) or `503 Service Unavailable` if the Asterisk ARI circuit breaker is open.

#### `POST /play`
Plays a generated audio WAV file to an active Asterisk channel.
- **Query / Form / JSON Parameters**:
  - `asterisk_chan` (string, required): Active Asterisk Stasis channel ID.
  - `msg_chk_sum` (string, required): Checksum identifying the WAV audio file (e.g. `1e971032`).
  - `lang` / `language` (string, optional): Language suffix matching language-scoped cached WAVs (`{msg_chk_sum}_{lang}.wav`).

---

### 3.2 `generate_audio` (Port 8082)

Synthesizes Asterisk-compliant 16-bit mono 8000 Hz WAV audio files from text messages using a Strategy-pattern architecture across 6 TTS engines with dynamic on-disk model discovery and cross-engine fallback.

#### `POST /make_audio`
Asynchronously triggers audio generation for a message or returns cached status if the file already exists.
- **Query / Form / JSON Parameters**:
  - `message` (string, required): Text message to synthesize.
  - `msg_chk_sum` (string, required): Unique checksum identifying the audio file.
  - `lang` / `language` (string, optional): Language code (e.g. `en`, `es`, `it`, `fr`, `de`, `ru`, `zh`, `hi`, `ar`, `he`).
  - `speed` (float, optional, default: `1.0`): Speech rate adjustment factor.
  - `engine` (string, optional): Explicit TTS engine override (`kokoro_tts`, `silero_tts`, `piper_tts`, `facebook_mms`, `aws_polly`, `google_gtts`).
- **Supported TTS Engines**:
  - `kokoro_tts`: Offline neural voice synthesis (Kokoro-82M v1.0).
  - `silero_tts`: Compact offline PyTorch V3 neural synthesis (~50 MB/model; English, Spanish, German, French, Russian, Indic).
  - `piper_tts`: Ultra-fast offline ONNX neural synthesis (validated on x86_64 and ARM64 RK3588).
  - `facebook_mms`: Offline PyTorch VITS architecture supporting 1,000+ languages.
  - `aws_polly`: Cloud-managed Amazon Polly synthesis.
  - `google_gtts`: Cloud fallback via Google Translate TTS.
- **Response**: `200 OK`
  ```json
  {
    "status": 200,
    "cached": false
  }
  ```

#### `GET /is_audio_ready`
Polls whether an audio file has finished synthesis and passed RIFF/non-zero validation for Asterisk playback.
- **Query Parameters**:
  - `msg_chk_sum` (string, required): Checksum of the audio file.
  - `lang` / `language` (string, optional): Language code matching audio generation.
- **Response**: `200 OK` (`{"exists": true}`).

#### `GET /languages`
Scans local on-disk `pre_trained_models/` directories and returns the active engine, available language options, country flags, and installed offline model weights.

#### `GET /audio/{filename}`
Serves generated 8 kHz mono WAV files directly for Asterisk playback and Web UI audio preview.

---

### 3.3 `caller_register` (Port 8083)

Central state store and database initializer. Owns Piccolo ORM migrations and call audit history.

#### `POST /register_call`
Records or updates an outbound call attempt in the `calls` table.
- **Parameters**: `phone`, `message`, `asterisk_chan` (and optional metadata such as `lang`, `oncall`, `backup_callee`).

#### `POST /msg`
Retrieves the voice message text and checksum associated with an active Asterisk channel (`call_register_app_route_voice_message = "msg"`).
- **Parameters**: `asterisk_chan` (string, required).
- **Response**: `200 OK`
  ```json
  {"status": 200, "message": "High CPU on server", "msg_chk_sum": "1e971032"}
  ```

#### `POST /scheduled_call`
Persists a scheduled call audit record in `scheduled_calls`.

#### `GET /ack`
Marks a call as acknowledged (`acknowledge_at`, `cycle_done = true`) upon DTMF `'4'` receipt or Web UI operator acknowledgment.
- **Query Parameters**: `asterisk_chan` (string, required).

#### `GET /heard`
Records that the callee answered/heard the audio (`heard_at`) before hanging up.
- **Query Parameters**: `asterisk_chan` (string, required).

---

### 3.4 `caller_prometheus_webhook` (Port 8084)

Receives standard Prometheus Alertmanager JSON payloads (from Alertmanager, Grafana, or **`openalertd`**) with optional M2M OAuth2 Bearer JWT validation (`require_auth = true`), deduplication (`DEDUPLICATION_WINDOW_SECONDS`), and alert storm coalescing (`coalescing_enabled`).

Default routes (configurable in `[caller_prometheus_webhook]`):
- **`POST /call_only`**: Dispatches emergency voice calls for firing alerts.
- **`POST /sms_only`**: Dispatches SMS / SIP `MESSAGE` notifications for firing alerts.
- **`POST /call_and_sms`**: Simultaneously dispatches both a voice call and an SMS / SIP `MESSAGE`.
- **`POST /sms_before_call`**: Dispatches an immediate SMS / SIP `MESSAGE`, waits `sms_before_call_wait_seconds` (or proceeds on fast failover), and then places a voice call. *(Default target for `openalertd` field-to-telephony bridge.)*

Setting `prometheus_webhook_receivers = ["oncall"]` dynamically resolves targets through `caller_address_book`.

- **Request Body (Alertmanager JSON Payload)**:
  ```json
  {
    "receiver": "py-phone-caller-webhook",
    "status": "firing",
    "alerts": [
      {
        "status": "firing",
        "labels": {
          "alertname": "HostDown",
          "severity": "critical",
          "instance": "db-primary.lan"
        },
        "annotations": {
          "summary": "Database node unreachable",
          "description": "PostgreSQL instance failed health check."
        }
      }
    ]
  }
  ```

---

### 3.5 `caller_sms` (Port 8085)

Dual-channel SMS and RFC 3428 SIP `MESSAGE` gateway service supporting three carriers:
1. **`on_premise`**: Native Rust PyO3 serial modem engine (`rust_engine`) with SQLite queue (`/tmp/sms.db`), round-robin/failover multi-modem support, **always-UCS-2 UTF-8 encoding**, and **70 UTF-16 code-unit multipart chunking** (preserving emojis and accented/special characters cleanly).
2. **`asterisk_sip`**: Direct RFC 3428 SIP `MESSAGE` delivery via Asterisk ARI (`endpoints/sendMessage`) for 4–6 digit local SIP extensions (e.g. `1000`) or `sip:`/`pjsip:` URIs—also acts as automatic failover when GSM delivery fails or no cellular `sms_phone_number` is set.
3. **`twilio`**: Cloud SMS via Twilio REST API (can also act as optional `sms_saas_fallback = true`).

#### `POST /send_sms`
Dispatches an outbound SMS or SIP `MESSAGE` and persists the result in the PostgreSQL `sms` table.
- **Query / Form / JSON Parameters**:
  - `phone` (string, required): Recipient cellular number (`+393341234567` / `00393341234567`), local SIP extension (`1000`), or the reserved alias `oncall` (resolves `sms_phone_number` first, falling back to `phone_number` / SIP `MESSAGE`).
  - `message` (string, required): UTF-8 text body (automatically UCS-2 encoded and chunked to 70 UTF-16 code units per segment on USB GSM modems).
- **Response**: `200 OK`
  ```json
  {"status": 200, "message": "SMS dispatched successfully", "carrier": "on_premise"}
  ```

#### `GET /get_sms`
Queries SMS audit logs from PostgreSQL with optional filtering.
- **Query Parameters**:
  - `limit` (integer, optional): Maximum number of records to return.
  - `phone` (string, optional): Filter by recipient phone/extension.
  - `status` (string, optional): Filter by delivery status.
- **Response**: `200 OK` (`{"status": 200, "records": [...]}`).

#### `POST /sms/inbound`
Inbound SMS webhook endpoint that parses incoming replies and correlates ACK tokens with active calls in PostgreSQL under a distributed Redis `call_mutex` lock.

---

### 3.6 `caller_scheduler` (Port 8086)

Schedules future and delayed voice alerts using Celery and Redis.

#### `POST /schedule_call`
Schedules a call for execution at a specified local time.
- **Query / Form / JSON Parameters**:
  - `phone` (string, required): Destination phone number, SIP extension, or `oncall`.
  - `message` (string, required): Voice message text.
  - `scheduled_at` (string, required): Target timestamp in local time (`YYYY-MM-DD HH:MM`).
  - `lang` / `language` (string, optional): TTS language override.
- **Behavior**: Converts `scheduled_at` to UTC using `local_timezone`, records an audit row in `scheduled_calls`, and enqueues `do_this_call` with ETA in Redis.

---

### 3.7 `caller_address_book` (Port 8087)

Manages dual-channel contacts (`phone_number` for voice/SIP + optional `sms_phone_number` for cellular SMS) and time-windowed on-call availability schedules.

#### `POST /contact_add`
Creates a new address book entry.
- **Request Body (JSON)**:
  ```json
  {
    "name": "Mario",
    "surname": "Rossi",
    "phone_number": "1000",
    "sms_phone_number": "00393341234567",
    "enabled": true,
    "on_call_availability": [
      {
        "start_at": "2026-11-21T00:00:00Z",
        "end_at": "2026-11-28T23:59:59Z",
        "priority": 0
      }
    ],
    "annotations": "Primary on-call SRE (Local SIP Ext 1000 + Cellular SMS)"
  }
  ```
- **Validation**: `phone_number` accepts 3–18 digit SIP extensions or E.164 numbers (`^(\+|00)?[0-9]{3,18}$`); optional `sms_phone_number` accepts 5–18 digit E.164/mobile numbers (`^(\+|00)?[0-9]{5,18}$`).
- **Response**: `201 Created` (`{"id": "<uuid>"}`).

#### `PUT /contact_modify/{id}`
Updates an existing contact by UUID. Returns `{"updated": 1}`.

#### `DELETE /contact_delete`
Deletes contacts by JSON body `{"ids": ["<uuid>", ...]}`. Returns `{"deleted": <count>}`.

#### `GET /contact_on_call`
Resolves the currently active on-call contact based on current UTC time and priority.
- **Response**: `200 OK` (or `404 Not Found` if nobody is on call):
  ```json
  {
    "phone_number": "1000",
    "sms_phone_number": "00393341234567"
  }
  ```

#### `GET /contacts_export_csv` & `POST /contacts_import_csv`
Exports all contact records (including `sms_phone_number` and `on_call_availability`) to CSV or imports/upserts contacts with Pydantic (`ContactCSVRow`) validation.

---

### 3.8 `py_phone_caller_ui` (Port 5000)

Flask web interface and Backend-for-Frontend (BFF) with full `Flask-Babel` internationalization (`en`, `es`, `de`, `fr`, `it`, plus RTL layouts for `ar` and `he`).

- **Blueprints & Capabilities**:
  - `home`: Main dashboard with quick action cards, live system status, Call Diagnostics, and interactive TTS audio preview (`POST /proxy_tts_preview`, `GET /proxy_languages`).
  - `login`: Operator authentication gate supporting Keycloak OIDC SSO (PKCE) and local PostgreSQL fallback.
  - `calls`: Real-time call history table with search, pagination, bulk acknowledgment (`POST /proxy_acknowledge`), and incident audit reporting (`GET /calls/audit_report`).
  - `sms`: Managed SMS & SIP `MESSAGE` history table with carrier tags (`on_premise`, `asterisk_sip`, `twilio`), lifecycle stepper modal, and CSV export.
  - `address_book`: Dual-channel contact editor (`phone_number` + `sms_phone_number`), on-call window creator, quick on-call toggle, CSV import/export, and coverage calendar.
  - `schedule_call`: Scheduled call queue with creation modal and cancellation controls.
  - `ws_events`: Live Asterisk WebSocket event log inspector with JSON modal.
  - `users`: User account administration, password reset, and role management.

#### Health, Telemetry & Diagnostics Endpoints
- `GET /health` & `GET /ready` *(unauthenticated)*: Public liveness and readiness JSON probes (`{"service": "py_phone_caller_ui", "status": "healthy", "version": "1.1.0"}`).
- `GET /api/cluster_health` *(authenticated)*: Concurrent health aggregation JSON across PostgreSQL, Redis, Asterisk ARI/WS, SMS engine, API Gateway, and IAM (also displayed live in the NOC Dashboard Cluster Health HUD). Redirects to `/login` when unauthenticated.
- `GET /api/dashboard_metrics` *(authenticated)*: Live KPI counters (call ack rate, SMS success rate, active schedules, on-call responders, call lifecycle breakdown).
- `GET /api/telemetry_stream` *(authenticated)*: Real-time Server-Sent Events (SSE) stream pushing live telephony and dashboard metric updates.
- `POST /api/diagnostics/test_call` & `POST /api/diagnostics/test_sms` *(authenticated)*: One-click diagnostic call and SMS triggers routed through internal microservices.
- `GET /api/languages` & `GET /api/audio_proxy/<filename>` *(authenticated)*: Proxies installed TTS languages and synthesized WAV previews from `generate_audio` (`:8082`).

#### Unified OpenAPI Portal & Air-Gap Proxy
- `GET /api/docs`: Unified OpenAPI Developer Portal aggregating the Web UI and all 7 internal microservices. In online mode it renders interactive Swagger UI; in `PPC_OFFLINE=1` mode it renders strict static HTML with zero external CDN requests and only same-origin links.
- `GET /docs/swagger.json`: Full OpenAPI 3.0.3 JSON specification for `py_phone_caller_ui`.
- `GET /api/v1/<service_slug>/docs/swagger.json`: Read-only BFF proxy fetching `/docs/swagger.json` from allowlisted internal microservices (`alerts`, `telephony`, `sms`, `contacts`, `schedules`, `audio`, `registry`). Returns `404` for unknown slugs and `502` if an upstream service is unreachable, allowing `/api/docs` to work over HTTPS in standalone and air-gapped topologies without APISIX or exposed internal ports.

#### Authentication Endpoints
- `GET /login` / `POST /login`: Local fallback login form against PostgreSQL `users` table.
- `GET /oauth2/login`: Initiates Keycloak OIDC Single Sign-On flow with PKCE (`S256`).
- `GET /oauth2/callback`: Exchanges authorization code, validates claims, maps roles (`alert-admin`, `alert-operator`, `alert-viewer`), and creates session.
- `GET /logout`: Terminates local session and, when authenticated via OIDC, redirects to Keycloak's end-session endpoint.

---

### 3.9 `asterisk_ws_monitor` (WebSocket Daemon)

- **Connection**: Connects to `ws://<asterisk_host>:<port>/ari/events?app=py-phone-caller`.
- **Events Processed**:
  - `StasisStart`: Queries `POST /msg` on `caller_register`, triggers `POST /make_audio` on `generate_audio`, polls `GET /is_audio_ready`, and calls `POST /play` on `asterisk_caller`.
  - `ChannelDtmfReceived`: Catches DTMF `'4'` (`GET /ack` + hangup) and `'5'` (repeat message).
  - `StasisEnd`: Records call completion/heard state (`GET /heard`) in `caller_register`.

---

### 3.10 `asterisk_recaller` (Background Retry Daemon)

- **Loop**: Periodically scans the `calls` table for unacknowledged calls (`cycle_done == false`) within `seconds_to_forget`.
- **Escalation**: Retries up to `times_to_dial` before escalating to the next-priority backup on-call contact. Guarded by distributed Redis locks (`py_phone_caller_utils.redis_lock`) for multi-instance safety.

---

### 3.11 `celery_worker` (Background Task Consumer)

- **Command**: `uv run celery -A py_phone_caller_utils.tasks.celery_task worker --loglevel=info`
- **Task**: `py_phone_caller_utils.tasks.celery_task.do_this_call`
- **Queues**: Priority routing across `p0_emergency` (urgent calls), `default` (scheduled calls), and `telephony.dlq` (dead-letter forensics persisted to `dead_letter_queue`).

---

### 3.12 `openalertd` (Ports 8090 / 8088, Optional Mesh Bridge)

Native Rust decentralized field alerting daemon ([`docs/openalert/README.md`](openalert/README.md)):
- **Port `8090` (HTTP/REST & Web UI)**: Admin NOC dashboard (`/`), Emergency `/sos` Captive Portal (`GET /sos`, `GET /api/v1/sos/challenge`, `POST /api/v1/sos/trigger`), REST alert ingress (`/api/v1/alert`, `/webhook/prometheus`), and optional NIP-57 Lightning Zap endpoints.
- **Port `8088` (Embedded Nostr Micro-Relay)**: Self-contained Nostr WebSocket relay (`NIP-ALERT` Kind 30000, NIP-17/NIP-59 0xChat E2EE C2, NIP-40 expiration, optional native `tokio-rustls` WSS).
- **Physical Radio & Hardware Transports**: LoRa 868 MHz serial transceivers, BitChat BLE GATT peripheral (Noise XX E2EE with BlueZ/Spreadtrum HCI self-healing & clean `SIGTERM` teardown), LAN UDP hub peering, and direct always-UCS-2 USB GSM SMS.
- **Bridge to `py-phone-caller`**: Dispatches standardized Alertmanager JSON payloads to `caller_prometheus_webhook` (e.g. `http://127.0.0.1:8084/sms_before_call`).

---

### 3.13 `apache_apisix` (Port 9080 / 9443, Dashboard 9001)

Cloud-native API Gateway acting as the single ingress entry point behind the edge TLS reverse proxy:
- `/realms/*`, `/resources/*`, `/admin/*`: Proxied to Keycloak (`127.0.0.1:8180`).
- `/api/v1/*`: Proxied to backend microservices (e.g. `/api/v1/alerts/*` → `caller_prometheus_webhook` `:8084`, `/api/v1/telephony/*` → `asterisk_caller` `:8081`, `/api/v1/sms/*` → `caller_sms` `:8085`).
- `/*`: Proxied to `py_phone_caller_ui` (`127.0.0.1:5000`).
- **APISIX Dashboard**: Port `9001` (authenticated Manager API).

---

### 3.14 `keycloak` (Port 8180 / 8443, Management 9009)

Enterprise Identity and Access Management (IAM) provider:
- **OIDC Discovery**: `GET /realms/py-phone-caller/.well-known/openid-configuration`
- **Token Endpoint**: `POST /realms/py-phone-caller/protocol/openid-connect/token`
- **Authorization Endpoint**: `GET /realms/py-phone-caller/protocol/openid-connect/auth`
- **End Session / Logout**: `POST /realms/py-phone-caller/protocol/openid-connect/logout`
- **Admin Console**: `https://<domain>/admin`

---

## 4. Shared Library: `py_phone_caller_utils`

The workspace shared library provides:
- **`config.py`**: Dynaconf configuration loaders supporting TOML files and `DYNACONF_*` environment variable overrides.
- **`telemetry.py`**: Standardized OpenTelemetry tracing, `/metrics` scrapers, and `/health`/`/healthz`/`/live` probes.
- **`redis_lock.py`**: Distributed Redis locks (`call_mutex`) for multi-instance HA safety.
- **`event_bus.py`**: Asynchronous internal event publishing (`sms_dispatched`, call lifecycle events).
- **`py_phone_caller_db`**: Piccolo ORM models and async query helpers (`db_call.py`, `db_address_book.py`, `db_sms.py`, `db_user.py`, `db_asterisk_recaller.py`).
- **`py_phone_caller_voices`**: Multi-engine TTS synthesis wrappers (`kokoro_tts.py`, `silero_tts.py`, `piper_tts.py`, `facebook_mms.py`, `aws_polly.py`, `google_gtts.py`).
- **`sms`**: Native Rust PyO3 bindings (`rust_engine` with always-UCS-2 + 70-unit chunking) and Twilio async client.
- **`web`**: Parameter extraction, service catalogs, `ReadinessRegistry`, offline Swagger UI (`setup_swagger_routes`), and Asterisk ARI Circuit Breakers.
- **`auth`**: OpenID Connect token validator, PKCE verifiers, and RBAC role resolver.

---

## 5. Database Models & Schemas (Piccolo ORM)

All tables live in PostgreSQL (`src/py-phone-caller-utils/py_phone_caller_utils/py_phone_caller_db/py_phone_caller_piccolo_app/tables.py`):
- **`calls`**: Audit trail of originated calls (`phone`, `message`, `asterisk_chan`, `msg_chk_sum`, `times_to_dial`, `dialed_times`, `first_dial`, `last_dial`, `heard_at`, `acknowledge_at`, `cycle_done`, `oncall`, `backup_callee`, `lang`).
- **`sms`**: Outbound & inbound SMS / SIP `MESSAGE` audit log (`phone`, `message`, `carrier`, `status`, `created_at`, `error`).
- **`address_book`**: Contact registry with dual-channel fields (`phone_number`, `sms_phone_number`), `on_call_availability` (JSONB schedule windows & priorities), `enabled`, and `annotations`.
- **`scheduled_calls`**: Future call reservations (`phone`, `message`, `call_chk_sum`, `inserted_at`, `scheduled_at`, `lang`).
- **`asterisk_ws_events`**: Raw Asterisk Stasis WebSocket event log (`asterisk_chan`, `event_type`, `json_data` JSONB).
- **`users`**: Local Web UI operator credentials (`given_name`, `email`, password hash, `is_active`, `created_on`, `last_login`, `annotations`).
- **`dead_letter_queue`**: Permanent Celery task failures (`task_id`, `task_name`, `queue`, `payload` JSONB, `exception`, `traceback`, `created_at`) isolated on `telephony.dlq`.
