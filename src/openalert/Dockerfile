# syntax=docker/dockerfile:1
# ==============================================================================
# OpenAlert Daemon - Production Runtime Containerfile
# Base: Debian Bookworm Slim with native libdbus, libudev, SQLite & BlueZ
# ==============================================================================

FROM docker.io/library/debian:bookworm-slim

LABEL org.opencontainers.image.title="OpenAlert Daemon" \
      org.opencontainers.image.description="Resilient Edge Alert Router (BLE Mesh, Nostr, Prometheus Webhook, UDP Peering)" \
      org.opencontainers.image.authors="Jorge <https://github.com/jcfdeb>" \
      org.opencontainers.image.source="https://github.com/jcfdeb/py-phone-caller" \
      org.opencontainers.image.licenses="BSD-3-Clause"

# Install runtime shared libraries and networking tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libdbus-1-3 \
    libudev1 \
    libsqlite3-0 \
    tzdata \
    bluez \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged non-root user and group
RUN addgroup --gid 10001 openalert && \
    adduser --uid 10001 --gid 10001 --disabled-password --gecos "" --home /var/lib/openalertd openalert

# Prepare directory tree
RUN mkdir -p /etc/openalertd /var/lib/openalertd /templates /var/log/openalertd

# Copy pre-compiled release binary
COPY target/release/openalertd /usr/local/bin/openalertd
RUN chmod +x /usr/local/bin/openalertd

# Copy default configuration and templates
COPY config/openalertd.toml /etc/openalertd/openalertd.toml
COPY templates/ /templates/

# Enforce secure permissions
RUN chown -R openalert:openalert /etc/openalertd /var/lib/openalertd /templates /var/log/openalertd && \
    chmod 750 /var/lib/openalertd /etc/openalertd

# Expose Axum HTTP REST/metrics port and UDP Peering ports
EXPOSE 8090 19876/udp 19877/udp 19878/udp

# Standard entrypoint and default configuration argument
ENTRYPOINT ["/usr/local/bin/openalertd"]
CMD ["/etc/openalertd/openalertd.toml"]
