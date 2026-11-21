#!/usr/bin/env python3
"""Validate and package Kubernetes raw manifests and the Helm v3 chart into dist/k8s/."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile
import yaml


def write_deterministic_tgz(source_dir: Path, arc_prefix: str, dest_path: Path) -> str:
    def reset_tarinfo(ti: tarfile.TarInfo) -> tarfile.TarInfo:
        ti.uid = 0
        ti.gid = 0
        ti.uname = "root"
        ti.gname = "root"
        ti.mtime = 0
        return ti

    with dest_path.open("wb") as raw_out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0) as gz_out:
            with tarfile.open(mode="w", fileobj=gz_out, format=tarfile.PAX_FORMAT) as tf:
                tf.add(source_dir, arcname=arc_prefix, recursive=False, filter=reset_tarinfo)
                for item in sorted(source_dir.rglob("*"), key=lambda p: p.relative_to(source_dir).as_posix()):
                    rel = item.relative_to(source_dir).as_posix()
                    tf.add(item, arcname=f"{arc_prefix}/{rel}", recursive=False, filter=reset_tarinfo)

    with dest_path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate_k8s_manifests(k8s_dir: Path) -> list[str]:
    kustom_path = k8s_dir / "kustomization.yaml"
    if not kustom_path.is_file():
        raise ValueError(f"Missing {kustom_path}")

    kustom = yaml.safe_load(kustom_path.read_text(encoding="utf-8"))
    resources = kustom.get("resources", [])
    if not resources:
        raise ValueError("kustomization.yaml defines no resources")

    for res_name in resources:
        res_path = k8s_dir / res_name
        if not res_path.is_file():
            raise ValueError(f"kustomization.yaml references missing file: {res_name}")
        docs = [doc for doc in yaml.safe_load_all(res_path.read_text(encoding="utf-8")) if doc is not None]
        if not docs:
            raise ValueError(f"Manifest {res_name} contains no YAML documents")
        for doc in docs:
            if not isinstance(doc, dict) or "apiVersion" not in doc or "kind" not in doc or "metadata" not in doc:
                raise ValueError(f"Invalid Kubernetes resource in {res_name}: {doc!r}")

    # Ensure 04_caller_config.yml does not contain plaintext passwords
    cfg_text = (k8s_dir / "04_caller_config.yml").read_text(encoding="utf-8")
    for forbidden_secret in ("asterisk_pass", "db_password", "twilio_auth_token"):
        if forbidden_secret in cfg_text:
            raise ValueError(f"04_caller_config.yml must not contain plaintext {forbidden_secret}")

    return [str(r) for r in resources]


def validate_helm_chart(helm_dir: Path) -> dict[str, object]:
    chart_yaml = helm_dir / "Chart.yaml"
    values_yaml = helm_dir / "values.yaml"
    templates_dir = helm_dir / "templates"
    if not chart_yaml.is_file() or not values_yaml.is_file() or not templates_dir.is_dir():
        raise ValueError(f"Incomplete Helm chart directory: {helm_dir}")

    chart_meta = yaml.safe_load(chart_yaml.read_text(encoding="utf-8"))
    values_meta = yaml.safe_load(values_yaml.read_text(encoding="utf-8"))
    if chart_meta.get("apiVersion") != "v2" or chart_meta.get("name") != "py-phone-caller":
        raise ValueError(f"Invalid Chart.yaml metadata: {chart_meta!r}")
    if "services" not in values_meta or "openalertd" not in values_meta:
        raise ValueError("values.yaml missing required sections")

    required_templates = (
        "_helpers.tpl",
        "configmap.yaml",
        "secret.yaml",
        "asterisk-endpoint.yaml",
        "postgresql.yaml",
        "redis.yaml",
        "microservices.yaml",
        "openalertd.yaml",
        "gateway.yaml",
        "ingress.yaml",
        "NOTES.txt",
    )
    for tpl in required_templates:
        if not (templates_dir / tpl).is_file():
            raise ValueError(f"Helm chart missing template: templates/{tpl}")

    return chart_meta


def build_all(args: argparse.Namespace) -> dict[str, object]:
    repo_root = Path(__file__).resolve().parents[3]
    k8s_dir = repo_root / "deploy" / "k8s"
    helm_dir = repo_root / "deploy" / "helm" / "py-phone-caller"

    resources = validate_k8s_manifests(k8s_dir)
    chart_meta = validate_helm_chart(helm_dir)
    version = str(chart_meta["version"])

    out_dir = Path(args.output_dir).resolve() if args.output_dir else repo_root / "dist" / "k8s"
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        raise ValueError(f"Output directory {out_dir} is not empty; pass --force or a new --output-dir")

    out_dir.mkdir(parents=True, exist_ok=True)
    if args.force:
        for existing in out_dir.glob("*"):
            if existing.is_file():
                existing.unlink()

    helm_archive = out_dir / f"py-phone-caller-{version}.tgz"
    helm_sha = write_deterministic_tgz(helm_dir, "py-phone-caller", helm_archive)

    manifests_archive = out_dir / f"py-phone-caller-k8s-manifests-v{version}.tar.gz"
    manifests_sha = write_deterministic_tgz(k8s_dir, f"py-phone-caller-k8s-v{version}", manifests_archive)

    artifacts = [
        {"filename": helm_archive.name, "sha256": helm_sha, "type": "helm-chart"},
        {"filename": manifests_archive.name, "sha256": manifests_sha, "type": "k8s-manifests"},
    ]
    checksum_lines = [f"{a['sha256']}  {a['filename']}" for a in sorted(artifacts, key=lambda x: x["filename"])]
    (out_dir / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "version": version,
        "kustomize_resources": resources,
        "artifacts": artifacts,
    }
    (out_dir / "release.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Packaged Helm chart and Kubernetes manifests in {out_dir}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", help="Output directory (default: dist/k8s)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing output files")
    args = parser.parse_args()
    try:
        build_all(args)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.exit(1, f"Kubernetes packaging error: {error}\n")


if __name__ == "__main__":
    main()
