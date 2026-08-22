#!/usr/bin/env bash

# Build all py-phone-caller container images
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

CONTAINER_ENGINE="${CONTAINER_ENGINE:-podman}"
CONTAINER_REGISTRY="${CONTAINER_REGISTRY:-quay.io/py-phone-caller}"
VERSION="${VERSION:-1.0.0}"

SERVICES=(
    "asterisk_caller"
    "asterisk_recaller"
    "asterisk_ws_monitor"
    "caller_address_book"
    "caller_prometheus_webhook"
    "caller_register"
    "caller_scheduler"
    "caller_sms"
    "generate_audio"
    "py_phone_caller_ui"
    "celery_worker"
)

for SERVICE in "${SERVICES[@]}"; do
    echo "--------------------------------------------------------"
    echo "Building container image for: ${SERVICE}:${VERSION}"
    echo "--------------------------------------------------------"
    "${CONTAINER_ENGINE}" build --format docker \
        -f "${PROJECT_ROOT}/src/${SERVICE}/Dockerfile" \
        "${PROJECT_ROOT}" \
        -t "${CONTAINER_REGISTRY}/${SERVICE}:${VERSION}" \
        -t "${CONTAINER_REGISTRY}/${SERVICE}:latest" \
        -t "${SERVICE}:${VERSION}"
done

echo "--------------------------------------------------------"
echo "All py-phone-caller container images built successfully!"
echo "--------------------------------------------------------"
