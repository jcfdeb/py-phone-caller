#!/usr/bin/env bash
# ==============================================================================
# OpenAlert Daemon (`openalertd`) Release Bundle Builder
# ==============================================================================
# Builds locked, target-verified native bundles. Requires Python 3.11+ and binutils.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON:-python3}" "${SCRIPT_DIR}/release_bundle.py" "$@"

