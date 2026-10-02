import pytest
from unittest.mock import patch, AsyncMock
from src.caller_address_book.caller_address_book import init_app, ContactCSVRow
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


def test_contact_csv_row_pydantic_validation():
    # Valid row
    valid = ContactCSVRow(
        name="Alice Admin",
        phone_number="+393349246425",
        enabled=True,
    )
    assert valid.name == "Alice Admin"
    assert valid.phone_number == "+393349246425"
    assert valid.enabled is True

    # Empty name should fail
    with pytest.raises(Exception) as exc_info:
        ContactCSVRow(name="   ", phone_number="+393349246425")
    assert "name" in str(exc_info.value)

    # Invalid phone format should fail
    with pytest.raises(Exception) as exc_info:
        ContactCSVRow(name="Bob", phone_number="abc-not-a-number")
    assert "phone number" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_post_contacts_import_csv_pydantic_validation(cli):
    csv_content = """name,surname,phone_number,enabled
Valid Contact,Test,+14155552671,true
,No Name,+14155552672,true
Bad Phone,Tester,invalid_phone,true
"""
    with patch("src.caller_address_book.caller_address_book.AddressBook.select") as mock_sel, \
         patch("src.caller_address_book.caller_address_book.add_contact", new_callable=AsyncMock) as mock_add:
        mock_sel.return_value = AsyncMock(return_value=[])()
        mock_add.return_value = "new-uuid"

        resp = await cli.post("/contacts_import_csv", data=csv_content, headers={"Content-Type": "text/csv"})
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == 200
        assert data["processed_rows"] == 3
        assert data["created"] == 1
        assert data["errors_count"] == 2
        # Verify errors contain human-readable schema validation errors with row numbers
        error_rows = [e["row"] for e in data["errors"]]
        assert 3 in error_rows  # Row 3 (index 3: empty name)
        assert 4 in error_rows  # Row 4 (index 4: invalid phone)
