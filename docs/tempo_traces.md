# 🔍 Grafana Tempo & Distributed Traces Guide

This guide explains how to collect, query, and visualize distributed OpenTelemetry traces across the **py-phone-caller** microservices stack using **Grafana Tempo**.

---

## 📑 Table of Contents

1. [Starting a Local Grafana + Tempo Stack](#1-starting-a-local-grafana--tempo-stack)
2. [Configuring py-phone-caller for OTLP gRPC Export](#2-configuring-py-phone-caller-for-otlp-grpc-export)
3. [Accessing Grafana & Tempo Datasource](#3-accessing-grafana--tempo-datasource)
4. [TraceQL Query Reference](#4-traceql-query-reference)
5. [Microservices Service Name Matrix](#5-microservices-service-name-matrix)
6. [Visualizing the Complete Call Lifecycle Trace](#6-visualizing-the-complete-call-lifecycle-trace)

---

## 1. Starting a Local Grafana + Tempo Stack

You can run a local Tempo and Grafana instance using Docker or Podman:

```yaml
# tempo-compose.yml
services:
  tempo:
    image: grafana/tempo:latest
    command: ["-config.file=/etc/tempo.yaml"]
    volumes:
      - ./tempo.yaml:/etc/tempo.yaml
    ports:
      - "3200:3200"  # Tempo HTTP
      - "4317:4317"  # OTLP gRPC
      - "4318:4318"  # OTLP HTTP

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      - GF_AUTH_ANONYMOUS_ENABLED=true
      - GF_AUTH_ANONYMOUS_ORG_ROLE=Admin
      - GF_AUTH_DISABLE_LOGIN_FORM=true
```

With minimal `tempo.yaml`:
```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: "0.0.0.0:4317"
        http:
          endpoint: "0.0.0.0:4318"

storage:
  trace:
    backend: local
    local:
      path: /tmp/tempo/traces
    wal:
      path: /tmp/tempo/wal
```

Start the stack:
```bash
docker compose -f tempo-compose.yml up -d
```

---

## 2. Configuring py-phone-caller for OTLP gRPC Export

Enable telemetry on your `py-phone-caller` services:

```bash
export ENABLE_TELEMETRY=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://<tempo-host>:4317
```

---

## 3. Accessing Grafana & Tempo Datasource

1. Open your browser to `http://localhost:3000`.
2. Go to **Connections** ➔ **Data sources** ➔ **Add data source** ➔ **Tempo**.
3. Set **URL** to `http://tempo:3200` (or `http://localhost:3200` if running outside container network).
4. Click **Save & test**.
5. Click **Explore** in the left sidebar and select **Tempo** as the datasource.

---

## 4. TraceQL Query Reference

Tempo uses **TraceQL** for fast span and trace search:

### Find all traces from a specific microservice:
```traceql
{resource.service.name = "asterisk_caller"}
```

```traceql
{resource.service.name = "py_phone_caller_ui"}
```

### Find traces containing errors:
```traceql
{status = error}
```

### Find slow call execution spans (> 2 seconds):
```traceql
{duration > 2s}
```

### Trace search for specific HTTP routes:
```traceql
{span.http.route = "/call_to_queue" || span.http.route = "/make_audio"}
```

### Complex multi-service trace query:
Find traces originating from the UI that caused an error in the Scheduler or Caller:
```traceql
{resource.service.name = "py_phone_caller_ui"} | {status = error}
```

---

## 5. Microservices Service Name Matrix

When querying in Grafana, filter by these registered service names:

| Service Name | Component Role |
| :--- | :--- |
| `py_phone_caller_ui` | Web Management Console & BFF |
| `asterisk_caller` | Outbound Call Queue & ARI Controller |
| `generate_audio` | Multi-engine TTS Neural Synthesis |
| `caller_register` | Database Migrations & Call State Registry |
| `caller_prometheus_webhook` | Alertmanager Webhook Receiver |
| `caller_sms` | SMS Gateway & Carrier Dispatcher |
| `caller_scheduler` | Delayed Call Scheduler |
| `caller_address_book` | Contact Directory & On-Call Rotation |
| `asterisk_ws_monitor` | Asterisk Stasis WebSocket Listener |
| `asterisk_recaller` | Call Retry & Backup Escalation Loop |
| `celery_worker` | Celery Background Task Consumer |

---

## 6. Visualizing the Complete Call Lifecycle Trace

In Grafana's waterfall view, an end-to-end incident call displays as a connected hierarchy:

```text
[ py_phone_caller_ui: POST /schedule_call ] (2.1s)
  ├── [ caller_scheduler: POST /schedule_call ] (15ms)
  │     └── [ Redis: Celery Task Enqueue ] (2ms)
  ├── [ celery_worker: do_this_call ] (1.8s)
  │     └── [ asterisk_caller: POST /call_to_queue ] (12ms)
  │           └── [ caller_address_book: GET /on_call_contact ] (4ms)
  │                 └── [ PostgreSQL: SELECT FROM address_book ] (1ms)
  └── [ asterisk_ws_monitor: StasisStart Event ] (850ms)
        ├── [ caller_register: POST /voice_message ] (5ms)
        ├── [ generate_audio: POST /make_audio ] (620ms)
        │     └── [ Neural Model: Kokoro-82M TTS Synthesis ] (580ms)
        └── [ asterisk_caller: POST /play ] (10ms)
```

Clicking any individual span reveals:
- Exact HTTP status codes and headers
- Database query strings and execution duration
- Python exception stack traces in case of failure
