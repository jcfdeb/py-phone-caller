#!/usr/bin/env python3
"""
Round-trip checks for toml_to_ansible_vars.py.

Runs standalone or under pytest:

    python3 assets/ansible/tools/test_toml_to_ansible_vars.py
    pytest assets/ansible/tools/test_toml_to_ansible_vars.py

Needs PyYAML, so that the generated files are parsed by the same library
Ansible uses rather than by the emitter that produced them.
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import yaml

try:
    import pytest
except ModuleNotFoundError:  # standalone run without the dev dependencies
    pytest = None

TOOL = Path(__file__).with_name("toml_to_ansible_vars.py")
REPO_ROOT = TOOL.resolve().parents[3]

_spec = importlib.util.spec_from_file_location("toml_to_ansible_vars", TOOL)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


HOSTILE_TOML = r"""
[weird]
plain = "hello"
with_quote = "she said \"hi\""
with_backslash = 'C:\path\to\thing'
with_newline = "line1\nline2"
with_tab = "a\tb"
percent = "%(asctime)s %(message)s"
colon = "key: value"
hash = "trailing # comment"
leading_space = "   padded   "
unicode = "caffe latte - naive"
yes_like = "yes"
no_like = "no"
null_like = "null"
num_like = "0123"
version_like = "1.2.3"
phone = "+393349246425"
empty = ""
brace = "Local/{phone}@py-phone-caller"
url = "redis://127.0.0.1:6379/7"
truthy = true
falsy = false
integer = 5038
negative = -17
floaty = 30.0
sci = 1e-3
arr = ["+39123", "+39456"]
nested_arr = [[1, 2], [3, 4]]
empty_arr = []

[weird.sub]
deep = "value"

[[weird.rows]]
id = "primary"
port = "/dev/ttyUSB2"
baud_rate = 115200
priority = 1

[[weird.rows]]
id = "backup"
port = "/dev/ttyUSB3"
baud_rate = 115200
priority = 2

[dates]
when = 2026-09-10T12:34:56Z
day = 2026-09-10

[reserved]
on = "a"
off = "b"
"no" = "c"
"y" = "d"
"weird key" = "e"
"dotted.key" = "f"
"""


def _merge_all(paths):
    merged: dict = {}
    for path in paths:
        tool.merge(merged, tool.load_toml(path))
    return tool.json_safe_copy(merged)


def _run(tmp: Path, sources, extra=()):
    out, sec = tmp / "vars.yml", tmp / "secrets.yml"
    args = [arg for path in sources for arg in ("-i", str(path))]
    assert tool.main([*args, "-o", str(out), "--secrets-output", str(sec), *extra]) == 0
    return out, sec


def _reassemble(out: Path, sec: Path):
    public = yaml.safe_load(out.read_text())[tool.DEFAULT_VAR_NAME]
    secrets = yaml.safe_load(sec.read_text())[tool.DEFAULT_SECRETS_VAR_NAME]
    merged: dict = {}
    tool.merge(merged, public or {})
    tool.merge(merged, secrets or {})
    return merged


if pytest is not None:

    @pytest.fixture(name="tmp")
    def _tmp(tmp_path: Path) -> Path:
        return tmp_path


def test_project_configuration_round_trips(tmp: Path) -> None:
    """The real settings.toml survives TOML -> YAML -> PyYAML unchanged."""
    sources = [
        REPO_ROOT / "src/config/settings.toml",
        REPO_ROOT / "src/config/.secrets.toml",
    ]
    sources = [path for path in sources if path.exists()]
    assert sources, "no configuration found under src/config"

    out, sec = _run(tmp, sources)
    assert _reassemble(out, sec) == _merge_all(sources)


def test_hostile_scalars_round_trip(tmp: Path) -> None:
    """Quotes, backslashes, newlines, %-formats and YAML-ambiguous words."""
    src = tmp / "settings.toml"
    src.write_text(HOSTILE_TOML, encoding="utf-8")

    out, sec = _run(tmp, [src])
    assert _reassemble(out, sec) == _merge_all([src])


def test_secrets_are_isolated(tmp: Path) -> None:
    src = tmp / "settings.toml"
    src.write_text('[database]\ndb_password = "hunter2"\ndb_name = "x"\n')

    out, sec = _run(tmp, [src])
    assert "hunter2" not in out.read_text()
    assert "hunter2" in sec.read_text()
    assert sec.stat().st_mode & 0o777 == 0o600


def test_no_split_secrets_keeps_one_file(tmp: Path) -> None:
    src = tmp / "settings.toml"
    src.write_text('[database]\ndb_password = "hunter2"\ndb_name = "x"\n')
    out = tmp / "vars.yml"

    assert tool.main(["-i", str(src), "-o", str(out), "--no-split-secrets"]) == 0
    assert yaml.safe_load(out.read_text())[tool.DEFAULT_VAR_NAME] == {
        "database": {"db_password": "hunter2", "db_name": "x"}
    }


def test_vault_encrypted_secrets_are_not_overwritten(tmp: Path) -> None:
    src = tmp / "settings.toml"
    src.write_text('[database]\ndb_password = "hunter2"\n')
    sec = tmp / "secrets.yml"
    sec.write_text("$ANSIBLE_VAULT;1.1;AES256\n3132\n")

    rc = tool.main(
        ["-i", str(src), "-o", str(tmp / "vars.yml"), "--secrets-output", str(sec)]
    )
    assert rc == 1
    assert sec.read_text().startswith("$ANSIBLE_VAULT")


def test_missing_input_is_an_error(tmp: Path) -> None:
    assert tool.main(["-i", str(tmp / "nope.toml"), "-o", str(tmp / "v.yml")]) == 1


if __name__ == "__main__":
    failures = 0
    with tempfile.TemporaryDirectory() as td:
        for name, fn in sorted(globals().items()):
            if not name.startswith("test_") or not callable(fn):
                continue
            case = Path(td) / name
            case.mkdir()
            try:
                fn(case)
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
            else:
                print(f"ok   {name}")
    raise SystemExit(1 if failures else 0)
