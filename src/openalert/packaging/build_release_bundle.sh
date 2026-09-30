#!/usr/bin/env bash
# ==============================================================================
# OpenAlert Daemon (`openalertd`) Release Bundle Builder
# ==============================================================================
# Builds optimized binary and packages self-contained distribution tarballs.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRATE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

VERSION=$(grep -m1 '^version' "${CRATE_DIR}/Cargo.toml" | cut -d '"' -f 2)
ARCH=$(uname -m)
BUNDLE_NAME="openalertd-v${VERSION}-linux-${ARCH}"
DIST_DIR="${CRATE_DIR}/dist"
STAGE_DIR="${DIST_DIR}/${BUNDLE_NAME}"

echo "🔨 Building release binary for openalertd v${VERSION} (${ARCH})..."
cd "${CRATE_DIR}"
cargo build --release

echo "📦 Assembling distribution bundle in ${STAGE_DIR}..."
rm -rf "${STAGE_DIR}" "${DIST_DIR}/${BUNDLE_NAME}.tar.gz"
mkdir -p "${STAGE_DIR}/bin"
mkdir -p "${STAGE_DIR}/templates"
mkdir -p "${STAGE_DIR}/systemd"
mkdir -p "${STAGE_DIR}/profiles"

# Copy binary
cp "${CRATE_DIR}/target/release/openalertd" "${STAGE_DIR}/bin/openalertd"
strip "${STAGE_DIR}/bin/openalertd" 2>/dev/null || true
chmod 0755 "${STAGE_DIR}/bin/openalertd"

# Copy templates
cp "${CRATE_DIR}/templates/"* "${STAGE_DIR}/templates/"

# Copy example config and turnkey profiles
cp "${SCRIPT_DIR}/openalertd.toml.example" "${STAGE_DIR}/openalertd.toml.example"
cp "${CRATE_DIR}/config/profiles/"*.toml "${STAGE_DIR}/profiles/"

# Copy systemd unit
cp "${SCRIPT_DIR}/systemd/openalertd.service" "${STAGE_DIR}/systemd/openalertd.service"

# Copy installer and verification scripts
cp "${SCRIPT_DIR}/install.sh" "${STAGE_DIR}/install.sh"
cp "${SCRIPT_DIR}/verify_install.sh" "${STAGE_DIR}/verify_install.sh"
chmod 0755 "${STAGE_DIR}/install.sh" "${STAGE_DIR}/verify_install.sh"

# Copy README
cp "${SCRIPT_DIR}/README.md" "${STAGE_DIR}/README.md"

echo "🗜️ Creating tarball ${DIST_DIR}/${BUNDLE_NAME}.tar.gz..."
cd "${DIST_DIR}"
tar -czf "${BUNDLE_NAME}.tar.gz" "${BUNDLE_NAME}"

echo "🔐 Generating SHA-256 checksum..."
sha256sum "${BUNDLE_NAME}.tar.gz" > "${BUNDLE_NAME}.tar.gz.sha256"

echo "✅ Release bundle created successfully:"
ls -lh "${DIST_DIR}/${BUNDLE_NAME}.tar.gz"
cat "${DIST_DIR}/${BUNDLE_NAME}.tar.gz.sha256"
