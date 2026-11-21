#!/usr/bin/env bash
# ==============================================================================
# py-phone-caller Ansible Release Bundle Builder Wrapper
# ==============================================================================
# Produces deterministic, secret-scrubbed Ansible release tarballs (.tar.gz +
# .sha256) with embedded release.json manifest for GitHub Releases and offline
# air-gapped controllers.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-python3}"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/build_ansible_bundle.py" "$@"
