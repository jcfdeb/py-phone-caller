# 🏛️ py-phone-caller Architecture & Call Flows Guide

This document provides a comprehensive technical architecture and sequence flow specification for **py-phone-caller** (Release 1.0.0).

---

## 📑 Table of Contents

1. [High-Level Platform Architecture](#1-high-level-platform-architecture)
2. [Domain-Driven Data & Service Boundaries](#2-domain-driven-data--service-boundaries)
3. [The Core Call Lifecycle & Asterisk ARI Pipeline](#3-the-core-call-lifecycle--asterisk-ari-pipeline)
4. [Real-Time DTMF Acknowledgment & Interactive Dialplan Flow](#4-real-time-dtmf-acknowledgment--interactive-dialplan-flow)
5. [Intelligent Recaller & Backup Contact Escalation Flow](#5-intelligent-recaller--backup-contact-escalation-flow)
6. [Out-of-Band SMS Notification Architecture (Twilio & Rust Modem Engine)](#6-out-of-band-sms-notification-architecture-twilio--rust-modem-engine)
7. [Prometheus Alertmanager & Monitoring Ingestion Pipeline](#7-prometheus-alertmanager--monitoring-ingestion-pipeline)
8. [Scheduled Calls & Background Celery Worker Pipeline](#8-scheduled-calls--background-celery-worker-pipeline)
9. [Air-Gapped & Offline Architecture Principles](#9-air-gapped--offline-architecture-principles)
10. [Enterprise API Gateway & Keycloak IAM Ingress Architecture](#10-enterprise-api-gateway--keycloak-iam-ingress-architecture)
11. [OIDC Single Sign-On (SSO) & M2M Token Authentication Sequence Flows](#11-oidc-single-sign-on-sso--m2m-token-authentication-sequence-flows)

---

## 1. High-Level Platform Architecture

**py-phone-caller** is structured as an ecosystem of 11 decoupled microservices interacting over asynchronous HTTP REST APIs, WebSockets, Celery task queues, and shared PostgreSQL/Redis data stores.

```mermaid
flowchart TB
    subgraph InboundAlerts[" Inbound Alert Sources "]
        direction TB
        AM["Prometheus Alertmanager"]
        NAG["Nagios / Zabbix Monitoring"]
        UI_TRIG["Operator Web Console"]
        CRON["Cron / Celery Scheduler"]
    end

    subgraph IngestionLayer[" Ingestion & Orchestration Layer "]
        direction TB
        CPW["caller_prometheus_webhook<br/>(Port 8084)"]
        CS["caller_scheduler<br/>(Port 8086)"]
        CW["celery_worker<br/>(Celery Worker Daemon)"]
        RQ[("Redis 7 / Valkey<br/>(Queue Broker)")]
    end

    subgraph TelephonyLayer[" Telephony & Audio Pipeline "]
        direction TB
        AC["asterisk_caller<br/>(Port 8081)"]
        WSM["asterisk_ws_monitor<br/>(WebSocket ARI Listener)"]
        GA["generate_audio<br/>(Port 8082 / TTS Models)"]
        AR["asterisk_recaller<br/>(Auto-Retry Daemon)"]
    end

    subgraph SMSLayer[" SMS Gateway Layer "]
        direction TB
        SMS["caller_sms<br/>(Port 8085)"]
        RUST_ENG["rust_engine (PyO3)<br/>GSM/LTE USB Modems"]
        TWILIO_API["Twilio Cloud REST API"]
    end

    subgraph DomainDataLayer[" Data & State Management "]
        direction TB
        CR["caller_register<br/>(Port 8083 / Migrations)"]
        CAB["caller_address_book<br/>(Port 8087 / On-Call)"]
        UI["py_phone_caller_ui<br/>(Port 5000 / Web Console)"]
        PG[("PostgreSQL 17 Database<br/>(Piccolo ORM Schema)")]
    end

    subgraph ExternalTelephony[" Telephony Infrastructure "]
        AST["Asterisk PBX 18/20/21<br/>(Stasis App: py-phone-caller)"]
        PSTN["PSTN / SIP Trunk / Mobile Network"]
    end

    %% Inbound triggers
    AM --> CPW
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
    AC -->|"Resolve On-Call"| CAB
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

    %% SMS flow
    SMS --> RUST_ENG
    SMS --> TWILIO_API
    SMS -->|"Log SMS Record"| PG

    %% Data persistence
    CR --> PG
    CAB --> PG
    UI --> PG
```

---

## 2. Domain-Driven Data & Service Boundaries

Each stateful service in `py-phone-caller` encapsulates its specific business domain:

| Service | Domain Responsibility | Owned Database Tables | Primary HTTP Endpoints |
| :--- | :--- | :--- | :--- |
| **`caller_register`** | Central call registry, state tracker, and Piccolo ORM migration engine | `calls`<br>`scheduled_calls`<br>`asterisk_ws_events` | `POST /register_call`<br>`POST /voice_message`<br>`GET /heard`<br>`GET /ack` |
| **`caller_address_book`** | Contact directory and time-based on-call availability management | `address_book` | `POST /add_contact`<br>`PUT /modify_contact/{id}`<br>`GET /on_call_contact`<br>`GET /contacts_export_csv` |
| **`caller_sms`** | Multi-carrier SMS dispatch and delivery tracking | `sms` | `POST /send_sms`<br>`GET /get_sms` |
| **`py_phone_caller_ui`** | Operator web console, dashboard, session authentication, and reporting | `users` | `GET /`<br>`GET /calls`<br>`GET /address_book`<br>`GET /sms`<br>`POST /login` |
| **`generate_audio`** | Multi-engine offline neural text-to-speech audio synthesis | *Stateless (Local Audio Cache)* | `POST /make_audio`<br>`GET /is_audio_ready` |
| **`asterisk_caller`** | Call placement queue, Asterisk ARI originate client, and playback bridge | *Stateless (Async Worker Queue)* | `POST /call_to_queue`<br>`POST /place_call`<br>`POST /play` |

---

## 3. The Core Call Lifecycle & Asterisk ARI Pipeline

The following sequence diagram illustrates what happens from the moment an alert arrives until the synthesized voice message is played to the receiver over the telephony network:

```mermaid
sequenceDiagram
    autonumber
    actor Monitoring as Alert System (Prometheus / Nagios)
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
    AC->>CAB: GET /on_call_contact
    CAB-->>AC: 200 OK {"phone": "00393341234567"}
    
    AC->>CR: POST /register_call (phone, message)
    CR-->>AC: 200 OK {"msg_chk_sum": "1e971032"}

    AC->>AST: POST /ari/channels?endpoint=PJSIP/00393341234567@trunk&app=py-phone-caller
    AST-->>AC: 200 OK {"id": "channel_1786970067.10"}
    deactivate AC

    AST->>Operator: Dials Phone via PSTN / SIP Trunk
    Operator->>AST: Answers Phone Call (Channel Answered)

    AST->>WSM: WebSocket Event: StasisStart (channel_1786970067.10)
    activate WSM
    WSM->>CR: POST /voice_message?asterisk_chan=channel_1786970067.10
    CR-->>WSM: 200 OK {"message": "Database Down", "msg_chk_sum": "1e971032"}

    WSM->>GA: POST /make_audio?message=Database+Down&msg_chk_sum=1e971032
    GA-->>WSM: 200 OK {"status": "generating"}

    loop Poll until Audio Ready (Max 60s)
        WSM->>GA: GET /is_audio_ready?msg_chk_sum=1e971032
        GA-->>WSM: 200 OK {"ready": true}
    end

    WSM->>AC: POST /play?asterisk_chan=channel_1786970067.10&msg_chk_sum=1e971032
    AC->>AST: POST /ari/channels/channel_1786970067.10/play?media=sound:/path/1e971032
    AST->>Operator: Plays Audio: "Database Down... Press 4 to acknowledge, 5 to repeat"
    deactivate WSM
```

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
        CR->>CR: Update `calls` Table: acknowledged=true
        WSM->>AC: POST /play (generic acknowledgement tone/message)
        WSM->>AST: POST /ari/channels/channel_1786970067.10 (Hangup)
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
        CR->>CR: Update `calls` Table: heard=true, acknowledged=false
        Note over CR: Call is flagged for Recaller retry!
    end
```

---

## 5. Intelligent Recaller & Backup Contact Escalation Flow

The `asterisk_recaller` background service ensures no emergency call goes unhandled:

```mermaid
flowchart TD
    START([asterisk_recaller Loop Start]) --> POLL[Poll Database: Find Calls where<br/>acknowledged == false AND<br/>created_time >= NOW - seconds_to_forget]
    
    POLL --> FOUND{Any Unacknowledged<br/>Calls Found?}
    FOUND -- No --> SLEEP[Sleep for retry_interval_seconds] --> START
    
    FOUND -- Yes --> CHECK_ATTEMPTS{Attempt Count <<br/>times_to_dial?}
    
    CHECK_ATTEMPTS -- Yes --> RETRY_PRIMARY[Increment retry count in DB]
    RETRY_PRIMARY --> DISPATCH_RETRY[POST /place_call to asterisk_caller<br/>(Call Original Phone Number)]
    DISPATCH_RETRY --> SLEEP
    
    CHECK_ATTEMPTS -- No --> CHECK_BACKUP{backup_callee == false AND<br/>backup_attempts < max_times?}
    
    CHECK_BACKUP -- Yes --> GET_BACKUP[Query caller_address_book for<br/>Next Priority On-Call Contact]
    GET_BACKUP --> ESCALATE[Set backup_callee = true<br/>Reset attempt counter]
    ESCALATE --> DISPATCH_BACKUP[POST /place_call to asterisk_caller<br/>(Call Backup Escalation Number)]
    DISPATCH_BACKUP --> SLEEP
    
    CHECK_BACKUP -- No --> EXHAUSTED[Mark call as EXHAUSTED / FORGOTTEN]
    EXHAUSTED --> SLEEP
```

---

## 6. Out-of-Band SMS Notification Architecture (Twilio & Rust Modem Engine)

When an emergency requires out-of-band text messages, `caller_sms` routes delivery based on configuration:

```mermaid
flowchart LR
    subgraph ClientLayer[" Inbound Trigger "]
        REQ["POST /send_sms<br/>(phone, message)"]
    end

    subgraph ServiceRouter[" caller_sms (:8085) "]
        ROUTER{"caller_sms_carrier"}
    end

    subgraph TwilioBackend[" Cloud Carrier Backend "]
        TWILIO["Twilio REST Client (Async)"]
        TWILIO_CLOUD["Twilio SMS Gateway API"]
    end

    subgraph RustOnPremiseBackend[" On-Premise Hardware Backend "]
        RUST_BIND["PyO3 Native Bindings (rust_engine)"]
        SQLITE[("SQLite Queue (/tmp/sms.db)")]
        THREAD_POOL["Worker Thread Pool"]
        AT_DRIVER["AT Command Serial Driver"]
        MODEM1["/dev/ttyUSB0 (SIM 1)"]
        MODEM2["/dev/ttyUSB1 (SIM 2)"]
    end

    subgraph Persistence[" Audit Database "]
        PG_SMS[("PostgreSQL: `sms` Table<br/>(Phone, Body, Carrier, Status, Error)")]
    end

    REQ --> ROUTER
    
    %% Twilio Path
    ROUTER -- "twilio" --> TWILIO
    TWILIO --> TWILIO_CLOUD
    TWILIO -->|"Persist Status"| PG_SMS

    %% Rust Path
    ROUTER -- "on_premise" --> RUST_BIND
    RUST_BIND -->|"enqueue_sms"| SQLITE
    SQLITE --> THREAD_POOL
    THREAD_POOL --> AT_DRIVER
    AT_DRIVER -- "Round-Robin" --> MODEM1
    AT_DRIVER -- "Round-Robin" --> MODEM2
    RUST_BIND -->|"Persist Status"| PG_SMS
```

### UTF-8 & UCS-2 Character Encoding
For on-premise USB modems, the native `rust_engine` evaluates message content:
- **Pure ASCII Messages**: Transmitted using standard GSM-7 text mode (`AT+CMGF=1`).
- **Accented / Non-ASCII Characters (e.g. `ù`, `é`, `à`, `€`, `ö`)**: Automatically switched to **UCS-2 16-bit encoding** (`AT+CSCS="UCS2"`, `AT+CSMP=17,167,0,8`, body converted to hexadecimal representation) ensuring 100% clean rendering on mobile devices without corruption.

---

## 7. Prometheus Alertmanager & Monitoring Ingestion Pipeline

The `caller_prometheus_webhook` service maps monitoring alert states to voice and SMS actions:

```mermaid
sequenceDiagram
    autonumber
    participant Prom as Prometheus Alertmanager
    participant CPW as caller_prometheus_webhook (:8084)
    participant AC as asterisk_caller (:8081)
    participant SMS as caller_sms (:8085)

    Prom->>CPW: POST /alertmanager_call_and_sms
    Note over Prom,CPW: Payload: {"alerts": [{"status": "firing", "annotations": {"summary": "High CPU", "description": "Host node-01 CPU > 95%"}, "labels": {"severity": "critical"}}]}

    CPW->>CPW: Format Text: "Alert: High CPU. Host node-01 CPU > 95%"
    
    par Dispatch Voice Call
        CPW->>AC: POST /call_to_queue?phone=oncall&message=Alert:+High+CPU...
        AC-->>CPW: 200 OK
    and Dispatch SMS Notification
        CPW->>SMS: POST /send_sms?phone=oncall&message=Alert:+High+CPU...
        SMS-->>CPW: 200 OK
    end

    CPW-->>Prom: 200 OK {"status": "alerts_processed"}
```

---

## 8. Scheduled Calls & Background Celery Worker Pipeline

For future alerts, maintenance reminders, and automated scheduled testing:

```mermaid
sequenceDiagram
    autonumber
    actor Operator as Operator (UI / API)
    participant CS as caller_scheduler (:8086)
    participant CR as caller_register (:8083)
    participant Redis as Redis Queue Broker
    participant Worker as celery_worker (Worker Process)
    participant AC as asterisk_caller (:8081)

    Operator->>CS: POST /schedule_call (phone, message, scheduled_at="2026-08-25 14:00")
    CS->>CS: Convert local timezone to UTC timestamp
    CS->>CR: POST /scheduled_call (Record audit row in `scheduled_calls` table)
    CS->>Redis: Enqueue Celery Task: `do_this_call.apply_async(eta=utc_time)`
    CS-->>Operator: 200 OK {"task_id": "abc-123-uuid"}

    Note over Redis,Worker: ETA window elapses...
    Redis->>Worker: Dispatch task `do_this_call`
    Worker->>AC: POST /call_to_queue?phone=00393341234567&message=Scheduled+Maintenance
    AC-->>Worker: 200 OK
    Worker->>CR: Update `scheduled_calls` row: status="dispatched"
```

---

## 9. Air-Gapped & Offline Architecture Principles

**py-phone-caller** is designed from the ground up for strict air-gapped data centers:

1. **Zero Runtime CDNs**: The Web UI bundles Bootstrap, FontAwesome, and custom CSS locally under `src/py_phone_caller_ui/static/`. No external Google Fonts, JavaScript CDNs, or telemetry endpoints are contacted.
2. **Pre-Packaged TTS Models**: Machine learning models for Kokoro TTS, Piper, and Facebook MMS are pre-downloaded during container build or deployment setup into `pre_trained_models/`. Synthesis runs 100% on local CPUs with zero Hugging Face or PyPI network requests at runtime.
3. **Multi-Package UV Locking**: All Python dependencies are locked in a single root `uv.lock`. Offline container builds and Ansible synchronizations install exclusively from local caches or on-premise PyPI mirrors.
4. **Local Telemetry & Storage**: Telemetry spans and Prometheus metrics export over standard OTLP/HTTP to internal collectors without sending data outside the trusted network.

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
