#!/bin/bash
# ==============================================================================
# Script: build_all_images.sh
# Project: py-phone-caller
#
# Purpose:
#   Builds all 11 microservice container images for py-phone-caller using either
#   Podman (default) or Docker.
#
# Architecture & Build Context:
#   - Every Dockerfile references shared Python dependencies, `pyproject.toml`,
#     and `uv.lock`. Therefore, all builds MUST execute with the repository root
#     as the build context (`$PROJECT_ROOT`).
#   - The `--format docker` flag is passed when using Podman to ensure standard
#     OCI/Docker compatibility across orchestration systems.
#
# Configurable Environment Variables:
#   - CONTAINER_ENGINE : Container builder binary (`podman` or `docker`). Default: `podman`
#   - IMAGE_REGISTRY   : Target registry prefix for tagging. Default: `localhost`
#   - IMAGE_TAG        : Image tag to assign. Default: `latest`
#
# Usage:
#   ./src/build_all_images.sh
#   CONTAINER_ENGINE=docker IMAGE_TAG=1.0.0 ./src/build_all_images.sh
# ==============================================================================

export SUPPRESS_BOLTDB_WARNING="true"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-localhost}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"

# Microservices to build (corresponds to subdirectories under src/)
SERVICES=(
    "asterisk_caller"
    "asterisk_recaller"
    "asterisk_ws_monitor"
    "caller_prometheus_webhook"
    "caller_register"
    "caller_scheduler"
    "caller_sms"
    "generate_audio"
    "caller_address_book"
    "py_phone_caller_ui"
    "celery_worker"
)

echo "=============================================================================="
echo " 🐳 Building All py-phone-caller Container Images"
echo " Engine:   ${CONTAINER_ENGINE}"
echo " Registry: ${IMAGE_REGISTRY}"
echo " Tag:      ${IMAGE_TAG}"
echo " Root:     ${PROJECT_ROOT}"
echo "=============================================================================="

TOTAL=${#SERVICES[@]}
COUNT=1

for SERVICE in "${SERVICES[@]}"; do
    DOCKERFILE_PATH="${PROJECT_ROOT}/src/${SERVICE}/Dockerfile"

    if [[ ! -f "$DOCKERFILE_PATH" ]]; then
        echo "⚠️  [${COUNT}/${TOTAL}] Dockerfile not found for ${SERVICE}: ${DOCKERFILE_PATH}. Skipping."
        COUNT=$((COUNT + 1))
        continue
    fi

    echo -e "\n[${COUNT}/${TOTAL}] Building image: ${IMAGE_REGISTRY}/${SERVICE}:${IMAGE_TAG}..."
    echo "------------------------------------------------------------------------------"

    BUILD_ARGS=()
    if [[ "${CONTAINER_ENGINE}" == *"podman"* ]]; then
        BUILD_ARGS+=(--format docker)
    fi

    if "${CONTAINER_ENGINE}" build "${BUILD_ARGS[@]}" \
        -f "${DOCKERFILE_PATH}" \
        "${PROJECT_ROOT}" \
        -t "${IMAGE_REGISTRY}/${SERVICE}:${IMAGE_TAG}" \
        -t "${SERVICE}:${IMAGE_TAG}"; then
        echo "✅ [${COUNT}/${TOTAL}] Successfully built: ${SERVICE}"
    else
        echo "❌ [${COUNT}/${TOTAL}] Failed to build: ${SERVICE}"
        exit 1
    fi
    COUNT=$((COUNT + 1))
done

echo -e "\n=============================================================================="
echo " 🎉 All ${TOTAL} images built successfully!"
echo "=============================================================================="
