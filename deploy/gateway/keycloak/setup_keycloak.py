#!/usr/bin/env python3
"""
Keycloak Realm, Roles, Clients, and Users provisioner for py-phone-caller.

Idempotent setup for the `py-phone-caller` realm on Keycloak.
"""

import os
import sys
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "https://127.0.0.1:8443")
ADMIN_USER = os.getenv("KEYCLOAK_ADMIN_USER", os.getenv("ADMIN_USER", "admin"))
ADMIN_PASS = os.getenv("KEYCLOAK_ADMIN_PASS", os.getenv("ADMIN_PASS", "admin123"))
REALM_NAME = os.getenv("KEYCLOAK_REALM", os.getenv("REALM_NAME", "py-phone-caller"))
M2M_SECRET = os.getenv("KEYCLOAK_M2M_SECRET", os.getenv("M2M_SECRET", "py-phone-caller-m2m-secret-2026"))
PUBLIC_URL = os.getenv("KEYCLOAK_PUBLIC_URL", os.getenv("PUBLIC_URL", "https://127.0.0.1:9443"))

USER_ADMIN_PASS = os.getenv("KEYCLOAK_USER_ADMIN_PASS", "Password123!")
USER_OPERATOR_PASS = os.getenv("KEYCLOAK_USER_OPERATOR_PASS", "Password123!")
USER_VIEWER_PASS = os.getenv("KEYCLOAK_USER_VIEWER_PASS", "Password123!")

ROLES = [
    {"name": "alert-admin", "description": "Platform Administrator with full unrestricted control"},
    {"name": "alert-operator", "description": "Duty Operator with dispatch, trigger, and ACK capabilities"},
    {"name": "alert-viewer", "description": "Read-only Monitor for NOC Wallboard and audit logs"},
]

USERS = [
    {
        "username": "admin_user",
        "email": "admin@openalert.lan",
        "firstName": "Admin",
        "lastName": "User",
        "password": USER_ADMIN_PASS,
        "role": "alert-admin",
    },
    {
        "username": "operator_user",
        "email": "operator@openalert.lan",
        "firstName": "Operator",
        "lastName": "User",
        "password": USER_OPERATOR_PASS,
        "role": "alert-operator",
    },
    {
        "username": "viewer_user",
        "email": "viewer@openalert.lan",
        "firstName": "Viewer",
        "lastName": "User",
        "password": USER_VIEWER_PASS,
        "role": "alert-viewer",
    },
]


def get_admin_token() -> str:
    url = f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token"
    data = {
        "client_id": "admin-cli",
        "username": ADMIN_USER,
        "password": ADMIN_PASS,
        "grant_type": "password",
    }
    resp = requests.post(url, data=data, verify=False, timeout=10)
    resp.raise_for_status()
    return resp.json()["access_token"]


def main():
    print(f"[*] Authenticating against Keycloak at {KEYCLOAK_URL}...")
    token = get_admin_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # 1. Create or verify Realm
    realms_resp = requests.get(f"{KEYCLOAK_URL}/admin/realms", headers=headers, verify=False, timeout=10)
    realms = [r["realm"] for r in realms_resp.json()]

    if REALM_NAME in realms:
        print(f"[+] Realm '{REALM_NAME}' already exists.")
    else:
        print(f"[*] Creating realm '{REALM_NAME}'...")
        realm_payload = {
            "realm": REALM_NAME,
            "enabled": True,
            "displayName": "PyPhoneCaller Identity & Access Management",
            "sslRequired": "none",
            "registrationAllowed": False,
            "rememberMe": True,
            "verifyEmail": False,
        }
        res = requests.post(f"{KEYCLOAK_URL}/admin/realms", headers=headers, json=realm_payload, verify=False, timeout=10)
        res.raise_for_status()
        print(f"[+] Realm '{REALM_NAME}' created successfully.")

    # 2. Create Realm Roles
    existing_roles_resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/roles", headers=headers, verify=False, timeout=10)
    existing_roles = {r["name"]: r for r in existing_roles_resp.json()}

    for role_def in ROLES:
        role_name = role_def["name"]
        if role_name in existing_roles:
            print(f"[+] Role '{role_name}' already exists.")
        else:
            print(f"[*] Creating role '{role_name}'...")
            res = requests.post(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/roles", headers=headers, json=role_def, verify=False, timeout=10)
            res.raise_for_status()
            print(f"[+] Role '{role_name}' created.")

    # Refresh roles dictionary
    existing_roles_resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/roles", headers=headers, verify=False, timeout=10)
    roles_map = {r["name"]: r for r in existing_roles_resp.json()}

    # 3. Create or update Clients
    clients_resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/clients", headers=headers, verify=False, timeout=10)
    existing_clients = {c["clientId"]: c for c in clients_resp.json()}

    # 3.1 Web UI Client (Public + PKCE + standard flow)
    ui_client_id = "py-phone-caller-ui"
    ui_payload = {
        "clientId": ui_client_id,
        "name": "PyPhoneCaller Web UI",
        "description": "Browser SSO client for Operator and Admin Web Portal",
        "enabled": True,
        "publicClient": True,
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": True,
        "rootUrl": f"{PUBLIC_URL}",
        "baseUrl": f"{PUBLIC_URL}/",
        "redirectUris": [
            f"{PUBLIC_URL}/*",
            "https://127.0.0.1:9443/*",
            "http://127.0.0.1:9080/*",
            "http://127.0.0.1:5000/*",
            "http://localhost:5000/*",
            "https://192.168.101.212:9443/*",
            "http://192.168.101.212:9080/*",
            "http://192.168.101.17:5000/*",
        ],
        "webOrigins": ["*"],
    }

    if ui_client_id in existing_clients:
        print(f"[+] Client '{ui_client_id}' already exists. Updating configuration...")
        c_id = existing_clients[ui_client_id]["id"]
        res = requests.put(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/clients/{c_id}", headers=headers, json=ui_payload, verify=False, timeout=10)
        res.raise_for_status()
        print(f"[+] Client '{ui_client_id}' updated.")
    else:
        print(f"[*] Creating client '{ui_client_id}'...")
        res = requests.post(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/clients", headers=headers, json=ui_payload, verify=False, timeout=10)
        res.raise_for_status()
        print(f"[+] Client '{ui_client_id}' created.")

    # 3.2 M2M Client (Confidential + Client Credentials)
    m2m_client_id = "py-phone-caller-m2m"
    m2m_payload = {
        "clientId": m2m_client_id,
        "name": "PyPhoneCaller M2M Client",
        "description": "Prometheus Alertmanager & Machine-to-Machine Integration Client",
        "enabled": True,
        "publicClient": False,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": True,
        "secret": M2M_SECRET,
    }

    if m2m_client_id in existing_clients:
        print(f"[+] Client '{m2m_client_id}' already exists. Updating configuration...")
        c_id = existing_clients[m2m_client_id]["id"]
        res = requests.put(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/clients/{c_id}", headers=headers, json=m2m_payload, verify=False, timeout=10)
        res.raise_for_status()
        m2m_internal_id = c_id
    else:
        print(f"[*] Creating client '{m2m_client_id}'...")
        res = requests.post(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/clients", headers=headers, json=m2m_payload, verify=False, timeout=10)
        res.raise_for_status()
        # Find internal ID
        c_resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/clients?clientId={m2m_client_id}", headers=headers, verify=False, timeout=10)
        m2m_internal_id = c_resp.json()[0]["id"]
        print(f"[+] Client '{m2m_client_id}' created.")

    # Assign alert-operator role to M2M service account
    sa_user_resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/clients/{m2m_internal_id}/service-account-user", headers=headers, verify=False, timeout=10)
    if sa_user_resp.status_code == 200:
        sa_user = sa_user_resp.json()
        sa_user_id = sa_user["id"]
        op_role = roles_map.get("alert-operator")
        if op_role:
            res = requests.post(
                f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/users/{sa_user_id}/role-mappings/realm",
                headers=headers,
                json=[{"id": op_role["id"], "name": op_role["name"]}],
                verify=False,
                timeout=10,
            )
            print(f"[+] Assigned 'alert-operator' role to M2M service account.")

    # 4. Create or update Users
    users_resp = requests.get(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/users", headers=headers, verify=False, timeout=10)
    existing_users = {u["username"]: u for u in users_resp.json()}

    for u_def in USERS:
        uname = u_def["username"]
        role_to_assign = u_def["role"]
        user_body = {
            "username": uname,
            "email": u_def["email"],
            "firstName": u_def["firstName"],
            "lastName": u_def["lastName"],
            "enabled": True,
            "emailVerified": True,
            "credentials": [
                {
                    "type": "password",
                    "value": u_def["password"],
                    "temporary": False,
                }
            ],
        }

        if uname in existing_users:
            print(f"[+] User '{uname}' already exists. Updating password...")
            user_id = existing_users[uname]["id"]
            pwd_payload = {
                "type": "password",
                "value": u_def["password"],
                "temporary": False,
            }
            res = requests.put(
                f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/users/{user_id}/reset-password",
                headers=headers,
                json=pwd_payload,
                verify=False,
                timeout=10,
            )
            res.raise_for_status()
            print(f"[+] Password for '{uname}' updated.")
        else:
            print(f"[*] Creating user '{uname}'...")
            res = requests.post(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/users", headers=headers, json=user_body, verify=False, timeout=10)
            res.raise_for_status()
            # fetch id
            u_lookup = requests.get(f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/users?username={uname}", headers=headers, verify=False, timeout=10)
            user_id = u_lookup.json()[0]["id"]
            print(f"[+] User '{uname}' created.")

        # Assign Role
        target_role = roles_map.get(role_to_assign)
        if target_role:
            requests.post(
                f"{KEYCLOAK_URL}/admin/realms/{REALM_NAME}/users/{user_id}/role-mappings/realm",
                headers=headers,
                json=[{"id": target_role["id"], "name": target_role["name"]}],
                verify=False,
                timeout=10,
            )
            print(f"[+] Role '{role_to_assign}' mapped to '{uname}'.")

    print("\n=======================================================")
    print(" Keycloak Configuration Complete!")
    print(f" Realm:    {REALM_NAME}")
    print(f" UI Client: {ui_client_id} (Public)")
    print(f" M2M Client:{m2m_client_id} (Secret: {M2M_SECRET})")
    print(f" Admin:     admin_user    / {USER_ADMIN_PASS}")
    print(f" Operator:  operator_user / {USER_OPERATOR_PASS}")
    print(f" Viewer:    viewer_user   / {USER_VIEWER_PASS}")
    print("=======================================================")


if __name__ == "__main__":
    main()
