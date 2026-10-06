"""
Unit and integration tests for asterisk_recaller.

Tests cover:
- recall_post HTTP client requests and error handling
- run_single_recall_cycle primary recall processing and delay pacing
- run_single_recall_cycle backup call handling with round-robin on-call contacts
- run_single_recall_cycle backup call handling when no on-call contacts exist
- Signal handling and loop resilience
- Schemas and domain dataclasses
- Modular AsteriskCallClient behavior under timeouts and errors
- RecallerService dependency injection and cycle execution
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from aiohttp import web, client_exceptions

from src.asterisk_recaller import (
    AsteriskCallClient,
    AsteriskRecallerError,
    BackupCallItem,
    NoOnCallContactsError,
    OnCallContact,
    RecallCycleResult,
    RecallItem,
    RecallerConnectionError,
    RecallerService,
    asterisk_recaller,
)
from src.asterisk_recaller.asterisk_recaller import (
    recall_post,
    run_single_recall_cycle,
    receive_signal,
)


@pytest.mark.asyncio
async def test_recall_post_success(aiohttp_client):
    app = web.Application()
    received_params = {}

    async def mock_place_call(request):
        received_params.update(request.rel_url.query)
        return web.json_response({"status": 200})

    app.router.add_route("POST", "/place_call", mock_place_call)
    client = await aiohttp_client(app)

    with patch(
        "src.asterisk_recaller.asterisk_recaller.ASTERISK_CALL_URL",
        str(client.make_url("")).rstrip("/"),
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.ASTERISK_CALL_APP_ROUTE_PLACE_CALL",
        "place_call",
    ):
        await recall_post(
            phone="0039123456789",
            message="Alert message",
            backup_callee="false",
        )

        assert received_params.get("phone") == "0039123456789"
        assert received_params.get("message") == "Alert message"
        assert received_params.get("backup_callee") == "false"


@pytest.mark.asyncio
async def test_recall_post_connector_error(caplog):
    # Connect to invalid port, should log exception and NOT raise
    with patch(
        "src.asterisk_recaller.asterisk_recaller.ASTERISK_CALL_URL",
        "http://127.0.0.1:59999",
    ):
        await recall_post("0039123456789", "Test alert")
        assert "Unable to connect to the Asterisk Call service" in caplog.text


@pytest.mark.asyncio
async def test_run_single_recall_cycle_empty():
    with patch(
        "src.asterisk_recaller.asterisk_recaller.select_to_recall",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.select_backup_calls",
        new_callable=AsyncMock,
        return_value=[],
    ):
        actions = await run_single_recall_cycle()
        assert actions == 0


@pytest.mark.asyncio
async def test_run_single_recall_cycle_primary_recalls():
    items = [\
        {"phone": "0039111", "message": "Alert 1", "seconds_to_forget": 60},
        {"phone": "0039222", "message": "Alert 2", "seconds_to_forget": 60},
    ]

    with patch(
        "src.asterisk_recaller.asterisk_recaller.select_to_recall",
        new_callable=AsyncMock,
        return_value=items,
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.select_backup_calls",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.recall_post",
        new_callable=AsyncMock,
    ) as mock_recall, patch(
        "asyncio.sleep",
        new_callable=AsyncMock,
    ):
        actions = await run_single_recall_cycle()
        assert actions == 2
        assert mock_recall.call_count == 2
        mock_recall.assert_any_call("0039111", "Alert 1")
        mock_recall.assert_any_call("0039222", "Alert 2")


@pytest.mark.asyncio
async def test_run_single_recall_cycle_backup_calls():
    backup_items = [
        {
            "id": "call-1",
            "phone": "0039999",
            "message": "Unack alert",
            "call_backup_callee_number_calls": 0,
        },
        {
            "id": "call-2",
            "phone": "0039888",
            "message": "Unack alert 2",
            "call_backup_callee_number_calls": 1,
        },
    ]
    contacts = [
        {"phone_number": "0039-oncall-0"},
        {"phone_number": "0039-oncall-1"},
    ]

    with patch(
        "src.asterisk_recaller.asterisk_recaller.select_to_recall",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.select_backup_calls",
        new_callable=AsyncMock,
        return_value=backup_items,
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.get_on_call_contacts",
        new_callable=AsyncMock,
        return_value=contacts,
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.recall_post",
        new_callable=AsyncMock,
    ) as mock_recall, patch(
        "src.asterisk_recaller.asterisk_recaller.increment_backup_call_count",
        new_callable=AsyncMock,
    ) as mock_incr, patch(
        "asyncio.sleep",
        new_callable=AsyncMock,
    ):
        actions = await run_single_recall_cycle()
        assert actions == 2
        assert mock_recall.call_count == 2
        # (0 + 1) % 2 = 1 -> contact 1
        mock_recall.assert_any_call("0039-oncall-1", "Unack alert", backup_callee="true")
        # (1 + 1) % 2 = 0 -> contact 0
        mock_recall.assert_any_call("0039-oncall-0", "Unack alert 2", backup_callee="true")

        assert mock_incr.call_count == 2
        mock_incr.assert_any_call("call-1")
        mock_incr.assert_any_call("call-2")


@pytest.mark.asyncio
async def test_run_single_recall_cycle_backup_calls_no_contacts(caplog):
    backup_items = [
        {
            "id": "call-1",
            "phone": "0039999",
            "message": "Unack alert",
            "call_backup_callee_number_calls": 0,
        }
    ]

    with patch(
        "src.asterisk_recaller.asterisk_recaller.select_to_recall",
        new_callable=AsyncMock,
        return_value=[],
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.select_backup_calls",
        new_callable=AsyncMock,
        return_value=backup_items,
    ), patch(
        "src.asterisk_recaller.asterisk_recaller.get_on_call_contacts",
        new_callable=AsyncMock,
        return_value=[],
    ):
        actions = await run_single_recall_cycle()
        assert actions == 0
        assert "No on-call contacts found for backup calls" in caplog.text


def test_receive_signal():
    with pytest.raises(SystemExit) as exc:
        receive_signal(2, None)
    assert exc.value.code == 0

    with pytest.raises(SystemExit) as exc:
        receive_signal(15, None)
    assert exc.value.code == 0


def test_schemas_dataclasses():
    item = RecallItem.from_dict({
        "phone": "+12345",
        "message": "Hello",
        "seconds_to_forget": 120,
    })
    assert item.phone == "+12345"
    assert item.message == "Hello"
    assert item.seconds_to_forget == 120

    backup = BackupCallItem.from_dict({
        "id": "abc-123",
        "phone": "+98765",
        "message": "Escalation",
        "call_backup_callee_number_calls": 2,
    })
    assert backup.call_id == "abc-123"
    assert backup.backup_count == 2

    contact = OnCallContact.from_dict({"phone_number": "+112233"})
    assert contact.phone_number == "+112233"

    result = RecallCycleResult(primary_actions=3, backup_actions=2)
    assert result.total_actions == 5


@pytest.mark.asyncio
async def test_client_place_call_error_handling(caplog):
    client = AsteriskCallClient(base_url="http://invalid.domain.local.9999", timeout_total=0.5)
    success = await client.place_call("+12345", "Test")
    assert success is False
    assert "Unable to connect to the Asterisk Call service" in caplog.text


@pytest.mark.asyncio
async def test_recaller_service_custom_injection():
    mock_dial = AsyncMock()
    mock_select_recall = AsyncMock(return_value=[{"phone": "123", "message": "msg", "seconds_to_forget": 10}])
    mock_select_backup = AsyncMock(return_value=[{"id": 1, "phone": "456", "message": "msg2", "call_backup_callee_number_calls": 0}])
    mock_contacts = AsyncMock(return_value=[{"phone_number": "789"}])
    mock_incr = AsyncMock()

    service = RecallerService(
        call_client_fn=mock_dial,
        select_to_recall_fn=mock_select_recall,
        select_backup_calls_fn=mock_select_backup,
        get_on_call_contacts_fn=mock_contacts,
        increment_backup_call_count_fn=mock_incr,
        sleep_and_retry=0.0,
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        actions = await service.run_single_cycle()
        assert actions == 2
        assert mock_dial.call_count == 2
        assert mock_incr.call_count == 1
