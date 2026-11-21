"""Tests for the deterministic Ansible release bundle builder."""

from __future__ import annotations

from argparse import Namespace
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


TESTS_DIR = Path(__file__).resolve().parent
ANSIBLE_DIR = TESTS_DIR.parent
PACKAGING_DIR = ANSIBLE_DIR / "packaging"

SPEC = importlib.util.spec_from_file_location(
    "build_ansible_bundle",
    PACKAGING_DIR / "build_ansible_bundle.py",
)
BUNDLE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(BUNDLE)


class AnsibleBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = tempfile.TemporaryDirectory(prefix=".test-ansible-bundle-", dir=TESTS_DIR)
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)

    def _default_args(self, **overrides: object) -> Namespace:
        defaults = {
            "version": None,
            "source_revision": "a" * 40,
            "with_collections": False,
            "collections_dir": None,
            "install_collections": False,
            "output_dir": str(self.root / "dist"),
            "force": False,
        }
        defaults.update(overrides)
        return Namespace(**defaults)

    def test_bundle_contents_manifest_checksum_and_secret_exclusion(self) -> None:
        result = BUNDLE.build_bundle(self._default_args())
        archive: Path = result["archive"]
        checksum: Path = result["checksum"]
        self.assertTrue(archive.is_file())
        self.assertTrue(checksum.is_file())

        expected_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(checksum.read_text(encoding="utf-8"), f"{expected_sha}  {archive.name}\n")

        with tarfile.open(archive, "r:gz") as tar:
            names = set(tar.getnames())
            prefix = archive.name.removesuffix(".tar.gz")
            self.assertIn(f"{prefix}/release.json", names)
            self.assertIn(f"{prefix}/site.yml", names)
            self.assertIn(f"{prefix}/verify.yml", names)
            self.assertIn(f"{prefix}/requirements.yml", names)
            for role in BUNDLE.REQUIRED_ROLES:
                self.assertIn(f"{prefix}/roles/{role}/tasks/main.yml", names)
            for pb in BUNDLE.REQUIRED_PLAYBOOKS:
                self.assertIn(f"{prefix}/{pb}", names)

            # Verify live inventories and credentials are strictly excluded
            for member_name in names:
                self.assertNotIn("/credentials/", member_name)
                self.assertFalse(member_name.endswith("/.vault_pass"))
                self.assertFalse(member_name.endswith("/inventory"))
                self.assertFalse(member_name.endswith("/inventory.ini"))
                self.assertFalse(member_name.endswith("/show-credentials.sh"))
                if member_name.endswith("secrets.yml"):
                    self.assertTrue(member_name.endswith("secrets.yml.example"))

            # Verify release.json per-file SHA-256 digests match archived files
            rel_member = tar.extractfile(f"{prefix}/release.json")
            self.assertIsNotNone(rel_member)
            metadata = json.loads(rel_member.read().decode("utf-8"))
            self.assertEqual(metadata["schema_version"], 1)
            self.assertEqual(metadata["package"], "py-phone-caller-ansible")
            self.assertFalse(metadata["bundled_collections"])
            self.assertEqual(metadata["source_revision"], "a" * 40)

            for rel_path, file_sha in metadata["files"].items():
                extracted = tar.extractfile(f"{prefix}/{rel_path}")
                self.assertIsNotNone(extracted, f"Missing {rel_path} in archive")
                actual_sha = hashlib.sha256(extracted.read()).hexdigest()
                self.assertEqual(actual_sha, file_sha, f"Digest mismatch for {rel_path}")

    def test_deterministic_reproducible_archive(self) -> None:
        res1 = BUNDLE.build_bundle(self._default_args(output_dir=str(self.root / "dist1")))
        res2 = BUNDLE.build_bundle(self._default_args(output_dir=str(self.root / "dist2")))
        self.assertEqual(res1["sha256"], res2["sha256"])
        self.assertEqual(res1["archive"].read_bytes(), res2["archive"].read_bytes())

    def test_existing_output_is_not_overwritten_without_force(self) -> None:
        res = BUNDLE.build_bundle(self._default_args())
        original_bytes = res["archive"].read_bytes()
        with self.assertRaisesRegex(ValueError, "already exists"):
            BUNDLE.build_bundle(self._default_args())
        self.assertEqual(res["archive"].read_bytes(), original_bytes)

        # With --force, overwrite succeeds
        forced = BUNDLE.build_bundle(self._default_args(force=True))
        self.assertEqual(forced["sha256"], res["sha256"])

    def test_offline_collections_bundling_and_version_guard(self) -> None:
        fake_cols = self.root / "collections"
        pinned = BUNDLE.parse_pinned_collections(ANSIBLE_DIR / "requirements.yml")
        for fqcn, version in pinned.items():
            ns, name = fqcn.split(".", 1)
            col_dir = fake_cols / "ansible_collections" / ns / name
            col_dir.mkdir(parents=True)
            (col_dir / "MANIFEST.json").write_text(
                json.dumps({"collection_info": {"namespace": ns, "name": name, "version": version}}),
                encoding="utf-8",
            )
            (col_dir / "README.md").write_text(f"# {fqcn}\n", encoding="utf-8")

        res = BUNDLE.build_bundle(
            self._default_args(
                with_collections=True,
                collections_dir=str(fake_cols),
                output_dir=str(self.root / "dist-offline"),
            )
        )
        self.assertTrue(res["archive"].name.endswith("-offline.tar.gz"))
        self.assertTrue(res["metadata"]["bundled_collections"])
        self.assertEqual(set(res["metadata"]["collections"].keys()), set(pinned.keys()))

        # Version mismatch must fail closed
        bad_ns, bad_name = next(iter(pinned)).split(".", 1)
        (fake_cols / "ansible_collections" / bad_ns / bad_name / "MANIFEST.json").write_text(
            json.dumps({"collection_info": {"namespace": bad_ns, "name": bad_name, "version": "0.0.1"}}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "version mismatch"):
            BUNDLE.build_bundle(
                self._default_args(
                    with_collections=True,
                    collections_dir=str(fake_cols),
                    output_dir=str(self.root / "dist-bad"),
                )
            )

    def test_verify_staged_tree_rejects_secrets_and_symlinks(self) -> None:
        staging = self.root / "stage"
        BUNDLE.build_bundle(self._default_args())
        archive, = (self.root / "dist").glob("*.tar.gz")
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(staging, filter="data")
        extracted_root, = staging.iterdir()

        # Inject a forbidden secret file
        secret_file = extracted_root / "on-vm_py-phone-caller" / ".vault_pass"
        secret_file.write_text("secret\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Forbidden secret"):
            BUNDLE.verify_staged_tree(extracted_root)
        secret_file.unlink()

        # Inject a symlink
        symlink_path = extracted_root / "roles" / "bad_link"
        symlink_path.symlink_to(extracted_root / "site.yml")
        with self.assertRaisesRegex(ValueError, "Symlinks are not permitted"):
            BUNDLE.verify_staged_tree(extracted_root)

    def test_shell_wrapper_execution(self) -> None:
        out_dir = self.root / "shell-dist"
        proc = subprocess.run(
            [
                "bash",
                str(PACKAGING_DIR / "build_ansible_bundle.sh"),
                "--source-revision",
                "b" * 40,
                "--output-dir",
                str(out_dir),
            ],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "PYTHON": sys.executable},
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Release:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
