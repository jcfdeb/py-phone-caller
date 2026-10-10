#!/usr/bin/env bash
# ===========================================================================
# show-credentials.sh
# Inspect generated credentials for py-phone-caller, APISIX, and Keycloak.
# Supports both plaintext and Ansible-Vault-encrypted credential files.
# ===========================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREDS_DIR="${SCRIPT_DIR}/credentials"

if [ ! -d "${CREDS_DIR}" ]; then
  echo "Error: Credentials directory '${CREDS_DIR}' does not exist yet." >&2
  echo "Run 'ansible-playbook deploy_py-phone-caller.yml' to generate them." >&2
  exit 1
fi

VAULT_OPTS=()
if [ -f "${SCRIPT_DIR}/.vault_pass" ]; then
  VAULT_OPTS=(--vault-password-file "${SCRIPT_DIR}/.vault_pass")
elif [ -f "${HOME}/.vault_pass" ]; then
  VAULT_OPTS=(--vault-password-file "${HOME}/.vault_pass")
fi

read_secret() {
  local filename="$1"
  local file="${CREDS_DIR}/${filename}"
  if [ ! -f "${file}" ]; then
    echo "<not generated yet>"
    return
  fi
  if head -n 1 "${file}" | grep -q '^\$ANSIBLE_VAULT;'; then
    ansible-vault view "${VAULT_OPTS[@]}" "${file}" 2>/dev/null || echo "<encrypted - vault password required>"
  else
    cat "${file}"
  fi
}

echo "========================================================================"
echo "           PY-PHONE-CALLER DEPLOYED SECRETS & CREDENTIALS               "
echo "========================================================================"
echo "Directory: ${CREDS_DIR}"
if [ ${#VAULT_OPTS[@]} -gt 0 ]; then
  echo "Status:    Encrypted with Ansible Vault (auto-unlocked via .vault_pass)"
else
  echo "Status:    Ansible Vault (interactive or manual password needed)"
fi
echo "------------------------------------------------------------------------"
echo "  [Web UI - Keycloak SSO Accounts]"
echo "    admin_user:         $(read_secret 'keycloak_user_admin_password.txt')  (Role: alert-admin)"
echo "    operator_user:      $(read_secret 'keycloak_user_operator_password.txt')  (Role: alert-operator)"
echo "    viewer_user:        $(read_secret 'keycloak_user_viewer_password.txt')  (Role: alert-viewer)"
echo ""
echo "  [Web UI - Local Fallback Admin]"
echo "    admin@...:          $(read_secret 'web_ui_admin_password.txt')"
echo ""
echo "  [Keycloak Master Admin Console (/admin)]"
echo "    admin:              $(read_secret 'keycloak_admin_password.txt')"
echo ""
echo "  [APISIX Dashboard (:9001)]"
echo "    admin:              $(read_secret 'apisix_dashboard_password.txt')"
echo ""
echo "  [Machine-to-Machine & Infrastructure]"
echo "    Keycloak M2M Secret:$(read_secret 'keycloak_m2m_client_secret.txt')"
echo "    Keycloak DB Pass:   $(read_secret 'keycloak_db_password.txt')"
echo "========================================================================"
