#!/usr/bin/env python3
"""
Convert py-phone-caller TOML configuration into Ansible vars files.

The TOML files under ``src/config`` are the single source of truth for the
platform configuration. This tool renders them into YAML vars files that the
``deploy_py-phone-caller`` role consumes, so a deployment never drifts from the
configuration developers run locally.

By default two files are produced:

* ``group_vars/app_servers/config.yml``   -> ``py_phone_caller_config``
* ``group_vars/app_servers/secrets.yml``  -> ``py_phone_caller_config_secrets``

The second file only holds the values listed in ``--secret`` (a sane default
list is built in) so it can be encrypted on its own::

    ansible-vault encrypt group_vars/app_servers/secrets.yml

The role merges both on top of its own defaults, secrets last.

Only the standard library is used, so the tool runs with any Python 3.11+
interpreter (``tomllib``) without installing PyYAML on the control node.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on old interpreters
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        sys.exit(
            "This tool needs Python 3.11+ (for 'tomllib') or the 'tomli' "
            f"package. Running interpreter: {sys.version.split()[0]}"
        )

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = (
    REPO_ROOT / "src" / "config" / "settings.toml",
    REPO_ROOT / "src" / "config" / ".secrets.toml",
)
# A group_vars/<group>/ DIRECTORY, not group_vars/<group>.yml files: Ansible
# reads every file inside such a directory, but only auto-loads a plain file
# whose stem is exactly the group name. "app_servers.secrets.yml" matches no
# group and is silently ignored.
DEFAULT_GROUP_VARS = (
    REPO_ROOT
    / "assets"
    / "ansible"
    / "on-vm_py-phone-caller"
    / "group_vars"
    / "app_servers"
)
DEFAULT_OUTPUT = DEFAULT_GROUP_VARS / "config.yml"
DEFAULT_SECRETS_OUTPUT = DEFAULT_GROUP_VARS / "secrets.yml"

DEFAULT_VAR_NAME = "py_phone_caller_config"
DEFAULT_SECRETS_VAR_NAME = "py_phone_caller_config_secrets"

# Dotted "section.key" paths that must never land in the plain vars file.
DEFAULT_SECRET_PATHS = (
    "commons.asterisk_pass",
    "commons.asterisk_ami_secret",
    "caller_sms.twilio_account_sid",
    "caller_sms.twilio_auth_token",
    "database.db_password",
    "py_phone_caller_ui.ui_secret_key",
)

# Characters that terminate a line in YAML 1.1 but that json.dumps leaves raw.
_YAML_LINE_BREAKS = {
    "\u0085": "\\u0085",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}


# --------------------------------------------------------------------------- #
# TOML loading
# --------------------------------------------------------------------------- #
def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as toml_file:
        return tomllib.load(toml_file)


def merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base``; lists replace, they never append."""
    for key, value in override.items():
        current = base.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            merge(current, value)
        else:
            base[key] = value
    return base


# --------------------------------------------------------------------------- #
# Secret extraction
# --------------------------------------------------------------------------- #
def split_secrets(
    config: Mapping[str, Any], secret_paths: Sequence[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(public, secret)`` copies of ``config`` split on dotted paths."""
    public: dict[str, Any] = json_safe_copy(config)
    secret: dict[str, Any] = {}

    for path in secret_paths:
        parts = path.split(".")
        node: Any = public
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if not isinstance(node, dict) or parts[-1] not in node:
            continue

        value = node.pop(parts[-1])
        target = secret
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value

    # Drop sections that became empty after extraction.
    for section in [key for key, value in public.items() if value == {}]:
        del public[section]

    return public, secret


def json_safe_copy(node: Any) -> Any:
    """Deep-copy while normalising TOML dates to ISO-8601 strings."""
    if isinstance(node, Mapping):
        return {str(key): json_safe_copy(value) for key, value in node.items()}
    if isinstance(node, (list, tuple)):
        return [json_safe_copy(item) for item in node]
    if isinstance(node, (dt.datetime, dt.date, dt.time)):
        return node.isoformat()
    return node


# --------------------------------------------------------------------------- #
# Minimal YAML emitter (block style, always-quoted strings)
# --------------------------------------------------------------------------- #
def yaml_quote(text: str) -> str:
    quoted = json.dumps(text, ensure_ascii=False)
    for raw, escaped in _YAML_LINE_BREAKS.items():
        quoted = quoted.replace(raw, escaped)
    return quoted


_PLAIN_KEY = re.compile(r"\A[A-Za-z_][A-Za-z0-9_-]*\Z")
# YAML 1.1 resolves these unquoted to booleans/null, so keys matching them stay quoted.
_RESERVED_PLAIN = frozenset(
    "y yes n no true false on off null none ~".split()
)


def yaml_key(name: str) -> str:
    """Emit ``name`` bare when it is unambiguous, quoted otherwise."""
    if _PLAIN_KEY.match(name) and name.lower() not in _RESERVED_PLAIN:
        return name
    return yaml_quote(name)


def yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"Cannot represent {value!r} in YAML")
        return repr(value)
    if isinstance(value, str):
        return yaml_quote(value)
    raise TypeError(f"Unsupported scalar type: {type(value).__name__}")


def is_scalar(value: Any) -> bool:
    return not isinstance(value, (Mapping, list, tuple))


def emit_block(node: Any, indent: int, lines: list[str]) -> None:
    pad = "  " * indent

    if isinstance(node, Mapping):
        for key, value in node.items():
            label = f"{pad}{yaml_key(str(key))}:"
            if is_scalar(value):
                lines.append(f"{label} {yaml_scalar(value)}")
            elif not value:
                lines.append(f"{label} {{}}" if isinstance(value, Mapping) else f"{label} []")
            else:
                lines.append(label)
                emit_block(value, indent + 1, lines)
        return

    for item in node:
        if is_scalar(item):
            lines.append(f"{pad}- {yaml_scalar(item)}")
        elif not item:
            lines.append(f"{pad}- {{}}" if isinstance(item, Mapping) else f"{pad}- []")
        else:
            item_lines: list[str] = []
            emit_block(item, indent + 1, item_lines)
            # Re-anchor the first line onto the "- " marker.
            first = item_lines[0].lstrip()
            lines.append(f"{pad}- {first}")
            lines.extend(item_lines[1:])


def display_path(path: Path) -> str:
    """Render ``path`` relative to the repository root so headers stay portable."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def render_vars_file(
    var_name: str, payload: Mapping[str, Any], *, sources: Sequence[Path], note: str
) -> str:
    lines = [
        "---",
        "# Generated by assets/ansible/tools/toml_to_ansible_vars.py - do not edit by hand.",
        f"# {note}",
        "# Source files:",
    ]
    lines.extend(f"#   - {display_path(source)}" for source in sources)
    lines.append("")

    if not payload:
        lines.append(f"{var_name}: {{}}")
    else:
        lines.append(f"{var_name}:")
        emit_block(payload, 1, lines)

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        "-i",
        action="append",
        dest="inputs",
        type=Path,
        metavar="TOML",
        help=(
            "TOML file to read; repeatable, later files win. "
            f"Default: {' '.join(str(path) for path in DEFAULT_INPUTS)}"
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Vars file to write. Default: {DEFAULT_OUTPUT}",
    )
    parser.add_argument(
        "--secrets-output",
        type=Path,
        default=DEFAULT_SECRETS_OUTPUT,
        help=f"Secrets vars file to write. Default: {DEFAULT_SECRETS_OUTPUT}",
    )
    parser.add_argument(
        "--var-name",
        default=DEFAULT_VAR_NAME,
        help=f"Top-level variable name. Default: {DEFAULT_VAR_NAME}",
    )
    parser.add_argument(
        "--secrets-var-name",
        default=DEFAULT_SECRETS_VAR_NAME,
        help=f"Top-level secrets variable name. Default: {DEFAULT_SECRETS_VAR_NAME}",
    )
    parser.add_argument(
        "--secret",
        action="append",
        dest="secrets",
        default=[],
        metavar="SECTION.KEY",
        help="Extra dotted path to treat as a secret; repeatable.",
    )
    parser.add_argument(
        "--no-default-secrets",
        action="store_true",
        help="Do not apply the built-in secret path list.",
    )
    parser.add_argument(
        "--no-split-secrets",
        action="store_true",
        help="Write everything to a single vars file (secrets included).",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print to stdout instead of writing files.",
    )
    parser.add_argument(
        "--ignore-missing",
        action="store_true",
        help="Skip input files that do not exist instead of failing.",
    )
    return parser.parse_args(argv)


def write_file(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    inputs = [Path(path) for path in (args.inputs or DEFAULT_INPUTS)]

    config: dict[str, Any] = {}
    loaded: list[Path] = []
    for source in inputs:
        if not source.exists():
            if args.ignore_missing:
                continue
            print(f"Input file not found: {source}", file=sys.stderr)
            return 1
        merge(config, load_toml(source))
        loaded.append(source)

    if not loaded:
        print("No TOML input files were read.", file=sys.stderr)
        return 1

    secret_paths: list[str] = [] if args.no_default_secrets else list(DEFAULT_SECRET_PATHS)
    secret_paths.extend(args.secrets)

    if args.no_split_secrets:
        public, secrets = json_safe_copy(config), {}
    else:
        public, secrets = split_secrets(config, secret_paths)

    public_yaml = render_vars_file(
        args.var_name,
        public,
        sources=loaded,
        note="Regenerate with: assets/ansible/tools/toml_to_ansible_vars.py",
    )

    if args.stdout:
        print(public_yaml, end="")
    else:
        write_file(args.output, public_yaml, mode=stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        print(f"Wrote {args.output}")

    if args.no_split_secrets:
        return 0

    secrets_yaml = render_vars_file(
        args.secrets_var_name,
        secrets,
        sources=loaded,
        note="Encrypt this file: ansible-vault encrypt <this file>",
    )

    if args.stdout:
        print("---8<--- secrets ---8<---")
        print(secrets_yaml, end="")
        return 0

    if is_vault_encrypted(args.secrets_output):
        print(
            f"Refusing to overwrite vault-encrypted {args.secrets_output}; "
            "decrypt it first or pass --secrets-output elsewhere.",
            file=sys.stderr,
        )
        return 1

    write_file(args.secrets_output, secrets_yaml, mode=stat.S_IRUSR | stat.S_IWUSR)
    print(f"Wrote {args.secrets_output} (0600, encrypt it with ansible-vault)")
    return 0


def is_vault_encrypted(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.readline().startswith("$ANSIBLE_VAULT")


if __name__ == "__main__":
    raise SystemExit(main())
