#!/usr/bin/env bash
# ==============================================================================
# py-phone-caller Master Release Packaging Script
# ==============================================================================
# Builds and verifies:
#   1. Ansible Release Bundle (dist/ansible/)
#   2. PyPI Wheels & Source Distributions (dist/pypi/)
#   3. Native Linux RPM & DEB Packages (dist/linux/)
#   4. Kubernetes Manifests & Helm Chart (dist/k8s/)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/build_all_releases.py" "$@"
