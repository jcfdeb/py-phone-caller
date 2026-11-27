"""Tests for native Linux (.deb and .rpm) package builder."""

from __future__ import annotations

from argparse import Namespace
import gzip
import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = REPO_ROOT / "deploy" / "packaging" / "linux" / "build_linux_packages.py"

SPEC = importlib.util.spec_from_file_location("build_linux_packages", BUILDER_PATH)
LINUX_BUILDER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(LINUX_BUILDER)


class LinuxPackagingTests(unittest.TestCase):
    def test_deb_and_rpm_packages_build_and_validate_headers(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".test-linux-pkg-") as tmp:
            tmp_path = Path(tmp)
            fake_bin = tmp_path / "openalertd"
            fake_bin.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 57)
            fake_bin.chmod(0o755)

            out_dir = tmp_path / "dist"
            args = Namespace(
                version="1.1.0",
                release="1",
                arch="x86_64",
                openalert_binary=str(fake_bin),
                output_dir=str(out_dir),
                force=False,
            )
            manifest = LINUX_BUILDER.build_all(args)
            self.assertEqual(len(manifest["packages"]), 4)
            self.assertTrue((out_dir / "SHA256SUMS").is_file())
            self.assertTrue((out_dir / "release.json").is_file())

            # Validate .deb archives with `ar t` and inspect control.tar.gz + data.tar.gz
            for deb_name in ("py-phone-caller_1.1.0-1_all.deb", "openalertd_1.1.0-1_amd64.deb"):
                deb_path = out_dir / deb_name
                self.assertTrue(deb_path.is_file())
                raw = deb_path.read_bytes()
                self.assertTrue(raw.startswith(b"!<arch>\n"))

                ar_out = subprocess.check_output(["ar", "t", str(deb_path)], text=True).splitlines()
                self.assertEqual(ar_out, ["debian-binary", "control.tar.gz", "data.tar.gz"])

                data_tar_bytes = subprocess.check_output(["ar", "p", str(deb_path), "data.tar.gz"])
                with tarfile.open(fileobj=io.BytesIO(data_tar_bytes), mode="r:gz") as tf:
                    members = set(tf.getnames())
                    if deb_name.startswith("py-phone-caller"):
                        self.assertIn("./etc/py-phone-caller/settings.toml", members)
                        self.assertIn("./lib/systemd/system/py-phone-caller.target", members)
                        self.assertIn("./lib/systemd/system/asterisk-caller.service", members)
                        self.assertIn("./opt/py-phone-caller/py-phone-caller/config/py-phone-caller.env", members)
                        self.assertFalse(any(m.startswith("./opt/py-phone-caller/src/") for m in members))
                        pyproject_member = tf.extractfile("./opt/py-phone-caller/pyproject.toml")
                        self.assertIsNotNone(pyproject_member)
                        pyproject_text = pyproject_member.read().decode("utf-8")
                        self.assertIn('"py-phone-caller/asterisk_caller"', pyproject_text)
                        self.assertNotIn('"src/asterisk_caller"', pyproject_text)
                        self.assertFalse(any(m.endswith(".secrets.toml") for m in members))
                    else:
                        self.assertIn("./usr/local/bin/openalertd", members)
                        self.assertIn("./etc/openalertd/openalertd.toml", members)
                        self.assertIn("./lib/systemd/system/openalertd.service", members)

            # Validate .rpm archives magic lead, signature header, main header, and cpio.gz payload
            for rpm_name in ("py-phone-caller-1.1.0-1.noarch.rpm", "openalertd-1.1.0-1.x86_64.rpm"):
                rpm_path = out_dir / rpm_name
                self.assertTrue(rpm_path.is_file())
                raw = rpm_path.read_bytes()
                self.assertEqual(raw[:4], b"\xed\xab\xee\xdb")  # RPMv4 Lead magic
                self.assertEqual(raw[96:100], b"\x8e\xad\xe8\x01")  # Signature Header magic
                # Locate gzip stream (1f 8b 08) inside RPM and verify cpio trailer
                gz_idx = raw.find(b"\x1f\x8b\x08")
                self.assertGreater(gz_idx, 96)
                cpio_bytes = gzip.decompress(raw[gz_idx:])
                self.assertTrue(cpio_bytes.startswith(b"070701"))
                self.assertIn(b"TRAILER!!!\x00", cpio_bytes)

    def test_deterministic_deb_and_rpm_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".test-linux-det-") as tmp:
            tmp_path = Path(tmp)
            fake_bin = tmp_path / "openalertd"
            fake_bin.write_bytes(b"\x7fELF\x02\x01\x01" + b"\x00" * 57)

            m1 = LINUX_BUILDER.build_all(
                Namespace(
                    version="1.1.0",
                    release="1",
                    arch="x86_64",
                    openalert_binary=str(fake_bin),
                    output_dir=str(tmp_path / "d1"),
                    force=False,
                )
            )
            m2 = LINUX_BUILDER.build_all(
                Namespace(
                    version="1.1.0",
                    release="1",
                    arch="x86_64",
                    openalert_binary=str(fake_bin),
                    output_dir=str(tmp_path / "d2"),
                    force=False,
                )
            )
            self.assertEqual(m1["packages"], m2["packages"])


if __name__ == "__main__":
    unittest.main()
