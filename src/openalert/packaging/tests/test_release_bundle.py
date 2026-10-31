"""Offline contract fixtures; no daemon, service or hardware is exercised."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


PACKAGING = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("release_bundle", PACKAGING / "release_bundle.py")
RELEASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RELEASE)


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix=".test-bundle-", dir=PACKAGING / "tests")
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.binary = self.root / "fixture"
        self.target = f"{platform.machine()}-unknown-linux-gnu"
        self.assertIn(self.target, RELEASE.TARGETS, "Run native fixtures on AMD64 or ARM64 Linux")
        subprocess.run(["cc", "-x", "c", "-o", str(self.binary), "-"],
                       input="int main(void) { return 99; }\n", text=True, check=True)

    def build(self, *extra, success=True):
        result = subprocess.run(
            ["bash", str(PACKAGING / "build_release_bundle.sh"), "--binary", str(self.binary),
             "--target", self.target, "--source-revision", "a" * 40,
             "--rustc-version", RELEASE.PINNED_RUST_VERSION,
             "--build-baseline", 'fixture OS "quoted"', "--output-dir", str(self.root / "dist"), *extra],
            text=True, capture_output=True, env={**os.environ, "PYTHON": sys.executable},
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def test_bundle_contents_metadata_checksum_and_permissions(self):
        self.build()
        archive, = (self.root / "dist").glob("*.tar.gz")
        expected = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(Path(f"{archive}.sha256").read_text(), f"{expected}  {archive.name}\n")
        with tarfile.open(archive) as bundle:
            prefix = archive.name.removesuffix(".tar.gz")
            metadata = json.load(bundle.extractfile(f"{prefix}/release.json"))
            self.assertEqual(metadata["schema_version"], 1)
            self.assertEqual(metadata["target"], self.target)
            self.assertEqual(metadata["architecture"], RELEASE.TARGETS[self.target][1])
            self.assertEqual(metadata["source_revision"], "a" * 40)
            self.assertEqual(metadata["build"]["baseline"], 'fixture OS "quoted"')
            self.assertIsNone(metadata["build"]["cargo_locked"])
            self.assertTrue(metadata["build"]["prebuilt"])
            self.assertRegex(metadata["runtime"]["minimum_glibc"], r"^\d+\.\d+")
            self.assertIn("libc.so.6", metadata["runtime"]["needed_libraries"])
            self.assertEqual(metadata["binary"]["sha256"], hashlib.sha256(self.binary.read_bytes()).hexdigest())
            for asset in ("bin/openalertd", "install.sh", "verify_install.sh"):
                self.assertEqual(bundle.getmember(f"{prefix}/{asset}").mode, 0o755)
            for asset in ("templates", "profiles", "systemd/openalertd.service", "wifi-ap/setup_wifi_ap.sh",
                          "README.md", "openalertd.toml.example"):
                bundle.getmember(f"{prefix}/{asset}")

    def test_wrong_architecture_is_rejected_before_output(self):
        other = next(target for target in RELEASE.TARGETS if target != self.target)
        result = self.build("--target", other, success=False)
        self.assertIn("architecture does not match", result.stderr)
        self.assertFalse((self.root / "dist").exists())

    def test_malformed_binary_is_rejected(self):
        self.binary.write_bytes(b"not an ELF executable\n")
        self.assertIn("ELF64", self.build(success=False).stderr)

    def test_relocatable_object_is_rejected(self):
        data = bytearray(self.binary.read_bytes())
        struct.pack_into("<H", data, 16, 1)
        self.binary.write_bytes(data)
        self.assertIn("relocatable", self.build(success=False).stderr)

    def test_incomplete_prebuilt_provenance_is_rejected(self):
        for option in ("--source-revision", "--build-baseline", "--rustc-version"):
            with self.subTest(option=option):
                self.build(option, "", success=False)
        self.build("--source-revision", "not-a-commit", success=False)
        self.build("--rustc-version", "1.0.0", success=False)

    def test_prebuilt_requires_explicit_target(self):
        result = subprocess.run([sys.executable, str(PACKAGING / "release_bundle.py"),
                                 "--binary", str(self.binary)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--target is required", result.stderr)

    def test_existing_output_is_not_overwritten(self):
        self.build()
        archive, = (self.root / "dist").glob("*.tar.gz")
        original = archive.read_bytes()
        self.assertIn("already exists", self.build(success=False).stderr)
        self.assertEqual(original, archive.read_bytes())

    def test_truncated_archive_fails_integrity(self):
        self.build()
        archive, = (self.root / "dist").glob("*.tar.gz")
        expected = Path(f"{archive}.sha256").read_text().split()[0]
        archive.write_bytes(archive.read_bytes()[:100])
        self.assertNotEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), expected)
        with self.assertRaises((tarfile.TarError, EOFError)):
            with tarfile.open(archive) as bundle:
                bundle.getmembers()

    def test_source_build_is_locked_and_target_explicit(self):
        target_dir = self.root / "target"
        compiled = target_dir / self.target / "release/openalertd"
        compiled.parent.mkdir(parents=True)
        shutil.copyfile(self.binary, compiled)
        from argparse import Namespace
        args = Namespace(binary=None, target=self.target, source_revision=None, rustc_version=None,
                         build_baseline="fixture", toolchain="stable", target_dir=str(target_dir),
                         output_dir=str(self.root / "dist"))
        binary_output = {
            option: RELEASE.output("readelf", "--wide", option, str(compiled))
            for option in ("--program-headers", "--dynamic", "--version-info")
        }

        def fixture_output(*command, **kwargs):
            if command[0] == "rustup":
                return f"rustc {RELEASE.PINNED_RUST_VERSION} (fixture)"
            if command[:2] == ("git", "rev-parse"):
                return "a" * 40
            if command[:2] == ("git", "status"):
                return ""
            return binary_output[command[2]]

        with patch.object(RELEASE, "output", side_effect=fixture_output), \
                patch.object(RELEASE.subprocess, "run") as run:
            RELEASE.build_bundle(args)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertIn("--locked", command)
        self.assertEqual(command[command.index("--target") + 1], self.target)
        self.assertEqual(command[command.index("--target-dir") + 1], str(target_dir))


if __name__ == "__main__":
    unittest.main()