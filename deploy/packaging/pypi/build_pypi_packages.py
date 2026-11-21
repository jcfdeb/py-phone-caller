#!/usr/bin/env python3
"""Build and verify PyPI wheels and source distributions for py-phone-caller."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile


WORKSPACE_PACKAGES: tuple[tuple[str, str, str | None], ...] = (
    ("py_phone_caller_utils", "src/py-phone-caller-utils", None),
    ("asterisk-caller", "src/asterisk_caller", "ppc-asterisk-caller"),
    ("asterisk-recaller", "src/asterisk_recaller", "ppc-asterisk-recaller"),
    ("asterisk-ws-monitor", "src/asterisk_ws_monitor", "ppc-asterisk-ws-monitor"),
    ("caller-address-book", "src/caller_address_book", "ppc-caller-address-book"),
    ("caller-prometheus-webhook", "src/caller_prometheus_webhook", "ppc-caller-prometheus-webhook"),
    ("caller-register", "src/caller_register", "ppc-caller-register"),
    ("caller-scheduler", "src/caller_scheduler", "ppc-caller-scheduler"),
    ("caller-sms", "src/caller_sms", "ppc-caller-sms"),
    ("celery-worker", "src/celery_worker", "ppc-celery-worker"),
    ("generate-audio", "src/generate_audio", "ppc-generate-audio"),
    ("py-phone-caller-ui", "src/py_phone_caller_ui", "ppc-ui"),
)

META_PACKAGE = ("py-phone-caller", "deploy/packaging/pypi/meta_package", "py-phone-caller")

EXCLUDED_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "pre_trained_models",
    "audio",
    "target",
}

FORBIDDEN_ARCHIVE_PATTERNS = (
    "Dockerfile",
    ".secrets.toml",
    "secrets.toml",
    ".vault_pass",
    "pre_trained_models/",
)


def git_output(*command: str, cwd: Path) -> str:
    return subprocess.check_output(
        command,
        cwd=cwd,
        text=True,
        env={**os.environ, "LC_ALL": "C"},
    ).strip()


def ignore_staging_files(_directory: str, contents: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in contents:
        if (
            name in EXCLUDED_DIRS
            or name.endswith(".egg-info")
            or name.startswith("Dockerfile")
            or name.endswith((".pyc", ".pyo", ".bak", ".orig"))
        ):
            ignored.add(name)
    return ignored


def verify_wheel(wheel_path: Path, expected_script: str | None) -> dict[str, object]:
    with zipfile.ZipFile(wheel_path, "r") as zf:
        names = zf.namelist()
        for name in names:
            for forbidden in FORBIDDEN_ARCHIVE_PATTERNS:
                if forbidden in name:
                    raise ValueError(f"Forbidden file {name!r} found inside wheel {wheel_path.name}")

        metadata_files = [n for n in names if n.endswith(".dist-info/METADATA")]
        if len(metadata_files) != 1:
            raise ValueError(f"Wheel {wheel_path.name} missing .dist-info/METADATA")

        if expected_script:
            ep_files = [n for n in names if n.endswith(".dist-info/entry_points.txt")]
            if len(ep_files) != 1:
                raise ValueError(f"Wheel {wheel_path.name} missing entry_points.txt for {expected_script}")
            ep_text = zf.read(ep_files[0]).decode("utf-8")
            if expected_script not in ep_text:
                raise ValueError(
                    f"Wheel {wheel_path.name} entry_points.txt does not declare {expected_script}"
                )

    with wheel_path.open("rb") as handle:
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"filename": wheel_path.name, "sha256": sha256, "size": wheel_path.stat().st_size}


def verify_sdist(sdist_path: Path) -> dict[str, object]:
    with tarfile.open(sdist_path, "r:gz") as tf:
        for member in tf.getnames():
            for forbidden in FORBIDDEN_ARCHIVE_PATTERNS:
                if forbidden in member:
                    raise ValueError(f"Forbidden file {member!r} found inside sdist {sdist_path.name}")
    with sdist_path.open("rb") as handle:
        sha256 = hashlib.file_digest(handle, "sha256").hexdigest()
    return {"filename": sdist_path.name, "sha256": sha256, "size": sdist_path.stat().st_size}


def build_single_package(
    repo_root: Path,
    pkg_name: str,
    rel_dir: str,
    expected_script: str | None,
    staging_parent: Path,
    out_dir: Path,
) -> dict[str, object]:
    src_dir = repo_root / rel_dir
    if not (src_dir / "pyproject.toml").is_file():
        raise ValueError(f"Missing pyproject.toml in {src_dir}")

    staged_pkg = staging_parent / pkg_name
    shutil.copytree(src_dir, staged_pkg, ignore=ignore_staging_files)

    # Copy root LICENSE into staged package if not already present
    root_license = repo_root / "LICENSE"
    if root_license.is_file() and not (staged_pkg / "LICENSE").exists():
        shutil.copyfile(root_license, staged_pkg / "LICENSE")

    pkg_out = staging_parent / f"out-{pkg_name}"
    pkg_out.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            "uv",
            "build",
            "--no-build-isolation",
            "--no-build-logs",
            "--out-dir",
            str(pkg_out),
            str(staged_pkg),
        ],
        cwd=repo_root,
        check=True,
    )

    wheels = list(pkg_out.glob("*.whl"))
    sdists = list(pkg_out.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError(f"Expected 1 wheel and 1 sdist for {pkg_name}, got {wheels} and {sdists}")

    wheel_info = verify_wheel(wheels[0], expected_script)
    sdist_info = verify_sdist(sdists[0])

    final_wheel = out_dir / wheels[0].name
    final_sdist = out_dir / sdists[0].name
    shutil.copyfile(wheels[0], final_wheel)
    shutil.copyfile(sdists[0], final_sdist)

    return {
        "package": pkg_name,
        "cli_script": expected_script,
        "wheel": wheel_info,
        "sdist": sdist_info,
    }


def build_all(args: argparse.Namespace) -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[3]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    out_dir = Path(args.output_dir).resolve() if args.output_dir else repo_root / "dist" / "pypi"
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        raise ValueError(f"Output directory {out_dir} is not empty; pass --force or a new --output-dir")

    out_dir.mkdir(parents=True, exist_ok=True)
    if args.force:
        for existing in out_dir.glob("*"):
            if existing.is_file():
                existing.unlink()

    all_specs = [*WORKSPACE_PACKAGES, META_PACKAGE]
    if args.package:
        wanted = set(args.package)
        all_specs = [spec for spec in all_specs if spec[0] in wanted]
        if not all_specs:
            raise ValueError(f"Unknown package(s): {args.package}")

    revision = args.source_revision or git_output("git", "rev-parse", "HEAD", cwd=repo_root)
    if not re.fullmatch(r"[0-9a-f]{40,64}", revision):
        raise ValueError("Invalid --source-revision")

    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix=".pypi-build-", dir=out_dir) as tmp:
        staging_parent = Path(tmp)
        for pkg_name, rel_dir, expected_script in all_specs:
            info = build_single_package(
                repo_root=repo_root,
                pkg_name=pkg_name,
                rel_dir=rel_dir,
                expected_script=expected_script,
                staging_parent=staging_parent,
                out_dir=out_dir,
            )
            results.append(info)

    checksum_lines: list[str] = []
    for item in results:
        whl = item["wheel"]
        sdt = item["sdist"]
        checksum_lines.append(f"{whl['sha256']}  {whl['filename']}")
        checksum_lines.append(f"{sdt['sha256']}  {sdt['filename']}")
    checksum_lines.sort(key=lambda line: line.split()[1])

    sha256sums_path = out_dir / "SHA256SUMS"
    sha256sums_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "version": version,
        "source_revision": revision,
        "package_count": len(results),
        "packages": results,
    }
    manifest_path = out_dir / "release.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Built and verified {len(results)} PyPI packages ({len(results) * 2} distributions) in {out_dir}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package",
        action="append",
        help="Build only the specified package(s) (repeatable; default builds all 13 packages)",
    )
    parser.add_argument("--source-revision", help="Explicit Git commit SHA for release.json")
    parser.add_argument("--output-dir", help="Output directory (default: dist/pypi)")
    parser.add_argument("--force", action="store_true", help="Clear existing distributions in output-dir")
    args = parser.parse_args()
    try:
        build_all(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"PyPI build error: {error}\n")


if __name__ == "__main__":
    main()
