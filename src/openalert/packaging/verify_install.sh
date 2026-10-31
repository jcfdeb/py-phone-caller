#!/usr/bin/env bash
# ==============================================================================
# OpenAlert Daemon (`openalertd`) Post-Installation Verification & Audit Script
# ==============================================================================
# Checks binary presence, configuration syntax, service-account directory access,
# systemd service status, and a read-only REST health probe.
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

usage() {
    printf '%s\n' \
        "Usage: $0 [options]" \
        '  --config PATH         Configuration file (default: /etc/openalertd/openalertd.toml)' \
        '  --unit NAME           Systemd unit (default: openalertd.service)' \
        '  --health-url URL      Health GET URL (default: http://127.0.0.1:8090/health)' \
        '  --binary PATH         Executable (default: /usr/local/bin/openalertd)' \
        '  --user NAME           Service account (default: openalert)' \
        '  --group NAME          Service group (default: openalert)' \
        '  --state-dir PATH      State directory (default: /var/lib/openalertd)' \
        '  --templates-dir PATH  Templates directory (default: /etc/openalertd/templates)' \
        '  --log-dir PATH        Log directory (default: /var/log/openalertd)' \
        '  -h, --help            Show this help' \
        'Paths must be absolute. Health verification requires curl and jq.' \
        'Only local checks and a health GET are performed; no alerts, calls or radio tests.'
}

CONF_PATH="/etc/openalertd/openalertd.toml"
UNIT_NAME="openalertd.service"
HEALTH_URL="http://127.0.0.1:8090/health"
BINARY_PATH="/usr/local/bin/openalertd"
SERVICE_USER="openalert"
SERVICE_GROUP="openalert"
STATE_DIR="/var/lib/openalertd"
TEMPLATES_DIR="/etc/openalertd/templates"
LOG_DIR="/var/log/openalertd"

while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -h|--help) usage; exit 0 ;;
        --config|--unit|--health-url|--binary|--user|--service-user|--group|--service-group|--state-dir|--templates-dir|--log-dir)
            if [[ "$#" -lt 2 || -z "$2" || "$2" == --* ]]; then
                report_fail "Option requires a non-empty value. See --help."
                exit 2
            fi
            case "$1" in
                --config) CONF_PATH="$2" ;;
                --unit) UNIT_NAME="$2" ;;
                --health-url) HEALTH_URL="$2" ;;
                --binary) BINARY_PATH="$2" ;;
                --user|--service-user) SERVICE_USER="$2" ;;
                --group|--service-group) SERVICE_GROUP="$2" ;;
                --state-dir) STATE_DIR="$2" ;;
                --templates-dir) TEMPLATES_DIR="$2" ;;
                --log-dir) LOG_DIR="$2" ;;
            esac
            shift 2
            ;;
        *) report_fail "Unknown option. See --help."; exit 2 ;;
    esac
done

for dir in "${CONF_PATH}" "${BINARY_PATH}" "${STATE_DIR}" "${TEMPLATES_DIR}" "${LOG_DIR}"; do
    if [[ "${dir}" != /* ]]; then
        report_fail "Configuration, binary and directory paths must be absolute."
        exit 2
    fi
done
if [[ "${HEALTH_URL}" != http://* && "${HEALTH_URL}" != https://* ]]; then
    report_fail "Health URL must use HTTP or HTTPS."
    exit 2
fi

echo "================================================================="
echo "   OpenAlert Daemon (openalertd) Post-Installation Audit Suite   "
echo "================================================================="

# 1. Binary checks
report_info "1. Checking openalertd binary..."
if [[ -f "${BINARY_PATH}" && -x "${BINARY_PATH}" ]]; then
    report_pass "Binary '${BINARY_PATH}' exists and is executable."
else
    report_fail "Binary '${BINARY_PATH}' missing or not executable."
fi

# 2. System user checks
report_info "2. Checking dedicated service account..."
if getent passwd "${SERVICE_USER}" >/dev/null 2>&1; then
    report_pass "System user '${SERVICE_USER}' exists."
    if [[ "$(id -u "${SERVICE_USER}" 2>/dev/null)" == 0 ]]; then
        report_fail "Service account must not be root."
    fi
else
    report_fail "System user '${SERVICE_USER}' does not exist."
fi

if getent group "${SERVICE_GROUP}" >/dev/null 2>&1; then
    report_pass "System group '${SERVICE_GROUP}' exists."
else
    report_fail "System group '${SERVICE_GROUP}' does not exist."
fi

SERVICE_RUNNER=()
SERVICE_CONTEXT=false
if [[ "$(id -un)" == "${SERVICE_USER}" && "$(id -gn)" == "${SERVICE_GROUP}" ]]; then
    SERVICE_CONTEXT=true
elif [[ "$(id -u)" -eq 0 ]] && command -v runuser >/dev/null 2>&1; then
    SERVICE_RUNNER=(runuser -u "${SERVICE_USER}" -g "${SERVICE_GROUP}" --)
    SERVICE_CONTEXT=true
else
    report_warn "Cannot assume the selected service account/group; configuration will be checked as the caller."
    report_warn "Service-account filesystem access is not verified; rerun as root with runuser or as the selected account/group."
fi

# 3. Directory and permissions check
report_info "3. Checking selected directory hierarchy..."
for dir in "$(dirname "${CONF_PATH}")" "${TEMPLATES_DIR}" "${STATE_DIR}" "${LOG_DIR}"; do
    if [[ -d "${dir}" ]]; then
        report_pass "Directory '${dir}' exists."
    else
        report_fail "Directory '${dir}' is missing."
    fi
done

if [[ "${SERVICE_CONTEXT}" == true ]]; then
    for dir in "${STATE_DIR}" "${LOG_DIR}"; do
        if "${SERVICE_RUNNER[@]}" test -w "${dir}" >/dev/null 2>&1 &&
           "${SERVICE_RUNNER[@]}" test -x "${dir}" >/dev/null 2>&1; then
            report_pass "Directory '${dir}' is writable/searchable by '${SERVICE_USER}:${SERVICE_GROUP}'."
        else
            report_fail "Directory '${dir}' is NOT writable/searchable by '${SERVICE_USER}:${SERVICE_GROUP}'."
        fi
    done
fi

# 4. Configuration file and syntax dry-run check
report_info "4. Checking configuration syntax and template parsing..."
if [[ -f "${CONF_PATH}" ]]; then
    report_pass "Configuration file '${CONF_PATH}' exists."
    if (cd "${STATE_DIR}" && "${SERVICE_RUNNER[@]}" "${BINARY_PATH}" check "${CONF_PATH}") >/dev/null 2>&1; then
        report_pass "Configuration dry-run passed (output suppressed; no transport or delivery test)."
    else
        report_fail "Configuration check FAILED for '${CONF_PATH}' (output suppressed to protect secrets)."
    fi
else
    report_fail "Configuration file '${CONF_PATH}' not found."
fi

# 5. Systemd unit registration and runtime checks (also supports template instances)
report_info "5. Checking selected systemd unit and runtime status..."
if command -v systemctl >/dev/null 2>&1; then
    if [[ "$(systemctl show --property=LoadState --value -- "${UNIT_NAME}" 2>/dev/null)" == loaded ]]; then
        report_pass "Systemd unit '${UNIT_NAME}' is loaded."
    else
        report_fail "Systemd unit '${UNIT_NAME}' is not loaded or cannot be queried."
    fi
    if systemctl is-active --quiet -- "${UNIT_NAME}" >/dev/null 2>&1; then
        report_pass "Service '${UNIT_NAME}' is ACTIVE and running."
    else
        report_fail "Service '${UNIT_NAME}' is inactive or cannot be queried."
    fi
else
    report_fail "systemctl is unavailable; unit and runtime status cannot be verified."
fi

# 6. Read-only health probe; never print the URL, response body or curl errors.
report_info "6. Checking HTTP health (GET only)..."
if ! command -v curl >/dev/null 2>&1; then
    report_fail "curl is unavailable; HTTP health cannot be verified."
elif ! command -v jq >/dev/null 2>&1; then
    report_fail "jq is unavailable; JSON health status cannot be verified."
elif HEALTH_RESP=$(curl --disable --globoff --silent --show-error --fail --request GET \
    --connect-timeout 2 --max-time 5 --max-filesize 65536 --proto '=http,https' \
    --write-out $'\n%{http_code}' -- "${HEALTH_URL}" 2>/dev/null); then
    if [[ "${HEALTH_RESP##*$'\n'}" == 200 ]] &&
       printf '%s' "${HEALTH_RESP%$'\n'*}" | jq -e -s \
           'length == 1 and (.[0] | type == "object" and .status == "ok")' >/dev/null 2>&1; then
        report_pass "HTTP health returned 200 with status ok (body suppressed)."
    else
        report_fail "HTTP health returned an unexpected status or invalid/unhealthy JSON (body suppressed)."
    fi
else
    report_fail "HTTP health request failed (details suppressed)."
fi
unset HEALTH_RESP

report_info "Limits: no binary provenance, systemd sandbox, unit-to-path mapping, alert delivery, calls or radio operation is verified."
echo "================================================================="
echo -e "Audit Summary: ${GREEN}${PASS_COUNT} Passed${NC}, ${RED}${FAIL_COUNT} Failed${NC}, ${YELLOW}${WARN_COUNT} Warnings${NC}"
echo "================================================================="

if [[ "${FAIL_COUNT}" -gt 0 ]]; then
    exit 1
fi

exit 0
