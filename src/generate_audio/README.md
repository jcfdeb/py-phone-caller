# Generate Audio Service

The `generate_audio` service is an asynchronous HTTP microservice built on `aiohttp` that converts text messages into Asterisk-compliant 16-bit mono 8 kHz WAV audio files using multiple Text-to-Speech (TTS) engines. It supports dynamic multi-engine language discovery, cross-engine fallback routing, configurable speech rates, and on-disk model preloading.

---

## Key Features

- **6 Supported TTS Engines**:
  - **Kokoro-82M** (`kokoro_tts`): Default local high-fidelity neural synthesizer.
  - **Silero TTS** (`silero_tts`): Fast, lightweight offline PyTorch neural voice synthesis.
  - **Piper ONNX** (`piper_tts`): Ultra-fast offline neural TTS via ONNX Runtime.
  - **Facebook MMS** (`facebook_mms`): Offline multilingual VITS checkpoints supporting hundreds of languages.
  - **AWS Polly** (`aws_polly`): Cloud-managed voice synthesis.
  - **Google gTTS** (`google_gtts`): Cloud fallback.
- **Dynamic Model Discovery & Capabilities Endpoint (`GET /languages`)**:
  - Automatically scans on-disk pre-trained model directories.
  - Exposes installed models, voices, and supported language codes with native names and flag emojis for frontend dropdowns.
- **Intelligent Engine & Language Routing**:
  - Dispatches calls dynamically using the Strategy Pattern (`TTS_DISPATCH_STRATEGIES`).
  - Resolves language aliases (e.g. `spa` / `es`, `eng` / `en`) and Kokoro voice prefixes (e.g. `ef_dora` -> Spanish).
  - Falls back to installed offline models across engines if the primary engine does not have the requested language model installed.
- **Language-Scoped Caching & Audio Utilities**:
  - Audio files are cached by checksum and language code (`{msg_chk_sum}_{lang}.wav` or `{msg_chk_sum}.wav`).
  - Validates WAV RIFF headers and non-zero file sizes asynchronously to prevent corrupt playback.
- **Automatic Model Preloading**:
  - Ensures required voice weights and configs are present in `pre_trained_models/` at startup, initiating automated downloads when configured.

---

## Modular Architecture

`generate_audio` is decomposed into cohesive, single-responsibility submodules:

```text
src/generate_audio/
├── __init__.py          # Package exports and public API
├── constants.py         # Configuration constants, directories, and defaults
├── enums.py             # TTSEngine enum and engine configuration resolution
├── languages.py         # Language mappings, flags, aliases, Kokoro voice prefixes
├── runners.py           # Subprocess runners for offline CLI engines (Piper, Kokoro, Silero)
├── discovery.py         # On-disk model directory scanners and language catalog builders
├── strategies.py        # Strategy dispatch dictionary and TTS synthesis coordinator
├── preloading.py        # Model verification and automatic downloader on startup
└── generate_audio.py    # aiohttp HTTP application coordinator, routes, and CLI entrypoint
```

### Module Responsibilities

| Submodule | Responsibility |
| :--- | :--- |
| [`enums.py`](enums.py) | Defines `TTSEngine` enum, loads active engine from settings, and sets default engine language fallbacks. |
| [`languages.py`](languages.py) | Defines `LANGUAGE_NAMES`, `LANGUAGE_FLAGS`, `LANGUAGE_ALIASES`, and `_kokoro_voice_to_lang`. |
| [`runners.py`](runners.py) | Implements offline TTS subprocess wrappers: `text_to_speech_piper_tts`, `text_to_speech_kokoro_tts`, `text_to_speech_silero_tts`. |
| [`discovery.py`](discovery.py) | Implements `scan_installed_languages()` and `resolve_engine_for_language()`. |
| [`strategies.py`](strategies.py) | Contains per-engine strategy handlers and `generate_tts_audio()` dispatch coordinator. |
| [`preloading.py`](preloading.py) | Handles background model downloads on service startup via `ensure_models_present()`. |
| [`generate_audio.py`](generate_audio.py) | HTTP request handlers (`create_audio`, `is_audio_ready`, `get_languages`), static audio server, service catalog, and OpenAPI routes. |

---

## HTTP API Endpoints

### 1. Generate Audio
`POST /make_audio`

Asynchronously triggers audio generation from text or returns immediate cached status if the file already exists.

- **Query / Body Parameters**:
  - `message` (*string, required*): Alert text to synthesize.
  - `msg_chk_sum` (*string, required*): Unique checksum identifier for the audio file.
  - `lang` (*string, optional*): Requested language code (e.g. `es`, `en`, `it`, `fr`, `de`, `zh`, `hi`, `ar`, `he`).
  - `speed` (*float, optional, default: 1.0*): Speech rate multiplier (e.g. `0.85` to `1.2`).
  - `engine` (*string, optional*): Explicitly override the TTS engine (e.g. `kokoro_tts`, `silero_tts`, `piper_tts`, `facebook_mms`).
- **Response**: `200 OK`
  ```json
  {
    "status": 200,
    "cached": false
  }
  ```

### 2. Audio Readiness Check
`GET /is_audio_ready`

Verifies whether an audio file has finished generation and is valid for playback by Asterisk.

- **Query Parameters**:
  - `msg_chk_sum` (*string, required*): Checksum of the audio file.
  - `lang` (*string, optional*): Language code used during generation.
- **Response**: `200 OK`
  ```json
  {
    "exists": true
  }
  ```

### 3. Language & Model Inventory
`GET /languages`

Returns the current active engine, its available language options, and installed weights across all offline engines.

- **Response**: `200 OK`
  ```json
  {
    "active_engine": "kokoro_tts",
    "default_language": "e",
    "languages": [
      {
        "code": "e",
        "voice": "ef_dora",
        "name": "Spanish",
        "engine": "kokoro_tts",
        "ready": true,
        "is_default": true,
        "flag": "🇪🇸"
      },
      {
        "code": "en",
        "voice": "af_heart",
        "name": "English",
        "engine": "kokoro_tts",
        "ready": true,
        "is_default": false,
        "flag": "🇬🇧"
      }
    ],
    "installed_models": {
      "kokoro_tts": {
        "model": "kokoro-v1_0.pth",
        "ready": true,
        "voices": ["af_heart", "bf_emma", "ef_dora", "ff_siwis"]
      },
      "silero_tts": [
        {"code": "en", "name": "English", "model": "v3_en.pt", "ready": true}
      ]
    }
  }
  ```

### 4. Audio Playback Serving
`GET /audio/{filename}.wav`

Static file endpoint serving generated 8 kHz mono WAV files for Asterisk Stasis channels.

---

## Configuration

Configured under the `[generate_audio]` table in `settings.toml`:

```toml
[generate_audio]
tts_engine = "kokoro_tts"             # Options: kokoro_tts, silero_tts, piper_tts, facebook_mms, aws_polly, google_gtts
generate_audio_host = "127.0.0.1"
generate_audio_port = 8082
generate_audio_app_route = "make_audio"
is_audio_ready_endpoint = "is_audio_ready"
languages_endpoint = "languages"
serving_audio_folder = "audio"
pre_trained_models_folder = "pre_trained_models"

# Engine-specific defaults
kokoro_lang = "e"                     # 'e' (Spanish), 'a' (US English), 'b' (UK English), etc.
silero_lang = "en"
silero_speaker = "en_0"
piper_language_code = "en_US"
facebook_mms_language_code = "spa"

# Optional startup preloading
[generate_audio.preload]
piper_tts = ["en_US", "it_IT"]
silero_tts = ["en", "es"]
```

---

## Running Locally

```bash
export CALLER_CONFIG_DIR=src/config
uv run python -m generate_audio.generate_audio
```
