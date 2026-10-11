# Turnkey Grafana Observability Dashboard for py-phone-caller

The `grafana-py-phone-caller.json` template provides a turnkey, production-grade NOC and SRE observability dashboard for `py-phone-caller` v1.2.0+.

---

## 1. Quick Import Guide

### Option A: Import via Grafana Web UI (Recommended)
1. Open your Grafana instance (e.g. `http://grafana.lan:3000`).
2. Navigate to **Dashboards** -> **New** -> **Import**.
3. Click **Upload dashboard JSON file** and select [`grafana-py-phone-caller.json`](file:///home/jcf/Workspace/PyCharm/py-phone-caller_release-github/deploy/dashboards/grafana-py-phone-caller.json).
4. In the **Prometheus** dropdown, select your active Prometheus datasource.
5. Click **Import**.

### Option B: Automated Import via Grafana HTTP API
```bash
curl -X POST http://admin:admin@grafana.lan:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @- << 'EOF'
{
  "dashboard": $(cat deploy/dashboards/grafana-py-phone-caller.json),
  "overwrite": true
}
EOF
```

---

## 2. Recommended Prometheus Scrape Configuration

Ensure your `prometheus.yml` contains the scrape targets for `py-phone-caller` microservices and Apache APISIX:

```yaml
scrape_configs:
  - job_name: "py-phone-caller-services"
    scrape_interval: 10s
    metrics_path: /metrics
    static_configs:
      - targets:
          - "127.0.0.1:8081" # asterisk_call / asterisk_caller
          - "127.0.0.1:8082" # generate_audio (TTS Engine)
          - "127.0.0.1:8083" # caller_register (DTMF Ack Registry)
          - "127.0.0.1:8084" # caller_prometheus_webhook (Alertmanager Ingestion)
          - "127.0.0.1:8085" # caller_sms (Hardware GSM / Twilio SMS)
          - "127.0.0.1:8086" # caller_scheduler (Scheduled Calls)
          - "127.0.0.1:8087" # caller_address_book (On-Call Contacts Roster)

  - job_name: "apisix-gateway"
    scrape_interval: 10s
    metrics_path: /apisix/prometheus/metrics
    static_configs:
      - targets:
          - "127.0.0.1:9091" # APISIX Internal Prometheus Exporter
```

---

## 3. Visualized Rows & Key Metrics

| Section | Visualized Panels | Key Metrics |
| :--- | :--- | :--- |
| **Executive Overview** | Total Dispatched, DTMF Ack %, SMS Delivery %, In-Flight Count | `py_phone_caller_calls_total`, `py_phone_caller_sms_dispatched_total` |
| **Call Lifecycle** | Throughput by status (`answered`, `failed`, `unacknowledged`, `busy`) | `sum(rate(py_phone_caller_calls_total[1m])) by (status)` |
| **DTMF Response Speed** | Responder Acknowledgment Latency (p50, p90, p99 quantiles) | `histogram_quantile(..., py_phone_caller_dtmf_ack_seconds_bucket)` |
| **TTS Performance** | Speech synthesis latency by engine (Kokoro, Piper, Facebook MMS, Silero) | `py_phone_caller_tts_duration_seconds_bucket` |
| **SMS Gateway Health** | SMS throughput, carrier failover rates, and modem health | `py_phone_caller_sms_dispatched_total{carrier=...}` |
| **API Gateway Ingress** | APISIX HTTP status code distribution (2xx, 4xx, 5xx) and latency | `apisix_http_status`, `apisix_http_latency_bucket` |
| **System Resources** | Process RSS memory and CPU utilization per microservice | `process_resident_memory_bytes`, `process_cpu_seconds_total` |
