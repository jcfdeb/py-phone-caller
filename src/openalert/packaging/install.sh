#!/usr/bin/env bash
# ==============================================================================
# OpenAlert Daemon (`openalertd`) Production Bare-Metal Installer
# ==============================================================================
# Installs openalertd as a hardened, unprivileged systemd service with ambient
# Linux network capabilities (CAP_NET_BIND_SERVICE, CAP_NET_ADMIN, CAP_NET_RAW).
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $*"; }

# 1. Root check
if [[ "${EUID}" -ne 0 ]]; then
    log_err "This installation script must be run as root or via sudo."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

log_info "Starting OpenAlert Daemon (openalertd) bare-metal installation..."

# 2. Locate or compile the openalertd binary
BINARY_PATH=""
if [[ -f "${SCRIPT_DIR}/bin/openalertd" ]]; then
    BINARY_PATH="${SCRIPT_DIR}/bin/openalertd"
elif [[ -f "${SCRIPT_DIR}/../target/release/openalertd" ]]; then
    BINARY_PATH="${SCRIPT_DIR}/../target/release/openalertd"
elif [[ -f "${REPO_ROOT}/src/openalert/target/release/openalertd" ]]; then
    BINARY_PATH="${REPO_ROOT}/src/openalert/target/release/openalertd"
elif [[ -f "${SCRIPT_DIR}/openalertd" ]]; then
    BINARY_PATH="${SCRIPT_DIR}/openalertd"
fi

if [[ -z "${BINARY_PATH}" || ! -f "${BINARY_PATH}" ]]; then
    log_warn "Precompiled openalertd release binary not found in standard paths."
    if command -v cargo >/dev/null 2>&1; then
        log_info "Compiling openalertd from source using cargo (--release)..."
        (cd "${REPO_ROOT}/src/openalert" && cargo build --release)
        BINARY_PATH="${REPO_ROOT}/src/openalert/target/release/openalertd"
    else
        log_err "Neither precompiled binary nor 'cargo' toolchain was found."
        log_err "Please build openalertd first or provide the release bundle."
        exit 1
    fi
fi

# 3. Create dedicated system user and group
if ! getent group openalert >/dev/null 2>&1; then
    log_info "Creating system group 'openalert'..."
    groupadd --system openalert
fi

if ! getent passwd openalert >/dev/null 2>&1; then
    log_info "Creating system user 'openalert'..."
    useradd --system \
        --gid openalert \
        --home-dir /var/lib/openalertd \
        --no-create-home \
        --shell /usr/sbin/nologin \
        --comment "OpenAlert Daemon Service" \
        openalert
fi

# Add openalert to bluetooth group if available on the system
if getent group bluetooth >/dev/null 2>&1; then
    usermod -aG bluetooth openalert || true
fi

# 4. Prepare directory hierarchy
log_info "Provisioning filesystem directory hierarchy..."
install -d -m 0755 /usr/local/bin
install -d -m 0750 -o root -g openalert /etc/openalertd
install -d -m 0755 -o root -g openalert /etc/openalertd/templates
install -d -m 0750 -o openalert -g openalert /var/lib/openalertd
install -d -m 0750 -o openalert -g openalert /var/log/openalertd

# 5. Copy executable binary and set capabilities
log_info "Installing openalertd binary to /usr/local/bin/openalertd..."
install -m 0755 "${BINARY_PATH}" /usr/local/bin/openalertd

if command -v setcap >/dev/null 2>&1; then
    log_info "Setting ambient file capabilities (CAP_NET_BIND_SERVICE, CAP_NET_ADMIN, CAP_NET_RAW)..."
    setcap 'cap_net_bind_service,cap_net_admin,cap_net_raw=+ep' /usr/local/bin/openalertd || {
        log_warn "setcap failed (filesystem may not support extended attributes). Relying on systemd AmbientCapabilities."
    }
else
    log_warn "'setcap' utility not found. Systemd AmbientCapabilities will be used."
fi

# 6. Install default template files
TEMPLATE_SRC=""
if [[ -d "${SCRIPT_DIR}/templates" ]]; then
    TEMPLATE_SRC="${SCRIPT_DIR}/templates"
elif [[ -d "${REPO_ROOT}/src/openalert/templates" ]]; then
    TEMPLATE_SRC="${REPO_ROOT}/src/openalert/templates"
fi

if [[ -n "${TEMPLATE_SRC}" && -d "${TEMPLATE_SRC}" ]]; then
    log_info "Installing alert payload Tera templates to /etc/openalertd/templates/..."
    cp -r "${TEMPLATE_SRC}/"* /etc/openalertd/templates/
    chown -R root:openalert /etc/openalertd/templates/
    chmod -R 0644 /etc/openalertd/templates/*.tera 2>/dev/null || true
    chmod 0755 /etc/openalertd/templates
fi

# 7. Install configuration file if not already present
EXAMPLE_CONF=""
if [[ -f "${SCRIPT_DIR}/openalertd.toml.example" ]]; then
    EXAMPLE_CONF="${SCRIPT_DIR}/openalertd.toml.example"
elif [[ -f "${REPO_ROOT}/src/openalert/config/openalertd.toml" ]]; then
    EXAMPLE_CONF="${REPO_ROOT}/src/openalert/config/openalertd.toml"
fi

if [[ ! -f /etc/openalertd/openalertd.toml && -n "${EXAMPLE_CONF}" ]]; then
    log_info "Deploying initial configuration from example..."
    install -m 0640 -o root -g openalert "${EXAMPLE_CONF}" /etc/openalertd/openalertd.toml
    # Set templates path to standard production location
    sed -i 's|template_dir = "templates"|template_dir = "/etc/openalertd/templates"|' /etc/openalertd/openalertd.toml || true
    sed -i 's|path = "data/openalert.db"|path = "/var/lib/openalertd/openalert.db"|' /etc/openalertd/openalertd.toml || true
    sed -i 's|logging = "default"|logging = "systemd"|' /etc/openalertd/openalertd.toml || true
else
    log_info "/etc/openalertd/openalertd.toml already exists. Preserving existing configuration."
fi

# 8. Deploy systemd service unit
SERVICE_SRC=""
if [[ -f "${SCRIPT_DIR}/systemd/openalertd.service" ]]; then
    SERVICE_SRC="${SCRIPT_DIR}/systemd/openalertd.service"
elif [[ -f "${REPO_ROOT}/src/openalert/packaging/systemd/openalertd.service" ]]; then
    SERVICE_SRC="${REPO_ROOT}/src/openalert/packaging/systemd/openalertd.service"
fi

if [[ -n "${SERVICE_SRC}" && -f "${SERVICE_SRC}" ]]; then
    log_info "Installing systemd unit to /etc/systemd/system/openalertd.service..."
    install -m 0644 "${SERVICE_SRC}" /etc/systemd/system/openalertd.service
    systemctl daemon-reload
fi

# 9. Dry-run validate configuration
log_info "Running dry-run validation check..."
if /usr/local/bin/openalertd check /etc/openalertd/openalertd.toml; then
    log_ok "Configuration dry-run check succeeded!"
else
    log_warn "Configuration dry-run reported issues. Please review /etc/openalertd/openalertd.toml"
fi

echo ""
log_ok "OpenAlert Daemon installation complete!"
echo ""
echo "To start and enable the service on system boot, run:"
echo "    sudo systemctl enable --now openalertd"
echo ""
echo "To inspect live service logs:"
echo "    journalctl -u openalertd -f"
echo ""
echo "To run operational diagnostics:"
echo "    openalertd status"
echo "    openalertd peers"
echo "    openalertd spool"
echo ""
