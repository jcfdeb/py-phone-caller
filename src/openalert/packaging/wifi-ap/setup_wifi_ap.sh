#!/usr/bin/env bash
# ==============================================================================
# OpenAlert Field Node - Optional Wi-Fi Access Point & Port 80 SOS Captive Portal
# ==============================================================================
# Configures a standard Linux Wi-Fi Access Point (hostapd + dnsmasq + nginx-light)
# on an embedded ARM / Linux board (e.g., Orange Pi Zero 3 / Raspberry Pi) so
# field users without BitChat or 0xChat can join the Wi-Fi hotspot and
# automatically receive the simplified "/sos" Emergency Web Portal on Port 80.
#
# Environment Variables (Optional Overrides):
#   AP_IFACE="wlan0"
#   AP_SSID="OpenAlert-SOS"
#   AP_PASS=""                 # Empty = Open Captive Portal (protected by SVG CAPTCHA)
#                              # Or set 8..63 char passphrase for WPA2-PSK
#   AP_CHANNEL="6"
#   AP_IP="10.42.0.1"
#   AP_DHCP_START="10.42.0.10"
#   AP_DHCP_END="10.42.0.50"
#   OPENALERT_PORT="8092"
#   SOS_PATH="/sos"
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $*"; }

if [[ "${EUID}" -ne 0 ]]; then
    log_err "This script must be run as root or via sudo."
    exit 1
fi

AP_IFACE="${AP_IFACE:-wlan0}"
AP_SSID="${AP_SSID:-OpenAlert-SOS}"
AP_PASS="${AP_PASS:-}"
AP_CHANNEL="${AP_CHANNEL:-6}"
AP_IP="${AP_IP:-10.42.0.1}"
AP_DHCP_START="${AP_DHCP_START:-10.42.0.10}"
AP_DHCP_END="${AP_DHCP_END:-10.42.0.50}"
OPENALERT_PORT="${OPENALERT_PORT:-8092}"
SOS_PATH="${SOS_PATH:-/sos}"

log_info "Configuring OpenAlert Wi-Fi Access Point ('${AP_SSID}') on ${AP_IFACE} (${AP_IP})..."

# 1. Install standard Linux packages if missing
MISSING_PKGS=()
command -v hostapd >/dev/null 2>&1 || MISSING_PKGS+=("hostapd")
command -v dnsmasq >/dev/null 2>&1 || MISSING_PKGS+=("dnsmasq")
command -v nginx   >/dev/null 2>&1 || MISSING_PKGS+=("nginx-light")

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    log_info "Installing required packages: ${MISSING_PKGS[*]}..."
    DEBIAN_FRONTEND=noninteractive apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${MISSING_PKGS[@]}"
fi

# 2. Release wireless interface from wpa_supplicant if running
if systemctl is-active --quiet wpa_supplicant.service; then
    log_info "Stopping wpa_supplicant.service so hostapd can manage ${AP_IFACE}..."
    systemctl stop wpa_supplicant.service || true
    systemctl disable wpa_supplicant.service || true
fi
rfkill unblock wifi || true

# 3. Configure static IP via systemd-networkd and immediate iproute2 assignment
log_info "Configuring static IPv4 ${AP_IP}/24 on ${AP_IFACE}..."
mkdir -p /etc/systemd/network
cat > "/etc/systemd/network/20-openalert-${AP_IFACE}-ap.network" <<EOF
[Match]
Name=${AP_IFACE}

[Network]
Address=${AP_IP}/24
ConfigureWithoutCarrier=yes
IgnoreCarrierLoss=yes
IPMasquerade=no
DHCPServer=no
EOF

ip link set "${AP_IFACE}" up || true
ip addr flush dev "${AP_IFACE}" || true
ip addr add "${AP_IP}/24" dev "${AP_IFACE}" || true
systemctl reload-or-restart systemd-networkd.service 2>/dev/null || true

# 4. Configure hostapd
log_info "Writing /etc/hostapd/hostapd.conf (SSID: ${AP_SSID}, Channel: ${AP_CHANNEL})..."
mkdir -p /etc/hostapd
cat > /etc/hostapd/hostapd.conf <<EOF
interface=${AP_IFACE}
driver=nl80211
ssid=${AP_SSID}
hw_mode=g
channel=${AP_CHANNEL}
ieee80211n=1
wmm_enabled=1
auth_algs=1
ignore_broadcast_ssid=0
EOF

if [[ -n "${AP_PASS}" ]]; then
    cat >> /etc/hostapd/hostapd.conf <<EOF
wpa=2
wpa_passphrase=${AP_PASS}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF
fi

if [[ -f /etc/default/hostapd ]]; then
    sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd || true
fi

# Add systemd drop-in so cold-booting without Ethernet guarantees IPv4 assignment after hostapd initializes
mkdir -p /etc/systemd/system/hostapd.service.d
cat > /etc/systemd/system/hostapd.service.d/openalert-ap.conf <<EOF
[Unit]
After=sys-subsystem-net-devices-${AP_IFACE}.device
Wants=sys-subsystem-net-devices-${AP_IFACE}.device

[Service]
ExecStartPost=/bin/sh -c "sleep 1 && /usr/sbin/ip addr replace ${AP_IP}/24 dev ${AP_IFACE} && /usr/sbin/ip link set ${AP_IFACE} up"
Restart=on-failure
RestartSec=3
EOF

systemctl daemon-reload
systemctl unmask hostapd.service || true
systemctl enable hostapd.service
systemctl restart hostapd.service

# Ensure IP address stays assigned on AP interface after hostapd resets interface state
sleep 1
ip addr replace "${AP_IP}/24" dev "${AP_IFACE}" 2>/dev/null || true

# 5. Configure dnsmasq for DHCP + Captive Portal DNS hijack
log_info "Writing /etc/dnsmasq.d/openalert-ap.conf..."
mkdir -p /etc/dnsmasq.d
cat > /etc/dnsmasq.d/openalert-ap.conf <<EOF
interface=${AP_IFACE}
listen-address=${AP_IP}
bind-dynamic
except-interface=lo
no-resolv
no-poll
domain-needed
bogus-priv
dhcp-range=${AP_DHCP_START},${AP_DHCP_END},255.255.255.0,1h
dhcp-option=option:router,${AP_IP}
dhcp-option=option:dns-server,${AP_IP}
dhcp-option=114,http://${AP_IP}${SOS_PATH}
address=/#/${AP_IP}
EOF

systemctl enable dnsmasq.service
systemctl restart dnsmasq.service

# 6. Configure Nginx Port 80 Reverse Proxy & Captive Portal Redirect
log_info "Configuring Nginx Port 80 reverse proxy -> 127.0.0.1:${OPENALERT_PORT}${SOS_PATH}..."
CLEAN_SOS_NAME="${SOS_PATH#/}"
cat > /etc/nginx/sites-available/default <<EOF
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    # 1. Proxy the simplified SOS Portal, SOS CAPTCHA/Trigger API, and Logo assets to openalertd
    location ~ ^/(${CLEAN_SOS_NAME}|api/v1/sos|api/v1/logo|logo\.png|health) {
        proxy_pass http://127.0.0.1:${OPENALERT_PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    }

    # 2. Catch-all (root "/" and iOS/Android/Windows Captive Portal probes) -> Redirect to ${SOS_PATH}
    location / {
        return 302 \$scheme://\$http_host${SOS_PATH};
    }
}
EOF

nginx -t
systemctl enable nginx.service
systemctl reload-or-restart nginx.service

log_ok "OpenAlert Wi-Fi Access Point & Port 80 SOS Captive Portal is LIVE!"
echo "  • Wi-Fi SSID        : ${AP_SSID} (Channel ${AP_CHANNEL})"
echo "  • Gateway / Portal  : http://${AP_IP}${SOS_PATH}"
echo "  • DHCP Pool         : ${AP_DHCP_START} - ${AP_DHCP_END}"
echo "  • Upstream Daemon   : http://127.0.0.1:${OPENALERT_PORT}"
