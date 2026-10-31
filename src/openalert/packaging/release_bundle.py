"""Build the versioned native release contract without executing supplied binaries."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
import tomllib


PINNED_RUST_VERSION = "1.99.1"
TARGETS = {
    "x86_64-unknown-linux-gnu": ("x86_64", "amd64", 62, "/lib64/ld-linux-x86-64.so.2"),
    "aarch64-unknown-linux-gnu": ("aarch64", "arm64", 183, "/lib/ld-linux-aarch64.so.1"),
}


def output(*command, cwd=None):
    return subprocess.check_output(command, cwd=cwd, text=True, env={**os.environ, "LC_ALL": "C"}).strip()


def inspect_binary(binary, target):
    with binary.open("rb") as source:
        header = source.read(64)
    if len(header) != 64 or header[:7] != b"\x7fELF\x02\x01\x01":
        raise ValueError("Expected a complete little-endian ELF64 binary")
    kind, machine = struct.unpack_from("<HH", header, 16)
    if kind not in (2, 3):
        raise ValueError("ELF must be an executable, not a relocatable object")
    if machine != TARGETS[target][2]:
        raise ValueError(f"Binary architecture does not match target {target}")
    segments = output("readelf", "--wide", "--program-headers", str(binary))
    match = re.search(r"Requesting program interpreter: ([^\]]+)\]", segments)
    if not match or match[1] != TARGETS[target][3]:
        raise ValueError("Binary must use the target GNU/Linux dynamic interpreter")
    dynamic = output("readelf", "--wide", "--dynamic", str(binary))
    versions = output("readelf", "--wide", "--version-info", str(binary))
    glibc = set(re.findall(r"\bGLIBC_(\d+\.\d+(?:\.\d+)?)\b", versions))
    if not glibc:
        raise ValueError("Cannot determine minimum glibc runtime")
    if "GLIBC_ABI_DT_RELR" in versions:
        glibc.add("2.36")
    return {
        "libc": "glibc",
        "minimum_glibc": max(glibc, key=lambda value: tuple(map(int, value.split(".")))),
        "interpreter": match[1],
        "needed_libraries": sorted(set(re.findall(r"\(NEEDED\).*\[([^\]]+)\]", dynamic))),
    }


def build_bundle(args):
    packaging = Path(__file__).resolve().parent
    crate = packaging.parent
    version = tomllib.loads((crate / "Cargo.toml").read_text())["package"]["version"]
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]*", version):
        raise ValueError("Unsafe package version")
    if args.binary and not args.target:
        raise ValueError("--target is required for a prebuilt binary")
    target = args.target or f"{platform.machine()}-unknown-linux-gnu"
    if target not in TARGETS:
        raise ValueError(f"Unsupported target: {target}")
    for asset in ("templates", "config/profiles"):
        if not (crate / asset).is_dir() or not any((crate / asset).iterdir()):
            raise ValueError(f"Missing release assets: {asset}")
    dirty = None
    if args.binary:
        if not args.source_revision or not re.fullmatch(r"[0-9a-f]{40,64}", args.source_revision):
            raise ValueError("Prebuilt binary requires --source-revision (full Git object ID)")
        if not args.build_baseline or not args.rustc_version:
            raise ValueError("Prebuilt binary requires --build-baseline and --rustc-version provenance")
        binary = Path(args.binary).resolve()
        revision = args.source_revision
        rustc_version = args.rustc_version
        baseline = args.build_baseline
        if rustc_version != PINNED_RUST_VERSION:
            raise ValueError(f"Prebuilt provenance requires pinned Rust {PINNED_RUST_VERSION}")
    else:
        rustc_version = output("rustup", "run", args.toolchain, "rustc", "--version").split()[1]
        if rustc_version != PINNED_RUST_VERSION:
            raise ValueError(f"Build requires pinned Rust {PINNED_RUST_VERSION}, got {rustc_version}")
        revision = output("git", "rev-parse", "HEAD", cwd=crate)
        dirty = bool(output("git", "status", "--porcelain", "--untracked-files=normal", "--", ".", cwd=crate))
        baseline = args.build_baseline or platform.freedesktop_os_release()["PRETTY_NAME"]
        target_dir = Path(args.target_dir).resolve() if args.target_dir else crate / "target"
        subprocess.run(
            ["rustup", "run", args.toolchain, "cargo", "build", "--locked", "--release",
             "--target", target, "--target-dir", str(target_dir)], cwd=crate, check=True,
        )
        binary = target_dir / target / "release/openalertd"
    runtime = inspect_binary(binary, target)
    with binary.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    arch, architecture, _, _ = TARGETS[target]
    name = f"openalertd-v{version}-linux-{arch}"
    destination = Path(args.output_dir).resolve() if args.output_dir else crate / "dist"
    archive = destination / f"{name}.tar.gz"
    checksum = destination / f"{name}.tar.gz.sha256"
    if archive.exists() or checksum.exists():
        raise ValueError("Release output already exists; use a new --output-dir to preserve existing artifacts")
    metadata = {
        "schema_version": 1, "package": "openalertd", "version": version,
        "release_id": f"{version}-{revision[:12]}-{architecture}-{digest[:12]}",
        "source_revision": revision, "source_dirty": dirty,
        "target": target, "architecture": architecture,
        "build": {"rustc_version": rustc_version, "baseline": baseline,
                  "prebuilt": bool(args.binary), "cargo_locked": None if args.binary else True},
        "runtime": runtime,
        "binary": {"path": "bin/openalertd", "sha256": digest},
    }
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bundle-", dir=destination) as work:
        staging = Path(work) / name
        (staging / "bin").mkdir(parents=True)
        shutil.copyfile(binary, staging / "bin/openalertd")
        (staging / "bin/openalertd").chmod(0o755)
        for source, relative in ((crate / "templates", "templates"),
                                 (crate / "config/profiles", "profiles"),
                                 (packaging / "systemd", "systemd"),
                                 (packaging / "wifi-ap", "wifi-ap")):
            shutil.copytree(source, staging / relative)
        for asset in ("install.sh", "verify_install.sh", "openalertd.toml.example", "README.md"):
            shutil.copyfile(packaging / asset, staging / asset)
            (staging / asset).chmod(0o755 if asset.endswith(".sh") else 0o644)
        (staging / "release.json").write_text(json.dumps(metadata, indent=2) + "\n")
        temporary_archive = Path(work) / archive.name
        with tarfile.open(temporary_archive, "w:gz") as bundle:
            bundle.add(staging, arcname=name)
        with temporary_archive.open("rb") as source:
            archive_hash = hashlib.file_digest(source, "sha256").hexdigest()
        temporary_checksum = Path(work) / checksum.name
        temporary_checksum.write_text(f"{archive_hash}  {archive.name}\n")
        temporary_archive.replace(archive)
        temporary_checksum.replace(checksum)
    print(f"Release: {archive}\nSHA-256: {archive_hash}\nIdentity: {metadata['release_id']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--binary", help="Package this prebuilt binary without executing it")
    parser.add_argument("--source-revision", help="Prebuilt binary's full source commit")
    parser.add_argument("--build-baseline", help="Build OS/image/sysroot provenance (required for prebuilt)")
    parser.add_argument("--rustc-version", help="Producer-attested compiler version for prebuilt binary")
    parser.add_argument("--toolchain", default=PINNED_RUST_VERSION,
                        help="Installed rustup toolchain; its compiler must match the pin")
    parser.add_argument("--target-dir", help="Cargo output directory (source builds only)")
    parser.add_argument("--output-dir", help="Fresh release directory (default: crate/dist)")
    args = parser.parse_args()
    try:
        build_bundle(args)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Release error: {error}\n")


if __name__ == "__main__":
    main()