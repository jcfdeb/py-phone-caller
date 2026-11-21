"""Unified CLI dispatcher for py-phone-caller microservices."""

from __future__ import annotations

import argparse
import importlib
import sys

from py_phone_caller import __version__


SERVICE_REGISTRY: dict[str, tuple[str, str, str]] = {
    "asterisk-caller": (
        "asterisk_caller.asterisk_caller",
        "main",
        "Outbound call origination and audio playback via Asterisk ARI (:8081)",
    ),
    "asterisk-ws-monitor": (
        "asterisk_ws_monitor.asterisk_ws_monitor",
        "cli_main",
        "Asterisk ARI WebSocket event monitor",
    ),
    "asterisk-recaller": (
        "asterisk_recaller.asterisk_recaller",
        "main",
        "Background worker for retrying unacknowledged calls and escalation",
    ),
    "caller-register": (
        "caller_register.caller_register",
        "main",
        "Central call attempt & status registry (:8083)",
    ),
    "generate-audio": (
        "generate_audio.generate_audio",
        "main",
        "Multi-engine neural TTS audio synthesis service (:8082)",
    ),
    "caller-sms": (
        "caller_sms.caller_sms",
        "main",
        "SMS dispatch service supporting Twilio and on-premise USB GSM modems (:8085)",
    ),
    "caller-prometheus-webhook": (
        "caller_prometheus_webhook.caller_prometheus_webhook",
        "main",
        "Prometheus Alertmanager webhook receiver (:8084)",
    ),
    "caller-scheduler": (
        "caller_scheduler.caller_scheduler",
        "main",
        "Celery-backed call scheduling service (:8086)",
    ),
    "caller-address-book": (
        "caller_address_book.caller_address_book",
        "main",
        "Contact and on-call rotation management service (:8087)",
    ),
    "celery-worker": (
        "celery_worker",
        "main",
        "Celery background worker for scheduled and priority calls",
    ),
    "ui": (
        "py_phone_caller_ui.app",
        "main",
        "Flask operations and management Web UI (:5000)",
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="py-phone-caller",
        description="Unified CLI for the py-phone-caller alerting platform.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"py-phone-caller {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-services", help="List available microservices and CLI entrypoints")

    run_parser = subparsers.add_parser("run", help="Run a specific py-phone-caller service")
    run_parser.add_argument(
        "service",
        choices=sorted(SERVICE_REGISTRY.keys()),
        help="Name of the service to start",
    )

    args = parser.parse_args(argv)
    if args.command == "list-services":
        for name, (mod_name, func_name, desc) in sorted(SERVICE_REGISTRY.items()):
            print(f"{name:28s}  ({mod_name}:{func_name}) - {desc}")
        return 0

    if args.command == "run":
        mod_name, func_name, _ = SERVICE_REGISTRY[args.service]
        module = importlib.import_module(mod_name)
        entry_fn = getattr(module, func_name)
        entry_fn()
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
