# 🐳 Docker Compose: Complete py-phone-caller Stack

This directory contains the **Docker Compose configuration** for running the entire **py-phone-caller** emergency alert platform in containerized environments.

Perfect for development, testing, and self-hosted production deployments where you want all services orchestrated with a single command.

---

## 🎯 What's Included

This Docker Compose stack deploys **14 containers** comprising the complete py-phone-caller ecosystem:

### Infrastructure Services (3)
- **PostgreSQL 18**: Persistent database for call logs, contacts, and schedules
- **Redis 7**: Message queue and Celery task broker
- **Caddy 2**: Reverse proxy with automatic HTTPS

### Microservices (11)
- `caller_register` - Call registry and persistence
- `generate_audio` - Text-to-speech audio generation
- `caller_address_book` - Contact and on-call management
- `asterisk_caller` - Outbound call orchestration
- `asterisk_ws_monitor` - Real-time Asterisk event monitoring
- `asterisk_recaller` - Intelligent retry and escalation
- `caller_sms` - SMS gateway (Twilio + on-premise)
- `caller_prometheus_webhook` - Prometheus Alertmanager integration
- `caller_scheduler` - Celery-powered call scheduling
- `py_phone_caller_ui` - Web dashboard
- `celery_worker` - Background task processor

**Note:** This stack does **NOT** include Asterisk PBX itself. You must have an external Asterisk instance configured with ARI support.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      Docker Compose Stack                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Internet/LAN                                                   │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────┐                                                    │
│  │  Caddy  │  Reverse Proxy (Port 80/443)                       │
│  └────┬────┘                                                    │
│       │                                                         │
│       ▼                                                         │
│  ┌──────────────────────┐                                       │
│  │  py-phone-caller-ui  │  Web Dashboard (Port 5000)            │
│  └──────────┬───────────┘                                       │
│             │                                                   │
│             ▼                                                   │
│  ┌─────────────────────────────────────────┐                    │
│  │         Microservices Layer             │                    │
│  │                                         │                    │
│  │  ┌──────────────┐  ┌──────────────┐     │                    │
│  │  │   caller_*   │  │  asterisk_*  │     │                    │
│  │  │   services   │  │   services   │     │                    │
│  │  └──────┬───────┘  └───────┬──────┘     │                    │
│  │         │                  │            │                    │
│  └─────────┼──────────────────┼────────────┘                    │
│            │                  │                                 │
│            ▼                  ▼                                 │
│  ┌─────────────────────────────────────┐                        │
│  │        Infrastructure Layer         │                        │
│  │                                     │                        │
│  │  ┌──────────┐      ┌──────────┐     │                        │
│  │  │PostgreSQL│      │  Redis   │     │                        │
│  │  └──────────┘      └──────────┘     │                        │
│  └─────────────────────────────────────┘                        │
│                                                                 │
│  External Connection: Asterisk PBX (host.containers.internal)   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📋 Prerequisites

### System Requirements
- **Docker**: 20.10+ or Docker Desktop
- **Docker Compose**: v2.0+ (or `docker compose` plugin)
- **RAM**: 4GB minimum (8GB recommended for TTS models)
- **Storage**: 10GB free space
- **CPU**: 4+ cores recommended

### External Dependencies
- **Asterisk PBX**: Must be running and accessible from Docker containers
  - **ARI enabled** on port 8088
  - **WebSocket support** configured
  - See [`../ansible/asterisk_py-phone-caller/README.md`](../ansible/asterisk_py-phone-caller/README.md) for Asterisk setup

### Network Requirements
- **Host Network Access**: Containers use `host.containers.internal` to reach host services
- **Ports Available**:
  - `80`, `443` - Caddy reverse proxy
  - `5000` - Web UI (direct access)
  - `5432` - PostgreSQL (optional external access)
  - `6379` - Redis (optional external access)
  - `8081-8087` - Microservice APIs (optional direct access)

---

## 🚀 Quick Start

### 1. Create Environment Configuration

Create a `.env` file in this directory to customize your deployment:

```bash
# .env file
# PostgreSQL
POSTGRES_PASSWORD=your_secure_db_password

# Caddy (set domain for HTTPS, leave as default for local)
CADDY_DOMAIN_NAME=py-phone-caller.lan

# OpenTelemetry (optional)
ENABLE_TELEMETRY=false
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc

# Docker Registry (optional, for custom images)
MY_DOCKER_REGISTRY=localhost
VERSION=latest
```

**Default values** (if `.env` is not provided):
- `POSTGRES_PASSWORD`: `py_phone_caller_password`
- `CADDY_DOMAIN_NAME`: `py-phone-caller.lan`
- `ENABLE_TELEMETRY`: (not set, telemetry disabled)
- `MY_DOCKER_REGISTRY`: `localhost`
- `VERSION`: `latest`

### 2. Build Images

Build all service images from source:

```bash
docker compose build
```

This will:
- Build all 11 microservice images
- Compile Rust extensions (SMS modem engine)
- Download and cache TTS models
- Install Python dependencies

**Note:** First build can take 15-30 minutes depending on your system.

### 3. Start the Stack

```bash
docker compose up -d
```

This will:
- Start PostgreSQL and Redis
- Initialize database schemas
- Start all microservices with health checks
- Start Caddy reverse proxy
- Start web UI

### 4. Verify Deployment

Check that all services are healthy:

```bash
docker compose ps
```

Expected output:
```
NAME                         STATUS              PORTS
asterisk-caller              Up (healthy)        8081/tcp
asterisk-recaller            Up (healthy)
asterisk-ws-monitor          Up (healthy)
caller-address-book          Up (healthy)        8087/tcp
caller-prometheus-webhook    Up (healthy)        8084/tcp
caller-register              Up (healthy)        8083/tcp
caller-scheduler             Up (healthy)        8086/tcp
caller-sms                   Up (healthy)        8085/tcp
celery-worker                Up
generate-audio               Up (healthy)        8082/tcp
py-phone-caller-db           Up (healthy)        5432/tcp
py-phone-caller-redis        Up (healthy)        6379/tcp
py-phone-caller-ui           Up (healthy)        5000/tcp
caddy                        Up                  80/tcp, 443/tcp
```

### 5. Access the Web UI

Open your browser and navigate to:
- **Local (HTTP)**: http://localhost:5000
- **Via Caddy**: http://py-phone-caller.lan (or your configured domain)
- **HTTPS** (if domain + email configured): https://your-domain.com

---

## ⚙️ Configuration

### Service Dependencies

The compose file defines health checks and startup dependencies:

```yaml
# Example: asterisk_caller waits for these services to be healthy
depends_on:
  caller_register:
    condition: service_healthy
  generate_audio:
    condition: service_healthy
  caller_address_book:
    condition: service_healthy
```

This ensures services start in the correct order.

### Common Environment Variables

All services inherit these environment variables via YAML anchors:

```yaml
x-common-env: &common-env
  OTEL_EXPORTER_OTLP_ENDPOINT: ${OTEL_EXPORTER_OTLP_ENDPOINT}
  OTEL_EXPORTER_OTLP_PROTOCOL: ${OTEL_EXPORTER_OTLP_PROTOCOL}
  ENABLE_TELEMETRY: ${ENABLE_TELEMETRY}

x-db-common-env: &db-common-env
  <<: *common-env
  DYNACONF_DATABASE__DB_HOST: db
  DYNACONF_DATABASE__DB_USER: py_phone_caller
  DYNACONF_DATABASE__DB_PASSWORD: ${POSTGRES_PASSWORD}
  DYNACONF_DATABASE__DB_NAME: py_phone_caller
  PICCOLO_CONF: py_phone_caller_utils.py_phone_caller_db.piccolo_conf
```

### Service-Specific Overrides

Services use **Dynaconf environment variables** to override defaults:

```yaml
environment:
  DYNACONF_ASTERISK_CALL__ASTERISK_CALL_HOST: asterisk_caller
  DYNACONF_GENERATE_AUDIO__GENERATE_AUDIO_HOST: generate_audio
  DYNACONF_QUEUE__QUEUE_HOST: redis
  DYNACONF_QUEUE__QUEUE_URL: redis://redis:6379
```

### Accessing Host Services

Containers can reach services on the Docker host using:

```yaml
extra_hosts:
  - "host.containers.internal:host-gateway"
```

**Example:** Asterisk PBX running on host:
- Configure in your service: `DYNACONF_COMMONS__ASTERISK_HOST: host.containers.internal`

### Persistent Storage

Data is persisted using named volumes:

```yaml
volumes:
  pgdata:           # PostgreSQL database
  audio_data:       # Generated TTS audio files
  caddy_data:       # Caddy SSL certificates
  caddy_config:     # Caddy configuration
```

**Location:** Volumes are stored in Docker's volume directory (usually `/var/lib/docker/volumes/`)

---

## 🎮 Usage

### Start Services

```bash
# Start all services in background
docker compose up -d

# Start with logs visible
docker compose up

# Start only specific services
docker compose up -d caller_register generate_audio
```

### Stop Services

```bash
# Stop all services (keeps data)
docker compose down

# Stop and remove volumes (deletes data!)
docker compose down -v
```

### View Logs

```bash
# View all logs
docker compose logs -f

# View logs for specific service
docker compose logs -f asterisk_caller

# View last 50 lines
docker compose logs --tail=50 py_phone_caller_ui
```

### Restart Services

```bash
# Restart all services
docker compose restart

# Restart specific service
docker compose restart asterisk_caller
```

### Rebuild and Update

```bash
# Rebuild images and restart
docker compose up -d --build

# Pull latest images (if using registry)
docker compose pull
docker compose up -d
```

---

## 🔧 Customization

### Enable SMS via USB Modem (On-Premise)

To use a USB GSM modem instead of Twilio:

1. **Identify the modem device:**
   ```bash
   ls -l /dev/ttyUSB*
   ```

2. **Uncomment the device mapping in `docker-compose.yml`:**
   ```yaml
   caller_sms:
     devices:
       - "/dev/ttyUSB2:/dev/ttyUSB2"  # Adjust device number
   ```

3. **Configure in your environment or settings.toml:**
   ```bash
   DYNACONF_CALLER_SMS__CALLER_SMS_CARRIER=on_premise
   DYNACONF_CALLER_SMS__MODEMS__0__PORT=/dev/ttyUSB2
   ```

4. **Restart the service:**
   ```bash
   docker compose restart caller_sms
   ```

### Enable HTTPS with Let's Encrypt

To enable automatic HTTPS via Caddy:

1. **Update `.env` file:**
   ```bash
   CADDY_DOMAIN_NAME=alerts.yourcompany.com
   CADDY_EMAIL=admin@yourcompany.com
   ```

2. **Ensure DNS points to your server:**
   ```bash
   dig +short alerts.yourcompany.com
   # Should return your server's public IP
   ```

3. **Restart Caddy:**
   ```bash
   docker compose restart caddy
   ```

Caddy will automatically obtain and renew SSL certificates from Let's Encrypt.

### Use Custom Docker Registry

To push/pull images from a private registry:

1. **Update `.env` file:**
   ```bash
   MY_DOCKER_REGISTRY=registry.yourcompany.com
   VERSION=v1.2.3
   ```

2. **Build and push:**
   ```bash
   docker compose build
   docker compose push
   ```

3. **Pull on another host:**
   ```bash
   docker compose pull
   docker compose up -d
   ```

### Enable OpenTelemetry Tracing

To enable distributed tracing:

1. **Update `.env` file:**
   ```bash
   ENABLE_TELEMETRY=true
   OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
   OTEL_EXPORTER_OTLP_PROTOCOL=grpc
   ```

2. **Add OpenTelemetry Collector to compose:**
   ```yaml
   otel_collector:
     image: otel/opentelemetry-collector-contrib:latest
     ports:
       - "4317:4317"
     volumes:
       - ./otel-collector-config.yaml:/etc/otel-collector-config.yaml
     command: ["--config=/etc/otel-collector-config.yaml"]
   ```

3. **Restart services:**
   ```bash
   docker compose up -d
   ```

---

## 📊 Monitoring & Health Checks

### Service Health Checks

Health checks are configured for all services:

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U py_phone_caller"]
  interval: 10s
  timeout: 5s
  retries: 5
```

View health status:
```bash
docker compose ps
```

### Manual Health Checks

Test individual service endpoints:

```bash
# PostgreSQL
docker compose exec db pg_isready -U py_phone_caller

# Redis
docker compose exec redis redis-cli ping

# Microservices
curl http://localhost:8083/health  # caller_register
curl http://localhost:8082/health  # generate_audio
curl http://localhost:8085/health  # caller_sms
```

### Resource Usage

Monitor container resource usage:

```bash
docker stats
```

---

## 🛠️ Troubleshooting

### Services Won't Start

**Symptoms:** Containers exit immediately or show unhealthy status

**Solutions:**
1. Check logs:
   ```bash
   docker compose logs <service_name>
   ```

2. Verify database is ready:
   ```bash
   docker compose exec db pg_isready -U py_phone_caller
   ```

3. Check for port conflicts:
   ```bash
   netstat -tlnp | grep -E ':(5000|5432|6379|808[1-7])'
   ```

4. Ensure sufficient disk space:
   ```bash
   df -h
   ```

### Database Connection Errors

**Symptoms:** Services can't connect to PostgreSQL

**Solutions:**
1. Verify PostgreSQL is running:
   ```bash
   docker compose ps db
   ```

2. Check database credentials in `.env`:
   ```bash
   cat .env | grep POSTGRES_PASSWORD
   ```

3. Test database connection:
   ```bash
   docker compose exec db psql -U py_phone_caller -d py_phone_caller -c '\l'
   ```

### Asterisk Connection Issues

**Symptoms:** Services can't reach Asterisk PBX on host

**Solutions:**
1. Verify Asterisk is running on host:
   ```bash
   asterisk -rx "core show version"
   ```

2. Test ARI connectivity from container:
   ```bash
   docker compose exec asterisk_caller curl -v http://host.containers.internal:8088/ari/asterisk/info
   ```

3. Check firewall rules:
   ```bash
   sudo firewall-cmd --list-all
   ```

4. Ensure `host.containers.internal` resolves:
   ```bash
   docker compose exec asterisk_caller ping -c 1 host.containers.internal
   ```

### Audio Generation Fails

**Symptoms:** TTS audio generation errors in `generate_audio` service

**Solutions:**
1. Check available disk space (models are large):
   ```bash
   df -h
   ```

2. Verify audio volume exists:
   ```bash
   docker volume inspect docker-compose_audio_data
   ```

3. Check logs for model download errors:
   ```bash
   docker compose logs generate_audio | grep -i download
   ```

4. Increase container memory if needed:
   ```yaml
   generate_audio:
     mem_limit: 2g
   ```

### SMS Not Sending

**Symptoms:** SMS messages not being delivered

**Solutions:**
1. Verify SMS carrier configuration:
   ```bash
   docker compose logs caller_sms | grep -i carrier
   ```

2. If using Twilio, check credentials
3. If using on-premise, verify USB device is mapped:
   ```bash
   docker compose exec caller_sms ls -l /dev/ttyUSB*
   ```

### Web UI Not Accessible

**Symptoms:** Can't access http://localhost:5000

**Solutions:**
1. Check if UI is running:
   ```bash
   docker compose ps py_phone_caller_ui
   ```

2. Verify port mapping:
   ```bash
   docker compose port py_phone_caller_ui 5000
   ```

3. Check Caddy reverse proxy:
   ```bash
   docker compose logs caddy
   ```

4. Test direct access:
   ```bash
   curl -I http://localhost:5000
   ```

---

## 🔐 Security Considerations

### Production Hardening

1. **Use Strong Passwords:**
   ```bash
   # Generate secure password
   openssl rand -base64 32
   ```

2. **Restrict External Access:**
   Remove port mappings for services that don't need external access:
   ```yaml
   # Remove these lines for internal-only services
   ports:
     - "8083:8083"
   ```

3. **Enable TLS:**
   Configure Caddy with a real domain and email for Let's Encrypt

4. **Network Isolation:**
   Create dedicated Docker networks:
   ```yaml
   networks:
     frontend:
     backend:
   ```

5. **Secrets Management:**
   Use Docker secrets instead of environment variables:
   ```yaml
   secrets:
     db_password:
       file: ./secrets/db_password.txt
   ```

### Environment File Security

Never commit `.env` to Git:

```bash
# .gitignore
.env
.secrets.toml
```

---

## 📚 Additional Resources

- **Source Code Documentation**: [`../../src/README.md`](../../src/README.md)
- **Ansible Deployment**: [`../ansible/deploy_all/README.md`](../ansible/deploy_all/README.md)
- **Asterisk Setup**: [`../ansible/asterisk_py-phone-caller/README.md`](../ansible/asterisk_py-phone-caller/README.md)
- **Main Project README**: [`../../README.md`](../../README.md)

---

## 🆘 Support

### View Compose Configuration

```bash
# View final resolved configuration
docker compose config

# Validate configuration
docker compose config --quiet
```

### Clean Start

```bash
# Stop and remove everything
docker compose down -v --remove-orphans

# Rebuild from scratch
docker compose build --no-cache

# Start fresh
docker compose up -d
```

### Backup Data

```bash
# Backup PostgreSQL
docker compose exec db pg_dump -U py_phone_caller py_phone_caller > backup.sql

# Backup volumes
docker run --rm -v docker-compose_pgdata:/data -v $(pwd):/backup \
  alpine tar czf /backup/pgdata-backup.tar.gz /data
```

---

**Maintained by:** py-phone-caller team
**Docker Compose Version:** 3.9
**Minimum Docker Version:** 20.10+
**Platform:** Linux, macOS, Windows (WSL2)
