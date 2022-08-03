#!/usr/bin/env bash

CONTAINER_VERSION=0.0.1

podman run -d --name=postgres_13 --network=py-phone-caller \
  --ip=172.19.0.50 \
  --restart=always \
  -e POSTGRES_PASSWORD=SWaaDvuf9zemkoCkkFhyo0HWx9zWApluiI9JS0 \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v pgdata:/var/lib/postgresql/data \
  docker.io/library/postgres:13.3-alpine3.14

podman run -d --name=asterisk_ws_monitor --network=py-phone-caller \
  --add-host postgres-service:172.19.0.50 \
  --restart=always \
  -v /opt/py-phone-caller/config/caller_config.toml:/opt/py-phone-caller/config/caller_config.toml \
  quay.io/py-phone-caller/asterisk_ws_monitor:0.0.1

podman run -d --name=asterisk_call --network=py-phone-caller \
  --restart=always \
  -p 8081:8081 \
  -v /opt/py-phone-caller/config/caller_config.toml:/opt/py-phone-caller/config/caller_config.toml \
  quay.io/py-phone-caller/asterisk_call:0.0.1

podman run -d --name=asterisk_recall --network=py-phone-caller \
  --add-host postgres-service:172.19.0.50 \
  --restart=always \
  -v /opt/py-phone-caller/config/caller_config.toml:/opt/py-phone-caller/config/caller_config.toml \
  quay.io/py-phone-caller/asterisk_recall:0.0.1

podman run -d --name=asterisk_call_register --network=py-phone-caller \
  --add-host postgres-service:172.19.0.50 \
  --restart=always \
  -p 8080:8080 \
  -v /opt/py-phone-caller/config/caller_config.toml:/opt/py-phone-caller/config/caller_config.toml \
  quay.io/py-phone-caller/call_register:0.0.1

podman run -d --name=caller_prometheus_webhook --network=py-phone-caller \
  --restart=always \
  -p 8084:8084 \
  -v /opt/py-phone-caller/config/caller_config.toml:/opt/py-phone-caller/config/caller_config.toml \
  quay.io/py-phone-caller/caller_prometheus_webhook:0.0.1

podman run -d --name=caller_sms --network=py-phone-caller \
  --restart=always \
  -p 8085:8085 \
  -v /opt/py-phone-caller/config/caller_config.toml:/opt/py-phone-caller/config/caller_config.toml \
  quay.io/py-phone-caller/caller_sms:0.0.1

podman run -d --name=generate_audio --network=py-phone-caller \
  --restart=always \
  -p 8082:8082 \
  -v /opt/py-phone-caller/config/caller_config.toml:/opt/py-phone-caller/config/caller_config.toml \
  quay.io/py-phone-callergenerate_audio:0.0.1
