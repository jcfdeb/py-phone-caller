# 📊 OpenTelemetry & Observability Guide

This guide explains how to monitor, trace, and scrape metrics across the **py-phone-caller** (Release 1.0.0) microservices stack.

---

## 📑 Table of Contents

1. [Observability Architecture Overview](#1-observability-architecture-overview)
2. [Standardized Health & Liveness Probes](#2-standardized-health--liveness-probes)
3. [Prometheus Metrics Scraping (`/metrics`)](#3-prometheus-metrics-scraping-metrics)
4. [Distributed Tracing with OpenTelemetry (OTel)](#4-distributed-tracing-with-opentelemetry-otel)
5. [Starting a Local Jaeger or Grafana Tempo Collector](#5-starting-a-local-jaeger-or-grafana-tempo-collector)
6. [Automatic Code Instrumentation](#6-automatic-code-instrumentation)

---

## 1. Observability Architecture Overview

**py-phone-caller** provides a dual-mode observability architecture:
1. **Pull-based Metrics & Health Checks**: Every web-based service exposes standardized `/health` and Prometheus `/metrics` endpoints.
2. **Push-based Distributed Tracing**: When enabled, services push OpenTelemetry (OTel) spans over OTLP gRPC to a centralized trace collector (Jaeger or Grafana Tempo).

```text
[ Prometheus / Scrapers ] <--- HTTP GET /metrics & /health --- [ All py-phone-caller Microservices ]
                                                                       |
[ Grafana Tempo / Jaeger ] <--- OTLP gRPC (Port 4317) -----------------+
```

---

## 2. Standardized Health & Liveness Probes

Every HTTP microservice automatically registers uniform JSON health check endpoints via `py_phone_caller_utils.telemetry`:

- `GET /health`
- `GET /healthz`
- `GET /live`

### Response Payload Schema:
```json
{
  "status": "healthy",
  "service": "asterisk_caller",
  "version": "1.0.0"
}
```

These endpoints are used by Docker `HEALTHCHECK` directives, Kubernetes `livenessProbe`/`readinessProbe`, and the `verify_deployment.py` automated validator script.

---

## 3. Prometheus Metrics Scraping (`/metrics`)

Each HTTP microservice exposes Prometheus metrics on its primary port:

| Microservice | Port | Metric URL | Health URL |
| :--- | :---: | :--- | :--- |
| **`py_phone_caller_ui`** | `5000` | `http://<host>:5000/metrics` | `http://<host>:5000/health` |
| **`asterisk_caller`** | `8081` | `http://<host>:8081/metrics` | `http://<host>:8081/health` |
| **`generate_audio`** | `8082` | `http://<host>:8082/metrics` | `http://<host>:8082/health` |
| **`caller_register`** | `8083` | `http://<host>:8083/metrics` | `http://<host>:8083/health` |
| **`caller_prometheus_webhook`** | `8084` | `http://<host>:8084/metrics` | `http://<host>:8084/health` |
| **`caller_sms`** | `8085` | `http://<host>:8085/metrics` | `http://<host>:8085/health` |
| **`caller_scheduler`** | `8086` | `http://<host>:8086/metrics` | `http://<host>:8086/health` |
| **`caller_address_book`** | `8087` | `http://<host>:8087/metrics` | `http://<host>:8087/health` |

### Prometheus Scrape Configuration (`prometheus.yml`):
```yaml
scrape_configs:
  - job_name: 'py-phone-caller'
    scrape_interval: 15s
    static_configs:
      - targets:
          - '127.0.0.1:5000'
          - '127.0.0.1:8081'
          - '127.0.0.1:8082'
          - '127.0.0.1:8083'
          - '127.0.0.1:8084'
          - '127.0.0.1:8085'
          - '127.0.0.1:8086'
          - '127.0.0.1:8087'
```

---

## 4. Distributed Tracing with OpenTelemetry (OTel)

When enabled, requests crossing service boundaries (e.g. from UI ➔ Scheduler ➔ Caller ➔ PBX) propagate W3C trace context headers, generating a unified distributed trace.

### Configuration

#### Via Environment Variables (Recommended):
```bash
export ENABLE_TELEMETRY=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
export OTEL_SERVICE_NAME=py-phone-caller
```

#### Via `settings.toml`:
```toml
[telemetry]
enabled = true
endpoint = "http://jaeger:4317"
```

---

## 5. Starting a Local Jaeger or Grafana Tempo Collector

### Option A: Jaeger All-In-One (Lightweight)
Run Jaeger in Docker or Podman:
```bash
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 4317:4317 \
  -e COLLECTOR_OTLP_ENABLED=true \
  jaegertracing/all-in-one:latest
```
- **Web UI**: Open `http://localhost:16686` to inspect traces.

### Option B: Grafana + Tempo Stack
For detailed TraceQL query capabilities, see the [Grafana Tempo Traces Guide](tempo_traces.md).

---

## 6. Automatic Code Instrumentation

The shared telemetry module (`py_phone_caller_utils.telemetry`) automatically instruments:
- **`aiohttp`** (Asynchronous HTTP server & client sessions)
- **`Flask`** (Web UI endpoints and request lifecycle)
- **`AsyncPG` & `Piccolo`** (PostgreSQL database queries and execution time)
- **`Celery`** (Task enqueueing, latency, and background worker execution)
- **`Requests`** (Synchronous external HTTP calls)
- **Process Metrics** (CPU utilization, virtual memory RSS, Python GC collections)

No manual span code is required in business logic; all incoming and outgoing calls are traced out of the box.
