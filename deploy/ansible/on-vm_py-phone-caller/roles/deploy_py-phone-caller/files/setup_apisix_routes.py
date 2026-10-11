#!/usr/bin/env python3
"""
Apache APISIX Gateway Route Provisioner for py-phone-caller.

Idempotently declares and updates routes on APISIX via the Manager API.
Configures upstreams to point to the local development host (192.168.101.17)
or any custom host provided via argument / environment variable.
"""

import os
import sys
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DASHBOARD_URL = os.getenv("APISIX_DASHBOARD_URL", "http://127.0.0.1:9001")
DASHBOARD_USER = os.getenv("APISIX_DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.getenv("APISIX_DASHBOARD_PASS", "admin")
UPSTREAM_HOST = os.getenv("UPSTREAM_HOST", "127.0.0.1")

KEYCLOAK_PORT = int(os.getenv("KEYCLOAK_PORT", "8180"))

ROUTES = [
    {
        "id": "route-keycloak-realms",
        "name": "keycloak_realms",
        "uri": "/realms/*",
        "priority": 20,
        "port": KEYCLOAK_PORT,
        "plugins": {
            "proxy-rewrite": {
                "use_real_request_uri_unsafe": True
            }
        },
    },
    {
        "id": "route-keycloak-resources",
        "name": "keycloak_resources",
        "uri": "/resources/*",
        "priority": 20,
        "port": KEYCLOAK_PORT,
        "plugins": {
            "proxy-rewrite": {
                "use_real_request_uri_unsafe": True
            }
        },
    },
    {
        "id": "route-keycloak-admin",
        "name": "keycloak_admin",
        "uri": "/admin/*",
        "priority": 20,
        "port": KEYCLOAK_PORT,
        "plugins": {
            "proxy-rewrite": {
                "use_real_request_uri_unsafe": True
            }
        },
    },
    {
        "id": "route-api-docs",
        "name": "api_docs_portal",
        "uri": "/api/docs*",
        "priority": 15,
        "port": 5000,
        "plugins": {
            "proxy-rewrite": {
                "use_real_request_uri_unsafe": True
            }
        },
    },
    {
        "id": "route-ui-root",
        "name": "py_phone_caller_ui",
        "uri": "/*",
        "priority": 0,
        "port": 5000,
        "plugins": {
            "proxy-rewrite": {
                "use_real_request_uri_unsafe": True
            }
        },
    },
    {
        "id": "route-telephony",
        "name": "asterisk_caller",
        "uri": "/api/v1/telephony/*",
        "priority": 10,
        "port": 8081,
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/api/v1/telephony/(.*)", "/$1"]
            },
            "limit-req": {
                "rate": 20,
                "burst": 30,
                "key_type": "var",
                "key": "remote_addr",
                "rejected_code": 429
            }
        },
    },
    {
        "id": "route-audio",
        "name": "generate_audio",
        "uri": "/api/v1/audio/*",
        "priority": 10,
        "port": 8082,
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/api/v1/audio/(.*)", "/$1"]
            }
        },
    },
    {
        "id": "route-registry",
        "name": "caller_register",
        "uri": "/api/v1/registry/*",
        "priority": 10,
        "port": 8083,
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/api/v1/registry/(.*)", "/$1"]
            }
        },
    },
    {
        "id": "route-alerts",
        "name": "caller_prometheus_webhook",
        "uri": "/api/v1/alerts/*",
        "priority": 10,
        "port": 8084,
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/api/v1/alerts/(.*)", "/$1"]
            },
            "limit-req": {
                "rate": 30,
                "burst": 50,
                "key_type": "var",
                "key": "remote_addr",
                "rejected_code": 429
            }
        },
    },
    {
        "id": "route-sms",
        "name": "caller_sms",
        "uri": "/api/v1/sms/*",
        "priority": 10,
        "port": 8085,
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/api/v1/sms/(.*)", "/$1"]
            }
        },
    },
    {
        "id": "route-schedules",
        "name": "caller_scheduler",
        "uri": "/api/v1/schedules/*",
        "priority": 10,
        "port": 8086,
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/api/v1/schedules/(.*)", "/$1"]
            }
        },
    },
    {
        "id": "route-contacts",
        "name": "caller_address_book",
        "uri": "/api/v1/contacts/*",
        "priority": 10,
        "port": 8087,
        "plugins": {
            "proxy-rewrite": {
                "regex_uri": ["^/api/v1/contacts/(.*)", "/$1"]
            }
        },
    },
]


def login_dashboard() -> str:
    url = f"{DASHBOARD_URL}/apisix/admin/user/login"
    payload = {"username": DASHBOARD_USER, "password": DASHBOARD_PASS}
    resp = requests.post(url, json=payload, verify=False, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    token = (data.get("data") or {}).get("token")
    if not token:
        raise RuntimeError(f"Failed to obtain dashboard auth token: {data}")
    return token


def main():
    print(f"[*] Authenticating against APISIX Manager API at {DASHBOARD_URL}...")
    token = login_dashboard()
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }
    print(f"[+] Successfully authenticated. Target upstream host: {UPSTREAM_HOST}")

    for r_def in ROUTES:
        r_id = r_def["id"]
        port = r_def["port"]
        upstream_node = f"{UPSTREAM_HOST}:{port}"

        route_payload = {
            "id": r_id,
            "name": r_def["name"],
            "uri": r_def["uri"],
            "priority": r_def["priority"],
            "plugins": r_def.get("plugins", {}),
            "upstream": {
                "type": "roundrobin",
                "nodes": {
                    upstream_node: 1
                }
            },
            "status": 1
        }

        url = f"{DASHBOARD_URL}/apisix/admin/routes/{r_id}"
        print(f"[*] Syncing route '{r_id}' ({r_def['uri']} -> {upstream_node})...")
        resp = requests.put(url, headers=headers, json=route_payload, verify=False, timeout=10)
        resp.raise_for_status()
        res_data = resp.json()
        if res_data.get("code") == 0:
            print(f"[+] Route '{r_id}' active.")
        else:
            print(f"[!] Warning for route '{r_id}': {res_data}")

    print("\n=======================================================")
    print(" APISIX Unified Gateway Routes Successfully Applied!")
    print(f" Public HTTP Gateway:  http://192.168.101.212:9080")
    print(f" Public HTTPS Gateway: https://192.168.101.212:9443")
    print(f" Upstream Target:      {UPSTREAM_HOST}")
    print("=======================================================")


if __name__ == "__main__":
    main()
