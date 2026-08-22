# syntax=docker/dockerfile:1
FROM rockylinux:9-minimal AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_HTTP_TIMEOUT=300

RUN microdnf install -y shadow-utils ca-certificates libsndfile gcc gcc-c++ make curl && \
    microdnf clean all

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN uv python install 3.14 && \
    uv venv /opt/venv --python 3.14 --python-preference only-managed

COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --package caller-sms

WORKDIR /app/src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine
ENV PYO3_PYTHON=/opt/venv/bin/python \
    PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
RUN cargo build --release
RUN cp target/release/librust_engine.so /app/src/py-phone-caller-utils/rust_engine.so && \
    cp target/release/librust_engine.so /app/src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine.so

FROM rockylinux:9-minimal

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src:/app/src/py-phone-caller-utils \
    PICCOLO_CONF=py_phone_caller_utils.py_phone_caller_db.piccolo_conf

RUN microdnf install -y shadow-utils ca-certificates libsndfile && \
    useradd -r -s /sbin/nologin -G dialout appuser && \
    microdnf clean all

WORKDIR /app

COPY --from=builder /opt/uv-python /opt/uv-python
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src/caller_sms /app/src/caller_sms
COPY --from=builder /app/src/py-phone-caller-utils /app/src/py-phone-caller-utils

RUN chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD /opt/venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8085/health', timeout=3)" || exit 1

ENTRYPOINT ["/opt/venv/bin/python"]
CMD ["-m", "caller_sms.caller_sms"]
