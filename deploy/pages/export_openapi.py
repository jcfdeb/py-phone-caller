#!/usr/bin/env python3
"""Pure-stdlib OpenAPI 3.0.3 specification exporter for all 8 Python HTTP services + openalertd."""

from __future__ import annotations

import ast
import importlib.util
import json
import tomllib
from pathlib import Path
from typing import Any

SERVICE_META: list[dict[str, Any]] = [
    {
        "id": "py_phone_caller_ui",
        "label": "Web UI & NOC Center",
        "port": 5000,
        "gateway_prefix": "/",
        "source": "src/py_phone_caller_ui/openapi.py",
        "kind": "ui",
    },
    {
        "id": "openalertd",
        "label": "OpenAlert Mesh Daemon",
        "port": 8090,
        "gateway_prefix": "/openalert",
        "source": "src/openalert/src/ingress/rest.rs",
        "kind": "rust",
    },
    {
        "id": "asterisk_caller",
        "label": "asterisk_caller",
        "port": 8081,
        "gateway_prefix": "/api/v1/telephony",
        "source": "src/asterisk_caller/routes.py",
        "constants": "src/asterisk_caller/constants.py",
        "kind": "aiohttp",
    },
    {
        "id": "generate_audio",
        "label": "generate_audio (TTS)",
        "port": 8082,
        "gateway_prefix": "/api/v1/audio",
        "source": "src/generate_audio/generate_audio.py",
        "constants": "src/generate_audio/constants.py",
        "kind": "aiohttp",
    },
    {
        "id": "caller_register",
        "label": "caller_register",
        "port": 8083,
        "gateway_prefix": "/api/v1/registry",
        "source": "src/caller_register/routes.py",
        "constants": "src/caller_register/constants.py",
        "kind": "aiohttp",
    },
    {
        "id": "caller_prometheus_webhook",
        "label": "caller_prometheus_webhook",
        "port": 8084,
        "gateway_prefix": "/api/v1/alerts",
        "source": "src/caller_prometheus_webhook/routes.py",
        "constants": "src/caller_prometheus_webhook/constants.py",
        "kind": "aiohttp",
    },
    {
        "id": "caller_sms",
        "label": "caller_sms",
        "port": 8085,
        "gateway_prefix": "/api/v1/sms",
        "source": "src/caller_sms/routes.py",
        "constants": "src/caller_sms/constants.py",
        "kind": "aiohttp",
    },
    {
        "id": "caller_scheduler",
        "label": "caller_scheduler",
        "port": 8086,
        "gateway_prefix": "/api/v1/schedules",
        "source": "src/caller_scheduler/routes.py",
        "constants": "src/caller_scheduler/constants.py",
        "kind": "aiohttp",
    },
    {
        "id": "caller_address_book",
        "label": "caller_address_book",
        "port": 8087,
        "gateway_prefix": "/api/v1/contacts",
        "source": "src/caller_address_book/routes.py",
        "constants": "src/caller_address_book/constants.py",
        "kind": "aiohttp",
    },
]


def _load_route_constants(repo_root: Path, constants_rel: str | None) -> dict[str, Any]:
    """Resolve route string constants from settings.toml + service constants.py without importing runtime deps."""
    settings_path = repo_root / "src" / "config" / "settings.toml"
    cfg = tomllib.loads(settings_path.read_text(encoding="utf-8")) if settings_path.is_file() else {}

    env: dict[str, Any] = {
        "ASTERISK_CALL_APP_ROUTE_PLACE_CALL": cfg.get("asterisk_call", {}).get("asterisk_call_app_route_place_call", "place_call"),
        "ASTERISK_CALL_APP_ROUTE_CALL_TO_QUEUE": cfg.get("asterisk_call", {}).get("asterisk_call_app_route_call_to_queue", "call_to_queue"),
        "ASTERISK_CALL_APP_ROUTE_PLAY": cfg.get("asterisk_call", {}).get("asterisk_call_app_route_play", "play"),
        "GENERATE_AUDIO_APP_ROUTE": cfg.get("generate_audio", {}).get("generate_audio_app_route", "make_audio"),
        "IS_AUDIO_READY_ENDPOINT": cfg.get("generate_audio", {}).get("is_audio_ready_endpoint", "is_audio_ready"),
        "LANGUAGES_ENDPOINT": "languages",
        "SERVING_AUDIO_FOLDER": cfg.get("generate_audio", {}).get("serving_audio_folder", "audio"),
        "CALL_REGISTER_APP_ROUTE_REGISTER_CALL": cfg.get("call_register", {}).get("call_register_app_route_register_call", "register_call"),
        "CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE": cfg.get("call_register", {}).get("call_register_app_route_voice_message", "msg"),
        "CALL_REGISTER_APP_ROUTE_ACKNOWLEDGE": cfg.get("call_register", {}).get("call_register_app_route_acknowledge", "ack"),
        "CALL_REGISTER_APP_ROUTE_HEARD": cfg.get("call_register", {}).get("call_register_app_route_heard", "heard"),
        "CALL_REGISTER_SCHEDULED_CALL_APP_ROUTE": cfg.get("call_register", {}).get("call_register_scheduled_call_app_route", "scheduled_call"),
        "PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_ONLY": cfg.get("caller_prometheus_webhook", {}).get("prometheus_webhook_app_route_call_only", "call_only"),
        "PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_ONLY": cfg.get("caller_prometheus_webhook", {}).get("prometheus_webhook_app_route_sms_only", "sms_only"),
        "PROMETHEUS_WEBHOOK_APP_ROUTE_SMS_BEFORE_CALL": cfg.get("caller_prometheus_webhook", {}).get("prometheus_webhook_app_route_sms_before_call", "sms_before_call"),
        "PROMETHEUS_WEBHOOK_APP_ROUTE_CALL_AND_SMS": cfg.get("caller_prometheus_webhook", {}).get("prometheus_webhook_app_route_call_and_sms", "call_and_sms"),
        "CALLER_SMS_APP_ROUTE": cfg.get("caller_sms", {}).get("caller_sms_app_route", "send_sms"),
        "SCHEDULED_CALL_APP_ROUTE": cfg.get("scheduled_calls", {}).get("scheduled_call_app_route", "schedule_call"),
        "CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT": cfg.get("caller_address_book", {}).get("caller_address_book_route_add_contact", "contacts"),
        "CALLER_ADDRESS_BOOK_ROUTE_LIST_CONTACTS": cfg.get("caller_address_book", {}).get("caller_address_book_route_list_contacts", "contacts"),
        "CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT": cfg.get("caller_address_book", {}).get("caller_address_book_route_on_call_contact", "on_call"),
    }

    if constants_rel and (repo_root / constants_rel).is_file():
        tree = ast.parse((repo_root / constants_rel).read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, (str, int, float, bool)):
                    env[name] = node.value.value
    return env


def _eval_ast_expr(node: ast.AST, env: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for val in node.values:
            if isinstance(val, ast.Constant):
                parts.append(str(val.value))
            elif isinstance(val, ast.FormattedValue):
                parts.append(str(_eval_ast_expr(val.value, env)))
        return "".join(parts)
    if isinstance(node, ast.Dict):
        out: dict[Any, Any] = {}
        for k, v in zip(node.keys, node.values, strict=True):
            if k is not None:
                out[_eval_ast_expr(k, env)] = _eval_ast_expr(v, env)
        return out
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_ast_expr(el, env) for el in node.elts]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_ast_expr(node.operand, env)
    raise ValueError(f"Unsupported AST expression in OpenAPI spec: {ast.dump(node)}")


def _standard_observability_paths(service_id: str, version: str) -> dict[str, Any]:
    return {
        "/health": {
            "get": {
                "tags": ["Observability"],
                "summary": "Liveness probe (/health, /healthz, /live)",
                "responses": {
                    "200": {
                        "description": "Process is alive",
                        "content": {
                            "application/json": {
                                "example": {"status": "healthy", "service": service_id, "version": version}
                            }
                        },
                    }
                },
            }
        },
        "/ready": {
            "get": {
                "tags": ["Observability"],
                "summary": "Dependency-aware readiness probe",
                "responses": {
                    "200": {"description": "Downstream dependencies (PostgreSQL / Redis / Asterisk ARI) ready"},
                    "503": {"description": "Dependency check degraded"},
                },
            }
        },
        "/metrics": {
            "get": {
                "tags": ["Observability"],
                "summary": "Prometheus text-format telemetry metrics",
                "responses": {"200": {"description": "Prometheus exposition payload"}},
            }
        },
    }


def _extract_aiohttp_openapi(repo_root: Path, meta: dict[str, Any], version: str) -> dict[str, Any]:
    src_file = repo_root / meta["source"]
    env = _load_route_constants(repo_root, meta.get("constants"))
    tree = ast.parse(src_file.read_text(encoding="utf-8"))

    # Also capture simple dict/constant assignments inside route setup functions (e.g. alertmanager_body)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target_name = node.targets[0].id
            if target_name not in env:
                try:
                    env[target_name] = _eval_ast_expr(node.value, env)
                except ValueError:
                    pass

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "setup_swagger_routes":
            kw = {k.arg: k.value for k in node.keywords if k.arg is not None}
            title = str(_eval_ast_expr(kw["service_name"], env))
            description = str(_eval_ast_expr(kw["description"], env))
            paths = dict(_eval_ast_expr(kw["paths"], env))
            for obs_path, obs_item in _standard_observability_paths(meta["id"], version).items():
                paths.setdefault(obs_path, obs_item)
            return {
                "openapi": "3.0.3",
                "info": {"title": title, "description": description, "version": version},
                "servers": [
                    {"url": f"http://127.0.0.1:{meta['port']}", "description": "Direct service listener"},
                    {"url": f"https://alerts.example.com{meta['gateway_prefix']}", "description": "Via APISIX Gateway"},
                ],
                "paths": paths,
            }
    raise RuntimeError(f"setup_swagger_routes(...) not found in {src_file}")


def _extract_ui_openapi(repo_root: Path, meta: dict[str, Any]) -> dict[str, Any]:
    spec_path = repo_root / meta["source"]
    mod_spec = importlib.util.spec_from_file_location("_ppc_ui_openapi", spec_path)
    if mod_spec is None or mod_spec.loader is None:
        raise RuntimeError(f"Unable to load {spec_path}")
    module = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(module)
    schema: dict[str, Any] = module.get_ui_openapi_spec()
    schema.setdefault(
        "servers",
        [
            {"url": "http://127.0.0.1:5000", "description": "Direct Flask UI listener"},
            {"url": "https://alerts.example.com", "description": "Via Edge TLS / APISIX Gateway"},
        ],
    )
    return schema


def _build_openalertd_openapi(version: str) -> dict[str, Any]:
    """Canonical OpenAPI 3.0.3 specification matching src/openalert/src/ingress/rest.rs Axum routes."""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "openalertd (OpenAlert Mesh Daemon)",
            "description": (
                "Autonomous Rust multi-protocol alert router bridging REST, Prometheus Alertmanager, "
                "Nostr (NIP-ALERT Kind 30000 & 0xChat NIP-17 C2), BitChat BLE (Noise XX), "
                "LoRa 868 MHz RF peering, GSM AT SMS, and Emergency /sos Wi-Fi Captive Portals."
            ),
            "version": version,
            "license": {"name": "MIT OR Apache-2.0"},
        },
        "servers": [
            {"url": "http://127.0.0.1:8090", "description": "Default openalertd HTTP & NOC Dashboard listener"},
        ],
        "paths": {
            "/api/v1/alerts": {
                "post": {
                    "tags": ["Alert Ingress"],
                    "summary": "Ingest a native OpenAlert JSON event",
                    "description": "Validates optional Basic/Bearer/HMAC credentials, deduplicates, persists to SQLite spool, and routes across Nostr, BitChat BLE, LoRa peering, GSM SMS, and py-phone-caller webhooks.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "example": {
                                    "id": "ups-room-temp-01",
                                    "severity": "critical",
                                    "summary": "Core rack temperature exceeded 42C",
                                    "source": "rest",
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Alert accepted and queued for multi-transport dispatch"},
                        "401": {"description": "Invalid Bearer token, Basic auth, or HMAC-SHA256 signature"},
                    },
                }
            },
            "/api/v1/webhook/prometheus": {
                "post": {
                    "tags": ["Alert Ingress"],
                    "summary": "Ingest a Prometheus Alertmanager v4 webhook payload",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "example": {
                                    "status": "firing",
                                    "alerts": [
                                        {
                                            "status": "firing",
                                            "labels": {"alertname": "GridPowerLost", "severity": "critical"},
                                            "annotations": {"summary": "Mains AC lost on substation B"},
                                        }
                                    ],
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "Alertmanager batch ingested"}},
                }
            },
            "/sos": {
                "get": {
                    "tags": ["Emergency SOS Portal"],
                    "summary": "Render the isolated mobile-first Emergency SOS Web Portal HTML",
                    "responses": {"200": {"description": "Self-contained HTML5 SOS dispatch form"}},
                }
            },
            "/api/v1/sos/challenge": {
                "get": {
                    "tags": ["Emergency SOS Portal"],
                    "summary": "Generate an offline 4-digit distorted SVG CAPTCHA challenge signed with HMAC-SHA256",
                    "responses": {"200": {"description": "Inline SVG CAPTCHA image and signed one-time token"}},
                }
            },
            "/api/v1/sos/trigger": {
                "post": {
                    "tags": ["Emergency SOS Portal"],
                    "summary": "Verify offline CAPTCHA nonce and dispatch a civilian/field SOS alert",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "example": {
                                    "category": "MEDICAL",
                                    "sender": "Sector 4 Aid Post",
                                    "message": "Urgent medical evacuation needed at trailhead marker 12",
                                    "captcha_token": "<SIGNED_TOKEN>",
                                    "captcha_answer": "4821",
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "SOS alert verified and broadcast across mesh/telephony"},
                        "400": {"description": "Invalid CAPTCHA or rate-limit cooldown active"},
                    },
                }
            },
            "/api/v1/sos/zap-invoice": {
                "post": {
                    "tags": ["Emergency SOS Portal"],
                    "summary": "Create a signed NIP-57 Kind 9734 Zap Request & BOLT-11 Lightning invoice",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "example": {
                                    "amount_sats": 1000,
                                    "category": "EMERGENCY",
                                    "sender": "Field Operator",
                                    "message": "Bridge washed out on highway sector 7",
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "BOLT-11 invoice + inline SVG QR metadata"}},
                }
            },
            "/api/v1/sos/zap-status/{zap_request_id}": {
                "get": {
                    "tags": ["Emergency SOS Portal"],
                    "summary": "Poll 6-stage cryptographic verification status of a NIP-57 Kind 9735 Zap Receipt",
                    "parameters": [
                        {
                            "name": "zap_request_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "example": "d4e5f6a7b8c90123456789abcdef0123"},
                        }
                    ],
                    "responses": {"200": {"description": "Zap settlement and Nostr/0xChat dispatch status"}},
                }
            },
            "/api/v1/status": {
                "get": {
                    "tags": ["Mesh & Telemetry"],
                    "summary": "Daemon runtime status, uptime, relay quorum, LoRa duty-cycle, and spool counts",
                    "responses": {"200": {"description": "JSON node health summary"}},
                }
            },
            "/api/v1/events/live": {
                "get": {
                    "tags": ["Mesh & Telemetry"],
                    "summary": "Server-Sent Events (SSE) real-time NOC telemetry stream (2s cadence)",
                    "responses": {"200": {"description": "text/event-stream live diagnostics"}},
                }
            },
            "/api/v1/peers": {
                "get": {
                    "tags": ["Peering & Spool"],
                    "summary": "List LAN, WireGuard, and LoRa RF peers, distance-vector routes, RSSI/SNR, and circuit breakers",
                    "responses": {"200": {"description": "Peer link state array"}},
                }
            },
            "/api/v1/peers/{name}/reset": {
                "post": {
                    "tags": ["Peering & Spool"],
                    "summary": "Manually reset a tripped peer circuit breaker back to Closed",
                    "parameters": [
                        {"name": "name", "in": "path", "required": True, "schema": {"type": "string", "example": "lora-hilltop-01"}}
                    ],
                    "responses": {"200": {"description": "Peer circuit breaker reset"}},
                }
            },
            "/api/v1/spool": {
                "get": {
                    "tags": ["Peering & Spool"],
                    "summary": "Inspect pending store-and-forward alerts in the embedded SQLite flash spool",
                    "responses": {"200": {"description": "Pending spool records"}},
                }
            },
            "/api/v1/spool/purge": {
                "post": {
                    "tags": ["Peering & Spool"],
                    "summary": "Purge pending records from the persistent SQLite flash spool",
                    "responses": {"200": {"description": "Spool purged"}},
                }
            },
            "/api/v1/sms/status": {
                "get": {
                    "tags": ["Cellular GSM & BitChat BLE"],
                    "summary": "Query USB GSM/LTE AT modem link state, signal quality, and recipient ACLs",
                    "responses": {"200": {"description": "Modem status JSON"}},
                }
            },
            "/api/v1/sms/history": {
                "get": {
                    "tags": ["Cellular GSM & BitChat BLE"],
                    "summary": "Query inbound and outbound UCS-2 SMS journal from SQLite",
                    "responses": {"200": {"description": "SMS history entries"}},
                }
            },
            "/api/v1/sms/send": {
                "post": {
                    "tags": ["Cellular GSM & BitChat BLE"],
                    "summary": "Send an outbound UTF-8 / UCS-2 SMS via the attached USB GSM AT modem",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "example": {"recipient": "+39000000000", "message": "Field test via openalertd GSM"}
                            }
                        },
                    },
                    "responses": {"200": {"description": "SMS transmitted"}},
                }
            },
            "/api/v1/bitchat/status": {
                "get": {
                    "tags": ["Cellular GSM & BitChat BLE"],
                    "summary": "Inspect BlueZ BLE GATT peripheral status and discovered BitChat mesh peers",
                    "responses": {"200": {"description": "BitChat radar status"}},
                }
            },
            "/api/v1/bitchat/broadcast": {
                "post": {
                    "tags": ["Cellular GSM & BitChat BLE"],
                    "summary": "Broadcast an advisory frame across the local BitChat Bluetooth LE mesh",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"example": {"message": "Evacuate sector B immediately"}}},
                    },
                    "responses": {"200": {"description": "BLE mesh frame queued"}},
                }
            },
            "/api/v1/config": {
                "get": {
                    "tags": ["Configuration & Crypto Tools"],
                    "summary": "Read active openalertd TOML configuration",
                    "responses": {"200": {"description": "Sanitized TOML configuration"}},
                },
                "post": {
                    "tags": ["Configuration & Crypto Tools"],
                    "summary": "Validate, back up (.bak), and persist updated TOML configuration",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "example": {"toml": '[node]\nname = "edge-01"\n\n[rest]\nlisten_port = 8090\n'}
                            }
                        },
                    },
                    "responses": {"200": {"description": "Configuration saved"}},
                },
            },
            "/api/v1/config/validate": {
                "post": {
                    "tags": ["Configuration & Crypto Tools"],
                    "summary": "Dry-run validate a candidate TOML configuration string",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "example": {"toml": '[node]\nname = "edge-01"\n\n[sos]\nenabled = true\npath = "/sos"\n'}
                            }
                        },
                    },
                    "responses": {"200": {"description": "Validation result"}},
                }
            },
            "/api/v1/tools/generate-keypair": {
                "post": {
                    "tags": ["Configuration & Crypto Tools"],
                    "summary": "Generate a BIP-340 Secp256k1 Nostr keypair (nsec / npub / hex)",
                    "responses": {"200": {"description": "Generated keypair"}},
                }
            },
            "/api/v1/tools/hash-password": {
                "post": {
                    "tags": ["Configuration & Crypto Tools"],
                    "summary": "Compute SHA-256 credential hash for [rest.auth], [dashboard.auth], or [sos.auth]",
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"example": {"password": "<PASSWORD>"}}},
                    },
                    "responses": {"200": {"description": "Hex SHA-256 digest"}},
                }
            },
            "/health": {
                "get": {
                    "tags": ["Observability"],
                    "summary": "Daemon liveness probe",
                    "responses": {"200": {"description": "openalertd healthy"}},
                }
            },
        },
    }


_FIELD_EXAMPLES: dict[str, Any] = {
    "phone": "1000",
    "phone_number": "1000",
    "sms_phone_number": "+39000000000",
    "recipient": "+39000000000",
    "sender": "+39000000000",
    "message": "Critical alert: primary database CPU at 98%",
    "lang": "en",
    "lang_code": "en",
    "language": "en",
    "engine": "kokoro_tts",
    "speed": 1.0,
    "msg_chk_sum": "9f86d081884c7d659a2feaa0c55ad015",
    "asterisk_chan": "1732660000.42",
    "filename": "9f86d081884c7d659a2feaa0c55ad015_en.wav",
    "contact_id": 1,
    "user_id": 2,
    "id": 1,
    "ids": [1, 2],
    "call_ids": [101, 102],
    "name": "Alice Rossi",
    "email": "operator@example.com",
    "username": "operator@example.com",
    "password": "<PASSWORD>",
    "new_password": "<PASSWORD>",
    "confirm_password": "<PASSWORD>",
    "current_password": "<PASSWORD>",
    "role": "operator",
    "priority": 5,
    "limit": 25,
    "page": 1,
    "per_page": 25,
    "q": "database",
    "search": "database",
    "status": "acknowledged",
    "service_slug": "telephony",
    "scheduled_at": "2026-12-01 09:30:00",
    "date": "2026-12-01",
    "time": "09:30",
    "month": "2026-12",
    "code": "auth_code_sample",
    "state": "csrf_state_token",
}


def _synthesize_schema_example(
    schema: dict[str, Any] | None,
    components: dict[str, Any],
    field_name: str = "",
    depth: int = 0,
) -> Any:
    """Recursively synthesize a concrete, sanitized example value from an OpenAPI 3.0 schema."""
    if not isinstance(schema, dict) or depth > 6:
        return _FIELD_EXAMPLES.get(field_name, "example")

    if (
        field_name
        and any(tok in field_name.lower() for tok in ("password", "secret", "token"))
        and schema.get("type") in (None, "string")
    ):
        return "<PASSWORD>"

    if "$ref" in schema:
        ref = str(schema["$ref"])
        if ref.startswith("#/components/schemas/"):
            ref_name = ref.removeprefix("#/components/schemas/")
            target = components.get("schemas", {}).get(ref_name)
            if isinstance(target, dict):
                return _synthesize_schema_example(target, components, field_name, depth + 1)

    if "example" in schema:
        val = schema["example"]
        if isinstance(val, str) and field_name and "password" in field_name.lower():
            return "<PASSWORD>"
        return val
    if "default" in schema:
        return schema["default"]
    if isinstance(schema.get("enum"), list) and schema["enum"]:
        return schema["enum"][0]

    for comb in ("allOf", "oneOf", "anyOf"):
        if isinstance(schema.get(comb), list) and schema[comb]:
            if comb == "allOf":
                merged: dict[str, Any] = {}
                for sub in schema[comb]:
                    sub_ex = _synthesize_schema_example(sub, components, field_name, depth + 1)
                    if isinstance(sub_ex, dict):
                        merged.update(sub_ex)
                if merged:
                    return merged
            return _synthesize_schema_example(schema[comb][0], components, field_name, depth + 1)

    stype = schema.get("type")
    if stype == "object" or "properties" in schema:
        props = schema.get("properties", {})
        if not isinstance(props, dict) or not props:
            return {"status": "ok"}
        obj: dict[str, Any] = {}
        for k, v in props.items():
            obj[k] = _synthesize_schema_example(v if isinstance(v, dict) else {}, components, k, depth + 1)
        return obj
    if stype == "array":
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        return [_synthesize_schema_example(item_schema, components, field_name, depth + 1)]
    if stype == "File" or schema.get("format") == "binary":
        return "@contacts.csv"
    if field_name in _FIELD_EXAMPLES:
        return _FIELD_EXAMPLES[field_name]
    if stype == "integer":
        return 1
    if stype == "number":
        return 1.0
    if stype == "boolean":
        return True
    return "example"


def _enrich_spec_examples(spec: dict[str, Any]) -> dict[str, Any]:
    """Attach concrete parameter, requestBody, and response examples across every operation in spec."""
    components = spec.get("components", {}) if isinstance(spec.get("components"), dict) else {}
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        return spec

    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "delete", "patch"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue

            # 1. Parameter examples
            for param in op.get("parameters", []):
                if isinstance(param, dict) and "example" not in param:
                    pschema = param.get("schema") if isinstance(param.get("schema"), dict) else {}
                    param["example"] = _synthesize_schema_example(pschema, components, str(param.get("name", "")))

            # 2. RequestBody examples (JSON, form-urlencoded, multipart)
            rb = op.get("requestBody")
            if isinstance(rb, dict) and isinstance(rb.get("content"), dict):
                for media_obj in rb["content"].values():
                    if isinstance(media_obj, dict) and "example" not in media_obj:
                        mschema = media_obj.get("schema")
                        if isinstance(mschema, dict):
                            media_obj["example"] = _synthesize_schema_example(mschema, components)

            # 3. Response examples (200 / 201 JSON)
            resps = op.get("responses")
            if isinstance(resps, dict):
                for code in ("200", "201"):
                    robj = resps.get(code)
                    if isinstance(robj, dict) and isinstance(robj.get("content"), dict):
                        jc = robj["content"].get("application/json")
                        if isinstance(jc, dict) and "example" not in jc and isinstance(jc.get("schema"), dict):
                            jc["example"] = _synthesize_schema_example(jc["schema"], components)

    return spec


def export_all_openapi_specs(repo_root: Path, out_dir: Path) -> dict[str, Any]:
    """Extract and write all 9 OpenAPI 3.0.3 JSON files plus catalog.json into out_dir."""
    version = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog_services: list[dict[str, Any]] = []
    total_operations = 0

    for meta in SERVICE_META:
        if meta["kind"] == "ui":
            spec = _extract_ui_openapi(repo_root, meta)
        elif meta["kind"] == "rust":
            spec = _build_openalertd_openapi(version)
        else:
            spec = _extract_aiohttp_openapi(repo_root, meta, version)

        spec = _enrich_spec_examples(spec)

        op_count = sum(
            1
            for item in spec.get("paths", {}).values()
            if isinstance(item, dict)
            for method in item
            if method.lower() in {"get", "post", "put", "delete", "patch"}
        )
        total_operations += op_count

        spec_filename = f"{meta['id']}.json"
        (out_dir / spec_filename).write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")

        catalog_services.append(
            {
                "id": meta["id"],
                "label": meta["label"],
                "port": meta["port"],
                "gateway_prefix": meta["gateway_prefix"],
                "source": meta["source"],
                "spec_file": spec_filename,
                "operations": op_count,
                "description": spec.get("info", {}).get("description", ""),
            }
        )

    catalog = {
        "version": version,
        "service_count": len(catalog_services),
        "total_operations": total_operations,
        "services": catalog_services,
    }
    (out_dir / "catalog.json").write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return catalog


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    target = root / "docs" / "assets" / "openapi"
    summary = export_all_openapi_specs(root, target)
    print(
        f"Exported {summary['service_count']} OpenAPI 3.0.3 specs "
        f"({summary['total_operations']} HTTP operations) to {target}"
    )
