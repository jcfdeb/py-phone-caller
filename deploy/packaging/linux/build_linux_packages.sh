#!/usr/bin/env bash
# ==============================================================================
# py-phone-caller & openalertd Native Linux Package Builder (.deb & .rpm)
# ==============================================================================
# Builds deterministic Debian (.deb) and RPM (.rpm) packages into dist/linux/.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/build_linux_packages.py" "$@"
