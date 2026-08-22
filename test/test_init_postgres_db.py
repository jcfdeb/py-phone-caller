import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure scripts directory is in sys.path
scripts_db_dir = Path(__file__).resolve().parent.parent / "assets" / "scripts" / "db"
if str(scripts_db_dir) not in sys.path:
    sys.path.insert(0, str(scripts_db_dir))

import init_postgres_db


def test_quote_helpers():
    assert init_postgres_db.quote_ident("normal_user") == '"normal_user"'
    assert init_postgres_db.quote_ident('user"with"quotes') == '"user""with""quotes"'
    assert init_postgres_db.quote_literal("secret_password") == "'secret_password'"
    assert init_postgres_db.quote_literal("pass'with'quotes") == "'pass''with''quotes'"


def test_build_parser_defaults():
    parser = init_postgres_db.build_parser()
    args = parser.parse_args([])
    assert args.admin_port == 5432
    assert args.admin_user == "postgres"
    assert args.admin_db == "postgres"
    assert args.app_db_name == "py_phone_caller"
    assert args.app_db_user == "py_phone_caller"
    assert not args.dry_run
    assert not args.skip_extensions


@pytest.mark.asyncio
async def test_provision_postgres_database_dry_run():
    result = await init_postgres_db.provision_postgres_database(
        admin_host="127.0.0.1",
        admin_port=5432,
        admin_user="postgres",
        admin_password="secret_admin_password",
        admin_db="postgres",
        app_db_name="py_phone_caller_test",
        app_db_user="py_phone_caller_test_user",
        app_db_password="test_password",
        dry_run=True,
    )
    assert result is True


@pytest.mark.asyncio
async def test_provision_postgres_database_success():
    mock_admin_conn = AsyncMock()
    mock_admin_conn.fetchval.side_effect = [None, None]  # Role does not exist, DB does not exist
    mock_admin_conn.execute.return_value = "OK"
    mock_admin_conn.close.return_value = None

    mock_app_admin_conn = AsyncMock()
    mock_app_admin_conn.execute.return_value = "OK"
    mock_app_admin_conn.close.return_value = None

    mock_user_conn = AsyncMock()
    mock_user_conn.fetchrow.return_value = {
        "current_user": "py_phone_caller",
        "current_database": "py_phone_caller",
        "version": "PostgreSQL 17.0 on x86_64",
    }
    mock_user_conn.close.return_value = None

    with patch("asyncpg.connect", side_effect=[mock_admin_conn, mock_app_admin_conn, mock_user_conn]) as mock_connect:
        result = await init_postgres_db.provision_postgres_database(
            admin_host="192.168.101.212",
            admin_port=5432,
            admin_user="postgres",
            admin_password="admin_password",
            admin_db="postgres",
            app_db_name="py_phone_caller",
            app_db_user="py_phone_caller",
            app_db_password="app_password",
        )

        assert result is True
        assert mock_connect.call_count == 3
        assert mock_admin_conn.execute.call_count == 3
        assert mock_app_admin_conn.execute.call_count == 5  # schema grants + 2 extensions
        mock_user_conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_provision_postgres_database_existing_role_and_db():
    mock_admin_conn = AsyncMock()
    mock_admin_conn.fetchval.side_effect = [1, 1]  # Role exists, DB exists
    mock_admin_conn.execute.return_value = "OK"
    mock_admin_conn.close.return_value = None

    mock_app_admin_conn = AsyncMock()
    mock_app_admin_conn.execute.return_value = "OK"
    mock_app_admin_conn.close.return_value = None

    mock_user_conn = AsyncMock()
    mock_user_conn.fetchrow.return_value = {
        "current_user": "py_phone_caller",
        "current_database": "py_phone_caller",
        "version": "PostgreSQL 17.0",
    }
    mock_user_conn.close.return_value = None

    with patch("asyncpg.connect", side_effect=[mock_admin_conn, mock_app_admin_conn, mock_user_conn]):
        result = await init_postgres_db.provision_postgres_database(
            admin_host="localhost",
            admin_port=5432,
            admin_user="postgres",
            admin_password="admin_password",
            admin_db="postgres",
            app_db_name="py_phone_caller",
            app_db_user="py_phone_caller",
            app_db_password="app_password",
            skip_extensions=True,
        )

        assert result is True
        # Verify ALTER statements were called
        execute_calls = [call.args[0] for call in mock_admin_conn.execute.call_args_list]
        assert any("ALTER ROLE" in sql for sql in execute_calls)
        assert any("ALTER DATABASE" in sql for sql in execute_calls)
