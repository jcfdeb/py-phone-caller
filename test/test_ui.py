import hashlib
import hmac
import importlib
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from py_phone_caller_ui.app import app
from py_phone_caller_ui.schemas import (
    LocaleMeta,
    TextDirection,
    ServiceEndpointSummary,
    AdminBootstrapResult,
)
from py_phone_caller_ui.services import (
    LocaleService,
    AdminBootstrapService,
    UserAuthenticationService,
)

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
        assert b'data-bs-target="#smsDetailModal"' in response.data
        assert b'openSmsDetails' in response.data
        assert b'id="smsDetailModal"' in response.data
        assert b'showToast' in response.data


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


# =========================================================================
# Phase 4 Tests: i18n Locales, Cookie Negotiation, & NOC Telemetry Dashboard
# =========================================================================

def test_set_locale_endpoint_and_cookie(client):
    for lang in ["it", "es", "de", "fr", "ru", "zh", "hi", "he", "ar", "en"]:
        response = client.get(f"/set_locale/{lang}")
        assert response.status_code == 302
        cookie_header = response.headers.get("Set-Cookie", "")
        assert f"locale={lang}" in cookie_header


@patch("py_phone_caller_ui.home.get_noc_dashboard_metrics", new_callable=AsyncMock)
def test_home_page_renders_noc_dashboard_with_translations(mock_metrics, client):
    import datetime
    from datetime import timezone
    mock_metrics.return_value = {
        "total_calls": 42,
        "ack_count": 35,
        "ack_rate": 83.3,
        "heard_count": 4,
        "escalated_count": 3,
        "in_flight_count": 0,
        "total_sms": 12,
        "sms_delivered": 11,
        "sms_failed": 1,
        "sms_rate": 91.7,
        "is_gsm": True,
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
    }

    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True
        sess["locale"] = "it"

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        response = client.get("/")
        assert response.status_code == 200
        content = response.data.decode("utf-8")
        assert "Chiamate gestite" in content
        assert "42" in content
        assert "83.3%" in content


@patch("py_phone_caller_ui.home.get_noc_dashboard_metrics", new_callable=AsyncMock)
def test_hebrew_arabic_french_rendering_and_rtl(mock_metrics, client):
    import datetime
    from datetime import timezone
    mock_metrics.return_value = {
        "total_calls": 10,
        "ack_count": 8,
        "ack_rate": 80.0,
        "heard_count": 1,
        "escalated_count": 1,
        "in_flight_count": 0,
        "total_sms": 5,
        "sms_delivered": 5,
        "sms_failed": 0,
        "sms_rate": 100.0,
        "is_gsm": True,
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
    }

    test_cases = [
        ("he", "rtl", "שיחות מנוהלות"),
        ("ar", "rtl", "المكالمات المدارة"),
        ("fr", "ltr", "Appels gérés"),
    ]

    for lang, expected_dir, expected_text in test_cases:
        with client.session_transaction() as sess:
            sess["_user_id"] = "1"
            sess["_fresh"] = True
            sess["locale"] = lang

        with patch("flask_login.utils._get_user") as mock_user:
            mock_user.return_value = MagicMock(is_authenticated=True)
            response = client.get("/")
            assert response.status_code == 200
            html = response.data.decode("utf-8")
            assert f'dir="{expected_dir}"' in html, f'Expected dir="{expected_dir}" for {lang}'
            assert expected_text in html, f'Expected "{expected_text}" in html for {lang}'


@patch("py_phone_caller_ui.home.get_noc_dashboard_metrics", new_callable=AsyncMock)
def test_api_dashboard_metrics_json(mock_metrics, client):
    import datetime
    from datetime import timezone
    mock_metrics.return_value = {
        "total_calls": 10,
        "ack_count": 8,
        "ack_rate": 80.0,
        "heard_count": 1,
        "escalated_count": 1,
        "in_flight_count": 0,
        "total_sms": 5,
        "sms_delivered": 5,
        "sms_failed": 0,
        "sms_rate": 100.0,
        "is_gsm": True,
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
    }

    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        response = client.get("/api/dashboard_metrics")
        assert response.status_code == 200
        data = response.get_json()
        assert data["total_calls"] == 10
        assert data["ack_rate"] == 80.0
        assert data["ack_count"] == 8
        assert data["sms_delivered"] == 5
        assert data["is_gsm"] is True


@pytest.mark.asyncio
async def test_get_noc_dashboard_metrics_calculation():
    import datetime
    from datetime import timezone
    from py_phone_caller_ui.home.telemetry import get_noc_dashboard_metrics

    fake_calls = [
        {
            "id": "1",
            "acknowledge_at": datetime.datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc),
            "heard_at": datetime.datetime(2026, 10, 2, 9, 59, 0, tzinfo=timezone.utc),
            "cycle_done": True,
            "backup_callee": False,
        },
        {
            "id": "2",
            "acknowledge_at": datetime.datetime.min,
            "heard_at": datetime.datetime(2026, 10, 2, 10, 1, 0, tzinfo=timezone.utc),
            "cycle_done": True,
            "backup_callee": False,
        },
        {
            "id": "3",
            "acknowledge_at": datetime.datetime.min,
            "heard_at": datetime.datetime.min,
            "cycle_done": True,
            "backup_callee": True,
        },
        {
            "id": "4",
            "acknowledge_at": datetime.datetime.min,
            "heard_at": datetime.datetime.min,
            "cycle_done": False,
            "backup_callee": False,
        },
    ]

    fake_sms = [
        {"id": "s1", "status": "sent"},
        {"id": "s2", "status": "delivered"},
        {"id": "s3", "status": "failed"},
    ]

    with patch("py_phone_caller_ui.home.telemetry.get_redis_client") as mock_redis, \
         patch("py_phone_caller_ui.home.telemetry.select_calls", new_callable=AsyncMock) as mock_sel_calls, \
         patch("py_phone_caller_ui.home.telemetry.select_sms", new_callable=AsyncMock) as mock_sel_sms:

        mock_r = MagicMock()
        mock_r.get = AsyncMock(return_value=None)
        mock_r.setex = AsyncMock()
        mock_redis.return_value = mock_r

        mock_sel_calls.return_value = fake_calls
        mock_sel_sms.return_value = fake_sms

        metrics = await get_noc_dashboard_metrics()

        assert metrics["total_calls"] == 4
        assert metrics["ack_count"] == 1
        assert metrics["heard_count"] == 1
        assert metrics["escalated_count"] == 1
        assert metrics["in_flight_count"] == 1
        assert metrics["ack_rate"] == 25.0
        assert metrics["total_sms"] == 3
        assert metrics["sms_delivered"] == 2
        assert metrics["sms_failed"] == 1
        assert metrics["sms_rate"] == 66.7


# =========================================================================
# Phase 5 Tests: Domain Models, Wallboard, SSE, Dark Mode, & Diagnostics
# =========================================================================

def test_shared_domain_models():
    from py_phone_caller_utils.models import (
        AlertSeverity, PrometheusAlertItem, PrometheusWebhookPayload,
        CallAlertRequest, ChannelState, CallEvent, DtmfAckPayload,
        CallDispatchSpec, SmsStatus, SmsPayload, SmsRecordModel,
        ContactModel, ContactCreatePayload, ContactUpdatePayload
    )
    # 1. Alert models
    item = PrometheusAlertItem(labels={"alertname": "HostHighCpu", "severity": "critical"})
    assert item.severity == AlertSeverity.CRITICAL
    assert item.alert_name == "HostHighCpu"

    webhook = PrometheusWebhookPayload(alerts=[item])
    assert len(webhook.alerts) == 1

    # 2. Call dispatch request validation
    call_req = CallAlertRequest(text="Alert test message", phone="+393349246425", speed=1.2)
    assert call_req.speed == 1.2
    assert call_req.phone == "+393349246425"

    # 3. SMS validation
    sms_p = SmsPayload(phone="+39 334-924-6425", message="Test SMS")
    assert sms_p.phone == "+393349246425"

    # 4. Contact validation
    contact = ContactCreatePayload(name="OnCall Lead", phone="+39 (334) 924 6425", group="devops")
    assert contact.phone == "+393349246425"


@patch("py_phone_caller_ui.home.get_noc_dashboard_metrics", new_callable=AsyncMock)
def test_wallboard_view(mock_metrics, client):
    import datetime
    from datetime import timezone
    mock_metrics.return_value = {
        "total_calls": 50,
        "ack_count": 45,
        "ack_rate": 90.0,
        "heard_count": 2,
        "escalated_count": 3,
        "in_flight_count": 0,
        "total_sms": 20,
        "sms_delivered": 19,
        "sms_failed": 1,
        "sms_rate": 95.0,
        "is_gsm": True,
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
    }
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        response = client.get("/wallboard")
        assert response.status_code == 200
        assert b"NOC Operations Center" in response.data
        assert b"90.0%" in response.data
        assert b'data-bs-theme="dark"' in response.data


def test_quick_diagnostics_validation(client):
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)

        # Missing phone in SMS
        res_sms = client.post("/api/diagnostics/test_sms", json={"phone": ""})
        assert res_sms.status_code == 400

        # Missing phone in Call
        res_call = client.post("/api/diagnostics/test_call", json={"phone": ""})
        assert res_call.status_code == 400


@patch("aiohttp.ClientSession.post")
def test_quick_diagnostics_dispatch_success(mock_post, client):
    # Mock successful response
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": 200})
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_resp
    mock_context.__aexit__.return_value = None
    mock_post.return_value = mock_context

    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)

        res_sms = client.post("/api/diagnostics/test_sms", json={"phone": "+393349246425", "message": "Test"})
        assert res_sms.status_code == 200
        assert res_sms.get_json()["success"] is True
        assert res_sms.get_json()["service"] == "caller_sms"

        res_call = client.post("/api/diagnostics/test_call", json={"phone": "+393349246425", "message": "Test"})
        assert res_call.status_code == 200
        assert res_call.get_json()["success"] is True
        assert res_call.get_json()["service"] == "asterisk_caller"


@patch("py_phone_caller_ui.home.get_noc_dashboard_metrics", new_callable=AsyncMock)
def test_dark_mode_and_modal_present_in_base(mock_metrics, client):
    mock_metrics.return_value = {
        "total_calls": 1,
        "ack_count": 1,
        "ack_rate": 100.0,
        "heard_count": 0,
        "escalated_count": 0,
        "in_flight_count": 0,
        "total_sms": 1,
        "sms_delivered": 1,
        "sms_failed": 0,
        "sms_rate": 100.0,
        "is_gsm": True,
        "timestamp": "2026-10-02T12:00:00Z",
    }
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        response = client.get("/")
        assert response.status_code == 200
        assert b"data-bs-theme" in response.data
        assert b"themeToggleBtn" in response.data
        assert b"quickDiagnosticsModal" in response.data
        assert b"toggleDarkMode" in response.data
        assert b"wallboard" in response.data


@patch("aiohttp.ClientSession.get")
def test_api_languages_proxy_endpoint(mock_get, client):
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={
        "status": "success",
        "active_engine": "silero_tts",
        "default_language": "en",
        "languages": [
            {"code": "en", "name": "English", "is_default": True, "flag": "🇬🇧"},
            {"code": "it", "name": "Italian", "is_default": False, "flag": "🇮🇹"},
        ]
    })
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_resp
    mock_context.__aexit__.return_value = None
    mock_get.return_value = mock_context

    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        res = client.get("/api/languages")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "success"
        assert len(data["languages"]) == 2
        assert data["languages"][1]["code"] == "it"


@patch("aiohttp.ClientSession.post")
def test_test_call_dispatch_with_language(mock_post, client):
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"status": 200})
    mock_context = AsyncMock()
    mock_context.__aenter__.return_value = mock_resp
    mock_context.__aexit__.return_value = None
    mock_post.return_value = mock_context

    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        res = client.post("/api/diagnostics/test_call", json={
            "phone": "+393349246425",
            "message": "Ciao mondo",
            "language": "it"
        })
        assert res.status_code == 200
        assert res.get_json()["success"] is True
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs.get("json", {}).get("lang") == "it"
        assert call_kwargs.get("json", {}).get("language") == "it"


@patch("py_phone_caller_ui.schedule_call.enqueue_the_call")
def test_schedule_picker_with_language(mock_enqueue, client):
    mock_enqueue.return_value = {"status": "enqueued"}
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        res = client.get("/schedule_picker", query_string={
            "phone": "+393349246425",
            "message": "Scheduled alert",
            "scheduled_date": "2026-10-05",
            "scheduled_time": "14:30",
            "lang": "it"
        })
        assert res.status_code == 200
        assert res.status_code == 200
        mock_enqueue.assert_called_once()
        args, kwargs = mock_enqueue.call_args
        assert args[0] == "+393349246425"
        assert args[1] == "Scheduled alert"
        assert kwargs.get("lang") == "it"


@patch("py_phone_caller_ui.calls.requests.get")
def test_proxy_acknowledge_success(mock_get, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": 200, "message": "Acknowledged"}
    mock_get.return_value = mock_resp

    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        res = client.get("/calls/proxy_acknowledge?asterisk_chan=PJSIP/101-0001")
        assert res.status_code == 200
        assert res.get_json()["status"] == 200
        assert res.get_json()["message"] == "Acknowledged"


def test_proxy_acknowledge_missing_param(client):
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        res = client.get("/calls/proxy_acknowledge")
        assert res.status_code == 400
        assert "Missing asterisk_chan" in res.get_json()["message"]


@patch("py_phone_caller_ui.calls.requests.get")
def test_api_bulk_acknowledge(mock_get, client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": 200}
    mock_get.return_value = mock_resp

    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    with patch("flask_login.utils._get_user") as mock_user:
        mock_user.return_value = MagicMock(is_authenticated=True)
        res = client.post("/calls/api/bulk_acknowledge", json={
            "channels": ["PJSIP/101-0001", "PJSIP/102-0002"]
        })
        assert res.status_code == 200
        data = res.get_json()
        assert data["total"] == 2
        assert data["acknowledged"] == 2


def test_locale_service_resolution_and_negotiation():
    svc = LocaleService()
    assert svc.resolve_locale("it-IT") == "it"
    assert svc.resolve_locale("es_ES") == "es"
    assert svc.resolve_locale("zh-CN") == "zh"
    assert svc.resolve_locale("unknown-lang") is None

    # Priority 1: session
    assert svc.negotiate_locale(session_locale="fr", cookie_locale="de") == "fr"
    # Priority 2: cookie
    assert svc.negotiate_locale(session_locale=None, cookie_locale="de") == "de"
    # Priority 3: header matcher
    assert svc.negotiate_locale(session_locale=None, cookie_locale=None, header_matcher=lambda candidates: "ru") == "ru"
    # Fallback: default 'en'
    assert svc.negotiate_locale(session_locale=None, cookie_locale=None, header_matcher=lambda candidates: None) == "en"


def test_schemas_dataclasses():
    meta = LocaleMeta(code="it", name="Italiano", flag="🇮🇹", direction=TextDirection.LTR)
    assert meta.to_dict() == {"name": "Italiano", "flag": "🇮🇹", "dir": "ltr"}

    boot = AdminBootstrapResult(admin_user="admin", already_initialized=True)
    assert boot.already_initialized is True
    assert boot.created is False


def test_user_authentication_service():
    mock_loader = MagicMock(return_value={"id": "1", "email": "test@example.com"})
    auth_svc = UserAuthenticationService(loader_fn=mock_loader)
    user = auth_svc.load_user("1")
    assert user is not None
    assert user.username == "test@example.com"

    mock_loader.return_value = None
    assert auth_svc.load_user("non-existent") is None
