# syntax=docker/dockerfile:1
FROM docker.io/mwader/static-ffmpeg:6.0 AS ffmpeg

FROM rockylinux:9-minimal AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    UV_HTTP_TIMEOUT=600

RUN microdnf install -y shadow-utils ca-certificates libsndfile gcc gcc-c++ make && \
    microdnf clean all

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

RUN uv python install 3.14 && \
    uv venv /opt/venv --python 3.14 --python-preference only-managed

COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --package generate-audio

RUN DYNACONF_LOGS__LOG_FORMATTER="%(asctime)s %(message)s" \
    DYNACONF_LOGS__LOG_LEVEL=INFO \
    DYNACONF_GENERATE_AUDIO__FACEBOOK_MMS_LANGUAGE_CODE=spa \
    DYNACONF_GENERATE_AUDIO__FACEBOOK_MMS_MODELS_FOLDER=facebook \
    DYNACONF_GENERATE_AUDIO__PIPER_VOICES_URL=https://huggingface.co/rhasspy/piper-voices/tree/main \
    DYNACONF_GENERATE_AUDIO__PRE_TRAINED_MODELS_FOLDER=pre_trained_models \
    DYNACONF_GENERATE_AUDIO__PIPER_MODELS_FOLDER=piper_tts \
    DYNACONF_GENERATE_AUDIO__PIPER_LANGUAGE_CODE=it_IT \
    DYNACONF_GENERATE_AUDIO__KOKORO_MODELS_FOLDER=kokoro_tts \
    DYNACONF_GENERATE_AUDIO__KOKORO_REPO_ID=hexgrad/Kokoro-82M \
    DYNACONF_GENERATE_AUDIO__KOKORO_MODEL_FILENAME=kokoro-v1_0.pth \
    PYTHONPATH=/app/src:/app/src/py-phone-caller-utils \
    /opt/venv/bin/python -m py_phone_caller_utils.py_phone_caller_voices.get_fb_mms_language_model && \
    DYNACONF_LOGS__LOG_FORMATTER="%(asctime)s %(message)s" \
    DYNACONF_LOGS__LOG_LEVEL=INFO \
    DYNACONF_GENERATE_AUDIO__FACEBOOK_MMS_LANGUAGE_CODE=spa \
    DYNACONF_GENERATE_AUDIO__FACEBOOK_MMS_MODELS_FOLDER=facebook \
    DYNACONF_GENERATE_AUDIO__PIPER_VOICES_URL=https://huggingface.co/rhasspy/piper-voices/tree/main \
    DYNACONF_GENERATE_AUDIO__PRE_TRAINED_MODELS_FOLDER=pre_trained_models \
    DYNACONF_GENERATE_AUDIO__PIPER_MODELS_FOLDER=piper_tts \
    DYNACONF_GENERATE_AUDIO__PIPER_LANGUAGE_CODE=it_IT \
    DYNACONF_GENERATE_AUDIO__KOKORO_MODELS_FOLDER=kokoro_tts \
    DYNACONF_GENERATE_AUDIO__KOKORO_REPO_ID=hexgrad/Kokoro-82M \
    DYNACONF_GENERATE_AUDIO__KOKORO_MODEL_FILENAME=kokoro-v1_0.pth \
    PYTHONPATH=/app/src:/app/src/py-phone-caller-utils \
    /opt/venv/bin/python -m py_phone_caller_utils.py_phone_caller_voices.get_pipper_tts_language_model && \
    DYNACONF_LOGS__LOG_FORMATTER="%(asctime)s %(message)s" \
    DYNACONF_LOGS__LOG_LEVEL=INFO \
    DYNACONF_GENERATE_AUDIO__PRE_TRAINED_MODELS_FOLDER=pre_trained_models \
    DYNACONF_GENERATE_AUDIO__KOKORO_MODELS_FOLDER=kokoro_tts \
    DYNACONF_GENERATE_AUDIO__KOKORO_REPO_ID=hexgrad/Kokoro-82M \
    DYNACONF_GENERATE_AUDIO__KOKORO_MODEL_FILENAME=kokoro-v1_0.pth \
    PYTHONPATH=/app/src:/app/src/py-phone-caller-utils \
    /opt/venv/bin/python -m py_phone_caller_utils.py_phone_caller_voices.get_kokoro_tts_model

FROM rockylinux:9-minimal

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src:/app/src/py-phone-caller-utils \
    NNPACK_VERBOSE=0 \
    TORCH_CPP_LOG_LEVEL=ERROR

RUN microdnf install -y shadow-utils ca-certificates libsndfile && \
    useradd -r -s /sbin/nologin appuser && \
    microdnf clean all

COPY --from=ffmpeg /ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg /ffprobe /usr/local/bin/ffprobe

WORKDIR /app

COPY --from=builder /opt/uv-python /opt/uv-python
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/pre_trained_models /app/pre_trained_models
COPY --from=builder /app/src/generate_audio /app/src/generate_audio
COPY --from=builder /app/src/py-phone-caller-utils /app/src/py-phone-caller-utils

RUN mkdir -p /app/audio && \
    chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD /opt/venv/bin/python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/health', timeout=3)" || exit 1

ENTRYPOINT ["/opt/venv/bin/python"]
CMD ["-m", "generate_audio.generate_audio"]
