# syntax=docker/dockerfile:1
FROM rockylinux:9-minimal AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_HTTP_TIMEOUT=300

RUN microdnf install -y shadow-utils ca-certificates libsndfile gcc gcc-c++ make && \
    microdnf clean all

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN uv python install 3.14 && \
    uv venv /opt/venv --python 3.14 --python-preference only-managed

COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --package asterisk-recaller

FROM rockylinux:9-minimal

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src:/app/src/py-phone-caller-utils \
    PICCOLO_CONF=py_phone_caller_utils.py_phone_caller_db.piccolo_conf

RUN microdnf install -y shadow-utils ca-certificates libsndfile && \
    useradd -r -s /sbin/nologin appuser && \
    microdnf clean all

WORKDIR /app

COPY --from=builder /opt/uv-python /opt/uv-python
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/src/asterisk_recaller /app/src/asterisk_recaller
COPY --from=builder /app/src/py-phone-caller-utils /app/src/py-phone-caller-utils

RUN chown -R appuser:appuser /app

USER appuser

ENTRYPOINT ["/opt/venv/bin/python"]
CMD ["-m", "asterisk_recaller.asterisk_recaller"]
