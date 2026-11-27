# 🏛️ py-phone-caller Architecture & Call Flows Guide

This document provides the technical architecture and sequence flow specification for **py-phone-caller** and its decentralized **OpenAlert (`openalertd`)** mesh bridge.

---

## 📑 Table of Contents

1. [High-Level Platform Architecture](#1-high-level-platform-architecture)
2. [Domain-Driven Data & Service Boundaries](#2-domain-driven-data--service-boundaries)
3. [The Core Call Lifecycle & Asterisk ARI Pipeline](#3-the-core-call-lifecycle--asterisk-ari-pipeline)
4. [Real-Time DTMF Acknowledgment & Interactive Dialplan Flow](#4-real-time-dtmf-acknowledgment--interactive-dialplan-flow)
5. [Intelligent Recaller & Backup Contact Escalation Flow](#5-intelligent-recaller--backup-contact-escalation-flow)
6. [Dual-Channel SMS & SIP MESSAGE Architecture (USB GSM, Asterisk SIP & Twilio)](#6-dual-channel-sms--sip-message-architecture-usb-gsm-asterisk-sip--twilio)
7. [Prometheus Alertmanager & OpenAlert Webhook Pipeline](#7-prometheus-alertmanager--openalert-webhook-pipeline)
8. [Scheduled Calls & Background Celery Worker Pipeline](#8-scheduled-calls--background-celery-worker-pipeline)
9. [Air-Gapped & Offline Architecture Principles](#9-air-gapped--offline-architecture-principles)
10. [Enterprise API Gateway & Keycloak IAM Ingress Architecture](#10-enterprise-api-gateway--keycloak-iam-ingress-architecture)
11. [OIDC Single Sign-On (SSO) & M2M Token Authentication Sequence Flows](#11-oidc-single-sign-on-sso--m2m-token-authentication-sequence-flows)

---

## 1. High-Level Platform Architecture

**py-phone-caller** is structured as 11 decoupled Python 3.14 microservices interacting over asynchronous HTTP REST APIs, Asterisk ARI WebSockets, Celery priority queues, and PostgreSQL/Redis stores—optionally paired with **`openalertd`** (native Rust field mesh daemon) for off-grid LoRa RF, BitChat BLE, `/sos` Captive Portal, and Nostr (`NIP-ALERT`) alerting.

```mermaid
flowchart TB
    subgraph InboundAlerts[" Inbound Alert Sources "]
        direction TB
        AM["Prometheus Alertmanager"]
        OA["openalertd (:8090 / :8088)<br/>LoRa RF / BitChat BLE / /sos Portal / Nostr"]
        NAG["Nagios / Zabbix Monitoring"]
        UI_TRIG["Multilingual Operator Web Console"]
        CRON["Cron / Celery Scheduler"]
    end

    subgraph IngestionLayer[" Ingestion & Orchestration Layer "]
        direction TB
        CPW["caller_prometheus_webhook<br/>(Port 8084)"]
        CS["caller_scheduler<br/>(Port 8086)"]
        CW["celery_worker<br/>(p0_emergency & default queues)"]
        RQ[("Redis 7/8 / Valkey<br/>(Broker & Distributed Locks)")]
    end

    subgraph TelephonyLayer[" Telephony & Audio Pipeline "]
        direction TB
        AC["asterisk_caller<br/>(Port 8081 / ARI Circuit Breaker)"]
        WSM["asterisk_ws_monitor<br/>(WebSocket ARI Listener)"]
        GA["generate_audio<br/>(Port 8082 / Kokoro, Silero, Piper, MMS)"]
        AR["asterisk_recaller<br/>(Auto-Retry & Escalation Daemon)"]
    end

    subgraph SMSLayer[" SMS & SIP MESSAGE Gateway Layer "]
        direction TB
        SMS["caller_sms<br/>(Port 8085 / Smart Dual-Channel Router)"]
        RUST_ENG["rust_engine (PyO3)<br/>USB GSM/LTE Modems (Always-UCS-2)"]
        TWILIO_API["Twilio Cloud REST API<br/>(Optional SaaS / Fallback)"]
    end

    subgraph DomainDataLayer[" Data & State Management "]
        direction TB
        CR["caller_register<br/>(Port 8083 / Migrations)"]
        CAB["caller_address_book<br/>(Port 8087 / phone_number + sms_phone_number)"]
        UI["py_phone_caller_ui<br/>(Port 5000 / Flask-Babel RTL UI)"]
        PG[("PostgreSQL 17/18 Database<br/>(Piccolo ORM Schema)")]
    end

    subgraph ExternalTelephony[" Telephony Infrastructure "]
        AST["Asterisk PBX 18/20/21/22<br/>(Stasis: py-phone-caller, Ext 1000, SIP MESSAGE)"]
        PSTN["PSTN / SIP Trunk / Local SIP Softphones / Mobile"]
    end

    %% Inbound triggers
    AM --> CPW
    OA -->|"POST /sms_before_call"| CPW
    NAG --> AC
    UI_TRIG --> UI
    UI --> CS
    UI --> CAB
    CRON --> CS

    %% Scheduler & Worker
    CS --> RQ
    RQ --> CW
    CW --> AC
    CPW --> AC
    CPW --> SMS

    %% Call flow
    AC -->|"HTTP POST /ari/channels"| AST
    AC -->|"Resolve Voice Target"| CAB
    AC -->|"Register Call"| CR
    AST --> PSTN
    AST -->|"WebSocket Events"| WSM
    WSM -->|"Request Audio"| GA
    WSM -->|"Trigger Playback"| AC
    WSM -->|"Log Stasis Events"| CR

    %% Recaller
    AR -->|"Poll Pending Calls"| PG
    AR -->|"Trigger Retry Call"| AC
    AR -->|"Query Backup On-Call"| CAB

    %% SMS & SIP MESSAGE flow
    SMS -->|"Resolve Dual Targets"| CAB
    SMS --> RUST_ENG
    SMS -->|"RFC 3428 SIP MESSAGE"| AST
    SMS --> TWILIO_API
    SMS -->|"Log SMS Record"| PG

    %% Data persistence
    CR --> PG
    CAB --> PG
    UI --> PG
```

---

## 2. Domain-Driven Data & Service Boundaries

Each stateful service in `py-phone-caller` encapsulates its specific business domain and exposes `/health`, `/healthz`, `/live`, dependency-aware `/ready`, `/metrics`, and OpenAPI `/docs`:

| Service | Domain Responsibility | Owned Database Tables | Primary HTTP Endpoints |
| :--- | :--- | :--- | :--- |
| **`caller_register`** | Central call registry, state tracker, and Piccolo ORM migration engine | `calls`<br>`scheduled_calls`<br>`asterisk_ws_events`<br>`dead_letter_queue` | `POST /register_call`<br>`POST /msg`<br>`POST /scheduled_call`<br>`GET /heard`<br>`GET /ack` |
| **`caller_address_book`** | Dual-channel contact directory (`phone_number` + `sms_phone_number`) and time-based on-call availability | `address_book` | `POST /contact_add`<br>`PUT /contact_modify/{id}`<br>`DELETE /contact_delete`<br>`GET /contact_on_call`<br>`GET /contacts_export_csv`<br>`POST /contacts_import_csv` |
| **`caller_sms`** | Smart dual-channel SMS & RFC 3428 SIP `MESSAGE` dispatch, inbound ACK correlation, and delivery tracking | `sms` | `POST /send_sms`<br>`GET /get_sms`<br>`POST /sms/inbound` |
| **`py_phone_caller_ui`** | Multilingual Flask-Babel (RTL) operator console, live TTS preview, diagnostics, auth, and audit reporting | `users` | `GET /`<br>`GET /calls`<br>`GET /address_book`<br>`GET /sms`<br>`POST /login`<br>`GET /oauth2/login` |
| **`generate_audio`** | Strategy-pattern multi-engine offline TTS synthesis (Kokoro, Silero, Piper, MMS) & cloud fallbacks | *Stateless (Language-Scoped Audio Cache)* | `POST /make_audio`<br>`GET /is_audio_ready`<br>`GET /languages`<br>`GET /audio/{filename}` |
| **`asterisk_caller`** | Call placement queue, Asterisk ARI originate client, ARI Circuit Breaker, and playback bridge | *Stateless (Async Worker Queue)* | `POST /call_to_queue`<br>`POST /place_call`<br>`POST /play` |
| **`caller_prometheus_webhook`** | Alertmanager & OpenAlert webhook ingestion, M2M Bearer JWT verification, deduplication, and coalescing | *Stateless (Dedup / Coalescing Buffer)* | `POST /call_only`<br>`POST /sms_only`<br>`POST /sms_before_call`<br>`POST /call_and_sms` |

---

## 3. The Core Call Lifecycle & Asterisk ARI Pipeline

The following sequence diagram illustrates what happens from the moment an alert arrives until the synthesized voice message is played to the receiver over the telephony network (PSTN/SIP trunk or local SIP extension such as `1000`):

```mermaid
sequenceDiagram
    autonumber
    actor Monitoring as Alert System (Prometheus / OpenAlert / Nagios)
    participant AC as asterisk_caller (:8081)
    participant CAB as caller_address_book (:8087)
    participant CR as caller_register (:8083)
    participant AST as Asterisk PBX (:8088 ARI)
    participant WSM as asterisk_ws_monitor
    participant GA as generate_audio (:8082)
    actor Operator as On-Call Engineer

    Monitoring->>AC: POST /call_to_queue?phone=oncall&message=Database+Down
    AC-->>Monitoring: 200 OK (Queued)

    activate AC
    AC->>CAB: GET /contact_on_call
    CAB-->>AC: 200 OK {"phone_number": "1000", "sms_phone_number": "00393341234567"}

    AC->>CR: POST /register_call (phone, message)
    CR-->>AC: 200 OK {"msg_chk_sum": "1e971032"}

    AC->>AST: POST /ari/channels?endpoint=PJSIP/1000&app=py-phone-caller
    AST-->>AC: 200 OK {"id": "channel_1786970067.10"}
    deactivate AC

    AST->>Operator: Dials Phone via Local SIP Extension or PSTN / SIP Trunk
    Operator->>AST: Answers Phone Call (Channel Answered)

    AST->>WSM: WebSocket Event: StasisStart (channel_1786970067.10)
    activate WSM
    WSM->>CR: POST /msg?asterisk_chan=channel_1786970067.10
    CR-->>WSM: 200 OK {"message": "Database Down", "msg_chk_sum": "1e971032"}

    WSM->>GA: POST /make_audio?message=Database+Down&msg_chk_sum=1e971032
    GA-->>WSM: 200 OK {"status": 200, "cached": false}

    loop Poll until Audio Ready (Max 60s)
        WSM->>GA: GET /is_audio_ready?msg_chk_sum=1e971032
        GA-->>WSM: 200 OK {"exists": true}
    end

    WSM->>AC: POST /play?asterisk_chan=channel_1786970067.10&msg_chk_sum=1e971032
    AC->>AST: POST /ari/channels/channel_1786970067.10/play?media=sound:/path/1e971032
    AST->>Operator: Plays Audio: "Database Down... Press 4 to acknowledge, 5 to repeat"
    deactivate WSM
```

> [!NOTE]
> **`asterisk_caller` ARI Circuit Breaker**: If Asterisk ARI suffers repeated timeouts or connection errors, the built-in Circuit Breaker trips to `OPEN` state and returns HTTP `503 Service Unavailable` immediately to protect upstream workers until PBX connectivity recovers.

---

## 4. Real-Time DTMF Acknowledgment & Interactive Dialplan Flow

When the call is in progress, the operator can interact with the call using their phone keypad:

```mermaid
sequenceDiagram
    autonumber
    actor Operator as On-Call Engineer
    participant AST as Asterisk PBX
    participant WSM as asterisk_ws_monitor
    participant CR as caller_register (:8083)
    participant AC as asterisk_caller (:8081)

    alt Operator Presses '4' (Acknowledge Alert)
        Operator->>AST: Presses DTMF '4'
        AST->>WSM: WebSocket Event: ChannelDtmfReceived (digit='4')
        WSM->>CR: GET /ack?asterisk_chan=channel_1786970067.10
        CR->>CR: Update `calls` Table: acknowledge_at=NOW, cycle_done=true
        WSM->>AC: POST /play (generic acknowledgement tone/message)
        WSM->>AST: DELETE /ari/channels/channel_1786970067.10 (Hangup)
        AST->>Operator: Call Terminated (Alert Resolved)

    else Operator Presses '5' (Repeat Message)
        Operator->>AST: Presses DTMF '5'
        AST->>WSM: WebSocket Event: ChannelDtmfReceived (digit='5')
        WSM->>AC: POST /play?asterisk_chan=channel_1786970067.10&msg_chk_sum=1e971032
        AST->>Operator: Replays Audio Message

    else Operator Hangs Up Without Acknowledging
        Operator->>AST: Hangs Up Call
        AST->>WSM: WebSocket Event: StasisEnd (channel_1786970067.10)
        WSM->>CR: GET /heard?asterisk_chan=channel_1786970067.10
        CR->>CR: Update `calls` Table: heard_at=NOW, cycle_done=false
        Note over CR: Call is flagged for Recaller retry!
    end
```

---

## 5. Intelligent Recaller & Backup Contact Escalation Flow

The `asterisk_recaller` background service (protected by distributed Redis locks via `py_phone_caller_utils.redis_lock`) ensures no emergency call goes unhandled:

```mermaid
flowchart TD
    START(["asterisk_recaller Loop Start"]) --> POLL["Poll Database: Find Calls where<br/>cycle_done == false AND<br/>first_dial >= NOW - seconds_to_forget"]

    POLL --> FOUND{"Any Unacknowledged<br/>Calls Found?"}
    FOUND -- No --> SLEEP["Sleep for retry interval"] --> START

    FOUND -- Yes --> CHECK_ATTEMPTS{"dialed_times < times_to_dial?"}

    CHECK_ATTEMPTS -- Yes --> RETRY_PRIMARY["Acquire Redis lock & increment dialed_times"]
    RETRY_PRIMARY --> DISPATCH_RETRY["POST /place_call to asterisk_caller<br/>(Call Original Phone Number)"]
    DISPATCH_RETRY --> SLEEP

    CHECK_ATTEMPTS -- No --> CHECK_BACKUP{"backup_callee == false AND<br/>backup attempts < max_times?"}

    CHECK_BACKUP -- Yes --> GET_BACKUP["Query caller_address_book for<br/>Next Priority On-Call Contact"]
    GET_BACKUP --> ESCALATE["Set backup_callee = true<br/>Reset attempt counter"]
    ESCALATE --> DISPATCH_BACKUP["POST /place_call to asterisk_caller<br/>(Call Backup Escalation Number)"]
    DISPATCH_BACKUP --> SLEEP

    CHECK_BACKUP -- No --> EXHAUSTED["Mark call as cycle_done / FORGOTTEN"]
    EXHAUSTED --> SLEEP
```

---

## 6. Dual-Channel SMS & SIP MESSAGE Architecture (USB GSM, Asterisk SIP & Twilio)

Each Address Book contact supports **dual-channel destinations**:
- **`phone_number`** *(required)*: Voice/SIP destination (either a local 4–6 digit SIP extension like `1000`, a SIP URI, or a full E.164 PSTN number).
- **`sms_phone_number`** *(optional)*: Dedicated cellular SMS number (e.g., `00393341234567`).

When `caller_sms` receives `POST /send_sms` (including `phone=oncall`), its `SmsDispatchService` automatically routes messages across three carriers:

```mermaid
flowchart LR
    subgraph ClientLayer[" Inbound Trigger "]
        REQ["POST /send_sms<br/>(phone='oncall' or number, message)"]
    end

    subgraph ServiceRouter[" caller_sms (:8085) "]
        ONCALL["Resolve 'oncall' via<br/>caller_address_book (/contact_on_call)"]
        ROUTER{"Target Type &<br/>caller_sms_carrier"}
    end

    subgraph RustOnPremiseBackend[" On-Premise USB GSM Backend (on_premise) "]
        RUST_BIND["PyO3 Native Bindings (rust_engine)"]
        SQLITE[("SQLite Queue (/tmp/sms.db)")]
        AT_DRIVER["AT Serial Driver<br/>Always-UCS-2 + 70-Unit Chunking"]
        MODEM1["/dev/ttyUSB* (SIM 1)"]
        MODEM2["/dev/ttyUSB* (SIM 2)"]
    end

    subgraph SipMessageBackend[" Local SIP MESSAGE Backend (asterisk_sip) "]
        ARI_MSG["Asterisk ARI endpoints/sendMessage<br/>(RFC 3428 SIP MESSAGE)"]
        SIP_PHONE["Local SIP Softphone (e.g. Ext 1000)"]
    end

    subgraph TwilioBackend[" Cloud Carrier Backend (twilio) "]
        TWILIO["Twilio REST Client (Async)"]
        TWILIO_CLOUD["Twilio SMS Gateway API"]
    end

    subgraph Persistence[" Audit Database "]
        PG_SMS[("PostgreSQL: sms Table<br/>(Phone, Body, Carrier, Status, Error)")]
    end

    REQ --> ONCALL --> ROUTER

    %% On-Premise GSM Path
    ROUTER -- "E.164 / sms_phone_number<br/>(on_premise)" --> RUST_BIND
    RUST_BIND -->|"enqueue_sms"| SQLITE
    SQLITE --> AT_DRIVER
    AT_DRIVER -- "Round-Robin / Failover" --> MODEM1
    AT_DRIVER -- "Round-Robin / Failover" --> MODEM2
    RUST_BIND -->|"Persist Status"| PG_SMS

    %% Asterisk SIP MESSAGE Path
    ROUTER -- "4-6 digit SIP ext / sip: URI<br/>or GSM Failover (asterisk_sip)" --> ARI_MSG
    ARI_MSG --> SIP_PHONE
    ARI_MSG -->|"Persist Status"| PG_SMS

    %% Twilio Path
    ROUTER -- "twilio / sms_saas_fallback" --> TWILIO
    TWILIO --> TWILIO_CLOUD
    TWILIO -->|"Persist Status"| PG_SMS
```

### Smart Routing & Failover Rules
1. **`phone=oncall` Dual-Channel Resolution**: `caller_sms` fetches `(sms_phone_number, phone_number)` from `caller_address_book` (`GET /contact_on_call`).
   - If `sms_phone_number` is populated, cellular SMS is dispatched via the configured carrier (`on_premise` USB GSM modem or `twilio`).
   - If cellular GSM delivery fails (or no `sms_phone_number` is configured) and `phone_number` is a local SIP extension (`4–6` digits or `sip:`/`pjsip:` URI), `caller_sms` automatically falls back to **RFC 3428 SIP `MESSAGE`** via Asterisk ARI (`asterisk_sip`) so local softphones (e.g., Linphone on Extension `1000`) still receive the text alert immediately.
2. **Always-UCS-2 UTF-8 Encoding & Multipart Chunking**:
   - In both `py_phone_caller_utils` (`rust_engine`) and `openalertd`, on-premise USB GSM modems **always** transmit SMS using **UCS-2 16-bit Unicode encoding** (`AT+CSCS="UCS2"`, `AT+CSMP=17,167,0,8`, hex-encoded UTF-16BE destination and payload). This guarantees that brackets (`[SOS]`), accents (`ù`, `é`, `ñ`), symbols, and non-Latin scripts render cleanly without GSM-7 charset corruption across different cellular modems.
   - Messages longer than **70 UTF-16 code units** are automatically split into numbered multipart segments (`(1/N) ...`) on clean UTF-16 boundaries without ever splitting surrogate pairs (such as emojis).
3. **Inbound SMS Acknowledgment (`POST /sms/inbound`)**: Incoming SMS replies containing ACK tokens are correlated against active calls in PostgreSQL (using Redis `call_mutex` locking) to acknowledge incidents remotely.

---

## 7. Prometheus Alertmanager & OpenAlert Webhook Pipeline

The `caller_prometheus_webhook` service (`:8084`) ingests standard Prometheus Alertmanager JSON payloads from both IT monitoring systems and **`openalertd`** field gateways (LoRa RF, BitChat BLE, `/sos` Captive Portal, Nostr). Setting `prometheus_webhook_receivers = ["oncall"]` dynamically routes alerts through the Address Book.

```mermaid
sequenceDiagram
    autonumber
    participant Source as Prometheus Alertmanager / openalertd
    participant CPW as caller_prometheus_webhook (:8084)
    participant SMS as caller_sms (:8085)
    participant AC as asterisk_caller (:8081)

    Source->>CPW: POST /sms_before_call (or /call_and_sms, /call_only, /sms_only)
    Note over Source,CPW: Payload: {"alerts": [{"status": "firing", "annotations": {"summary": "[SOS] ...", "description": "..."}, "labels": {"severity": "critical"}}]}

    CPW->>CPW: Optional M2M Bearer JWT Check + Dedup / Coalescing
    CPW->>SMS: POST /send_sms (phone="oncall", message="...")
    SMS-->>CPW: 200 OK (Dispatched via USB GSM / SIP MESSAGE / Twilio)

    Note over CPW: Wait sms_before_call_wait_seconds (or skip delay on immediate failover)

    CPW->>AC: POST /place_call (phone="oncall", message="...")
    AC-->>CPW: 200 OK (Voice call originated via Asterisk ARI)

    CPW-->>Source: 200 OK {"status": "200"}
```

---

## 8. Scheduled Calls & Background Celery Worker Pipeline

For future alerts, maintenance reminders, and emergency priority preemption:

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (UI / API)
    participant CS as caller_scheduler (:8086)
    participant CR as caller_register (:8083)
    participant Redis as Redis Queue Broker
    participant Worker as celery_worker (p0_emergency / default)
    participant AC as asterisk_caller (:8081)

    Operator->>CS: POST /schedule_call (phone, message, scheduled_at="2026-11-21 14:00", lang="en")
    CS->>CS: Convert local timezone to UTC timestamp
    CS->>CR: POST /scheduled_call (Record audit row in `scheduled_calls` table)
    CS->>Redis: Enqueue Celery Task: `do_this_call.apply_async(eta=utc_time)`
    CS-->>Operator: 200 OK {"task_id": "abc-123-uuid"}

    Note over Redis,Worker: ETA window elapses...
    Redis->>Worker: Dispatch task `do_this_call`
    Worker->>AC: POST /call_to_queue?phone=00393341234567&message=Scheduled+Maintenance
    AC-->>Worker: 200 OK
```

- **Priority Routing & DLQ**: Urgent dispatches can preempt standard scheduled traffic via the `p0_emergency` Celery queue; permanently failing tasks are isolated into `telephony.dlq` and logged in the PostgreSQL `dead_letter_queue` table for operator forensics.

---

## 9. Air-Gapped & Offline Architecture Principles

**py-phone-caller** and **OpenAlert** are validated for strict 100% air-gapped operation (including physical ARM64 appliances such as Orange Pi 5 Plus RK3588 with `systemd` `IPAddressDeny=any` enforcement):

1. **Zero Runtime CDNs**: The Web UI bundles Bootstrap and FontAwesome assets locally under `src/py_phone_caller_ui/static/` and serves `/api/docs` using same-origin service OpenAPI JSON links with zero external CDNs or telemetry calls. When `PPC_OFFLINE=1` is set in strict air-gapped deployments, `/docs` returns a static `503` offline page while `/api/docs` renders HTTP `200` as an offline portal linking only local JSON specs without external Swagger UI CDN scripts.
2. **Pre-Packaged Offline Neural TTS Models**: Weights for **Kokoro-82M**, **Silero V3**, **Piper ONNX**, and **Facebook MMS** are pre-downloaded into `pre_trained_models/` and discovered locally via `GET /languages`. Speech synthesis runs 100% on local CPUs (x86_64 and ARM64) with zero runtime Hugging Face or PyPI traffic.
3. **Deterministic UV Locking & Offline Bundles**: All Python 3.14 dependencies are locked in a single root `uv.lock`. Native Ansible air-gapped deployments install exclusively from local wheel bundles, signed `file:` APT mirrors, and pre-built `openalertd` / `rust_engine` binaries (see [`deploy/docs/09-arm64-appliance-and-airgapped-deployment.md`](../deploy/docs/09-arm64-appliance-and-airgapped-deployment.md)).
4. **Off-Grid Field Ingestion & Delivery**: `openalertd` receives alerts with zero Internet via LoRa 868 MHz RF, BitChat BLE (with BlueZ/Spreadtrum HCI self-healing), and the `OpenAlert-SOS` Wi-Fi Captive Portal (`/sos` + offline SVG CAPTCHA), then triggers local Asterisk 22 voice calls (e.g., local SIP Extension `1000`) and always-UCS-2 USB GSM modem SMS.
5. **Local Telemetry & Storage**: OpenTelemetry spans and Prometheus `/metrics` export strictly over private LAN/loopback endpoints.

---

## 10. Enterprise API Gateway & Keycloak IAM Ingress Architecture

In production environments, direct exposure of internal microservice ports (`8081`–`8087`, `5000`) is prohibited. Instead, incoming user and machine traffic passes through an enterprise perimeter ingress layer composed of **Apache APISIX** and **Keycloak IAM**:

```mermaid
flowchart TB
    subgraph Clients[" External Traffic "]
        direction TB
        Browser["Operator Browser<br/>(HTTPS / WSS)"]
        Prometheus["Prometheus Alertmanager<br/>(HTTP / JSON Webhook)"]
        AdminCLI["SRE / Admin CLI<br/>(cURL / REST API)"]
    end

    subgraph EdgeIngress[" Public Ingress & TLS Termination "]
        direction TB
        TLS["Public Reverse Proxy<br/>(Apache 2 / Nginx / Caddy)<br/>Port 80 / 443 (Let's Encrypt TLS)"]
    end

    subgraph GatewayIAM[" Enterprise Gateway & Identity Layer "]
        direction TB
        APISIX["Apache APISIX Gateway<br/>(Port 9080 / 9443)<br/>Route Matching & Token Verification"]
        ETCD[("etcd Cluster<br/>(Port 2379 / Loopback)")]
        KC["Keycloak IAM<br/>(Port 8180 / 8443)<br/>Realm: py-phone-caller"]
        APISIX <--> ETCD
    end

    subgraph InternalMicroservices[" Internal Microservice Mesh (127.0.0.1 / Bridge) "]
        direction TB
        UI["py_phone_caller_ui<br/>(Port 5000)"]
        WEBHOOK["caller_prometheus_webhook<br/>(Port 8084)"]
        REST_APIS["Internal REST APIs<br/>(:8081 - :8087)"]
        AST["Asterisk PBX<br/>(:8088 ARI / 5060 SIP)"]
    end

    Browser -->|TLS 443| TLS
    Prometheus -->|TLS 443| TLS
    AdminCLI -->|TLS 443| TLS

    TLS -->|"Proxy to APISIX (:9080)"| APISIX
    TLS -->|"Direct or Proxied /auth (:8180)"| KC

    APISIX -->|"Path / (Web UI & Static)"| UI
    APISIX -->|"Path /webhook (Alert Ingestion)"| WEBHOOK
    APISIX -->|"Path /api/* (Internal Proxy)"| REST_APIS
```

### Key Security Guardrails:
1. **Network Boundary**: Internal service ports (5000, 8081-8087) bind to `0.0.0.0` or bridge IPs, but are strictly shielded from public routing by host packet filters (`ufw` / `firewalld`).
2. **Reverse Proxy Offloading**: Public TLS is terminated either by Apache 2 / Nginx / Caddy at ports 80/443, proxying to APISIX on port 9080 with proper `X-Forwarded-For` and `X-Forwarded-Proto` headers.
3. **Role-Based Access Control (RBAC)**: Keycloak realm `py-phone-caller` manages 3 distinct realm roles:
   - `alert-admin`: Full access to user management, phone configuration, and alert escalation.
   - `alert-operator`: Can view live calls, acknowledge alerts, and trigger manual notifications.
   - `alert-viewer`: Read-only access to call histories and audit logs.

---

## 11. OIDC Single Sign-On (SSO) & M2M Token Authentication Sequence Flows

### 11.1 Web UI OpenID Connect (OIDC) Flow with PKCE

For human operators logging into the management portal:

```mermaid
sequenceDiagram
    autonumber
    actor User as Operator Browser
    participant Gateway as APISIX Gateway (:9080)
    participant UI as py_phone_caller_ui (:5000)
    participant Keycloak as Keycloak IAM (:8180)

    User->>Gateway: GET /
    Gateway->>UI: Proxy GET /
    UI-->>User: 302 Redirect to /login
    User->>UI: Click "Login with Keycloak SSO"
    UI->>UI: Generate PKCE code_verifier & code_challenge (S256)
    UI-->>User: 302 Redirect to Keycloak /auth?response_type=code&code_challenge=...
    User->>Keycloak: Present credentials (Username / Password / 2FA)
    Keycloak-->>User: 302 Redirect to UI /oauth2/callback?code=AUTH_CODE
    User->>UI: GET /oauth2/callback?code=AUTH_CODE
    UI->>Keycloak: POST /protocol/openid-connect/token (code + code_verifier)
    Keycloak-->>UI: 200 OK (id_token, access_token, refresh_token)
    UI->>Keycloak: GET /protocol/openid-connect/userinfo
    Keycloak-->>UI: 200 OK (username, roles: ["alert-admin"])
    UI->>UI: Establish Flask session & set secure session cookie
    UI-->>User: 302 Redirect to / (Dashboard rendered with Operator profile)
```

> [!NOTE]
> If Keycloak is unreachable, operators can still log in using the **Local Emergency Fallback** form directly on `/login`, authenticating against the local PostgreSQL `users` table.

### 11.2 Machine-to-Machine (M2M) Alert Ingestion Flow

For automated monitoring systems (e.g. Prometheus Alertmanager) pushing incident payloads:

```mermaid
sequenceDiagram
    autonumber
    participant AM as Prometheus Alertmanager
    participant KC as Keycloak IAM (:8180)
    participant APISIX as APISIX Gateway (:9080)
    participant Webhook as caller_prometheus_webhook (:8084)
    participant Caller as asterisk_caller (:8081)

    AM->>KC: POST /realms/py-phone-caller/protocol/openid-connect/token<br/>(grant_type=client_credentials, client_id=py-phone-caller-m2m)
    KC-->>AM: 200 OK {"access_token": "JWT_TOKEN", "expires_in": 300}
    AM->>APISIX: POST /webhook<br/>Authorization: Bearer JWT_TOKEN<br/>{"alerts": [{"status": "firing", "labels": {"alertname": "HostDown"}}]}
    APISIX->>APISIX: Verify JWT token signature, expiry, and realm issuer
    APISIX->>Webhook: Forward POST /webhook (stripped or validated)
    Webhook->>Caller: POST /call_to_queue (Initiate emergency phone call)
    Caller-->>Webhook: 200 OK
    Webhook-->>APISIX: 200 OK
    APISIX-->>AM: 200 OK {"status": "dispatched"}
```
