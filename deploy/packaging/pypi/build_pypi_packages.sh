#!/usr/bin/env bash
# ==============================================================================
# py-phone-caller PyPI Wheel & Sdist Release Builder
# ==============================================================================
# Builds and verifies all 12 workspace packages plus the `py-phone-caller`
# meta-package into dist/pypi/ with SHA256SUMS and release.json.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/build_pypi_packages.py" "$@"
