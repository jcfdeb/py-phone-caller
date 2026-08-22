import os
import pytest
from unittest.mock import patch, MagicMock

from src.generate_audio.generate_audio import (
    init_app,
    generate_tts_audio,
    TTSEngine,
    wave_file_exists,
)
from src.generate_audio.constants import (
    GENERATE_AUDIO_APP_ROUTE,
    IS_AUDIO_READY_ENDPOINT,
)
from py_phone_caller_utils.py_phone_caller_voices.facebook_mms import (
    resolve_mms_model_path,
    convert_numbers_in_string,
    text_to_speech_facebook_mms,
)
from py_phone_caller_utils.py_phone_caller_voices.kokoro_tts import (
    resolve_kokoro_model_dir,
)
from py_phone_caller_utils.py_phone_caller_voices.get_kokoro_tts_model import (
    download_kokoro_model_async,
    DEFAULT_VOICES,
)


@pytest.fixture
async def cli(aiohttp_client):
    app = await init_app()
    return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_make_audio_missing_params(cli):
    resp = await cli.post(f"/{GENERATE_AUDIO_APP_ROUTE}")
    assert resp.status == 400


@pytest.mark.asyncio
async def test_make_audio_cached(cli):
    with patch(
        "src.generate_audio.generate_audio.wave_file_exists",
        return_value=True,
    ):
        resp = await cli.post(
            f"/{GENERATE_AUDIO_APP_ROUTE}?message=Test&msg_chk_sum=chk123"
        )
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": 200, "cached": True}


@pytest.mark.asyncio
async def test_make_audio_generate_success(cli):
    with patch(
        "src.generate_audio.generate_audio.wave_file_exists",
        return_value=False,
    ), patch("src.generate_audio.generate_audio.generate_tts_audio") as mock_gen:
        resp = await cli.post(
            f"/{GENERATE_AUDIO_APP_ROUTE}?message=Hello&msg_chk_sum=chk456"
        )
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": 200, "cached": False}
        mock_gen.assert_called_once()


@pytest.mark.asyncio
async def test_make_audio_generate_failure(cli):
    with patch(
        "src.generate_audio.generate_audio.wave_file_exists",
        return_value=False,
    ), patch(
        "src.generate_audio.generate_audio.generate_tts_audio",
        side_effect=RuntimeError("TTS engine crash"),
    ):
        resp = await cli.post(
            f"/{GENERATE_AUDIO_APP_ROUTE}?message=Hello&msg_chk_sum=chk789"
        )
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": 500, "cached": False}


def test_tts_engine_from_string():
    assert TTSEngine.from_string("facebook_mms") == TTSEngine.FACEBOOK_MMS
    assert TTSEngine.from_string("kokoro_tts") == TTSEngine.KOKORO
    assert TTSEngine.from_string("piper_tts") == TTSEngine.PIPER
    assert TTSEngine.from_string("google_gtts") == TTSEngine.GOOGLE_GTTS
    assert TTSEngine.from_string("aws_polly") == TTSEngine.AWS_POLLY

    with pytest.raises(ValueError, match="Invalid TTS engine"):
        TTSEngine.from_string("invalid_engine_name")


@pytest.mark.asyncio
async def test_is_audio_ready_missing_params(cli):
    resp = await cli.get(f"/{IS_AUDIO_READY_ENDPOINT}")
    assert resp.status == 400


@pytest.mark.asyncio
async def test_is_audio_ready_not_found(cli):
    resp = await cli.get(f"/{IS_AUDIO_READY_ENDPOINT}?msg_chk_sum=notfound")
    assert resp.status == 200
    data = await resp.json()
    assert data["exists"] is False


def test_mms_model_path_resolution(tmp_path):
    # 1. Non-existent path falls back to canonical HF repo id
    resolved = resolve_mms_model_path("fra", model_path="/nonexistent/path")
    assert resolved == "facebook/mms-tts-fra"

    # 2. Existing directory is returned directly
    model_dir = tmp_path / "mms-tts-spa"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}")
    resolved_existing = resolve_mms_model_path("spa", model_path=str(model_dir))
    assert resolved_existing == str(model_dir)


def test_convert_numbers_in_string():
    # Spanish
    res_es = convert_numbers_in_string("Hay 2 servidores caídos", lang="es")
    assert "dos" in res_es
    assert "2" not in res_es

    # Italian
    res_it = convert_numbers_in_string("Ci sono 3 allarmi", lang="it")
    assert "tre" in res_it
    assert "3" not in res_it

    # Unknown language code fallback doesn't crash
    res_raw = convert_numbers_in_string("Test 123", lang="unknown_lang")
    assert "Test" in res_raw


def test_facebook_mms_error_propagation(tmp_path):
    out = str(tmp_path / "test.wav")
    with patch(
        "py_phone_caller_utils.py_phone_caller_voices.facebook_mms.create_audio_through_facebook_mms",
        side_effect=RuntimeError("Synthesis error"),
    ):
        with pytest.raises(RuntimeError, match="MMS audio generation failed"):
            text_to_speech_facebook_mms("Test error", "spa", out)


def test_facebook_mms_audio_generation(tmp_path):
    local_mms = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "generate_audio",
        "pre_trained_models",
        "facebook",
        "mms-tts-spa",
    )
    if not os.path.exists(os.path.join(local_mms, "config.json")):
        pytest.skip("Facebook MMS Spanish model not present locally")

    out_wav = str(tmp_path / "mms_test.wav")
    generate_tts_audio("Prueba de audio", out_wav, engine=TTSEngine.FACEBOOK_MMS)

    assert os.path.exists(out_wav)
    assert os.path.getsize(out_wav) > 0
    assert wave_file_exists(out_wav) is True


@pytest.mark.asyncio
async def test_download_kokoro_model_async_local_dir(tmp_path):
    downloaded_calls = []

    def mock_hf_download(repo_id, filename, local_dir):
        downloaded_calls.append((repo_id, filename, local_dir))
        target = os.path.join(local_dir, filename)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as f:
            f.write("mock_content")
        return target

    dest = tmp_path / "kokoro_test_dir"
    with patch(
        "py_phone_caller_utils.py_phone_caller_voices.get_kokoro_tts_model.hf_hub_download",
        side_effect=mock_hf_download,
    ):
        result_dir = await download_kokoro_model_async(
            base_dir=str(dest), voice_names=["ef_dora"]
        )

        assert str(dest) in result_dir
        assert any(c[1] == "config.json" for c in downloaded_calls)
        assert any(c[1] == "kokoro-v1_0.pth" for c in downloaded_calls)
        assert any(c[1] == "voices/ef_dora.pt" for c in downloaded_calls)
        for _, _, local_dir in downloaded_calls:
            assert local_dir == result_dir


def test_kokoro_model_dir_resolution(tmp_path):
    # 1. Existing custom directory with config.json is resolved directly
    kdir = tmp_path / "custom_kokoro_tts"
    kdir.mkdir()
    (kdir / "config.json").write_text("{}")
    assert resolve_kokoro_model_dir(str(kdir)) == str(kdir)

    # 2. Candidate resolution finds the local workspace directory if present
    resolved = resolve_kokoro_model_dir()
    if resolved is not None:
        assert os.path.exists(resolved)
        assert os.path.exists(os.path.join(resolved, "config.json"))


def test_kokoro_tts_audio_generation(tmp_path):
    local_kokoro = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "generate_audio",
        "pre_trained_models",
        "kokoro_tts",
    )
    if not os.path.exists(os.path.join(local_kokoro, "config.json")):
        pytest.skip("Kokoro model not present locally")

    out_wav = str(tmp_path / "kokoro_test.wav")
    generate_tts_audio("Prueba de audio Kokoro", out_wav, engine=TTSEngine.KOKORO)

    assert os.path.exists(out_wav)
    assert os.path.getsize(out_wav) > 0
    assert wave_file_exists(out_wav) is True
