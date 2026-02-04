# Generate Audio

HTTP service that converts text messages into audio files using multiple TTS
engines, and reports when audio files are ready for playback.

## Responsibilities
- Generate `.wav` audio for call messages.
- Support multiple TTS engines (gTTS, Facebook MMS, Piper, AWS Polly, Kokoro).
- Serve audio readiness checks for callers.

## HTTP API
Routes are configured in `settings.toml` under `[generate_audio]`:
- POST `/<generate_audio_app_route>`
- GET `/<is_audio_ready_endpoint>`

## Configuration
- Uses `py_phone_caller_utils.config` to load `settings.toml`.
- Key settings include `config_tts_engine` and model directories.
- Point it with `CALLER_CONFIG_DIR=src/config` or `CALLER_CONFIG=/path/to/settings.toml`.

## Run locally
```bash
export CALLER_CONFIG_DIR=src/config
PYTHONPATH="src:$PYTHONPATH"
python3 -m generate_audio.generate_audio
```

## Docker
```bash
docker build -t generate-audio -f src/generate_audio/Dockerfile src/
```
