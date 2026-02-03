#!/bin/bash

# Script to build all py-phone-caller microservice images correctly.
# This script must be run from the 'src' directory.

export SUPPRESS_BOLTDB_WARNING="true"

set -e

# Check if we are in the 'src' directory
if [[ "$(basename "$(pwd)")" != "src" ]]; then
    echo "Error: This script must be run from the 'src' directory."
    exit 1
fi

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
    
    podman build --format docker -f "${SERVICE}/Dockerfile" . -t "${SERVICE}"
    
    if [ $? -eq 0 ]; then
        echo "Successfully built ${SERVICE}"
    else
        echo "Failed to build ${SERVICE}"
        exit 1
    fi
done

echo "--------------------------------------------------------"
echo "All images built successfully!"
echo "--------------------------------------------------------"
