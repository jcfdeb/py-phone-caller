import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
from aiohttp import web, client_exceptions

from src.asterisk_ws_monitor import (
    AsteriskPlaybackClient,
    AsteriskWsMonitorError,
    AudioGenerationResult,
    AudioReadyStatus,
    AudioServiceClient,
    CallRegisterClient,
    EventBroadcaster,
    StasisEvent,
    VoiceMessageInfo,
    WsMonitorService,
)
from src.asterisk_ws_monitor.asterisk_ws_monitor import (
    audio_operations,
    audio_play_status_log,
    broadcast_stasis_event,
    generate_the_audio_file,
    get_asterisk_chan,
    play_audio_to_channel,
    querying_call_register,
    receive_signal,
    take_control_of_dialplan,
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


def test_stasis_event_schema_and_actionable():
    event = StasisEvent.from_dict({
        "type": "StasisStart",
        "channel": {"id": "chan-42", "state": "Up"},
        "timestamp": "2026-10-06T10:00:00Z",
    })
    assert event.event_type == "StasisStart"
    assert event.channel_id == "chan-42"
    assert event.channel_state == "Up"
    assert event.is_actionable("StasisStart", "Up") is True
    assert event.is_actionable("StasisEnd", "Up") is False

    playback_event = StasisEvent.from_dict({
        "type": "PlaybackFinished",
        "playback": {"target_uri": "channel:chan-99"},
    })
    assert playback_event.channel_id == "chan-99"
    assert playback_event.is_actionable() is False


def test_voice_message_info_schema():
    info = VoiceMessageInfo.from_dict({
        "message": "Critical Alert",
        "msg_chk_sum": "hash123",
        "lang": "es",
        "speed": "1.2",
    })
    assert info.message == "Critical Alert"
    assert info.msg_chk_sum == "hash123"
    assert info.lang == "es"
    assert info.speed == 1.2


def test_receive_signal():
    with pytest.raises(SystemExit) as exc2:
        receive_signal(2, None)
    assert exc2.value.code == 0

    with pytest.raises(SystemExit) as exc15:
        receive_signal(15, None)
    assert exc15.value.code == 0


@pytest.mark.asyncio
async def test_call_register_client_connection_error():
    client = CallRegisterClient(base_url="http://127.0.0.1:59998", timeout_total=0.5)
    with pytest.raises(web.HTTPBadRequest):
        await client.query_voice_message("chan-1")


@pytest.mark.asyncio
async def test_audio_service_client_connection_error():
    client = AudioServiceClient(base_url="http://127.0.0.1:59998", timeout_total=0.5)
    with pytest.raises(web.HTTPBadRequest):
        await client.generate_and_wait({"message": "test", "msg_chk_sum": "abc"})


@pytest.mark.asyncio
async def test_ws_monitor_service_take_control_non_matching_event():
    mock_reg = AsyncMock()
    mock_audio = AsyncMock()
    mock_play = AsyncMock()
    mock_broadcast = AsyncMock()
    mock_insert = AsyncMock()

    service = WsMonitorService(
        call_register_client=mock_reg,
        audio_service_client=mock_audio,
        playback_client=mock_play,
        broadcaster=mock_broadcast,
        insert_ws_event_fn=mock_insert,
    )

    # Event not StasisStart -> should return immediately without calling clients
    await service.take_control_of_dialplan(
        event_type="ChannelDestroyed",
        response_json={"channel": {"state": "Up"}},
        asterisk_chan="chan-1",
    )
    mock_reg.query_voice_message.assert_not_called()
    mock_audio.generate_and_wait.assert_not_called()
    mock_play.play_audio_to_channel.assert_not_called()
