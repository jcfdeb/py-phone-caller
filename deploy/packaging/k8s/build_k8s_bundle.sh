#!/usr/bin/env bash
# ==============================================================================
# py-phone-caller Kubernetes & Helm Chart Release Builder
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/build_k8s_bundle.py" "$@"
