# 🔌 py-phone-caller Services & Endpoints Reference

This document is the authoritative API and microservices reference for **py-phone-caller** (Release 1.0.0).

---

## 📑 Table of Contents

1. [Microservices Overview & Port Allocations](#1-microservices-overview--port-allocations)
2. [Standardized Telemetry & Health Probes](#2-standardized-telemetry--health-probes)
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
4. [Shared Library: `py_phone_caller_utils`](#4-shared-library-py_phone_caller_utils)
5. [Database Models & Schemas (Piccolo ORM)](#5-database-models--schemas-piccolo-orm)

---

## 1. Microservices Overview & Port Allocations

| Service Name | Default Port | Protocol / Type | Primary Responsibility |
| :--- | :---: | :--- | :--- |
| **`asterisk_caller`** | `8081` | HTTP (aiohttp) | Originates Asterisk ARI calls, manages call queue, plays audio |
| **`generate_audio`** | `8082` | HTTP (aiohttp) | Offline neural TTS audio synthesis (Kokoro, Piper, MMS, Polly) |
| **`caller_register`** | `8083` | HTTP (aiohttp) | Central call registry, state tracker, and Piccolo ORM migrations |
| **`caller_prometheus_webhook`** | `8084` | HTTP (aiohttp) | Prometheus Alertmanager webhook receiver for voice and SMS |
| **`caller_sms`** | `8085` | HTTP (aiohttp) | Multi-carrier SMS gateway (Twilio API / on-premise Rust modems) |
| **`caller_scheduler`** | `8086` | HTTP (aiohttp) | Delayed call scheduling via Celery and Redis |
| **`caller_address_book`** | `8087` | HTTP (aiohttp) | Contact directory, time-based on-call rotation, CSV tools |
| **`py_phone_caller_ui`** | `5000` | HTTP (Flask/Gunicorn) | Web management console, dashboard, auth, CSV reports |
| **`asterisk_ws_monitor`** | *N/A* | WebSocket Client | Listens to Asterisk ARI events, triggers audio generation & playback |
| **`asterisk_recaller`** | *N/A* | Background Daemon | Automated polling loop for retrying unacknowledged calls |
| **`celery_worker`** | *N/A* | Redis Task Consumer | Background execution worker for scheduled call dispatch |

---

## 2. Standardized Telemetry & Health Probes

All HTTP microservices automatically register uniform health and Prometheus metric endpoints via `py_phone_caller_utils.telemetry`:

### Health Endpoints (`/health`, `/healthz`, `/live`)
- **HTTP Method**: `GET`
- **Response Format**: `application/json`
- **Response Schema**:
  ```json
  {
    "status": "healthy",
    "service": "asterisk_caller",
    "version": "1.0.0"
  }
  ```
- **HTTP Status Codes**:
  - `200 OK`: Service is healthy and operational.

### Prometheus Metrics Endpoint (`/metrics`)
- **HTTP Method**: `GET`
- **Response Format**: `text/plain; version=0.0.4; charset=utf-8`
- Exposes standard Python process metrics, garbage collection statistics, CPU/memory usage, and custom HTTP request counters.

---

## 3. Microservices Detailed Specification

### 3.1 `asterisk_caller` (Port 8081)

Interfaces directly with Asterisk ARI to originate outbound calls and manage audio playback.

#### `POST /call_to_queue`
Enqueues a phone call into the internal async worker queue. **This is the recommended endpoint for monitoring integrations (Alertmanager, Nagios, Zabbix).**
- **Query / Form Parameters**:
  - `phone` (string, required): Destination phone number (e.g. `00393341234567`) or the reserved keyword `oncall`.
  - `message` (string, required): The alert message to be synthesized to speech.
- **Behavior**: If `phone=oncall`, resolves current on-call contact from `caller_address_book`. If no contact is available, logs an operational warning and safely skips without crashing.
- **Response**: `200 OK`
  ```json
  {"status": 200, "message": "Call queued successfully"}
  ```

#### `POST /place_call`
Directly and synchronously initiates an outbound call via Asterisk ARI without queueing.
- **Query / Form Parameters**:
  - `phone` (string, required): Phone number or `oncall`.
  - `message` (string, required): Alert message.
  - `backup_callee` (boolean, optional, default: `false`): Flag indicating if this is an automated backup retry.
- **Response**: `200 OK`
  ```json
  {"status": 200, "message": "Call placed successfully", "channel_id": "1786970067.10"}
  ```

#### `POST /play`
Plays a generated audio WAV file to an active Asterisk channel.
- **Query Parameters**:
  - `asterisk_chan` (string, required): The active Asterisk Stasis channel ID.
  - `msg_chk_sum` (string, required): Checksum identifying the WAV audio file (e.g. `1e971032`).

---

### 3.2 `generate_audio` (Port 8082)

Synthesizes high-quality, Asterisk-compliant 16-bit mono 8000 Hz WAV audio files from text messages.

#### `POST /make_audio`
Asynchronously triggers audio generation for a message.
- **Query Parameters**:
  - `message` (string, required): Text message to synthesize.
  - `msg_chk_sum` (string, required): Checksum for the resulting audio file.
- **TTS Engines**:
  - `kokoro_tts`: High-fidelity neural voice synthesis (Kokoro-82M v1.0).
  - `piper_tts`: Ultra-fast neural synthesis via local ONNX.
  - `facebook_mms`: Multilingual PyTorch VITS architecture.
  - `aws_polly`: Cloud synthesis fallback.
  - `gtts`: Google TTS fallback.
- **Response**: `200 OK`
  ```json
  {"status": 200, "msg_chk_sum": "1e971032", "audio_path": "/app/src/generate_audio/audio/1e971032.wav"}
  ```

#### `GET /is_audio_ready`
Polls whether an audio file has finished synthesis and is ready for playback.
- **Query Parameters**:
  - `msg_chk_sum` (string, required): Checksum of the audio file.
- **Response**: `200 OK`
  ```json
  {"status": 200, "is_ready": true}
  ```

---

### 3.3 `caller_register` (Port 8083)

Central state store and database initializer. Owns migrations and call audit history.

#### `POST /register_call`
Records a newly placed outbound call attempt.
- **Query Parameters**:
  - `phone` (string, required): Destination phone number.
  - `message` (string, required): Alert text message.
- **Response**: `200 OK`
  ```json
  {"status": 200, "msg_chk_sum": "1e971032"}
  ```

#### `POST /voice_message`
Retrieves message text and checksum associated with an active Asterisk channel.
- **Query Parameters**:
  - `asterisk_chan` (string, required): Active Asterisk channel ID.
- **Response**: `200 OK`
  ```json
  {"status": 200, "message": "High CPU on server", "msg_chk_sum": "1e971032"}
  ```

#### `GET /ack`
Marks a call as acknowledged when the operator presses DTMF key `'4'`.
- **Query Parameters**:
  - `asterisk_chan` (string, required): Active channel ID.

#### `GET /heard`
Marks a call as heard when audio finishes playing or the operator hangs up.
- **Query Parameters**:
  - `asterisk_chan` (string, required): Active channel ID.

---

### 3.4 `caller_prometheus_webhook` (Port 8084)

Receives standard Prometheus Alertmanager webhook JSON payloads and triggers notifications.

#### `POST /alertmanager_call_only`
Dispatches an emergency voice call for firing alerts.

#### `POST /alertmanager_sms_only`
Dispatches an SMS notification for firing alerts.

#### `POST /alertmanager_call_and_sms`
Simultaneously dispatches both a voice call and an SMS message.

#### `POST /alertmanager_sms_before_call`
Sends an immediate SMS, waits a configurable interval (`sms_before_call_wait_seconds`), and then places a voice call.

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

SMS gateway service supporting Twilio and on-premise hardware GSM/LTE modems.

#### `POST /send_sms`
Dispatches an outbound SMS message and records the attempt in the PostgreSQL `sms` table.
- **Query / Form Parameters**:
  - `phone` (string, required): Recipient phone number (e.g. `+393341234567` or `00393341234567`).
  - `message` (string, required): SMS text body (supports full UTF-8 and UCS-2 characters).
- **Response**: `200 OK`
  ```json
  {"status": 200, "message": "SMS dispatched successfully", "carrier": "twilio"}
  ```

#### `GET /get_sms`
Queries SMS audit logs with optional filtering.
- **Query Parameters**:
  - `limit` (integer, optional, default: 50): Number of records.
  - `offset` (integer, optional, default: 0): Pagination offset.
- **Response**: `200 OK` (Array of SMS log objects).

---

### 3.6 `caller_scheduler` (Port 8086)

Schedules future and delayed voice alerts using Celery and Redis.

#### `POST /schedule_call`
Schedules a call for execution at a specified local time.
- **Query / Form Parameters**:
  - `phone` (string, required): Destination phone number.
  - `message` (string, required): Voice message text.
  - `scheduled_at` (string, required): Target timestamp in local time (`YYYY-MM-DD HH:MM`).
- **Behavior**: Automatically converts `scheduled_at` to UTC based on configured `LOCAL_TIMEZONE`, records a row in `scheduled_calls`, and enqueues a Celery task with ETA in Redis.
- **Response**: `200 OK`
  ```json
  {"status": 200, "task_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d", "scheduled_at_utc": "2026-08-25T12:00:00Z"}
  ```

---

### 3.7 `caller_address_book` (Port 8087)

Manages contacts and time-windowed on-call availability.

#### `POST /add_contact`
Creates a new address book entry.
- **Request Body (JSON)**:
  ```json
  {
    "name": "Mario",
    "surname": "Rossi",
    "phone_number": "00393341234567",
    "enabled": true,
    "on_call_availability": [
      {
        "start_at": "2026-08-20T00:00:00Z",
        "end_at": "2026-08-27T23:59:59Z",
        "priority": 0
      }
    ],
    "annotations": "Primary on-call SRE"
  }
  ```

#### `GET /on_call_contact`
Resolves the currently active on-call contact based on current UTC time and priority.
- **Response**: `200 OK`
  ```json
  {
    "status": 200,
    "contact": {
      "id": "uuid-here",
      "name": "Mario Rossi",
      "phone_number": "00393341234567",
      "priority": 0
    }
  }
  ```

#### `GET /contacts_export_csv`
Streams all contact records as a downloadable CSV file.

#### `POST /contacts_import_csv`
Imports contact records from an uploaded CSV payload.

---

### 3.8 `py_phone_caller_ui` (Port 5000)

Flask web interface and Backend-for-Frontend (BFF).

- **Blueprints**:
  - `home`: Main dashboard with quick action cards and system status.
  - `login`: Operator authentication gate and session management.
  - `calls`: Real-time call history table with search, pagination, and monthly CSV export.
  - `sms`: Managed SMS history table with carrier tags, status badges, and monthly CSV export.
  - `address_book`: Contact list, on-call window creator, and interactive monthly coverage calendar.
  - `schedule_call`: Scheduled call queue with creation modal and cancellation controls.
  - `ws_events`: Live Asterisk WebSocket event log inspector with JSON view modal.
  - `users`: User account administration, password reset, and role management.

---

### 3.9 `asterisk_ws_monitor` (WebSocket Daemon)

- **Connection**: Connects to `ws://<asterisk_host>:<port>/ari/events?app=py-phone-caller`.
- **Events Processed**:
  - `StasisStart`: Resolves voice message, triggers audio generation, requests Asterisk playback.
  - `ChannelDtmfReceived`: Catches DTMF keypresses (`'4'` for ACK, `'5'` for repeat).
  - `StasisEnd`: Records completion or hangup state in database.

---

### 3.10 `asterisk_recaller` (Background Retry Daemon)

- **Loop**: Periodically scans `calls` table for unacknowledged calls (`acknowledged == false`).
- **Escalation**: Retries up to `times_to_dial` before escalating to the backup on-call contact.

---

### 3.11 `celery_worker` (Background Task Consumer)

- **Command**: `python -m celery -A py_phone_caller_utils.tasks.celery_task worker --loglevel=info`
- **Task**: `py_phone_caller_utils.tasks.celery_task.do_this_call`
- Dispatches queued calls to `asterisk_caller` when their scheduled ETA arrives.

---

## 4. Shared Library: `py_phone_caller_utils`

The workspace shared library provides:
- **`config.py`**: Dynaconf configuration loaders supporting TOML files and `DYNACONF_*` environment variable overrides.
- **`telemetry.py`**: Standardized OpenTelemetry tracing setup, `/metrics` scrapers, and `/health` probe instrumentation.
- **`py_phone_caller_db`**: Asynchronous database query helpers (`db_call.py`, `db_address_book.py`, `db_sms.py`, `db_user.py`, `db_asterisk_recaller.py`).
- **`py_phone_caller_voices`**: Multi-engine TTS synthesis wrappers (Kokoro, Piper, Facebook MMS, AWS Polly).
- **`sms`**: Native Rust bindings (`rust_engine`) and Twilio async clients.

---

## 5. Database Models & Schemas (Piccolo ORM)

All relational models are defined in `py_phone_caller_utils.py_phone_caller_db.py_phone_caller_piccolo_app.tables`:

```python
# 1. Calls Table
class Calls(Table):
    id = UUID(primary_key=True)
    phone = Varchar(length=64)
    message = Varchar(length=1024)
    msg_chk_sum = Varchar(length=64)
    asterisk_chan = Varchar(length=64)
    heard = Boolean(default=False)
    acknowledged = Boolean(default=False)
    times_to_dial = Integer(default=0)
    created_time = Timestamp()
    oncall = Boolean(default=False)
    backup_callee = Boolean(default=False)
    call_backup_callee_number_calls = Integer(default=0)

# 2. AddressBook Table
class AddressBook(Table):
    id = UUID(primary_key=True)
    name = Varchar(length=64)
    surname = Varchar(length=64)
    phone_number = Varchar(length=64)
    on_call_availability = JSONB(default="[]")
    enabled = Boolean(default=True)
    created_time = Timestamp()
    annotations = Varchar(length=1024)

# 3. Sms Table
class Sms(Table):
    id = UUID(primary_key=True)
    phone = Varchar(length=64)
    message = Varchar(length=2048)
    carrier = Varchar(length=32)
    status = Varchar(length=32)
    error = Varchar(length=1024)
    created_time = Timestamp()

# 4. ScheduledCalls Table
class ScheduledCalls(Table):
    id = UUID(primary_key=True)
    phone = Varchar(length=64)
    message = Varchar(length=1024)
    scheduled_at = Timestamp()
    created_time = Timestamp()
    task_id = Varchar(length=64)

# 5. Users Table
class Users(Table):
    id = UUID(primary_key=True)
    email = Varchar(length=128, unique=True)
    password_hash = Varchar(length=256)
    active = Boolean(default=True)
    created_time = Timestamp()
    annotations = Varchar(length=2048)
```
