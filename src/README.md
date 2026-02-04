# 🚀 py-phone-caller Source Code

Welcome to the **py-phone-caller** microservices architecture—a production-ready emergency alert and notification platform built with Python, Asterisk PBX, and modern cloud-native technologies.

---

## 📐 Architecture Overview

The `src/` directory contains **11 microservices** organized into a distributed, event-driven system. Each service is independently deployable via Docker, runs as a systemd service, and communicates through REST APIs and message queues.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Emergency Alert Flow                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Trigger (Prometheus/UI/API)                                    │
│         │                                                       │
│         ▼                                                       │
│  ┌──────────────────┐      ┌──────────────────┐                 │
│  │ caller_scheduler │◄─────┤ Celery Worker    │                 │
│  │   (Future)       │      │   (Background)   │                 │
│  └────────┬─────────┘      └──────────────────┘                 │
│           │                                                     │
│           ▼                                                     │
│  ┌──────────────────┐                                           │
│  │ asterisk_caller  │──────► Asterisk PBX ──► Phone Network     │
│  │  (Initiate Call) │                                           │
│  └────────┬─────────┘                                           │
│           │                                                     │
│           ▼                                                     │
│  ┌──────────────────────┐                                       │
│  │ asterisk_ws_monitor  │◄─── WebSocket Events                  │
│  │   (Call Lifecycle)   │                                       │
│  └────────┬─────────────┘                                       │
│           │                                                     │
│           ▼                                                     │
│  ┌──────────────────┐      ┌──────────────────┐                 │
│  │ generate_audio   │      │ caller_register  │                 │
│  │   (TTS Engine)   │      │   (Call History) │                 │
│  └──────────────────┘      └──────────────────┘                 │
│           │                          │                          │
│           ▼                          ▼                          │
│  ┌──────────────────────────────────────────┐                   │
│  │      asterisk_recaller (Retry Logic)     │                   │
│  └──────────────────────────────────────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🧩 Microservices

### Call Management & Asterisk Integration

#### **asterisk_caller**
> **Outbound Call Orchestrator**

HTTP service that places phone calls through Asterisk ARI, manages call queues, and plays generated audio on active channels.

- **Port:** `8081`
- **Key Responsibilities:**
  - Place immediate or queued calls
  - Register calls with `caller_register`
  - Fetch and play TTS audio from `generate_audio`
  - Resolve on-call contacts via `caller_address_book`

📄 [Learn more](asterisk_caller/README.md)

---

#### **asterisk_recaller**
> **Intelligent Retry & Escalation Engine**

Background worker that retries failed or unacknowledged calls and escalates to backup contacts when the primary call window expires.

- **Key Responsibilities:**
  - Query database for retry candidates
  - Enforce retry windows and backoff timing
  - Trigger calls via `asterisk_caller`
  - Escalate to on-call backup contacts

📄 [Learn more](asterisk_recaller/README.md)

---

#### **asterisk_ws_monitor**
> **Real-Time Event Listener**

WebSocket client for Asterisk ARI events. Reacts to call lifecycle events, requests audio generation, and triggers playback on active channels.

- **Key Responsibilities:**
  - Connect to Asterisk ARI WebSocket
  - Fetch message data from `caller_register`
  - Request `generate_audio` to create audio on-demand
  - Trigger playback and log events to database

📄 [Learn more](asterisk_ws_monitor/README.md)

---

### Core Services

#### **caller_register**
> **Call Registry & Persistence**

HTTP service that stores call attempts, message payloads, and call status (acknowledged, heard, retry count).

- **Port:** `8083`
- **Key Responsibilities:**
  - Register new calls and link to voice messages
  - Track acknowledgement and retry status
  - Store scheduled call metadata
  - Initialize and migrate database schema (Piccolo ORM)

📄 [Learn more](caller_register/README.md)

---

#### **generate_audio**
> **Text-to-Speech Engine**

HTTP service that converts text messages into audio files using multiple TTS engines.

- **Port:** `8082`
- **Supported TTS Engines:**
  - **gTTS** _(Google Text-to-Speech)_
  - **Facebook MMS** _(Offline-capable)_
  - **Piper TTS** _(Offline-capable)_
  - **AWS Polly** _(AWS Text-to-Speech)_
  - **Kokoro TTS** _(Offline-capable)_
- **Key Responsibilities:**
  - Generate `.wav` audio for call messages
  - Serve audio readiness checks
  - Cache generated audio files

📄 [Learn more](generate_audio/README.md)

---

#### **caller_scheduler**
> **Celery-Powered Scheduling**

HTTP service that schedules future calls using Celery tasks backed by Redis.

- **Port:** `8086`
- **Key Responsibilities:**
  - Accept schedule requests with target datetime
  - Convert local time to UTC
  - Enqueue Celery tasks for delayed execution
  - Return scheduling status to caller

📄 [Learn more](caller_scheduler/README.md)

---

#### **caller_address_book**
> **Contact & On-Call Management**

HTTP service for managing contacts and on-call rotations used by call and recall flows.

- **Port:** `8087`
- **Key Responsibilities:**
  - CRUD operations for contacts
  - Fetch active on-call contact
  - Import/export contacts in CSV format
  - Initialize and migrate database schema (Piccolo ORM)

📄 [Learn more](caller_address_book/README.md)

---

### Communication Services

#### **caller_sms**
> **SMS Gateway (Twilio & On-Premise)**

HTTP service for sending SMS notifications. Supports Twilio and an on-premise USB modem backend powered by a **Rust engine**.

- **Port:** `8085`
- **Backends:**
  - **Twilio**: Cloud-based SMS via API
  - **On-Premise**: USB GSM modem (D-Link DWM-222 verified, or one like [this](https://www.amazon.it/dp/B09R4HXP41?ref=ppx_yo2ov_dt_b_fed_asin_title))
- **Key Responsibilities:**
  - Expose simple SMS API
  - Send SMS via configured backend
  - Handle async dispatch and retries

📄 [Learn more](caller_sms/README.md)

---

### Integration & UI

#### **caller_prometheus_webhook**
> **Alertmanager Integration**

Prometheus Alertmanager-compatible webhook that turns alerts into phone calls and SMS notifications.

- **Port:** `8084`
- **Notification Workflows:**
  - Call-only
  - SMS-only
  - SMS-before-call
  - Call-and-SMS (parallel)
- **Key Responsibilities:**
  - Accept Alertmanager payloads
  - Dispatch notifications via `asterisk_caller` and `caller_sms`
  - Use asyncio queues to throttle requests

📄 [Learn more](caller_prometheus_webhook/README.md)

---

#### **py_phone_caller_ui**
> **Web Dashboard**

Flask web UI for managing calls, schedules, users, WebSocket events, and the address book.

- **Port:** `5000`
- **Features:**
  - Login-protected pages
  - Call history and status views
  - Schedule management
  - User and contact management
  - WebSocket event logs
- **Structure:**
  - `app.py`: Flask app and blueprint wiring
  - `templates/` and `static/`: HTML, CSS, JavaScript
  - Feature blueprints: `calls`, `schedule_call`, `users`, `ws_events`, `address_book`

📄 [Learn more](py_phone_caller_ui/README.md)

---

#### **celery_worker**
> **Background Task Processor**

Celery worker that processes scheduled calls and other background tasks from the Redis queue.

- **Key Responsibilities:**
  - Process scheduled call tasks
  - Execute background jobs
  - Integrate with `caller_register`, `asterisk_caller`, and `caller_scheduler`

---

### Shared Library

#### **py-phone-caller-utils**
> **Common Utilities & Extensions**

Shared Python library providing configuration, database access, telemetry, TTS helpers, and SMS integrations used across all services.

- **Modules:**
  - `config`: Dynaconf-based settings loader
  - `py_phone_caller_db`: Piccolo ORM models and query helpers
  - `py_phone_caller_voices`: TTS engine wrappers
  - `sms`: SMS integrations + **Rust modem engine**
  - `tasks`: Celery task helpers
  - `telemetry`: OpenTelemetry setup and instrumentation

📄 [Learn more](py-phone-caller-utils/README.md)

---

## 🔧 Configuration

All services use a unified configuration system powered by **Dynaconf**. Configuration files are stored in `config/`:

- **`settings.toml`**: Main configuration file
- **`.secrets.toml`**: Sensitive credentials (not committed to Git)

### Environment Variables
Services use these environment variables to locate configuration:

```bash
export CALLER_CONFIG_DIR=src/config
# OR
export CALLER_CONFIG=/path/to/settings.toml
```

---

## 🚀 Running Services

### Option 1: Docker Compose (Recommended)
See [`assets/docker-compose/README.md`](../assets/docker-compose/README.md) for Docker deployment.

### Option 2: Local Development
Each service can be run locally with:

```bash
export CALLER_CONFIG_DIR=src/config
export PYTHONPATH="src:$PYTHONPATH"
python3 -m <service_name>.<service_name>
```

**Example:**
```bash
python3 -m asterisk_caller.asterisk_caller
```

### Option 3: Ansible Deployment
See [`assets/ansible/deploy_all/README.md`](../assets/ansible/deploy_all/README.md) for production deployment.

---

## 🏗️ Building Docker Images

Build all images at once:

```bash
cd src
./build_all_images.sh
```

Or build individual services:

```bash
docker build -t asterisk-caller -f asterisk_caller/Dockerfile .
```

---

## 📊 Service Ports Reference

| Service | Port | Protocol | Description |
|---------|------|----------|-------------|
| `asterisk_caller` | 8081 | HTTP | Place calls |
| `generate_audio` | 8082 | HTTP | TTS audio generation |
| `caller_register` | 8083 | HTTP | Call registry |
| `caller_prometheus_webhook` | 8084 | HTTP | Prometheus webhooks |
| `caller_sms` | 8085 | HTTP | SMS gateway |
| `caller_scheduler` | 8086 | HTTP | Schedule calls |
| `caller_address_book` | 8087 | HTTP | Contact management |
| `py_phone_caller_ui` | 5000 | HTTP | Web UI |

---

## 🗄️ Infrastructure Dependencies

### Required External Services
- **Asterisk PBX**: v18/20+ with ARI enabled
- **PostgreSQL**: 12+ (Database)
- **Redis**: 6+ (Message queue & Celery backend)

### Optional Services
- **Prometheus + Alertmanager**: For alert-triggered calls
- **OpenTelemetry Collector**: For distributed tracing
- **Caddy**: Reverse proxy with automatic HTTPS

---

## 🛠️ Development Setup

### Prerequisites
- **Python**: 3.12+
- **pip-tools**: For dependency management
- **Rust**: 1.70+ (for SMS modem engine)
- **Maturin**: For building Rust extensions

### Install Dependencies

```bash
# Base dependencies
pip install -r requirements.txt

# Audio/TTS dependencies (large download)
pip install -r requirements-audio.txt

# Development tools
pip install -r requirements-dev.txt
```

### Build Rust Extensions

```bash
cd py-phone-caller-utils
maturin develop
```

---

## 📦 Deployment

### Production Deployment
Use Ansible for production deployments:

```bash
cd assets/ansible/deploy_all
ansible-playbook deploy_py-phone-caller_stack.yml
```

See the [deployment README](../assets/ansible/deploy_all/README.md) for detailed instructions.

### Docker Compose Deployment
For containerized deployments:

```bash
cd assets/docker-compose
docker compose up -d
```

See the [Docker Compose README](../assets/docker-compose/README.md) for configuration options.

---

## 🔐 Security Notes

- **Credentials**: Never commit `.secrets.toml` to Git
- **Vault**: Use Ansible Vault for production secrets
- **Firewall**: Only expose necessary ports (5000, 8081-8087)
- **HTTPS**: Use Caddy or nginx for SSL termination in production
- **User Permissions**: Services run as unprivileged `py-phone-caller` user

---

## 📚 Additional Resources

- **Main Project README**: [`../README.md`](../README.md)
- **Ansible Deployment**: [`../assets/ansible/deploy_all/README.md`](../assets/ansible/deploy_all/README.md)
- **Docker Compose**: [`../assets/docker-compose/README.md`](../assets/docker-compose/README.md)
- **Asterisk Role**: [`../assets/ansible/asterisk_py-phone-caller/README.md`](../assets/ansible/asterisk_py-phone-caller/README.md)

---

## 🧪 Testing

### Health Checks
Each service exposes a `/health` endpoint:

```bash
curl http://localhost:8083/health  # caller_register
curl http://localhost:8082/health  # generate_audio
curl http://localhost:8085/health  # caller_sms
# ... etc
```

### End-to-End Test

```bash
# Test emergency call flow
curl -X POST http://localhost:8081/place_call \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+1234567890",
    "message": "Test emergency alert"
  }'

# Check call was registered
curl http://localhost:8083/calls | jq
```

---

## 🤝 Contributing

Contributions are welcome! Each service is independently maintained and can be improved separately.

1. Make changes to individual services
2. Run tests locally
3. Build Docker images to verify
4. Submit pull requests with detailed descriptions

---

**Maintained by:** py-phone-caller team
**License:** Check main project repository
**Python Version:** 3.12+
**Architecture:** Cloud-Native Microservices
