"""
Comprehensive OpenAPI 3.0.3 specification builder for py-phone-caller Web UI and Operations Center.

Documents all administrative endpoints, telemetry streams, diagnostic dispatchers,
call records, scheduling engine, on-call contact rosters, SMS tracking, PBX event monitors,
user management, and authentication flows.
"""

from typing import Any, Dict


def get_ui_openapi_spec() -> Dict[str, Any]:
    """
    Constructs a complete, production-grade OpenAPI 3.0.3 specification for the Web UI.
    """
    tags = [
        {
            "name": "NOC Operations & Telemetry",
            "description": "Real-time Operations Center dashboard, wallboard mode, cluster health HUD, and telemetry streams",
        },
        {
            "name": "Diagnostics & Dispatches",
            "description": "Immediate diagnostic test calls, test SMS triggers, TTS audio proxies, and engine discovery",
        },
        {
            "name": "Call Registry & Auditing",
            "description": "Managed call records, search, filtering, CSV export, printable incident audits, and DTMF ACK proxies",
        },
        {
            "name": "Call Scheduling",
            "description": "Scheduled call queue management, calendar pickers, CSV downloads, and dispatcher enqueuing",
        },
        {
            "name": "Address Book & Duty Roster",
            "description": "Responder contact directory, on-call shifts, calendar views, CSV import/export, and availability toggles",
        },
        {
            "name": "SMS Gateway Logs",
            "description": "Outbound SMS transmission logs, carrier statuses, delivery audits, and CSV reports",
        },
        {
            "name": "PBX WebSocket Events",
            "description": "Live Asterisk WebSocket Stasis event monitoring, channel state inspection, and CSV export",
        },
        {
            "name": "User Administration",
            "description": "Administrative user account provisioning, role management, password updates, and account status toggles",
        },
        {
            "name": "Authentication & Session",
            "description": "Local credential login, session termination, and Keycloak OpenID Connect (OIDC) Single Sign-On flows",
        },
        {
            "name": "System & Observability",
            "description": "Kubernetes liveness and readiness probes, Prometheus metrics, locale selectors, and Swagger documentation",
        },
    ]

    components: Dict[str, Any] = {
        "securitySchemes": {
            "cookieAuth": {
                "type": "apiKey",
                "in": "cookie",
                "name": "session",
                "description": "Secure Flask HTTP-only session cookie set upon successful authentication.",
            },
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Standard OIDC / Keycloak Bearer JWT token for programmatic API access.",
            },
        },
        "schemas": {
            "ErrorResponse": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "example": False},
                    "error": {"type": "string", "example": "Invalid request parameter"},
                    "message": {"type": "string", "example": "Resource not found"},
                    "status": {"type": "integer", "example": 400},
                },
            },
            "DashboardMetrics": {
                "type": "object",
                "properties": {
                    "total_calls": {"type": "integer", "example": 142},
                    "acknowledged_calls": {"type": "integer", "example": 138},
                    "ack_rate": {"type": "number", "format": "float", "example": 97.2},
                    "heard_calls": {"type": "integer", "example": 140},
                    "escalated_calls": {"type": "integer", "example": 4},
                    "total_sms": {"type": "integer", "example": 320},
                    "sms_success": {"type": "integer", "example": 318},
                    "sms_success_rate": {"type": "number", "format": "float", "example": 99.4},
                    "active_scheduled": {"type": "integer", "example": 3},
                    "active_oncall_contacts": {"type": "integer", "example": 5},
                    "lifecycle": {
                        "type": "object",
                        "properties": {
                            "initiated": {"type": "integer", "example": 142},
                            "dialing": {"type": "integer", "example": 1},
                            "ringing": {"type": "integer", "example": 1},
                            "answered": {"type": "integer", "example": 2},
                            "dtmf_heard": {"type": "integer", "example": 140},
                            "acknowledged": {"type": "integer", "example": 138},
                            "escalated": {"type": "integer", "example": 4},
                            "completed": {"type": "integer", "example": 138},
                        },
                    },
                },
            },
            "ComponentHealth": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["healthy", "warning", "error"], "example": "healthy"},
                    "badge": {"type": "string", "example": "PostgreSQL"},
                    "detail": {"type": "string", "example": "Connected (Piccolo query latency 1.4ms)"},
                },
            },
            "ClusterHealth": {
                "type": "object",
                "properties": {
                    "overall": {"type": "string", "enum": ["healthy", "warning", "error"], "example": "healthy"},
                    "timestamp": {"type": "number", "example": 1728481234.56},
                    "gateway": {"$ref": "#/components/schemas/ComponentHealth"},
                    "iam": {"$ref": "#/components/schemas/ComponentHealth"},
                    "database": {"$ref": "#/components/schemas/ComponentHealth"},
                    "redis": {"$ref": "#/components/schemas/ComponentHealth"},
                    "asterisk": {"$ref": "#/components/schemas/ComponentHealth"},
                    "sms": {"$ref": "#/components/schemas/ComponentHealth"},
                },
            },
            "TestCallRequest": {
                "type": "object",
                "required": ["phone"],
                "properties": {
                    "phone": {"type": "string", "example": "+34600112233", "description": "Target destination E.164 phone number"},
                    "message": {"type": "string", "example": "Diagnostic voice alert verification from py-phone-caller.", "description": "Alert notification text for TTS speech synthesis"},
                    "language": {"type": "string", "example": "es", "description": "Optional ISO/MMS language code for TTS engine"},
                },
            },
            "TestSmsRequest": {
                "type": "object",
                "required": ["phone"],
                "properties": {
                    "phone": {"type": "string", "example": "+34600112233", "description": "Target recipient phone number"},
                    "message": {"type": "string", "example": "py-phone-caller diagnostic test SMS message.", "description": "SMS text body"},
                },
            },
            "DispatchResult": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "example": True},
                    "target": {"type": "string", "example": "+34600112233"},
                    "service": {"type": "string", "example": "asterisk_caller"},
                    "details": {"type": "object"},
                    "error": {"type": "string"},
                },
            },
            "BulkAcknowledgeRequest": {
                "type": "object",
                "required": ["channels"],
                "properties": {
                    "channels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["PJSIP/carrier-trunk-0000001a", "PJSIP/carrier-trunk-0000001b"],
                        "description": "List of active Asterisk channel IDs to acknowledge in bulk",
                    }
                },
            },
            "BulkAcknowledgeResponse": {
                "type": "object",
                "properties": {
                    "status": {"type": "integer", "example": 200},
                    "total": {"type": "integer", "example": 2},
                    "acknowledged": {"type": "integer", "example": 2},
                    "details": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "channel": {"type": "string"},
                                "status": {"type": "integer"},
                                "success": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
            "ContactCreateRequest": {
                "type": "object",
                "required": ["name", "phone_number"],
                "properties": {
                    "name": {"type": "string", "example": "Jane"},
                    "surname": {"type": "string", "example": "Doe"},
                    "phone_number": {"type": "string", "example": "+34600112233"},
                    "city": {"type": "string", "example": "Barcelona"},
                    "enabled": {"type": "boolean", "default": True},
                    "on_call_availability": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start_at": {"type": "string", "format": "date-time", "example": "2026-10-01T08:00:00Z"},
                                "end_at": {"type": "string", "format": "date-time", "example": "2026-10-01T20:00:00Z"},
                                "priority": {"type": "integer", "example": 1},
                            },
                        },
                    },
                },
            },
            "ContactDeleteRequest": {
                "type": "object",
                "required": ["ids"],
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["e3d81b40-8b22-4211-b0ef-63471c26b349"],
                    }
                },
            },
            "QuickOncallToggleRequest": {
                "type": "object",
                "required": ["contact_id", "enabled"],
                "properties": {
                    "contact_id": {"type": "string", "example": "e3d81b40-8b22-4211-b0ef-63471c26b349"},
                    "enabled": {"type": "boolean", "example": True},
                },
            },
            "UserCreateRequest": {
                "type": "object",
                "required": ["given_name", "email"],
                "properties": {
                    "given_name": {"type": "string", "example": "John Doe"},
                    "email": {"type": "string", "format": "email", "example": "johndoe@example.com"},
                },
            },
            "ChangePasswordRequest": {
                "type": "object",
                "required": ["user_id", "old_password", "new_password", "confirm_password"],
                "properties": {
                    "user_id": {"type": "string", "example": "91a82bc1-01f4-42b7-84bc-29df342a6142"},
                    "old_password": {"type": "string", "format": "password", "example": "CurrentP@ssw0rd!"},
                    "new_password": {"type": "string", "format": "password", "example": "NewStr0ngP@ssw0rd!"},
                    "confirm_password": {"type": "string", "format": "password", "example": "NewStr0ngP@ssw0rd!"},
                },
            },
            "UserIdRequest": {
                "type": "object",
                "required": ["user_id"],
                "properties": {
                    "user_id": {"type": "string", "example": "91a82bc1-01f4-42b7-84bc-29df342a6142"}
                },
            },
            "GlobalSearchResult": {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "example": "NOC Dashboard"},
                                "subtitle": {"type": "string", "example": "+34600112233 (Madrid)"},
                                "category": {"type": "string", "example": "Navigation"},
                                "icon": {"type": "string", "example": "bi-speedometer2"},
                                "url": {"type": "string", "example": "/"},
                            },
                        },
                    }
                },
            },
        },
    }

    paths: Dict[str, Any] = {
        "/": {
            "get": {
                "tags": ["NOC Operations & Telemetry"],
                "summary": "NOC Dashboard Homepage",
                "description": "Renders the main authenticated Operations Center dashboard featuring real-time KPI metrics, active lifecycle breakdown, cluster health HUD, and command navigation.",
                "operationId": "getDashboardHome",
                "security": [{"cookieAuth": []}],
                "responses": {
                    "200": {"description": "HTML dashboard view successfully rendered."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/wallboard": {
            "get": {
                "tags": ["NOC Operations & Telemetry"],
                "summary": "24/7 High-Contrast NOC Wallboard",
                "description": "Renders a high-contrast, large-format operations wallboard view optimized for 24/7 TV screens, projector displays, and NOC monitoring walls.",
                "operationId": "getWallboardView",
                "security": [{"cookieAuth": []}],
                "responses": {
                    "200": {"description": "HTML wallboard view successfully rendered."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/api/dashboard_metrics": {
            "get": {
                "tags": ["NOC Operations & Telemetry"],
                "summary": "Real-time Telemetry Metrics JSON",
                "description": "Returns calculated real-time NOC metrics including total call volumes, DTMF acknowledgment rates, carrier SMS counters, and telephony lifecycle breakdown.",
                "operationId": "getDashboardMetrics",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "responses": {
                    "200": {
                        "description": "Current telemetry metrics payload.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/DashboardMetrics"}
                            }
                        },
                    },
                    "401": {"description": "Authentication required."},
                },
            }
        },
        "/api/cluster_health": {
            "get": {
                "tags": ["NOC Operations & Telemetry"],
                "summary": "Cluster Component Health HUD",
                "description": "Aggregates concurrent live health checks across the API Gateway, Keycloak IAM, PostgreSQL database, Redis broker, Asterisk ARI engine, and SMS carrier gateway.",
                "operationId": "getClusterHealth",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "responses": {
                    "200": {
                        "description": "Cluster components health status dictionary.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ClusterHealth"}
                            }
                        },
                    },
                    "401": {"description": "Authentication required."},
                },
            }
        },
        "/api/telemetry_stream": {
            "get": {
                "tags": ["NOC Operations & Telemetry"],
                "summary": "Server-Sent Events (SSE) Live Telemetry Stream",
                "description": "Continuous SSE event stream pushing real-time KPI metrics and live Asterisk PBX channel events to connected browser sessions with keep-alive heartbeats.",
                "operationId": "streamTelemetryEvents",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "responses": {
                    "200": {
                        "description": "text/event-stream real-time SSE push connection.",
                        "content": {
                            "text/event-stream": {
                                "schema": {"type": "string", "example": "event: metrics\\ndata: {...}\\n\\n"}
                            }
                        },
                    },
                    "401": {"description": "Authentication required."},
                },
            }
        },
        "/api/global_search": {
            "get": {
                "tags": ["NOC Operations & Telemetry"],
                "summary": "Command Palette Universal Search",
                "description": "Instant global search endpoint used by the Ctrl+K Command Palette to search across Address Book contacts, Call records, and UI navigation targets.",
                "operationId": "globalSearch",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "parameters": [
                    {
                        "name": "q",
                        "in": "query",
                        "required": False,
                        "description": "Search query substring matching phone numbers, contact names, cities, or navigation titles",
                        "schema": {"type": "string", "example": "Madrid"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Ranked search results array.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/GlobalSearchResult"}
                            }
                        },
                    },
                    "401": {"description": "Authentication required."},
                },
            }
        },
        "/api/quick_oncall_status": {
            "get": {
                "tags": ["NOC Operations & Telemetry"],
                "summary": "Active On-Call Responders Status",
                "description": "Retrieves the current roster of active and standby on-call responders for the navigation header widget and quick status badge.",
                "operationId": "getQuickOncallStatus",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "responses": {
                    "200": {
                        "description": "On-call responder roster summary and count.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "active_count": {"type": "integer", "example": 3},
                                        "active_contacts": {"type": "array", "items": {"type": "object"}},
                                        "contacts": {"type": "array", "items": {"type": "object"}},
                                    },
                                }
                            }
                        },
                    },
                    "401": {"description": "Authentication required."},
                },
            }
        },
        "/api/quick_oncall_toggle": {
            "post": {
                "tags": ["NOC Operations & Telemetry"],
                "summary": "Toggle On-Call Responder Availability",
                "description": "Enables or disables an on-call responder directly from the header dropdown menu without navigating away from the dashboard.",
                "operationId": "toggleQuickOncall",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/QuickOncallToggleRequest"}
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Contact availability successfully toggled.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean", "example": True},
                                        "contact_id": {"type": "string"},
                                        "enabled": {"type": "boolean"},
                                    },
                                }
                            }
                        },
                    },
                    "400": {"description": "Missing contact_id or enabled flag."},
                    "401": {"description": "Authentication required."},
                    "500": {"description": "Database update failed."},
                },
            }
        },
        "/api/diagnostics/test_call": {
            "post": {
                "tags": ["Diagnostics & Dispatches"],
                "summary": "Trigger Diagnostic Test Call",
                "description": "Initiates an immediate outbound telephony call via Asterisk ARI. Automatically synthesizes and caches the required TTS audio waveform beforehand.",
                "operationId": "dispatchDiagnosticCall",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/TestCallRequest"}
                        },
                        "application/x-www-form-urlencoded": {
                            "schema": {"$ref": "#/components/schemas/TestCallRequest"}
                        },
                    },
                },
                "responses": {
                    "200": {
                        "description": "Call successfully originated via Asterisk ARI.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/DispatchResult"}
                            }
                        },
                    },
                    "400": {"description": "Missing or invalid destination phone number."},
                    "401": {"description": "Authentication required."},
                    "500": {"description": "Asterisk caller microservice connection failed."},
                },
            }
        },
        "/api/diagnostics/test_sms": {
            "post": {
                "tags": ["Diagnostics & Dispatches"],
                "summary": "Trigger Diagnostic Test SMS",
                "description": "Transmits an immediate diagnostic SMS message to the target recipient via the caller_sms gateway microservice.",
                "operationId": "dispatchDiagnosticSms",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/TestSmsRequest"}
                        },
                        "application/x-www-form-urlencoded": {
                            "schema": {"$ref": "#/components/schemas/TestSmsRequest"}
                        },
                    },
                },
                "responses": {
                    "200": {
                        "description": "SMS successfully queued for transmission.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/DispatchResult"}
                            }
                        },
                    },
                    "400": {"description": "Missing destination phone number."},
                    "401": {"description": "Authentication required."},
                    "500": {"description": "SMS carrier connection error."},
                },
            }
        },
        "/api/audio_proxy/{filename}": {
            "get": {
                "tags": ["Diagnostics & Dispatches"],
                "summary": "Stream TTS Audio Preview WAV",
                "description": "Proxies synthesized TTS WAV audio files from the internal generate_audio microservice to the authenticated browser, preventing CORS issues.",
                "operationId": "proxyAudioPreview",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {
                        "name": "filename",
                        "in": "path",
                        "required": True,
                        "description": "Synthesized audio filename (format: [a-zA-Z0-9_-]+.wav)",
                        "schema": {"type": "string", "example": "a1b2c3d4e5f6.wav"},
                    }
                ],
                "responses": {
                    "200": {
                        "description": "Raw audio WAV binary stream.",
                        "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
                    },
                    "400": {"description": "Invalid audio filename pattern."},
                    "404": {"description": "Audio file not found or still generating."},
                    "502": {"description": "generate_audio microservice unreachable."},
                },
            }
        },
        "/api/languages": {
            "get": {
                "tags": ["Diagnostics & Dispatches"],
                "summary": "Discover Supported TTS Languages",
                "description": "Queries the active text-to-speech engine (Facebook MMS, Piper, Kokoro, eSpeak) to return installed language models and defaults.",
                "operationId": "getLanguages",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "responses": {
                    "200": {
                        "description": "Active TTS engine configuration and language list.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "active_engine": {"type": "string", "example": "facebook_mms"},
                                        "default_language": {"type": "string", "example": "spa"},
                                        "languages": {"type": "array", "items": {"type": "object"}},
                                        "installed_models": {"type": "object"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/api/docs": {
            "get": {
                "tags": ["Diagnostics & Dispatches"],
                "summary": "Unified OpenAPI Developer Portal",
                "description": "Interactive developer portal aggregating all microservice OpenAPI 3.0 specifications with a dropdown selector and Keycloak Bearer token authentication.",
                "operationId": "getUnifiedDocsPortal",
                "responses": {
                    "200": {
                        "description": "Swagger UI 5 developer portal HTML page.",
                        "content": {"text/html": {"schema": {"type": "string"}}},
                    }
                },
            }
        },
        "/calls": {
            "get": {
                "tags": ["Call Registry & Auditing"],
                "summary": "Call Registry Log Viewer",
                "description": "Displays a paginated, searchable, and sortable registry table of all automated and dispatched telephone calls.",
                "operationId": "getCallsView",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "search", "in": "query", "description": "Search string matching phone number, message text, or channel", "schema": {"type": "string"}},
                    {"name": "sort_by", "in": "query", "description": "Sort column (first_dial_time, last_dial_time, heard_at, acknowledge_at, times_to_dial, dialed_times)", "schema": {"type": "string", "default": "first_dial_time"}},
                    {"name": "sort_order", "in": "query", "description": "Sort order (asc, desc)", "schema": {"type": "string", "enum": ["asc", "desc"], "default": "desc"}},
                    {"name": "page", "in": "query", "description": "Page number (1-indexed)", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "description": "Items per page", "schema": {"type": "integer", "default": 50}},
                ],
                "responses": {
                    "200": {"description": "Rendered HTML table view of call records."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/calls/export_csv": {
            "get": {
                "tags": ["Call Registry & Auditing"],
                "summary": "Export Call Records to CSV",
                "description": "Filters call logs by the specified month and generates a downloadable CSV file containing complete call records, timestamps, and checksums.",
                "operationId": "exportCallsCsv",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "export_month", "in": "query", "required": True, "description": "Target month in YYYY-MM format", "schema": {"type": "string", "example": "2026-10"}}
                ],
                "responses": {
                    "200": {
                        "description": "CSV stream attachment download.",
                        "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
                    },
                    "400": {"description": "Missing or malformed export_month parameter."},
                },
            }
        },
        "/calls/audit_report": {
            "get": {
                "tags": ["Call Registry & Auditing"],
                "summary": "Printable Incident Audit Report",
                "description": "Renders a high-density, printable HTML/PDF-ready incident audit report with DTMF acknowledgment proof, timestamps, responder tracking, and resolution rates.",
                "operationId": "getCallAuditReport",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "export_month", "in": "query", "required": False, "description": "Target month in YYYY-MM format (omitted for All Time)", "schema": {"type": "string", "example": "2026-10"}}
                ],
                "responses": {
                    "200": {"description": "Rendered audit report HTML view."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/calls/proxy_acknowledge": {
            "get": {
                "tags": ["Call Registry & Auditing"],
                "summary": "One-Click Call Acknowledgment Proxy",
                "description": "Proxies an acknowledgment request for a specific Asterisk channel to the internal caller_register microservice, verifying DTMF receipt.",
                "operationId": "proxyAcknowledgeCall",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "parameters": [
                    {"name": "asterisk_chan", "in": "query", "required": True, "description": "Asterisk channel identifier to acknowledge", "schema": {"type": "string", "example": "PJSIP/carrier-trunk-0000001a"}}
                ],
                "responses": {
                    "200": {
                        "description": "Call successfully acknowledged.",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    "400": {"description": "Missing asterisk_chan parameter."},
                    "500": {"description": "Backend caller_register service error."},
                },
            }
        },
        "/calls/api/bulk_acknowledge": {
            "post": {
                "tags": ["Call Registry & Auditing"],
                "summary": "Bulk Acknowledge Multiple Calls",
                "description": "Acknowledges an array of active Asterisk call channels in a single batch request.",
                "operationId": "bulkAcknowledgeCalls",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/BulkAcknowledgeRequest"}
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Bulk acknowledgment batch results.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/BulkAcknowledgeResponse"}
                            }
                        },
                    },
                    "400": {"description": "Missing channels array."},
                    "401": {"description": "Authentication required."},
                },
            }
        },
        "/schedule_call": {
            "get": {
                "tags": ["Call Scheduling"],
                "summary": "Scheduled Calls Log & Dispatcher View",
                "description": "Displays queued scheduled calls, contact selectors, and scheduling controls with pagination and filtering.",
                "operationId": "getScheduledCallsView",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "search", "in": "query", "description": "Search string matching phone or message text", "schema": {"type": "string"}},
                    {"name": "sort_by", "in": "query", "description": "Sort column (element, scheduled_time)", "schema": {"type": "string", "default": "element"}},
                    {"name": "sort_order", "in": "query", "description": "Sort order (asc, desc)", "schema": {"type": "string", "enum": ["asc", "desc"], "default": "asc"}},
                    {"name": "page", "in": "query", "description": "Page number (1-indexed)", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "description": "Items per page", "schema": {"type": "integer", "default": 50}},
                ],
                "responses": {
                    "200": {"description": "HTML schedule calls view rendered successfully."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/schedule_call/export_csv": {
            "get": {
                "tags": ["Call Scheduling"],
                "summary": "Export Scheduled Calls to CSV",
                "description": "Exports scheduled call queue entries for a specified month as a downloadable CSV file.",
                "operationId": "exportScheduledCallsCsv",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "export_month", "in": "query", "required": True, "description": "Target month in YYYY-MM format", "schema": {"type": "string", "example": "2026-10"}}
                ],
                "responses": {
                    "200": {
                        "description": "CSV stream attachment download.",
                        "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
                    },
                    "400": {"description": "Missing or malformed export_month parameter."},
                },
            }
        },
        "/schedule_picker": {
            "get": {
                "tags": ["Call Scheduling"],
                "summary": "Enqueue and Persist Scheduled Call",
                "description": "Enqueues an automated outbound voice call into the caller_scheduler queue and persists it into caller_register with pre-generated TTS audio.",
                "operationId": "enqueueScheduledCall",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "parameters": [
                    {"name": "phone", "in": "query", "required": True, "description": "Destination phone number", "schema": {"type": "string", "example": "+34600112233"}},
                    {"name": "message", "in": "query", "required": True, "description": "Voice alert text message", "schema": {"type": "string", "example": "Scheduled server maintenance notice"}},
                    {"name": "scheduled_date", "in": "query", "required": True, "description": "Date in YYYY-MM-DD format", "schema": {"type": "string", "example": "2026-10-15"}},
                    {"name": "scheduled_time", "in": "query", "required": True, "description": "Time in HH:MM format", "schema": {"type": "string", "example": "14:30"}},
                    {"name": "lang", "in": "query", "required": False, "description": "Language code for TTS audio synthesis", "schema": {"type": "string", "example": "en"}},
                ],
                "responses": {
                    "200": {"description": "Successfully enqueued ('Scheduled OK')."},
                    "500": {"description": "Scheduler or register service communication failure."},
                },
            }
        },
        "/address_book": {
            "get": {
                "tags": ["Address Book & Duty Roster"],
                "summary": "Address Book & Duty Roster Directory",
                "description": "Displays the complete list of on-call responder contacts, availability windows, and status toggles with search and sorting.",
                "operationId": "getAddressBookView",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "search", "in": "query", "description": "Filter by contact name, phone, or city", "schema": {"type": "string"}},
                    {"name": "sort_by", "in": "query", "description": "Sort column (name, phone_number, enabled, created_time)", "schema": {"type": "string", "default": "created_time"}},
                    {"name": "sort_order", "in": "query", "description": "Sort order (asc, desc)", "schema": {"type": "string", "enum": ["asc", "desc"], "default": "desc"}},
                ],
                "responses": {
                    "200": {"description": "HTML address book directory view."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/address_book/api/add": {
            "post": {
                "tags": ["Address Book & Duty Roster"],
                "summary": "Create Contact",
                "description": "Creates a new responder contact with on-call availability windows and persists it in the Piccolo database.",
                "operationId": "addContact",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ContactCreateRequest"}
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Contact created successfully."},
                    "400": {"description": "Invalid JSON or missing required fields."},
                    "500": {"description": "Backend address book service communication error."},
                },
            }
        },
        "/address_book/api/modify/{contact_id}": {
            "post": {
                "tags": ["Address Book & Duty Roster"],
                "summary": "Modify Contact",
                "description": "Updates an existing contact's attributes, phone number, enabled status, or on-call availability shift schedules.",
                "operationId": "modifyContact",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "parameters": [
                    {"name": "contact_id", "in": "path", "required": True, "description": "Unique UUID of the contact", "schema": {"type": "string", "example": "e3d81b40-8b22-4211-b0ef-63471c26b349"}}
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"type": "object", "description": "Key-value attributes to update"}
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Contact successfully modified."},
                    "400": {"description": "Invalid JSON payload."},
                    "500": {"description": "Failed to update contact."},
                },
            }
        },
        "/address_book/api/delete": {
            "post": {
                "tags": ["Address Book & Duty Roster"],
                "summary": "Bulk Delete Contacts",
                "description": "Deletes one or more responder contacts from the address book by their unique identifiers.",
                "operationId": "deleteContacts",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ContactDeleteRequest"}
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Contacts deleted successfully."},
                    "400": {"description": "Missing or empty ids list."},
                    "500": {"description": "Error deleting contacts."},
                },
            }
        },
        "/address_book/export_csv": {
            "get": {
                "tags": ["Address Book & Duty Roster"],
                "summary": "Export Contacts to CSV",
                "description": "Downloads the entire address book responder directory as a CSV file.",
                "operationId": "exportContactsCsv",
                "security": [{"cookieAuth": []}],
                "responses": {
                    "200": {
                        "description": "CSV contacts stream attachment.",
                        "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
                    },
                    "500": {"description": "Failed to generate CSV export."},
                },
            }
        },
        "/address_book/import_csv": {
            "post": {
                "tags": ["Address Book & Duty Roster"],
                "summary": "Bulk Import Contacts from CSV",
                "description": "Imports new contacts or updates existing entries from an uploaded CSV file containing columns: name, surname, phone_number, city.",
                "operationId": "importContactsCsv",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file"],
                                "properties": {
                                    "file": {"type": "string", "format": "binary", "description": "CSV file upload"}
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {"description": "Contacts successfully imported."},
                    "400": {"description": "No file uploaded or malformed CSV format."},
                    "500": {"description": "Error during CSV import process."},
                },
            }
        },
        "/address_book/calendar": {
            "get": {
                "tags": ["Address Book & Duty Roster"],
                "summary": "On-Call Roster Calendar View",
                "description": "Renders a monthly calendar grid visualizing on-call responder availability windows, duty shifts, and priority tiers.",
                "operationId": "getOncallCalendarView",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "month", "in": "query", "required": False, "description": "Month in YYYY-MM format (defaults to current month)", "schema": {"type": "string", "example": "2026-10"}}
                ],
                "responses": {
                    "200": {"description": "HTML calendar view rendered successfully."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/address_book/calendar/export_csv": {
            "get": {
                "tags": ["Address Book & Duty Roster"],
                "summary": "Export On-Call Shifts to CSV",
                "description": "Generates a downloadable CSV containing all active on-call shift windows (id, name, surname, start_at, end_at, priority) for a specific month.",
                "operationId": "exportCalendarShiftsCsv",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "month", "in": "query", "required": False, "description": "Month in YYYY-MM format", "schema": {"type": "string", "example": "2026-10"}}
                ],
                "responses": {
                    "200": {
                        "description": "CSV shift schedule file download.",
                        "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
                    }
                },
            }
        },
        "/address_book/calendar/import_csv": {
            "post": {
                "tags": ["Address Book & Duty Roster"],
                "summary": "Import On-Call Shifts from CSV",
                "description": "Uploads and merges on-call availability shift intervals into responder profiles from a CSV file.",
                "operationId": "importCalendarShiftsCsv",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "multipart/form-data": {
                            "schema": {
                                "type": "object",
                                "required": ["file"],
                                "properties": {
                                    "file": {"type": "string", "format": "binary", "description": "CSV shift intervals file"}
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Shift import summary with processed rows and updated contacts count.",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    },
                    "400": {"description": "Missing file or invalid CSV schema."},
                },
            }
        },
        "/sms": {
            "get": {
                "tags": ["SMS Gateway Logs"],
                "summary": "SMS Message Logs & Delivery History",
                "description": "Displays a paginated, searchable, and sortable table of all outbound carrier SMS alerts and delivery confirmation statuses.",
                "operationId": "getSmsView",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "search", "in": "query", "description": "Filter by recipient phone, carrier, message, or delivery error", "schema": {"type": "string"}},
                    {"name": "sort_by", "in": "query", "description": "Sort column (created_at, phone, status)", "schema": {"type": "string", "default": "created_at"}},
                    {"name": "sort_order", "in": "query", "description": "Sort order (asc, desc)", "schema": {"type": "string", "enum": ["asc", "desc"], "default": "desc"}},
                    {"name": "page", "in": "query", "description": "Page number (1-indexed)", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "description": "Items per page", "schema": {"type": "integer", "default": 50}},
                ],
                "responses": {
                    "200": {"description": "HTML SMS logs view rendered successfully."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/sms/export_csv": {
            "get": {
                "tags": ["SMS Gateway Logs"],
                "summary": "Export SMS Logs to CSV",
                "description": "Exports SMS transmission records for a specific month as a downloadable CSV file.",
                "operationId": "exportSmsCsv",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "export_month", "in": "query", "required": True, "description": "Target month in YYYY-MM format", "schema": {"type": "string", "example": "2026-10"}}
                ],
                "responses": {
                    "200": {
                        "description": "CSV stream attachment download.",
                        "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
                    },
                    "400": {"description": "Missing or malformed export_month parameter."},
                },
            }
        },
        "/ws_events": {
            "get": {
                "tags": ["PBX WebSocket Events"],
                "summary": "Asterisk WebSocket Stasis Events Log",
                "description": "Displays live and historical Asterisk ARI WebSocket Stasis events including ChannelCreated, Dial, PlaybackStarted, and ChannelDestroyed.",
                "operationId": "getWsEventsView",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "search", "in": "query", "description": "Search by channel name, event type, or JSON content", "schema": {"type": "string"}},
                    {"name": "sort_by", "in": "query", "description": "Sort column (timestamp, asterisk_chan, event_type)", "schema": {"type": "string", "default": "timestamp"}},
                    {"name": "sort_order", "in": "query", "description": "Sort order (asc, desc)", "schema": {"type": "string", "enum": ["asc", "desc"], "default": "desc"}},
                    {"name": "page", "in": "query", "description": "Page number (1-indexed)", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "description": "Items per page", "schema": {"type": "integer", "default": 50}},
                ],
                "responses": {
                    "200": {"description": "HTML WebSocket events log view rendered successfully."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/ws_events/export_csv": {
            "get": {
                "tags": ["PBX WebSocket Events"],
                "summary": "Export WebSocket Events to CSV",
                "description": "Exports Asterisk PBX Stasis event stream entries for a given month as a downloadable CSV file.",
                "operationId": "exportWsEventsCsv",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "export_month", "in": "query", "required": True, "description": "Target month in YYYY-MM format", "schema": {"type": "string", "example": "2026-10"}}
                ],
                "responses": {
                    "200": {
                        "description": "CSV stream attachment download.",
                        "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
                    },
                    "400": {"description": "Missing or malformed export_month parameter."},
                },
            }
        },
        "/users": {
            "get": {
                "tags": ["User Administration"],
                "summary": "User Accounts Directory",
                "description": "Displays the user accounts list with activity statuses and role permissions. Regular operators can view their own profile; administrators can manage all users.",
                "operationId": "getUsersView",
                "security": [{"cookieAuth": []}],
                "parameters": [
                    {"name": "search", "in": "query", "description": "Search by given name or email address", "schema": {"type": "string"}},
                    {"name": "sort_by", "in": "query", "description": "Sort column (given_name, email, created_on, last_login)", "schema": {"type": "string", "default": "given_name"}},
                    {"name": "sort_order", "in": "query", "description": "Sort order (asc, desc)", "schema": {"type": "string", "enum": ["asc", "desc"], "default": "asc"}},
                    {"name": "page", "in": "query", "description": "Page number (1-indexed)", "schema": {"type": "integer", "default": 1}},
                    {"name": "per_page", "in": "query", "description": "Items per page", "schema": {"type": "integer", "default": 10}},
                ],
                "responses": {
                    "200": {"description": "HTML users directory rendered successfully."},
                    "302": {"description": "Redirects to /login if unauthenticated."},
                },
            }
        },
        "/users/add": {
            "post": {
                "tags": ["User Administration"],
                "summary": "Provision New User Account",
                "description": "Admin-only endpoint to create a new user account with an automatically generated complex password.",
                "operationId": "addUser",
                "security": [{"cookieAuth": []}, {"bearerAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/x-www-form-urlencoded": {
                            "schema": {"$ref": "#/components/schemas/UserCreateRequest"}
                        },
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/UserCreateRequest"}
                        },
                    },
                },
                "responses": {
                    "200": {
                        "description": "User created successfully. Returns the auto-generated initial password.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean", "example": True},
                                        "message": {"type": "string", "example": "User created successfully"},
                                        "password": {"type": "string", "example": "A9k!wZ3#pL90"},
                                    },
                                }
                            }
                        },
                    },
                    "400": {"description": "Missing required fields or invalid email."},
                    "403": {"description": "Forbidden: Only Admin can add users."},
                },
            }
        },
        "/users/change_password": {
            "post": {
                "tags": ["User Administration"],
                "summary": "Change User Password",
                "description": "Updates a user's password after validating current password and enforcing complexity policies (length, upper, lower, digits, symbols).",
                "operationId": "changePassword",
                "security": [{"cookieAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/x-www-form-urlencoded": {
                            "schema": {"$ref": "#/components/schemas/ChangePasswordRequest"}
                        },
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ChangePasswordRequest"}
                        },
                    },
                },
                "responses": {
                    "200": {
                        "description": "Password successfully updated.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean", "example": True},
                                        "message": {"type": "string", "example": "Password changed successfully"},
                                    },
                                }
                            }
                        },
                    },
                    "400": {"description": "Password validation failed or current password incorrect."},
                    "403": {"description": "Forbidden: Insufficient privileges."},
                    "404": {"description": "User account not found."},
                },
            }
        },
        "/users/toggle_active": {
            "post": {
                "tags": ["User Administration"],
                "summary": "Toggle User Account Activation",
                "description": "Admin-only endpoint to activate or deactivate a user account, controlling system access without deleting account history.",
                "operationId": "toggleUserActive",
                "security": [{"cookieAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/x-www-form-urlencoded": {
                            "schema": {"$ref": "#/components/schemas/UserIdRequest"}
                        },
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/UserIdRequest"}
                        },
                    },
                },
                "responses": {
                    "200": {
                        "description": "User status successfully updated.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean", "example": True},
                                        "message": {"type": "string", "example": "User status updated"},
                                        "is_active": {"type": "boolean", "example": False},
                                    },
                                }
                            }
                        },
                    },
                    "400": {"description": "Missing user_id or attempt to toggle admin account."},
                    "403": {"description": "Forbidden: Only Admin can activate/deactivate users."},
                    "404": {"description": "User account not found."},
                },
            }
        },
        "/users/delete": {
            "post": {
                "tags": ["User Administration"],
                "summary": "Delete User Account",
                "description": "Admin-only endpoint to permanently delete a user account from the system.",
                "operationId": "deleteUser",
                "security": [{"cookieAuth": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/x-www-form-urlencoded": {
                            "schema": {"$ref": "#/components/schemas/UserIdRequest"}
                        },
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/UserIdRequest"}
                        },
                    },
                },
                "responses": {
                    "200": {
                        "description": "User account deleted successfully.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "success": {"type": "boolean", "example": True},
                                        "message": {"type": "string", "example": "User deleted"},
                                    },
                                }
                            }
                        },
                    },
                    "400": {"description": "Missing user_id or attempt to delete protected admin account."},
                    "403": {"description": "Forbidden: Only Admin can delete users."},
                    "404": {"description": "User not found."},
                },
            }
        },
        "/login": {
            "get": {
                "tags": ["Authentication & Session"],
                "summary": "Render Login Form",
                "description": "Renders the login user interface supporting local database credentials and OpenID Connect (Keycloak) Single Sign-On.",
                "operationId": "getLoginForm",
                "responses": {
                    "200": {"description": "HTML login form rendered successfully."},
                    "302": {"description": "Redirects to / if user is already authenticated."},
                },
            },
            "post": {
                "tags": ["Authentication & Session"],
                "summary": "Authenticate User Credentials",
                "description": "Validates user email and password against Piccolo database credentials, initializing the session and updating last_login timestamp.",
                "operationId": "loginUser",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/x-www-form-urlencoded": {
                            "schema": {
                                "type": "object",
                                "required": ["email", "password"],
                                "properties": {
                                    "email": {"type": "string", "format": "email", "example": "admin@example.com"},
                                    "password": {"type": "string", "format": "password", "example": "SecretPass123!"},
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "302": {"description": "Redirects to / on successful authentication."},
                    "200": {"description": "Re-renders login page with error alert on failure."},
                },
            },
        },
        "/logout": {
            "get": {
                "tags": ["Authentication & Session"],
                "summary": "Logout and Terminate Session",
                "description": "Terminates the local user session and initiates Keycloak OIDC Single Sign-Out if logged in via OAuth2.",
                "operationId": "logoutUser",
                "security": [{"cookieAuth": []}],
                "responses": {
                    "302": {"description": "Redirects to Keycloak logout URL or local /login page."},
                },
            }
        },
        "/oauth2/login": {
            "get": {
                "tags": ["Authentication & Session"],
                "summary": "Initiate Keycloak OIDC PKCE Flow",
                "description": "Generates PKCE code challenge and cryptographically signed state token, redirecting the user to Keycloak authorization endpoint.",
                "operationId": "initiateOidcLogin",
                "responses": {
                    "302": {"description": "Redirect to Keycloak Single Sign-On authorization server."},
                },
            }
        },
        "/oauth2/callback": {
            "get": {
                "tags": ["Authentication & Session"],
                "summary": "Handle OIDC Authorization Callback",
                "description": "Receives authorization code from Keycloak, validates PKCE state, exchanges code for access & ID tokens, and establishes the user session.",
                "operationId": "handleOidcCallback",
                "parameters": [
                    {"name": "code", "in": "query", "required": False, "description": "Authorization code issued by Keycloak", "schema": {"type": "string"}},
                    {"name": "state", "in": "query", "required": False, "description": "Signed PKCE state token", "schema": {"type": "string"}},
                    {"name": "error", "in": "query", "required": False, "description": "OIDC error code if authorization failed", "schema": {"type": "string"}},
                ],
                "responses": {
                    "302": {"description": "Redirect to / on success or /login on error."},
                },
            }
        },
        "/health": {
            "get": {
                "tags": ["System & Observability"],
                "summary": "Service Liveness Health Check",
                "description": "Basic liveness check confirming the Flask Web UI process is alive and responsive.",
                "operationId": "checkLiveness",
                "responses": {
                    "200": {
                        "description": "Service is healthy and responsive.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string", "example": "healthy"},
                                        "service": {"type": "string", "example": "py_phone_caller_ui"},
                                        "version": {"type": "string", "example": "1.0.0"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/healthz": {
            "get": {
                "tags": ["System & Observability"],
                "summary": "Kubernetes Liveness Probe Alias",
                "description": "Standard Kubernetes healthz endpoint.",
                "operationId": "checkHealthz",
                "responses": {
                    "200": {
                        "description": "Service is healthy.",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ComponentHealth"}}},
                    }
                },
            }
        },
        "/live": {
            "get": {
                "tags": ["System & Observability"],
                "summary": "Container Liveness Probe Alias",
                "description": "Docker and Kubernetes liveness probe alias.",
                "operationId": "checkLive",
                "responses": {
                    "200": {"description": "Service is live."},
                },
            }
        },
        "/ready": {
            "get": {
                "tags": ["System & Observability"],
                "summary": "Readiness Probe",
                "description": "Verifies that the service is initialized and ready to receive external network traffic.",
                "operationId": "checkReadiness",
                "responses": {
                    "200": {
                        "description": "Service is ready to handle traffic.",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string", "example": "healthy"},
                                        "service": {"type": "string", "example": "py_phone_caller_ui"},
                                        "version": {"type": "string", "example": "1.0.0"},
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/metrics": {
            "get": {
                "tags": ["System & Observability"],
                "summary": "Prometheus Metrics Endpoint",
                "description": "Exposes standard Prometheus metrics in text format for OpenTelemetry and Prometheus scrapers.",
                "operationId": "getPrometheusMetrics",
                "responses": {
                    "200": {
                        "description": "Prometheus text-format metrics stream.",
                        "content": {"text/plain": {"schema": {"type": "string"}}},
                    }
                },
            }
        },
        "/set_locale/{lang_code}": {
            "get": {
                "tags": ["System & Observability"],
                "summary": "Set UI Locale & Language",
                "description": "Switches the active user interface language (en, es, ca, fr, de, it, pt, nl, zh, ja). Persists the choice in the session and a long-lived cookie.",
                "operationId": "setLocale",
                "parameters": [
                    {
                        "name": "lang_code",
                        "in": "path",
                        "required": True,
                        "description": "Target language or locale code (e.g., en, es, ca, fr, de, it)",
                        "schema": {"type": "string", "example": "es"},
                    }
                ],
                "responses": {
                    "302": {"description": "Redirects back to the referrer page with Set-Cookie: locale."},
                },
            }
        },
        "/docs": {
            "get": {
                "tags": ["System & Observability"],
                "summary": "Swagger UI Documentation",
                "description": "Interactive standalone Swagger UI documentation for all py-phone-caller Web UI endpoints.",
                "operationId": "getSwaggerUiDocs",
                "responses": {
                    "200": {
                        "description": "HTML Swagger UI documentation page.",
                        "content": {"text/html": {"schema": {"type": "string"}}},
                    }
                },
            }
        },
        "/docs/swagger.json": {
            "get": {
                "tags": ["System & Observability"],
                "summary": "OpenAPI 3.0 Specification JSON",
                "description": "Returns this complete, production-grade OpenAPI 3.0.3 JSON specification document.",
                "operationId": "getOpenApiSpecJson",
                "responses": {
                    "200": {
                        "description": "Complete OpenAPI 3.0.3 specification JSON.",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
    }

    servers = [
        {"url": "/", "description": "Current Environment / Relative Root"},
        {"url": "https://py-phone-caller.link", "description": "Production Domain (Reverse Proxied via APISIX)"},
        {"url": "http://127.0.0.1:5000", "description": "Local Web UI Service"},
    ]

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "py-phone-caller Web UI & Operations Center",
            "description": (
                "Comprehensive OpenAPI 3.0 reference for the py-phone-caller Web Dashboard, "
                "telemetry streaming bus, diagnostic dispatches, call registries, scheduler queues, "
                "address book rosters, carrier SMS tracking, and administrative REST endpoints."
            ),
            "version": "1.0.0",
            "contact": {
                "name": "py-phone-caller Support",
                "url": "https://github.com/jcfdeb/py-phone-caller",
            },
            "license": {
                "name": "GPL-3.0-or-later",
                "url": "https://github.com/jcfdeb/py-phone-caller/blob/main/LICENSE",
            },
        },
        "servers": servers,
        "tags": tags,
        "paths": paths,
        "components": components,
    }
