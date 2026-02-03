# syntax=docker/dockerfile:1
FROM rockylinux:9-minimal AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_HTTP_TIMEOUT=600

RUN microdnf install -y shadow-utils ca-certificates libsndfile python3.12 gcc python3.12-devel && \
    microdnf clean all

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN uv venv /opt/venv --python python3.12

COPY requirements-audio.txt .
RUN VIRTUAL_ENV=/opt/venv uv pip install --no-cache \
    --index-strategy unsafe-best-match \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements-audio.txt

COPY config ./config
COPY py-phone-caller-utils/py_phone_caller_utils ./py_phone_caller_utils
RUN VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH" \
    CALLER_CONFIG_DIR=/app/config \
    PYTHONPATH=/app \
    python3 -m py_phone_caller_utils.py_phone_caller_voices.get_fb_mms_language_model && \
    VIRTUAL_ENV=/opt/venv PATH="/opt/venv/bin:$PATH" \
    CALLER_CONFIG_DIR=/app/config \
    PYTHONPATH=/app \
    python3 -m py_phone_caller_utils.py_phone_caller_voices.get_pipper_tts_language_model

FROM rockylinux:9-minimal

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    CALLER_CONFIG_DIR=/app/config \
    NNPACK_VERBOSE=0 \
    TORCH_CPP_LOG_LEVEL=ERROR

RUN microdnf install -y shadow-utils ca-certificates libsndfile python3.12 && \
    useradd -r -s /sbin/nologin appuser && \
    microdnf clean all

COPY --from=mwader/static-ffmpeg:6.0 /ffmpeg /usr/local/bin/ffmpeg
COPY --from=mwader/static-ffmpeg:6.0 /ffprobe /usr/local/bin/ffprobe

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

COPY --from=builder /app/pre_trained_models /app/pre_trained_models

COPY config /app/config
COPY generate_audio /app/generate_audio
COPY py-phone-caller-utils/py_phone_caller_utils /app/py_phone_caller_utils

RUN mkdir -p /app/audio && \
    chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "import socket; s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.settimeout(2); s.connect(('127.0.0.1', 8082)); s.close()" || exit 1

ENTRYPOINT ["python3"]
CMD ["-m", "generate_audio.generate_audio"]
