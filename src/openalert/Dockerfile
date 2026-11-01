# syntax=docker/dockerfile:1
# ==============================================================================
# OpenAlert Daemon (openalertd) - Multi-Stage Production Dockerfile
#
# Supports flexible build context:
#   - From src/openalert:  docker build -t openalertd:1.0.0 .
#   - From repo root:      docker build -f src/openalert/Dockerfile --build-arg OPENALERT_DIR=src/openalert -t openalertd:1.0.0 .
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Multi-Stage Rust Builder (Debian Bookworm Slim)
# ------------------------------------------------------------------------------
FROM docker.io/library/rust:1-slim-bookworm AS builder

ARG OPENALERT_DIR=.

# Install minimal native C headers required for BlueZ D-Bus (bluer), libudev (tokio-serial), and bundled SQLite
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config \
    libdbus-1-dev \
    libudev-dev \
    build-essential \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/openalertd

# 1. Dependency caching layer: compile external crates once before copying application source
COPY ${OPENALERT_DIR}/Cargo.toml ${OPENALERT_DIR}/Cargo.lock ./
RUN mkdir -p src && \
    echo "pub fn placeholder() {}" > src/lib.rs && \
    echo "fn main() {}" > src/main.rs && \
    cargo build --release --locked && \
    rm -rf src

# 2. Copy actual OpenAlert Rust sources, templates, and default configuration
COPY ${OPENALERT_DIR}/src ./src
COPY ${OPENALERT_DIR}/templates ./templates
COPY ${OPENALERT_DIR}/config ./config

# 3. Compile final release binary and strip debug symbols for optimal image size
RUN touch src/lib.rs src/main.rs && \
    cargo build --release --locked && \
    strip /usr/src/openalertd/target/release/openalertd

# ------------------------------------------------------------------------------
# Stage 2: Minimal Hardened Production Runtime (Debian Bookworm Slim)
# ------------------------------------------------------------------------------
FROM docker.io/library/debian:bookworm-slim AS runtime

LABEL org.opencontainers.image.title="OpenAlert Daemon (openalertd)" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.description="Decentralized Edge Alert Router (Nostr NIP-ALERT, NIP-57 Lightning Zaps, 0xChat NIP-17 C2, BitChat BLE, LoRa RF, GSM SMS & Telephony Bridge)" \
      org.opencontainers.image.authors="Jorge <https://github.com/jcfdeb>" \
      org.opencontainers.image.source="https://github.com/jcfdeb/py-phone-caller" \
      org.opencontainers.image.licenses="BSD-3-Clause"

# Install only shared runtime libraries (rusqlite is statically bundled inside openalertd)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    libdbus-1-3 \
    libudev1 \
    tzdata \
    bluez \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged service user and group (UID/GID 10001) and grant dialout/bluetooth group membership for optional hardware passthrough
RUN addgroup --gid 10001 openalert && \
    adduser --uid 10001 --gid 10001 --disabled-password --gecos "" --home /var/lib/openalertd openalert && \
    usermod -aG dialout,bluetooth openalert 2>/dev/null || true

# Prepare runtime filesystem hierarchy (with /var/lib/openalertd/data for default SQLite path)
RUN mkdir -p /etc/openalertd /var/lib/openalertd/data /var/lib/openalertd/templates /templates /var/log/openalertd

# Copy stripped release binary and runtime assets from builder stage
COPY --from=builder /usr/src/openalertd/target/release/openalertd /usr/local/bin/openalertd
COPY --from=builder /usr/src/openalertd/config/openalertd.toml /etc/openalertd/openalertd.toml
COPY --from=builder /usr/src/openalertd/config/profiles /etc/openalertd/profiles
COPY --from=builder /usr/src/openalertd/templates/ /templates/
COPY --from=builder /usr/src/openalertd/templates/ /var/lib/openalertd/templates/

# Enforce strict ownership and permissions
RUN chmod 0755 /usr/local/bin/openalertd && \
    chown -R openalert:openalert /etc/openalertd /var/lib/openalertd /templates /var/log/openalertd && \
    chmod 0750 /var/lib/openalertd /etc/openalertd

# Expose:
#   8090/tcp        - NOC Mission Control Dashboard (/), Emergency SOS Portal (/sos), REST API & Prometheus /metrics
#   8088/tcp        - Embedded Nostr Micro-Relay (ws:// and wss://)
#   19876-19878/udp - Encrypted XChaCha20-Poly1305 UDP Peering & Multi-Hop Mesh
EXPOSE 8090 8088 19876/udp 19877/udp 19878/udp

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8090/health || exit 1

USER openalert:openalert
WORKDIR /var/lib/openalertd

ENTRYPOINT ["/usr/local/bin/openalertd"]
CMD ["/etc/openalertd/openalertd.toml"]
