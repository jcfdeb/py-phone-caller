#!/bin/bash

# Script to build all py-phone-caller microservice images correctly.
# It can be run from any directory and uses the repository root as build context
# so every Dockerfile can access pyproject.toml and uv.lock.

export SUPPRESS_BOLTDB_WARNING="true"

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-localhost}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"

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

for SERVICE in "${SERVICES[@]}"; do
    echo "--------------------------------------------------------"
    echo "Building image for: ${SERVICE}"
    echo "--------------------------------------------------------"
    
    if "${CONTAINER_ENGINE}" build --format docker \
        -f "${PROJECT_ROOT}/src/${SERVICE}/Dockerfile" \
        "${PROJECT_ROOT}" \
        -t "${IMAGE_REGISTRY}/${SERVICE}:${IMAGE_TAG}" \
        -t "${SERVICE}:${IMAGE_TAG}"; then
        echo "Successfully built ${SERVICE}"
    else
        echo "Failed to build ${SERVICE}"
        exit 1
    fi
done

echo "--------------------------------------------------------"
echo "All images built successfully!"
echo "--------------------------------------------------------"
