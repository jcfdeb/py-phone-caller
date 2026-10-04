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
from py_phone_caller_utils.py_phone_caller_voices.silero_tts import (
    resolve_silero_model_path,
    text_to_speech_silero,
)
from py_phone_caller_utils.py_phone_caller_voices.get_silero_tts_model import (
    download_silero_model_async,
    SILERO_MODELS,
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
    assert TTSEngine.from_string("silero_tts") == TTSEngine.SILERO

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


# =========================================================================
# PHASE 3 TESTS: Multi-Language Audio Scoping, Speed & Fallbacks
# =========================================================================

def test_resolve_audio_filename():
    from src.generate_audio.generate_audio import resolve_audio_filename
    # No language -> backward compatibility
    assert resolve_audio_filename("a1b2c3d4") == "a1b2c3d4.wav"
    assert resolve_audio_filename("a1b2c3d4", None) == "a1b2c3d4.wav"
    assert resolve_audio_filename("a1b2c3d4", "") == "a1b2c3d4.wav"
    # With language
    assert resolve_audio_filename("a1b2c3d4", "spa") == "a1b2c3d4_spa.wav"
    assert resolve_audio_filename("a1b2c3d4", "it_IT") == "a1b2c3d4_it_IT.wav"


@pytest.mark.asyncio
async def test_make_audio_language_scoped_and_speed(cli):
    with patch(
        "src.generate_audio.generate_audio.wave_file_exists",
        return_value=False,
    ), patch("src.generate_audio.generate_audio.generate_tts_audio") as mock_gen:
        resp = await cli.post(
            f"/{GENERATE_AUDIO_APP_ROUTE}?message=Hola&msg_chk_sum=scoped123&lang=spa&speed=0.85"
        )
        assert resp.status == 200
        data = await resp.json()
        assert data == {"status": 200, "cached": False}
        mock_gen.assert_called_once()
        args, kwargs = mock_gen.call_args
        assert "scoped123_spa.wav" in args[1]
        assert kwargs.get("language") == "spa"
        assert kwargs.get("speed") == 0.85


@pytest.mark.asyncio
async def test_is_audio_ready_language_scoped(cli):
    with patch(
        "src.generate_audio.generate_audio.wave_file_exists",
        side_effect=lambda p: "scoped123_spa.wav" in p,
    ):
        # Querying with matching lang returns true
        resp_spa = await cli.get(
            f"/{IS_AUDIO_READY_ENDPOINT}?msg_chk_sum=scoped123&lang=spa"
        )
        assert resp_spa.status == 200
        data_spa = await resp_spa.json()
        assert data_spa["exists"] is True

        # Querying with different lang returns false
        resp_eng = await cli.get(
            f"/{IS_AUDIO_READY_ENDPOINT}?msg_chk_sum=scoped123&lang=eng"
        )
        assert resp_eng.status == 200
        data_eng = await resp_eng.json()
        assert data_eng["exists"] is False


def test_missing_model_fallback_piper():
    with patch("os.path.exists") as mock_exists, patch("subprocess.run") as mock_run:
        from src.generate_audio.constants import PIPER_LANGUAGE_CODE
        def exists_side_effect(path):
            if "de_DE" in str(path):
                return False
            return True
        mock_exists.side_effect = exists_side_effect
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        from src.generate_audio.generate_audio import text_to_speech_piper_tts
        text_to_speech_piper_tts("Hallo Welt", "/tmp/out.wav", language="de_DE")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        # Should have fallen back to configured default PIPER_LANGUAGE_CODE
        expected_model = f"{PIPER_LANGUAGE_CODE}.onnx"
        assert any(expected_model in arg for arg in cmd)


def test_missing_model_fallback_kokoro():
    with patch("os.path.exists", return_value=True), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        from src.generate_audio.generate_audio import text_to_speech_kokoro_tts
        # Unknown language code 'xyz'
        text_to_speech_kokoro_tts("Testing", "/tmp/out.wav", language="xyz", speed=0.9)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--speed" in cmd
        assert "0.9" in cmd
        # Lang fell back to default KOKORO_LANG ('e')
        assert "--lang" in cmd
        idx = cmd.index("--lang")
        assert cmd[idx + 1] == "e"


# =========================================================================
# SILERO TTS TESTS
# =========================================================================

def test_silero_model_path_resolution(tmp_path):
    # 1. Existing file returned directly
    test_pt = tmp_path / "v3_en.pt"
    test_pt.write_text("model_data")
    assert resolve_silero_model_path("en", model_path=str(test_pt)) == str(test_pt)

    # 2. Existing folder with subfolder <p>/<lang>/<filename>
    sub_dir = tmp_path / "silero_dir" / "en"
    sub_dir.mkdir(parents=True)
    sub_pt = sub_dir / "v3_en.pt"
    sub_pt.write_text("sub_model_data")
    assert resolve_silero_model_path("en", model_path=str(tmp_path / "silero_dir")) == str(sub_pt)

    # 3. Direct folder with <p>/v3_en.pt
    direct_dir = tmp_path / "direct_dir"
    direct_dir.mkdir(parents=True)
    direct_pt = direct_dir / "v3_en.pt"
    direct_pt.write_text("direct_model_data")
    assert resolve_silero_model_path("en", model_path=str(direct_dir)) == str(direct_pt)


@pytest.mark.asyncio
async def test_download_silero_model_async_local_dir(tmp_path):
    dest = tmp_path / "silero_models"

    async def mock_download_file(client, url, dest_path):
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"dummy_silero_model_bytes_" + b"0" * 2000000)
        return True

    with patch(
        "py_phone_caller_utils.py_phone_caller_voices.get_silero_tts_model.download_file",
        side_effect=mock_download_file,
    ):
        result_path = await download_silero_model_async("en", base_dir=str(dest))
        assert os.path.exists(result_path)
        assert result_path.endswith("v3_en.pt")
        assert "en" in result_path


def test_silero_tts_generation_mock(tmp_path):
    import torch
    import numpy as np

    fake_model = MagicMock()
    # 1 second of 8000Hz sine wave as torch tensor
    fake_audio = torch.zeros(8000)
    fake_model.apply_tts.return_value = fake_audio

    model_file = tmp_path / "v3_en.pt"
    model_file.write_text("mock_model")

    out_wav = str(tmp_path / "silero_output.wav")

    with patch("py_phone_caller_utils.py_phone_caller_voices.silero_tts.load_silero_model", return_value=fake_model):
        text_to_speech_silero(
            message="Alert: fire alarm triggered",
            output_path=out_wav,
            lang="en",
            speaker="en_0",
            sample_rate=8000,
            model_path=str(model_file),
        )

    assert os.path.exists(out_wav)
    assert os.path.getsize(out_wav) > 0
    assert wave_file_exists(out_wav) is True
    fake_model.apply_tts.assert_called_once_with(
        text="Alert: fire alarm triggered",
        speaker="en_0",
        sample_rate=8000,
    )


def test_generate_tts_audio_silero_dispatch():
    with patch("src.generate_audio.generate_audio.text_to_speech_silero_tts") as mock_silero:
        generate_tts_audio(
            message="Server room over temperature",
            output_path="/tmp/silero_test.wav",
            engine=TTSEngine.SILERO,
            language="en",
            speed=1.0,
        )
        mock_silero.assert_called_once_with(
            "Server room over temperature",
            "/tmp/silero_test.wav",
            language="en",
            speed=1.0,
        )


def test_missing_model_fallback_silero():
    with patch("os.path.exists", return_value=True), patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        from src.generate_audio.generate_audio import text_to_speech_silero_tts
        from src.generate_audio.constants import SILERO_LANG

        # Unsupported language 'unsupported_xyz'
        text_to_speech_silero_tts("Alert", "/tmp/silero_fb.wav", language="unsupported_xyz", speed=1.0)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--lang" in cmd
        idx = cmd.index("--lang")
        assert cmd[idx + 1] == SILERO_LANG


@pytest.mark.asyncio
async def test_get_languages_endpoint(cli):
    resp = await cli.get("/languages")
    assert resp.status == 200
    data = await resp.json()
    assert "active_engine" in data
    assert "default_language" in data
    assert "languages" in data
    assert isinstance(data["languages"], list)
    assert len(data["languages"]) > 0
    assert "installed_models" in data
    default_items = [l for l in data["languages"] if l.get("is_default")]
    assert len(default_items) == 1
    assert default_items[0]["code"] == data["default_language"]


def test_scan_installed_languages_structure():
    from src.generate_audio.generate_audio import scan_installed_languages
    result = scan_installed_languages()
    assert result["active_engine"] in ["facebook_mms", "piper_tts", "kokoro_tts", "silero_tts", "google_gtts", "aws_polly"]
    assert isinstance(result["languages"], list)
    assert "installed_models" in result
    assert "facebook_mms" in result["installed_models"]
    assert "piper_tts" in result["installed_models"]
    assert "kokoro_tts" in result["installed_models"]
    assert "silero_tts" in result["installed_models"]
