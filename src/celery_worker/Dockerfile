# syntax=docker/dockerfile:1
FROM rockylinux:9-minimal AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_HTTP_TIMEOUT=300

RUN microdnf install -y shadow-utils ca-certificates libsndfile python3.12 gcc python3.12-devel && \
    microdnf clean all

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN uv venv /opt/venv --python python3.12

COPY requirements.txt .
RUN VIRTUAL_ENV=/opt/venv uv pip install --no-cache -r requirements.txt

FROM rockylinux:9-minimal

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    CALLER_CONFIG_DIR=/app/config

RUN microdnf install -y shadow-utils ca-certificates libsndfile python3.12 && \
    useradd -r -s /sbin/nologin appuser && \
    microdnf clean all

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

COPY config /app/config
COPY py-phone-caller-utils/py_phone_caller_utils /app/py_phone_caller_utils

RUN chown -R appuser:appuser /app

USER appuser

ENTRYPOINT ["celery"]
CMD ["-A", "py_phone_caller_utils.tasks.celery_task", "worker", "--loglevel=info"]
