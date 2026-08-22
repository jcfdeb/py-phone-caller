import pytest
from unittest.mock import patch, AsyncMock
from aiohttp import web
from src.asterisk_ws_monitor.asterisk_ws_monitor import (
    get_asterisk_chan,
    audio_play_status_log,
    take_control_of_dialplan,
    querying_call_register,
    generate_the_audio_file,
    play_audio_to_channel,
)


@pytest.mark.asyncio
async def test_get_asterisk_chan_standard():
    resp_json = {"type": "StasisStart", "channel": {"id": "1786970067.10"}}
    chan_id = await get_asterisk_chan(resp_json)
    assert chan_id == "1786970067.10"


@pytest.mark.asyncio
async def test_get_asterisk_chan_playback():
    resp_json = {
        "type": "PlaybackStarted",
        "playback": {"target_uri": "channel:1786970067.10"},
    }
    chan_id = await get_asterisk_chan(resp_json)
    assert chan_id == "1786970067.10"


@pytest.mark.asyncio
async def test_audio_play_status_log():
    await audio_play_status_log(
        {"msg_chk_sum": "abc12345"}, "1786970067.10", "Audio played"
    )


@pytest.mark.asyncio
async def test_take_control_of_dialplan():
    event_type = "StasisStart"
    response_json = {
        "type": "StasisStart",
        "channel": {"id": "1786970067.10", "state": "Up"},
    }
    with patch(
        "src.asterisk_ws_monitor.asterisk_ws_monitor.querying_call_register",
        new_callable=AsyncMock,
        return_value={"message": "Alerta", "msg_chk_sum": "1e971032"},
    ) as mock_query, patch(
        "src.asterisk_ws_monitor.asterisk_ws_monitor.generate_the_audio_file",
        new_callable=AsyncMock,
        return_value={"status": 200},
    ) as mock_gen, patch(
        "src.asterisk_ws_monitor.asterisk_ws_monitor.audio_operations",
        new_callable=AsyncMock,
    ) as mock_ops:
        await take_control_of_dialplan(event_type, response_json, "1786970067.10")
        mock_query.assert_called_once_with("1786970067.10")
        mock_gen.assert_called_once()
        mock_ops.assert_called_once()


@pytest.mark.asyncio
async def test_querying_call_register_destination_integration(aiohttp_client):
    app = web.Application()
    with patch(
        "src.caller_register.caller_register.get_msg_chk_sum",
        new_callable=AsyncMock,
    ) as mock_get:
        mock_get.return_value = ("Alert payload", "chksum123")
        from src.caller_register.caller_register import voice_message

        app.router.add_route("POST", "/voice_message", voice_message)
        client = await aiohttp_client(app)

        with patch(
            "src.asterisk_ws_monitor.asterisk_ws_monitor.CALL_REGISTER_URL",
            str(client.make_url("")).rstrip("/"),
        ), patch(
            "src.asterisk_ws_monitor.asterisk_ws_monitor.CALL_REGISTER_APP_ROUTE_VOICE_MESSAGE",
            "voice_message",
        ):
            result = await querying_call_register("1786970067.10")
            assert result == {"message": "Alert payload", "msg_chk_sum": "chksum123"}
            mock_get.assert_called_once_with("1786970067.10")


@pytest.mark.asyncio
async def test_generate_the_audio_file_destination_integration(aiohttp_client):
    app = web.Application()
    from src.generate_audio.generate_audio import create_audio, is_audio_ready

    with patch(
        "src.generate_audio.generate_audio.wave_file_exists",
        return_value=True,
    ):
        app.router.add_route("POST", "/make_audio", create_audio)
        app.router.add_route("GET", "/is_audio_ready", is_audio_ready)
        client = await aiohttp_client(app)

        with patch(
            "src.asterisk_ws_monitor.asterisk_ws_monitor.GENERATE_AUDIO_URL",
            str(client.make_url("")).rstrip("/"),
        ), patch(
            "src.asterisk_ws_monitor.asterisk_ws_monitor.GENERATE_AUDIO_APP_ROUTE",
            "make_audio",
        ), patch(
            "src.asterisk_ws_monitor.asterisk_ws_monitor.IS_AUDIO_READY_ENDPOINT",
            "is_audio_ready",
        ):
            result = await generate_the_audio_file(
                {"message": "Test Audio", "msg_chk_sum": "aabbccdd"}
            )
            assert result["status"] == 200
            assert result["cached"] is True


@pytest.mark.asyncio
async def test_play_audio_to_channel_destination_integration(aiohttp_client):
    app = web.Application()
    from src.asterisk_caller.asterisk_caller import asterisk_play

    mock_ari_session = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status = 201
    mock_ari_session.post.return_value = mock_resp

    with patch(
        "src.asterisk_caller.asterisk_caller.send_ari_continue",
        new_callable=AsyncMock,
    ) as mock_cont, patch(
        "src.asterisk_caller.asterisk_caller.ClientSession"
    ) as mock_session_cls:
        mock_session_cls.return_value.__aenter__.return_value = mock_ari_session

        app.router.add_route("POST", "/play", asterisk_play)
        client = await aiohttp_client(app)

        with patch(
            "src.asterisk_ws_monitor.asterisk_ws_monitor.ASTERISK_CALL_URL",
            str(client.make_url("")).rstrip("/"),
        ), patch(
            "src.asterisk_ws_monitor.asterisk_ws_monitor.ASTERISK_CALL_APP_ROUTE_PLAY",
            "play",
        ):
            await play_audio_to_channel("1786970067.10", {"msg_chk_sum": "aabbccdd"})
            mock_cont.assert_called_once()
            mock_ari_session.post.assert_called_once()
