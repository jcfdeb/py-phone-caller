import hashlib
import hmac
import importlib
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from py_phone_caller_ui.app import app

db_user = importlib.import_module(
    "py_phone_caller_utils.py_phone_caller_db.db_user"
)


def _patch_db_user_attr(monkeypatch, attr_name, value):
    monkeypatch.setattr(db_user, attr_name, value)


def _legacy_sha512_hash(password, salt="legacy-salt"):
    hashval = hmac.new(salt.encode(), password.encode(), hashlib.sha512).hexdigest()
    return f"sha512${salt}${hashval}"


@pytest.mark.asyncio
async def test_missing_admin_is_not_recreated_when_users_exist(
    monkeypatch,
):
    mock_insert_user = AsyncMock()
    mock_generate_password = MagicMock()
    mock_select_user = AsyncMock()
    mock_is_users_table_empty = AsyncMock()
    _patch_db_user_attr(monkeypatch, "insert_user", mock_insert_user)
    _patch_db_user_attr(
        monkeypatch, "generate_complex_password", mock_generate_password
    )
    _patch_db_user_attr(monkeypatch, "select_user", mock_select_user)
    _patch_db_user_attr(
        monkeypatch, "is_users_table_empty_async", mock_is_users_table_empty
    )
    mock_select_user.return_value = None
    mock_is_users_table_empty.return_value = False

    password = await db_user.ensure_admin_user_exists("admin@test.com")

    assert password is None
    mock_generate_password.assert_not_called()
    mock_insert_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_initial_admin_is_created_when_users_table_is_empty(
    monkeypatch,
):
    mock_insert_user = AsyncMock()
    mock_generate_password = MagicMock()
    mock_select_user = AsyncMock()
    mock_is_users_table_empty = AsyncMock()
    _patch_db_user_attr(monkeypatch, "insert_user", mock_insert_user)
    _patch_db_user_attr(
        monkeypatch, "generate_complex_password", mock_generate_password
    )
    _patch_db_user_attr(monkeypatch, "select_user", mock_select_user)
    _patch_db_user_attr(
        monkeypatch, "is_users_table_empty_async", mock_is_users_table_empty
    )
    monkeypatch.setenv("UI_USER_RESET_PASSWORD", "true")
    mock_select_user.return_value = None
    mock_is_users_table_empty.return_value = True
    mock_generate_password.return_value = "generated-password"

    password = await db_user.ensure_admin_user_exists("admin@test.com")

    assert password == "generated-password"
    mock_insert_user.assert_awaited_once_with(
        "Admin", "admin@test.com", "generated-password"
    )


@pytest.mark.asyncio
async def test_initial_admin_is_not_created_without_password_setup_flag(
    monkeypatch,
):
    mock_insert_user = AsyncMock()
    mock_generate_password = MagicMock()
    mock_select_user = AsyncMock()
    mock_is_users_table_empty = AsyncMock()
    _patch_db_user_attr(monkeypatch, "insert_user", mock_insert_user)
    _patch_db_user_attr(
        monkeypatch, "generate_complex_password", mock_generate_password
    )
    _patch_db_user_attr(monkeypatch, "select_user", mock_select_user)
    _patch_db_user_attr(
        monkeypatch, "is_users_table_empty_async", mock_is_users_table_empty
    )
    monkeypatch.delenv("UI_USER_RESET_PASSWORD", raising=False)
    mock_select_user.return_value = None
    mock_is_users_table_empty.return_value = True

    password = await db_user.ensure_admin_user_exists("admin@test.com")

    assert password is None
    mock_generate_password.assert_not_called()
    mock_insert_user.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_password_reset_is_skipped_when_admin_is_missing(
    monkeypatch,
):
    mock_update_password = AsyncMock()
    mock_generate_password = MagicMock()
    mock_select_user = AsyncMock()
    _patch_db_user_attr(monkeypatch, "update_password", mock_update_password)
    _patch_db_user_attr(
        monkeypatch, "generate_complex_password", mock_generate_password
    )
    _patch_db_user_attr(monkeypatch, "select_user", mock_select_user)
    monkeypatch.setenv("UI_USER_RESET_PASSWORD", "true")
    mock_select_user.return_value = None

    password = await db_user.reset_admin_password_if_needed("admin@test.com")

    assert password is None
    mock_generate_password.assert_not_called()
    mock_update_password.assert_not_awaited()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_login_page_loads(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"py-phone-caller" in response.data
    assert b"Sign In" in response.data


@patch("py_phone_caller_ui.login.select_user", new_callable=AsyncMock)
def test_login_failure_user_not_found(mock_select_user, client):
    mock_select_user.return_value = None
    response = client.post(
        "/login",
        data={"email": "wrong@test.com", "password": "password"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Invalid username or password" in response.data
    assert b"alert-danger" in response.data


@patch("py_phone_caller_ui.login.select_user", new_callable=AsyncMock)
def test_login_failure_wrong_password(mock_select_user, client):
    mock_select_user.return_value = {
        "email": "admin@test.com",
        "password": "hashed_password",
        "is_active": True,
    }
    with patch("py_phone_caller_ui.login.check_user_password") as mock_check:
        mock_check.return_value = False
        response = client.post(
            "/login",
            data={"email": "admin@test.com", "password": "wrong"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"Invalid username or password" in response.data


@patch("py_phone_caller_ui.login.update_password", new_callable=AsyncMock)
@patch("py_phone_caller_ui.login.select_user", new_callable=AsyncMock)
def test_login_with_legacy_sha512_hash_upgrades_password(
    mock_select_user, mock_update_password, client
):
    password = "correct-password"
    mock_select_user.return_value = {
        "email": "admin@test.com",
        "password": _legacy_sha512_hash(password),
        "is_active": True,
    }
    update_query = MagicMock()
    update_query.where = AsyncMock()
    users_stub = MagicMock()
    users_stub.update.return_value = update_query

    with (
        patch("py_phone_caller_ui.login.login_user") as mock_login_user,
        patch("py_phone_caller_ui.login.Users", users_stub),
    ):
        response = client.post(
            "/login",
            data={"email": "admin@test.com", "password": password},
        )

    assert response.status_code == 302
    mock_update_password.assert_awaited_once_with("admin@test.com", password)
    mock_login_user.assert_called_once()


@patch("py_phone_caller_ui.login.select_user", new_callable=AsyncMock)
def test_login_failure_disabled_account(mock_select_user, client):
    mock_select_user.return_value = {
        "email": "admin@test.com",
        "password": "hashed_password",
        "is_active": False,
    }
    response = client.post(
        "/login",
        data={"email": "admin@test.com", "password": "password"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Account is disabled" in response.data


@patch("py_phone_caller_ui.address_book._select_contacts", new_callable=AsyncMock)
def test_address_book_page_loads(mock_select, client):
    mock_select.return_value = []
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        response = client.get("/address_book")
        assert response.status_code == 200
        assert b"Address Book" in response.data


def test_sms_page_unauthenticated_redirects(client):
    response = client.get("/sms")
    assert response.status_code == 200
    assert b"unauthorized" in response.data.lower() or b"sign in" in response.data.lower()


@patch("py_phone_caller_ui.sms.select_sms", new_callable=AsyncMock)
def test_sms_page_loads_for_authenticated_user(mock_select_sms, client):
    mock_select_sms.return_value = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "phone": "+393349246425",
            "message": "Test SMS message content",
            "carrier": "on_premise",
            "status": "sent",
            "created_at": None,
            "error": "",
        }
    ]
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        response = client.get("/sms")
        assert response.status_code == 200
        assert b"Managed SMS" in response.data
        assert b"+393349246425" in response.data
        assert b"Test SMS message content" in response.data
        assert b"on_premise" in response.data
        assert b"Sent" in response.data


@patch("py_phone_caller_ui.sms.select_sms", new_callable=AsyncMock)
def test_sms_page_search_filtering(mock_select_sms, client):
    mock_select_sms.return_value = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "phone": "+393349246425",
            "message": "Alert critical server down",
            "carrier": "on_premise",
            "status": "sent",
            "created_at": None,
            "error": "",
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "phone": "+393331234567",
            "message": "Daily routine reminder",
            "carrier": "twilio",
            "status": "queued",
            "created_at": None,
            "error": "",
        },
    ]
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        response = client.get("/sms?search=critical")
        assert response.status_code == 200
        assert b"Alert critical server down" in response.data
        assert b"Daily routine reminder" not in response.data


@patch("py_phone_caller_ui.sms.select_sms", new_callable=AsyncMock)
def test_sms_export_csv(mock_select_sms, client):
    import datetime
    mock_select_sms.return_value = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "phone": "+393349246425",
            "message": "Exportable message",
            "carrier": "on_premise",
            "status": "sent",
            "created_at": datetime.datetime(2026, 8, 15, 12, 0, 0),
            "error": "",
        }
    ]
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        # Missing parameter
        res_missing = client.get("/sms/export_csv")
        assert res_missing.status_code == 400

        # Invalid month
        res_invalid = client.get("/sms/export_csv?export_month=invalid")
        assert res_invalid.status_code == 400

        # Valid month
        res_valid = client.get("/sms/export_csv?export_month=2026-08")
        assert res_valid.status_code == 200
        assert res_valid.headers["Content-Disposition"] == "attachment;filename=sms_2026-08.csv"
        assert b"ID,Phone,Message,Carrier,Status,Created At,Error" in res_valid.data
        assert b"Exportable message" in res_valid.data
