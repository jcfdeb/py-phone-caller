import pytest
from unittest.mock import patch
from src.caller_address_book.caller_address_book import init_app
from src.caller_address_book.constants import (
    CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT,
    CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT,
)


@pytest.fixture
async def cli(aiohttp_client):
    with patch("src.caller_address_book.caller_address_book._ensure_db_pool"):
        app = await init_app()
        return await aiohttp_client(app)


@pytest.mark.asyncio
async def test_get_on_call_contact_not_found(cli):
    with patch(
        "src.caller_address_book.caller_address_book.get_on_call_contact"
    ) as mock_get:
        mock_get.return_value = None
        resp = await cli.get(f"/{CALLER_ADDRESS_BOOK_ROUTE_ON_CALL_CONTACT}")
        assert resp.status == 404
        data = await resp.json()
        assert data["error"] == "No on-call contact found"


@pytest.mark.asyncio
async def test_add_contact_invalid_json(cli):
    resp = await cli.post(f"/{CALLER_ADDRESS_BOOK_ROUTE_ADD_CONTACT}", data="not json")
    assert resp.status == 400
    assert await resp.text() == "Invalid JSON body"
