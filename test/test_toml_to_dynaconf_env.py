import importlib.util
from pathlib import Path

from dynaconf import Dynaconf


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "scripts"
    / "config"
    / "toml_to_dynaconf_env.py"
)
SPEC = importlib.util.spec_from_file_location("toml_to_dynaconf_env", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
toml_to_dynaconf_env = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(toml_to_dynaconf_env)


def test_iter_dynaconf_env_flattens_nested_toml_values():
    entries = dict(
        toml_to_dynaconf_env.iter_dynaconf_env(
            {
                "database": {
                    "db_host": "db",
                    "db_port": 5432,
                    "db_max_inactive_connection_lifetime": 30.0,
                },
                "logs": {"log_level": "INFO"},
            }
        )
    )

    assert entries["DYNACONF_DATABASE__DB_HOST"] == '"db"'
    assert entries["DYNACONF_DATABASE__DB_PORT"] == "5432"
    assert entries["DYNACONF_DATABASE__DB_MAX_INACTIVE_CONNECTION_LIFETIME"] == "30.0"
    assert entries["DYNACONF_LOGS__LOG_LEVEL"] == '"INFO"'


def test_iter_dynaconf_env_serializes_lists_with_json_converter():
    entries = dict(
        toml_to_dynaconf_env.iter_dynaconf_env(
            {
                "caller_sms": {
                    "modems": [
                        {
                            "id": "primary_carrier",
                            "port": "/dev/ttyUSB2",
                            "baud_rate": 115200,
                            "priority": 1,
                        }
                    ]
                }
            }
        )
    )

    assert (
        entries["DYNACONF_CALLER_SMS__MODEMS"]
        == '@json [{"id":"primary_carrier","port":"/dev/ttyUSB2","baud_rate":115200,"priority":1}]'
    )


def test_merge_dicts_keeps_existing_values_and_overrides_nested_values():
    merged = toml_to_dynaconf_env.merge_dicts(
        {
            "database": {
                "db_host": "postgresql.lan",
                "db_port": 5432,
            },
            "logs": {"log_level": "INFO"},
        },
        {
            "database": {
                "db_host": "db",
            }
        },
    )

    assert merged == {
        "database": {
            "db_host": "db",
            "db_port": 5432,
        },
        "logs": {"log_level": "INFO"},
    }


def test_render_env_file_supports_shell_exports():
    content = toml_to_dynaconf_env.render_env_file(
        [("DYNACONF_LOGS__LOG_FORMATTER", '"%(asctime)s %(message)s"')],
        source_files=[],
        output_format="shell",
        include_header=False,
    )

    assert content == 'export DYNACONF_LOGS__LOG_FORMATTER=\'"%(asctime)s %(message)s"\'\n'


def test_generated_values_are_parsed_by_dynaconf(monkeypatch):
    monkeypatch.setenv("DYNACONF_DATABASE__DB_HOST", '"db"')
    monkeypatch.setenv("DYNACONF_DATABASE__DB_PORT", "5432")
    monkeypatch.setenv(
        "DYNACONF_CALLER_SMS__MODEMS",
        '@json [{"id":"primary_carrier","port":"/dev/ttyUSB2"}]',
    )

    settings = Dynaconf(
        envvar_prefix="DYNACONF",
        environments=False,
        merge_enabled=True,
    )

    assert settings.database.db_host == "db"
    assert settings.database.db_port == 5432
    assert settings.caller_sms.modems == [
        {"id": "primary_carrier", "port": "/dev/ttyUSB2"}
    ]