#!/usr/bin/env python3
"""Build a deterministic, secret-scrubbed Ansible release bundle (.tar.gz + .sha256)."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import yaml


REQUIRED_ROLES = (
    "asterisk_py_phone_caller",
    "deploy_py-phone-caller",
    "firewall",
    "gateway",
    "openalert",
    "postgresql",
    "queue",
    "reverse_proxy",
    "stack_airgap",
    "stack_lifecycle",
    "stack_preflight",
)

REQUIRED_ROOT_FILES = (
    "ansible.cfg",
    "requirements.yml",
    "site.yml",
    "verify.yml",
    ".ansible-lint",
    "README.md",
)

REQUIRED_PLAYBOOKS = (
    "playbooks/adopt.yml",
    "playbooks/backup.yml",
    "playbooks/restore.yml",
    "playbooks/rollback.yml",
)

REQUIRED_TASKS = (
    "tasks/combined_pbx.yml",
    "tasks/pbx_aliases.yml",
)

COMPATIBILITY_SAFE_FILES = (
    "deploy_all/ansible.cfg",
    "deploy_all/deploy_py-phone-caller_stack.yml",
    "deploy_all/README.md",
    "deploy_all/requirements.yml",
    "asterisk_py-phone-caller/ansible.cfg",
    "asterisk_py-phone-caller/deploy_asterisk.yml",
    "asterisk_py-phone-caller/README.md",
    "asterisk_py-phone-caller/README_install_module_manually.md",
    "asterisk_py-phone-caller/requirements.yml",
    "on-vm_py-phone-caller/ansible.cfg",
    "on-vm_py-phone-caller/deploy_py-phone-caller.yml",
    "on-vm_py-phone-caller/README.md",
    "on-vm_py-phone-caller/render_check.yml",
    "on-vm_py-phone-caller/requirements.yml",
    "on-vm_py-phone-caller/verify.yml",
    "on-vm_py-phone-caller/examples/group_vars-app_servers-config.yml.example",
    "on-vm_py-phone-caller/examples/group_vars-app_servers-secrets.yml.example",
    "on-vm_py-phone-caller/group_vars/all.yml",
)

CONTROLLER_TEST_FILES = (
    "tests/README.md",
    "tests/requirements-controller.txt",
    "tests/render.yml",
    "tests/preflight.yml",
)

FORBIDDEN_PATH_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime",
    ".rendered",
    ".ansible",
    "credentials",
}

FORBIDDEN_FILENAMES = {
    ".vault_pass",
    "secrets.yml",
    "secrets.toml",
    ".secrets.toml",
    "inventory",
    "inventory.ini",
    "show-credentials.sh",
}


def git_output(*command: str, cwd: Path) -> str:
    return subprocess.check_output(
        command,
        cwd=cwd,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    ).strip()


def load_version(repo_root: Path, override: str | None = None) -> str:
    if override:
        version = override
    else:
        pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
        version = pyproject["project"]["version"]
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]*", version):
        raise ValueError(f"Unsafe package version: {version!r}")
    return version


def parse_pinned_collections(requirements_path: Path) -> dict[str, str]:
    data = yaml.safe_load(requirements_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("collections"), list):
        raise ValueError(f"Invalid requirements.yml structure in {requirements_path}")
    pinned: dict[str, str] = {}
    for entry in data["collections"]:
        name = entry.get("name")
        version = entry.get("version")
        if not name or not version or "." not in name:
            raise ValueError(f"All collections in requirements.yml must pin name and version: {entry!r}")
        pinned[str(name)] = str(version)
    if not pinned:
        raise ValueError("requirements.yml defines no collections")
    return pinned


def ignore_junk(_directory: str, contents: list[str]) -> set[str]:
    ignored: set[str] = set()
    for item in contents:
        if (
            item in FORBIDDEN_PATH_PARTS
            or item in FORBIDDEN_FILENAMES
            or item.startswith(".vault_pass")
            or item.endswith((".pyc", ".pyo", ".bak", ".orig", "~"))
        ):
            ignored.add(item)
    return ignored


def stage_collections(
    collections_source: Path,
    staging_root: Path,
    pinned_collections: dict[str, str],
) -> dict[str, dict[str, str]]:
    acl_root = collections_source / "ansible_collections"
    if not acl_root.is_dir():
        raise ValueError(
            f"Collections directory {acl_root} does not exist. "
            "Run `ansible-galaxy collection install -r requirements.yml -p .collections` "
            "or pass --install-collections."
        )
    verified: dict[str, dict[str, str]] = {}
    for fqcn, expected_version in sorted(pinned_collections.items()):
        namespace, name = fqcn.split(".", 1)
        src_col = acl_root / namespace / name
        manifest_path = src_col / "MANIFEST.json"
        if not manifest_path.is_file():
            raise ValueError(f"Missing required collection {fqcn} at {src_col}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        info = manifest.get("collection_info", {})
        actual_version = str(info.get("version", ""))
        if actual_version != expected_version:
            raise ValueError(
                f"Collection {fqcn} version mismatch: expected {expected_version}, got {actual_version}"
            )
        dest_col = staging_root / ".collections" / "ansible_collections" / namespace / name
        dest_col.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_col, dest_col, ignore=ignore_junk)
        verified[fqcn] = {
            "version": actual_version,
            "path": f".collections/ansible_collections/{namespace}/{name}",
        }
    return verified


def verify_staged_tree(staging: Path) -> dict[str, str]:
    for rel in (*REQUIRED_ROOT_FILES, *REQUIRED_PLAYBOOKS, *REQUIRED_TASKS):
        if not (staging / rel).is_file():
            raise ValueError(f"Staged bundle is missing required file: {rel}")
    for role in REQUIRED_ROLES:
        role_dir = staging / "roles" / role
        if not role_dir.is_dir() or not (role_dir / "tasks" / "main.yml").is_file():
            raise ValueError(f"Staged bundle is missing required role tasks: roles/{role}/tasks/main.yml")

    file_hashes: dict[str, str] = {}
    for path in sorted(staging.rglob("*")):
        rel_parts = path.relative_to(staging).parts
        rel_posix = path.relative_to(staging).as_posix()

        if path.is_symlink():
            raise ValueError(f"Symlinks are not permitted in Ansible release bundle: {rel_posix}")

        for part in rel_parts:
            if part in FORBIDDEN_PATH_PARTS:
                raise ValueError(f"Forbidden directory or runtime artifact in bundle: {rel_posix}")

        if path.is_file():
            fname = path.name
            if (
                fname in FORBIDDEN_FILENAMES
                or fname.startswith(".vault_pass")
                or (fname.endswith("secrets.yml") and not fname.endswith(".example"))
                or fname.endswith((".pyc", ".pyo", ".env"))
                or (fname.endswith((".key", ".pem")) and not rel_posix.startswith(".collections/"))
            ):
                raise ValueError(f"Forbidden secret or site-specific file in bundle: {rel_posix}")

            # Normalize file permissions
            if path.suffix == ".sh" or path.suffix == ".py":
                with path.open("rb") as shebang_stream:
                    first_line = shebang_stream.readline()
                path.chmod(0o755 if first_line.startswith(b"#!") else 0o644)
            else:
                path.chmod(0o644)

            with path.open("rb") as handle:
                file_hashes[rel_posix] = hashlib.file_digest(handle, "sha256").hexdigest()
        elif path.is_dir():
            path.chmod(0o755)

    return file_hashes


def write_deterministic_tar_gz(source_dir: Path, arcname: str, archive_path: Path) -> str:
    """Create a reproducible .tar.gz archive with normalized uid/gid and mtime."""
    def reset_tarinfo(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
        tarinfo.uid = 0
        tarinfo.gid = 0
        tarinfo.uname = "root"
        tarinfo.gname = "root"
        tarinfo.mtime = 0
        return tarinfo

    with archive_path.open("wb") as raw_file:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_file, mtime=0) as gz_file:
            with tarfile.open(mode="w", fileobj=gz_file, format=tarfile.PAX_FORMAT) as bundle:
                bundle.add(source_dir, arcname=arcname, recursive=False, filter=reset_tarinfo)
                for item in sorted(source_dir.rglob("*"), key=lambda p: p.relative_to(source_dir).as_posix()):
                    rel = item.relative_to(source_dir).as_posix()
                    bundle.add(item, arcname=f"{arcname}/{rel}", recursive=False, filter=reset_tarinfo)

    with archive_path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def build_bundle(args: argparse.Namespace) -> dict[str, object]:
    packaging_dir = Path(__file__).resolve().parent
    ansible_dir = packaging_dir.parent.resolve()
    repo_root = ansible_dir.parent.parent.resolve()

    version = load_version(repo_root, args.version)
    pinned_collections = parse_pinned_collections(ansible_dir / "requirements.yml")

    if args.source_revision:
        if not re.fullmatch(r"[0-9a-f]{40,64}", args.source_revision):
            raise ValueError("--source-revision must be a full 40-to-64 hex commit SHA")
        revision = args.source_revision
        dirty: bool | None = None
    else:
        revision = git_output("git", "rev-parse", "HEAD", cwd=repo_root)
        dirty = bool(
            git_output("git", "status", "--porcelain", "--untracked-files=normal", "--", "deploy/ansible", cwd=repo_root)
        )

    suffix = "-offline" if (args.with_collections or args.install_collections) else ""
    bundle_name = f"py-phone-caller-ansible-v{version}{suffix}"
    destination = Path(args.output_dir).resolve() if args.output_dir else ansible_dir / "dist"
    archive = destination / f"{bundle_name}.tar.gz"
    checksum = destination / f"{bundle_name}.tar.gz.sha256"

    if (archive.exists() or checksum.exists()) and not args.force:
        raise ValueError(
            f"Release output {archive.name} already exists; pass --force or use a new --output-dir"
        )

    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ansible-bundle-", dir=destination) as work:
        work_path = Path(work)
        staging = work_path / bundle_name
        staging.mkdir(parents=True)

        # 1. Stage root files, playbooks, tasks, controller test files, and compatibility wrappers
        for rel in (
            *REQUIRED_ROOT_FILES,
            *REQUIRED_PLAYBOOKS,
            *REQUIRED_TASKS,
            *CONTROLLER_TEST_FILES,
            *COMPATIBILITY_SAFE_FILES,
        ):
            src = ansible_dir / rel
            if not src.is_file():
                raise ValueError(f"Missing source file required for Ansible bundle: {rel}")
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)

        # 2. Stage roles, docs, example inventories, and tools
        for rel_dir in ("roles", "docs", "inventories/examples", "tools"):
            src_dir = ansible_dir / rel_dir
            if not src_dir.is_dir():
                raise ValueError(f"Missing source directory required for Ansible bundle: {rel_dir}")
            shutil.copytree(src_dir, staging / rel_dir, ignore=ignore_junk)

        # Remove unit test file from tools/ in the operator bundle if present
        tools_test = staging / "tools" / "test_toml_to_ansible_vars.py"
        if tools_test.exists():
            tools_test.unlink()

        # 3. Stage packaging README inside packaging/
        if (packaging_dir / "README.md").is_file():
            (staging / "packaging").mkdir(parents=True, exist_ok=True)
            shutil.copyfile(packaging_dir / "README.md", staging / "packaging" / "README.md")

        # 4. Optionally install and/or bundle pinned Ansible Galaxy collections
        bundled_collections_meta: dict[str, dict[str, str]] = {}
        if args.install_collections:
            temp_cols = work_path / "installed_collections"
            temp_cols.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "ansible-galaxy",
                    "collection",
                    "install",
                    "--force",
                    "-r",
                    str(ansible_dir / "requirements.yml"),
                    "-p",
                    str(temp_cols),
                ],
                check=True,
            )
            bundled_collections_meta = stage_collections(temp_cols, staging, pinned_collections)
        elif args.with_collections:
            cols_dir = Path(args.collections_dir).resolve() if args.collections_dir else ansible_dir / ".collections"
            bundled_collections_meta = stage_collections(cols_dir, staging, pinned_collections)

        # 5. Verify staged tree and compute per-file SHA-256 digests
        file_hashes = verify_staged_tree(staging)

        metadata: dict[str, object] = {
            "schema_version": 1,
            "package": "py-phone-caller-ansible",
            "version": version,
            "release_id": f"{version}-{revision[:12]}{suffix}",
            "source_revision": revision,
            "source_dirty": dirty,
            "bundled_collections": bool(bundled_collections_meta),
            "pinned_collections": pinned_collections,
            "collections": bundled_collections_meta,
            "roles": list(REQUIRED_ROLES),
            "playbooks": ["site.yml", "verify.yml", *REQUIRED_PLAYBOOKS],
            "files": file_hashes,
        }
        release_json = staging / "release.json"
        release_json.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        release_json.chmod(0o644)

        temporary_archive = work_path / archive.name
        archive_hash = write_deterministic_tar_gz(staging, bundle_name, temporary_archive)
        temporary_checksum = work_path / checksum.name
        temporary_checksum.write_text(f"{archive_hash}  {archive.name}\n", encoding="utf-8")

        temporary_archive.replace(archive)
        temporary_checksum.replace(checksum)

    print(f"Release: {archive}\nSHA-256: {archive_hash}\nIdentity: {metadata['release_id']}")
    return {
        "archive": archive,
        "checksum": checksum,
        "sha256": archive_hash,
        "metadata": metadata,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="Override release version (defaults to root pyproject.toml)")
    parser.add_argument("--source-revision", help="Explicit full Git commit SHA for provenance")
    parser.add_argument(
        "--with-collections",
        action="store_true",
        help="Bundle verified offline Ansible collections from --collections-dir (default: deploy/ansible/.collections)",
    )
    parser.add_argument(
        "--collections-dir",
        help="Directory containing ansible_collections/ when using --with-collections",
    )
    parser.add_argument(
        "--install-collections",
        action="store_true",
        help="Run ansible-galaxy collection install -r requirements.yml and bundle them into an offline archive",
    )
    parser.add_argument("--output-dir", help="Output directory (default: deploy/ansible/dist)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output archive if present")
    args = parser.parse_args()
    try:
        build_bundle(args)
    except (OSError, ValueError, subprocess.CalledProcessError, KeyError) as error:
        parser.exit(1, f"Ansible bundle error: {error}\n")


if __name__ == "__main__":
    main()
