#!/usr/bin/env bash

VERSION="0.0.1"

# asterisk_call
podman build -t quay.io/py-phone-caller/asterisk_call:${VERSION} -f Dockerfile.asterisk_call

# asterisk_recall
podman build -t quay.io/py-phone-caller/asterisk_recall:${VERSION} -f Dockerfile.asterisk_recall

# asterisk_ws_monitor
podman build -t quay.io/py-phone-caller/asterisk_ws_monitor:${VERSION} -f Dockerfile.asterisk_ws_monitor

# call_register
podman build -t quay.io/py-phone-caller/call_register:${VERSION} -f Dockerfile.call_register

# caller_prometheus_webhook
podman build -t quay.io/py-phone-caller/caller_prometheus_webhook:${VERSION} -f Dockerfile.caller_prometheus_webhook

# caller_sms
podman build -t quay.io/py-phone-caller/caller_sms:${VERSION} -f Dockerfile.caller_sms

# generate_audio
podman build -t quay.io/py-phone-caller/generate_audio:${VERSION} -f Dockerfile.generate_audio
