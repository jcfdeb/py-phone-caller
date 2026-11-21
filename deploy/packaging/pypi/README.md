# PyPI Packaging (`py-phone-caller`)

> **Centralized Step-by-Step Guide**: See **[`deploy/docs/06-pypi-and-systemd-deployment.md`](../../docs/06-pypi-and-systemd-deployment.md)** (and the **[Deployment Documentation Hub](../../docs/README.md)**) for the complete step-by-step Python wheel, virtual environment, and systemd deployment guide.

This directory contains the PyPI distribution builder (`build_pypi_packages.py`) and the `py-phone-caller` umbrella meta-package (`meta_package/`).

## Package Architecture

The release produces 13 publishable Python packages (both `.whl` and `.tar.gz` sdist):

| Package | CLI Entrypoint | Purpose |
| :--- | :--- | :--- |
| `py-phone-caller` | `py-phone-caller` | Meta-package with `[services]`, `[audio]`, `[ui]`, and `[all]` extras and unified CLI dispatcher |
| `py_phone_caller_utils` | *(library)* | Shared database, configuration, TTS, SMS, OIDC, and telemetry library |
| `asterisk-caller` | `ppc-asterisk-caller` | Asterisk ARI outbound call origination and playback service |
| `asterisk-recaller` | `ppc-asterisk-recaller` | Unacknowledged call retry and escalation worker |
| `asterisk-ws-monitor` | `ppc-asterisk-ws-monitor` | Asterisk ARI WebSocket event consumer |
| `caller-address-book` | `ppc-caller-address-book` | Contact and on-call rotation management service |
| `caller-prometheus-webhook` | `ppc-caller-prometheus-webhook` | Prometheus Alertmanager webhook service |
| `caller-register` | `ppc-caller-register` | Call attempt & status registry service |
| `caller-scheduler` | `ppc-caller-scheduler` | Celery-backed scheduled call service |
| `caller-sms` | `ppc-caller-sms` | Twilio and on-premise USB GSM modem SMS gateway |
| `celery-worker` | `ppc-celery-worker` | Celery worker for priority and scheduled call tasks |
| `generate-audio` | `ppc-generate-audio` | Multi-engine neural TTS synthesis service |
| `py-phone-caller-ui` | `ppc-ui` | Multilingual Flask management Web UI |

## Building & Verifying Distributions

From the repository root:

```bash
uv run python deploy/packaging/pypi/build_pypi_packages.py --force
```

All 26 artifacts (13 wheels + 13 sdists), `SHA256SUMS`, and `release.json` are written to `dist/pypi/`.

## Publishing to PyPI or Private Package Index

```bash
uv publish dist/pypi/*.whl dist/pypi/*.tar.gz
```
