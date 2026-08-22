#!/usr/bin/env bash

# Start py-phone-caller containers using Podman
set -e

CONTAINER_VERSION="${CONTAINER_VERSION:-1.0.0}"
CONTAINER_REGISTRY="${CONTAINER_REGISTRY:-quay.io/py-phone-caller}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-py_phone_caller_password}"
CONFIG_DIR="${CONFIG_DIR:-/opt/py-phone-caller/config}"
NETWORK_NAME="${NETWORK_NAME:-py-phone-caller}"

# Create network if it doesn't exist
podman network exists "${NETWORK_NAME}" || podman network create "${NETWORK_NAME}" --subnet 172.19.0.0/24

# Create persistent volumes
podman volume exists pgdata || podman volume create pgdata
podman volume exists audio_data || podman volume create audio_data

# Common environment for database access
DB_ENV=(
  -e DYNACONF_DATABASE__DB_HOST=172.19.0.50
  -e DYNACONF_DATABASE__DB_USER=py_phone_caller
  -e DYNACONF_DATABASE__DB_PASSWORD="${POSTGRES_PASSWORD}"
  -e DYNACONF_DATABASE__DB_NAME=py_phone_caller
  -e PICCOLO_CONF=py_phone_caller_utils.py_phone_caller_db.piccolo_conf
)

# 1. PostgreSQL 17
podman run -d --name=postgres_17 --network="${NETWORK_NAME}" \
  --ip=172.19.0.50 \
  --restart=always \
  -e POSTGRES_USER=py_phone_caller \
  -e POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
  -e POSTGRES_DB=py_phone_caller \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pgdata:/var/lib/postgresql/data:Z \
  docker.io/library/postgres:17-alpine

# 2. Redis 7
podman run -d --name=redis --network="${NETWORK_NAME}" \
  --ip=172.19.0.51 \
  --restart=always \
  docker.io/library/redis:7-alpine

# 3. caller_register (Database Initializer & Registry)
podman run -d --name=caller_register --network="${NETWORK_NAME}" \
  --ip=172.19.0.83 \
  --restart=always \
  -p 8083:8083 \
  "${DB_ENV[@]}" \
  "${CONTAINER_REGISTRY}/caller_register:${CONTAINER_VERSION}"

# 4. caller_address_book
podman run -d --name=caller_address_book --network="${NETWORK_NAME}" \
  --ip=172.19.0.87 \
  --restart=always \
  -p 8087:8087 \
  "${DB_ENV[@]}" \
  "${CONTAINER_REGISTRY}/caller_address_book:${CONTAINER_VERSION}"

# 5. generate_audio
podman run -d --name=generate_audio --network="${NETWORK_NAME}" \
  --ip=172.19.0.82 \
  --restart=always \
  -p 8082:8082 \
  -v audio_data:/app/audio:Z \
  "${CONTAINER_REGISTRY}/generate_audio:${CONTAINER_VERSION}"

# 6. asterisk_caller
podman run -d --name=asterisk_caller --network="${NETWORK_NAME}" \
  --ip=172.19.0.81 \
  --restart=always \
  -p 8081:8081 \
  -e DYNACONF_CALL_REGISTER__CALL_REGISTER_HOST=172.19.0.83 \
  -e DYNACONF_GENERATE_AUDIO__GENERATE_AUDIO_HOST=172.19.0.82 \
  -e DYNACONF_CALLER_ADDRESS_BOOK__CALLER_ADDRESS_BOOK_HOST=172.19.0.87 \
  "${CONTAINER_REGISTRY}/asterisk_caller:${CONTAINER_VERSION}"

# 7. asterisk_ws_monitor
podman run -d --name=asterisk_ws_monitor --network="${NETWORK_NAME}" \
  --ip=172.19.0.10 \
  --restart=always \
  "${DB_ENV[@]}" \
  -e DYNACONF_ASTERISK_CALL__ASTERISK_CALL_HOST=172.19.0.81 \
  -e DYNACONF_GENERATE_AUDIO__GENERATE_AUDIO_HOST=172.19.0.82 \
  -e DYNACONF_CALL_REGISTER__CALL_REGISTER_HOST=172.19.0.83 \
  "${CONTAINER_REGISTRY}/asterisk_ws_monitor:${CONTAINER_VERSION}"

# 8. asterisk_recaller
podman run -d --name=asterisk_recaller --network="${NETWORK_NAME}" \
  --ip=172.19.0.11 \
  --restart=always \
  "${DB_ENV[@]}" \
  -e DYNACONF_ASTERISK_CALL__ASTERISK_CALL_HOST=172.19.0.81 \
  "${CONTAINER_REGISTRY}/asterisk_recaller:${CONTAINER_VERSION}"

# 9. caller_sms
podman run -d --name=caller_sms --network="${NETWORK_NAME}" \
  --ip=172.19.0.85 \
  --restart=always \
  -p 8085:8085 \
  "${DB_ENV[@]}" \
  "${CONTAINER_REGISTRY}/caller_sms:${CONTAINER_VERSION}"

# 10. caller_prometheus_webhook
podman run -d --name=caller_prometheus_webhook --network="${NETWORK_NAME}" \
  --ip=172.19.0.84 \
  --restart=always \
  -p 8084:8084 \
  -e DYNACONF_ASTERISK_CALL__ASTERISK_CALL_HOST=172.19.0.81 \
  -e DYNACONF_CALLER_SMS__CALLER_SMS_HOST=172.19.0.85 \
  "${CONTAINER_REGISTRY}/caller_prometheus_webhook:${CONTAINER_VERSION}"

# 11. caller_scheduler
podman run -d --name=caller_scheduler --network="${NETWORK_NAME}" \
  --ip=172.19.0.86 \
  --restart=always \
  -p 8086:8086 \
  -e DYNACONF_QUEUE__QUEUE_HOST=172.19.0.51 \
  -e DYNACONF_QUEUE__QUEUE_URL=redis://172.19.0.51:6379 \
  "${CONTAINER_REGISTRY}/caller_scheduler:${CONTAINER_VERSION}"

# 12. py_phone_caller_ui
podman run -d --name=py_phone_caller_ui --network="${NETWORK_NAME}" \
  --ip=172.19.0.5 \
  --restart=always \
  -p 5000:5000 \
  "${DB_ENV[@]}" \
  -e DYNACONF_SCHEDULED_CALLS__SCHEDULED_CALLS_HOST=172.19.0.86 \
  -e DYNACONF_CALL_REGISTER__CALL_REGISTER_HOST=172.19.0.83 \
  -e DYNACONF_CALLER_ADDRESS_BOOK__CALLER_ADDRESS_BOOK_HOST=172.19.0.87 \
  "${CONTAINER_REGISTRY}/py_phone_caller_ui:${CONTAINER_VERSION}"

# 13. celery_worker
podman run -d --name=celery_worker --network="${NETWORK_NAME}" \
  --ip=172.19.0.52 \
  --restart=always \
  "${DB_ENV[@]}" \
  -e DYNACONF_QUEUE__QUEUE_HOST=172.19.0.51 \
  -e DYNACONF_QUEUE__QUEUE_URL=redis://172.19.0.51:6379 \
  -e DYNACONF_CALL_REGISTER__CALL_REGISTER_HOST=172.19.0.83 \
  -e DYNACONF_ASTERISK_CALL__ASTERISK_CALL_HOST=172.19.0.81 \
  -e DYNACONF_SCHEDULED_CALLS__SCHEDULED_CALLS_HOST=172.19.0.86 \
  "${CONTAINER_REGISTRY}/celery_worker:${CONTAINER_VERSION}"

echo "All py-phone-caller containers started successfully via Podman."
