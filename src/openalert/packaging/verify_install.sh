#!/usr/bin/env bash
# ==============================================================================
# OpenAlert Daemon (`openalertd`) Post-Installation Verification & Audit Script
# ==============================================================================
# Validates binary integrity, configuration syntax, directory permissions,
# system user privileges, systemd service status, and REST health probe.
# ==============================================================================

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

report_pass() { echo -e "${GREEN}[PASS]${NC} $*"; ((PASS_COUNT++)); }
report_fail() { echo -e "${RED}[FAIL]${NC} $*"; ((FAIL_COUNT++)); }
report_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; ((WARN_COUNT++)); }
report_info() { echo -e "${BLUE}[INFO]${NC} $*"; }

echo "================================================================="
echo "   OpenAlert Daemon (openalertd) Post-Installation Audit Suite   "
echo "================================================================="

# 1. Binary checks
report_info "1. Checking openalertd binary..."
if [[ -x /usr/local/bin/openalertd ]]; then
    report_pass "Binary /usr/local/bin/openalertd exists and is executable."
else
    report_fail "Binary /usr/local/bin/openalertd missing or not executable."
fi

# 2. System user checks
report_info "2. Checking dedicated service account..."
if getent passwd openalert >/dev/null 2>&1; then
    report_pass "System user 'openalert' exists."
else
    report_fail "System user 'openalert' does not exist."
fi

if getent group openalert >/dev/null 2>&1; then
    report_pass "System group 'openalert' exists."
else
    report_fail "System group 'openalert' does not exist."
fi

# 3. Directory and permissions check
report_info "3. Checking standard directory hierarchy..."
for dir in /etc/openalertd /etc/openalertd/templates /var/lib/openalertd /var/log/openalertd; do
    if [[ -d "${dir}" ]]; then
        report_pass "Directory '${dir}' exists."
    else
        report_fail "Directory '${dir}' is missing."
    fi
done

# Check database directory writable by openalert
if command -v su >/dev/null 2>&1 && [[ "${EUID}" -eq 0 ]]; then
    if su -s /bin/sh openalert -c "test -w /var/lib/openalertd"; then
        report_pass "Storage directory /var/lib/openalertd is writable by 'openalert' user."
    else
        report_fail "Storage directory /var/lib/openalertd is NOT writable by 'openalert' user."
    fi
fi

# 4. Configuration file and syntax dry-run check
report_info "4. Checking configuration syntax and template parsing..."
CONF_PATH="/etc/openalertd/openalertd.toml"
if [[ -f "${CONF_PATH}" ]]; then
    report_pass "Configuration file '${CONF_PATH}' exists."
    if /usr/local/bin/openalertd check "${CONF_PATH}" >/dev/null 2>&1; then
        report_pass "Configuration check passed (syntax, templates, listening addresses verified)."
    else
        report_fail "Configuration check FAILED for '${CONF_PATH}'."
    fi
else
    report_fail "Configuration file '${CONF_PATH}' not found."
fi

# 5. D-Bus socket check (for BitChat BLE)
report_info "5. Checking D-Bus system bus accessibility..."
if [[ -S /var/run/dbus/system_bus_socket || -S /run/dbus/system_bus_socket ]]; then
    report_pass "D-Bus system bus socket exists."
else
    report_warn "D-Bus system bus socket not detected (BitChat BLE mesh requires D-Bus)."
fi

# 6. Systemd unit registration check
report_info "6. Checking systemd service unit..."
if [[ -f /etc/systemd/system/openalertd.service ]]; then
    report_pass "Systemd unit /etc/systemd/system/openalertd.service is installed."
else
    report_fail "Systemd unit /etc/systemd/system/openalertd.service is missing."
fi

# 7. Service runtime and health check
report_info "7. Checking service runtime status..."
if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet openalertd; then
        report_pass "Service 'openalertd' is ACTIVE and running."

        # Probe REST health endpoint
        if command -v curl >/dev/null 2>&1; then
            HEALTH_RESP=$(curl -s --connect-timeout 2 http://127.0.0.1:8090/health 2>/dev/null || echo "")
            if echo "${HEALTH_RESP}" | grep -q '"ok"'; then
                report_pass "HTTP health probe response: ${HEALTH_RESP}"
            else
                report_warn "HTTP health probe failed on http://127.0.0.1:8090/health. (Endpoint returned: '${HEALTH_RESP}')"
            fi
        fi
    else
        report_warn "Service 'openalertd' is currently INACTIVE. (Start with 'sudo systemctl start openalertd')"
    fi
fi

echo "================================================================="
echo -e "Audit Summary: ${GREEN}${PASS_COUNT} Passed${NC}, ${RED}${FAIL_COUNT} Failed${NC}, ${YELLOW}${WARN_COUNT} Warnings${NC}"
echo "================================================================="

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
    exit 1
fi

exit 0
