#!/usr/bin/env python3
"""Master release orchestrator building Ansible, PyPI, RPM/DEB, and Kubernetes artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


def run_step(name: str, cmd: list[str], cwd: Path) -> None:
    print(f"==> [{name}] {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def build_all_releases(args: argparse.Namespace) -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[2]
    version = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    dist_root = Path(args.output_dir).resolve() if args.output_dir else repo_root / "dist"
    dist_root.mkdir(parents=True, exist_ok=True)

    py = sys.executable

    # 1. Ansible Release Bundle
    ansible_out = dist_root / "ansible"
    run_step(
        "Ansible",
        [
            py,
            str(repo_root / "deploy" / "ansible" / "packaging" / "build_ansible_bundle.py"),
            "--output-dir",
            str(ansible_out),
            "--force",
        ],
        cwd=repo_root,
    )

    # 2. PyPI Wheels & Source Distributions
    pypi_out = dist_root / "pypi"
    run_step(
        "PyPI",
        [
            py,
            str(repo_root / "deploy" / "packaging" / "pypi" / "build_pypi_packages.py"),
            "--output-dir",
            str(pypi_out),
            "--force",
        ],
        cwd=repo_root,
    )

    # 3. Native Linux Packages (.deb & .rpm)
    linux_out = dist_root / "linux"
    linux_cmd = [
        py,
        str(repo_root / "deploy" / "packaging" / "linux" / "build_linux_packages.py"),
        "--output-dir",
        str(linux_out),
        "--force",
    ]
    if args.openalert_binary:
        linux_cmd.extend(["--openalert-binary", args.openalert_binary])
    run_step("RPM/DEB", linux_cmd, cwd=repo_root)

    # 4. Kubernetes Raw Manifests & Helm v3 Chart
    k8s_out = dist_root / "k8s"
    run_step(
        "Kubernetes/Helm",
        [
            py,
            str(repo_root / "deploy" / "packaging" / "k8s" / "build_k8s_bundle.py"),
            "--output-dir",
            str(k8s_out),
            "--force",
        ],
        cwd=repo_root,
    )

    # Aggregate SHA256SUMS across all release targets
    all_checksums: list[str] = []
    target_summaries: dict[str, list[str]] = {}
    for target in ("ansible", "pypi", "linux", "k8s"):
        tdir = dist_root / target
        target_summaries[target] = []
        for fpath in sorted(tdir.iterdir()):
            if fpath.is_file() and fpath.name not in {"SHA256SUMS", "release.json"} and not fpath.name.endswith(".sha256"):
                with fpath.open("rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                rel = f"{target}/{fpath.name}"
                all_checksums.append(f"{digest}  {rel}")
                target_summaries[target].append(rel)

    (dist_root / "SHA256SUMS").write_text("\n".join(all_checksums) + "\n", encoding="utf-8")
    summary = {
        "schema_version": 1,
        "version": version,
        "targets": target_summaries,
        "total_artifacts": len(all_checksums),
    }
    (dist_root / "RELEASE_MANIFEST.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"==> Completed release build v{version}: {len(all_checksums)} artifacts in {dist_root}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="Top-level dist directory (default: ./dist)")
    parser.add_argument("--openalert-binary", help="Optional path to prebuilt openalertd ELF binary")
    args = parser.parse_args()
    try:
        build_all_releases(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Master release build error: {error}\n")


if __name__ == "__main__":
    main()
