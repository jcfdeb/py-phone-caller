"""Local unit/contract tests only: no host preparation, model inference or mirror qualification.

Synthetic payloads exercise copying and the actual role's contract, not a real
runtime/cache/model. Signing tests inspect command construction; they do not
claim an apt-ftparchive/GPG integration or install local packages.
"""

import contextlib
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import yaml
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tests/files/prepare_airgap_fixture.py"
CHECKER = ROOT / "deploy/ansible/roles/stack_airgap/library/stack_airgap_check.py"
module_spec = importlib.util.spec_from_file_location("prepare_airgap_fixture", HELPER)
preparation = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(preparation)
checker = preparation.load_checker(CHECKER)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".airgap-unit-", dir=ROOT / "tests")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def file(self, relative, content=b"unit-test payload; not a real offline artifact\n", mode=0o644):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(mode)
        return path

    def source(self):
        self.file("source/pyproject.toml", b'[tool.uv]\nbuild-constraint-dependencies = ["cython==3.0.12"]\n')
        self.file("source/uv.lock")
        self.file("source/" + preparation.SOURCE_REQUIRED[2])
        self.file("source/LICENSE")
        self.file("source/assets/a file.txt")
        (self.root / "source/link").symlink_to("assets/a file.txt")
        (self.root / "source/linked-assets").symlink_to("assets", target_is_directory=True)
        return self.root / "source"

    def specification(self):
        self.source()
        self.file("tools/uv", mode=0o755)
        self.file("runtime/bin/python3.14", mode=0o755)
        self.file("runtime/lib/runtime-data")
        self.file("runtime/lib/python3.14/venv/__init__.py")
        self.file("uv-cache/archive-v0/data")
        (self.root / "uv-cache/wheels-v5").mkdir()
        (self.root / "uv-cache/wheels-v5/link").symlink_to("../archive-v0/data")
        self.file("cargo/bin/rustup", mode=0o755)
        for name in ("cargo", "rustc"):
            (self.root / "cargo/bin" / name).symlink_to("rustup")
        self.file("cargo/registry/cache/crate.data")
        self.file("rustup/toolchains/1.88.0-x86_64-unknown-linux-gnu/bin/rustc", mode=0o755)
        self.file("rustup/toolchains/1.88.0-x86_64-unknown-linux-gnu/lib/library.data")
        self.file("models/voice.onnx")
        self.file("models/voice.onnx.json", b'{"audio": {"sample_rate": 22050}}')
        result = {
            "source_root": str(self.root / "source"), "output_root": str(self.root / "output"),
            "uv_binary": str(self.root / "tools/uv"), "python_root": str(self.root / "runtime"),
            "uv_cache": str(self.root / "uv-cache"), "cargo_home": str(self.root / "cargo"),
            "rustup_home": str(self.root / "rustup"), "rust_toolchain": "1.88.0-x86_64-unknown-linux-gnu",
            "architecture": "x86_64", "python_version": "3.14.5", "uv_version": "0.11.15",
            "build_constraints": ["cython==3.0.12"], "piper_language": "en_US-lessac-medium",
            "piper_model": str(self.root / "models/voice.onnx"),
            "piper_config": str(self.root / "models/voice.onnx.json"),
        }
        for key in ("piper_model", "piper_config"):
            result[key + "_sha256"] = "sha256:" + hashlib.sha256(Path(result[key]).read_bytes()).hexdigest()
        return result

    def test_source_manifest_roundtrip_complete_files_and_links(self):
        source = self.source()
        output = self.root / "manifest.json"
        checksum = preparation.validate_manifest(checker, source, output, "source")
        manifest = checker.verify_manifest(source, output, checksum)
        self.assertEqual(set(manifest["files"]), {*preparation.SOURCE_REQUIRED, "LICENSE", "assets/a file.txt"})
        self.assertEqual(manifest["symlinks"], {"link": "assets/a file.txt", "linked-assets": "assets"})
        self.assertEqual(checker.source_build_constraints(source), ["cython==3.0.12"])

    def test_manifest_detects_unlisted_and_modified_files(self):
        source = self.source()
        output = self.root / "manifest.json"
        checksum = preparation.validate_manifest(checker, source, output, "source")
        extra = self.file("source/extra")
        with self.assertRaisesRegex(ValueError, "Unlisted file"):
            checker.verify_manifest(source, output, checksum)
        extra.unlink()
        self.file("source/LICENSE", b"changed")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            checker.verify_manifest(source, output, checksum)

    def test_manifest_detects_changed_links(self):
        source = self.source()
        output = self.root / "manifest.json"
        checksum = preparation.validate_manifest(checker, source, output, "source")
        (source / "link").unlink()
        (source / "link").symlink_to("LICENSE")
        with self.assertRaisesRegex(ValueError, "altered symlink"):
            checker.verify_manifest(source, output, checksum)

    def test_manifest_cannot_be_inside_tree_or_overwritten(self):
        source = self.source()
        with self.assertRaisesRegex(ValueError, "outside"):
            preparation.validate_manifest(checker, source, source / "manifest.json", "source")
        output = self.root / "manifest.json"
        preparation.validate_manifest(checker, source, output, "source")
        before = output.read_bytes()
        with self.assertRaisesRegex(ValueError, "overwrite"):
            preparation.validate_manifest(checker, source, output, "source")
        self.assertEqual(output.read_bytes(), before)

    def test_safe_recursive_copy_preserves_links_and_normalizes_modes(self):
        source = self.source()
        executable = self.file("source/script", mode=0o6777)
        (source / "LICENSE").chmod(0o666)
        (source / "assets").chmod(0o777)
        destination = self.root / "copied"
        preparation.copy_tree(source, destination, source_tree=True)
        self.assertEqual(preparation.inventory(source), preparation.inventory(destination))
        self.assertTrue((destination / "linked-assets").is_symlink())
        self.assertEqual(stat.S_IMODE((destination / "script").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((destination / "LICENSE").stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE((destination / "assets").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(executable.stat().st_mode), 0o6777)

    def test_symlink_escape_absolute_dangling_and_cycle_rejected(self):
        source = self.source()
        self.file("outside")
        for target in ("../outside", str(source / "LICENSE"), "missing", "bad"):
            with self.subTest(target=target):
                (source / "bad").symlink_to(target)
                with self.assertRaises((ValueError, OSError, RuntimeError)):
                    preparation.inventory(source)
                (source / "bad").unlink()

    def test_symlinked_root_and_ancestor_rejected(self):
        source = self.source()
        (self.root / "alias").symlink_to(source)
        for path in (self.root / "alias", self.root / "alias/assets"):
            with self.assertRaisesRegex(ValueError, "symlinked"):
                preparation.inventory(path)

    def test_secret_and_live_state_paths_rejected(self):
        for name in (".git/config", ".env", ".env.production", "src/config/.secrets.toml",
                     "src/config/settings.toml", ".ssh/id_ed25519", "credentials.toml",
                     "secret.yaml", "tls/server.key", ".venv/bin/python", "runtime/pyvenv.cfg",
                     "deploy/ansible/group_vars/all.yml"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "forbidden"):
                preparation.guard_name(name, source=True)
        preparation.guard_name("rustup/settings.toml")
        preparation.guard_name("package/certifi/cacert.pem")

    def test_private_key_content_rejected_even_with_innocent_name(self):
        self.file("input/data", b"-----BEGIN OPENSSH PRIVATE KEY-----\n")
        with self.assertRaisesRegex(ValueError, "Private key"):
            preparation.inventory(self.root / "input")

    def test_private_key_guard_does_not_reject_quoted_test_code(self):
        self.file("input/test_guard.py", b'header = "-----BEGIN OPENSSH PRIVATE KEY-----"\n')
        self.assertIn("test_guard.py", preparation.inventory(self.root / "input")["files"])

    def test_special_file_rejected(self):
        source = self.source()
        os.mkfifo(source / "fifo")
        with self.assertRaisesRegex(ValueError, "Special file"):
            preparation.inventory(source)

    def test_stage_bundle_roundtrip_uses_real_validator_not_runtime_qualification(self):
        specification = self.specification()
        pins = preparation.validate_inputs(specification, checker)
        bundle = self.root / "bundle"
        preparation.stage_bundle(specification, bundle, pins)
        manifest = preparation.inventory(bundle)
        manifest.update({key: specification[key] for key in ("architecture", "python_version", "uv_version")})
        output = self.root / "bundle-manifest.json"
        preparation.write_json(output, manifest)
        checksum = "sha256:" + checker.digest(output)
        # Unit trees deliberately do not claim production root ownership.
        checked = checker.verify_manifest(bundle, output, checksum, root_owned=False)
        checker.verify_bundle(bundle, checked, "x86_64", "3.14.5", "0.11.15", specification["rust_toolchain"],
                              preparation.model_config(bundle, specification), pins)
        self.assertTrue((bundle / "cargo/bin/cargo").is_symlink())
        self.assertEqual((bundle / "build-constraints.txt").read_text(), "cython==3.0.12\n")
        self.assertEqual((bundle / "models/piper/en_US-lessac-medium/en_US-lessac-medium.onnx").read_bytes(),
                         Path(specification["piper_model"]).read_bytes())
        for name in ("huggingface", "torch", "cache"):
            self.assertTrue((bundle / "models" / name).is_dir())

    def test_missing_inputs_report_checklist_without_creating_output(self):
        specification = self.specification()
        Path(specification["piper_model"]).unlink()
        (Path(specification["rustup_home"]) / "toolchains" / specification["rust_toolchain"] / "bin/rustc").unlink()
        with self.assertRaises(ValueError) as error:
            preparation.export_fixture(specification, checker)
        self.assertIn("checklist", str(error.exception))
        self.assertIn("voice.onnx", str(error.exception))
        self.assertIn("bin/rustc", str(error.exception))
        self.assertFalse(Path(specification["output_root"]).exists())

    def test_missing_spec_fields_are_listed(self):
        with self.assertRaisesRegex(ValueError, "build_constraints.*cargo_home.*piper_model"):
            preparation.validate_inputs({}, checker)

    def test_unpinned_source_and_disagreeing_pins_rejected(self):
        specification = self.specification()
        specification["build_constraints"] = ["cython==3.0.11"]
        with self.assertRaisesRegex(ValueError, "must match exact"):
            preparation.validate_inputs(specification, checker)
        for pins in ('["cython<3.1"]', '[]'):
            self.file("source/pyproject.toml", ("[tool.uv]\nbuild-constraint-dependencies = " + pins).encode())
            with self.assertRaisesRegex(ValueError, "exact"):
                preparation.validate_inputs(specification, checker)

    def test_wrong_or_missing_reviewed_model_digest_rejected(self):
        specification = self.specification()
        for digest in ("", "sha256:" + "0" * 64):
            specification["piper_model_sha256"] = digest
            with self.assertRaisesRegex(ValueError, "sha256|checksum mismatch"):
                preparation.validate_inputs(specification, checker)

    def test_empty_model_and_nonexecutable_tool_rejected(self):
        specification = self.specification()
        Path(specification["piper_model"]).write_bytes(b"")
        Path(specification["uv_binary"]).chmod(0o644)
        with self.assertRaises(ValueError) as error:
            preparation.validate_inputs(specification, checker)
        self.assertIn("voice.onnx", str(error.exception))
        self.assertIn("tools/uv", str(error.exception))

    def test_wrong_toolchain_pin_rejected(self):
        specification = self.specification()
        for pin in ("stable", "1.88.0-aarch64-unknown-linux-gnu"):
            specification["rust_toolchain"] = pin
            with self.assertRaisesRegex(ValueError, "architecture-matched"):
                preparation.validate_inputs(specification, checker)

    def test_missing_source_lock_rejected(self):
        source = self.source()
        (source / preparation.SOURCE_REQUIRED[2]).unlink()
        with self.assertRaisesRegex(ValueError, "Cargo.lock"):
            preparation.validate_manifest(checker, source, self.root / "manifest.json", "source")

    def test_root_owned_output_is_never_weakened_for_unit_tests(self):
        self.root.chmod(0o777)
        with self.assertRaisesRegex(ValueError, "root-owned"):
            preparation.new_output(self.root / "output", [])

    def test_bundle_manifest_helper_enforces_real_ownership_contract(self):
        specification = self.specification()
        bundle = self.root / "bundle"
        preparation.stage_bundle(specification, bundle, specification["build_constraints"])
        self.root.chmod(0o777)
        with self.assertRaisesRegex(ValueError, "ancestors must be root-owned"):
            preparation.validate_manifest(checker, bundle, self.root / "bundle.json", "bundle", specification)

    def test_model_changed_after_input_validation_is_not_exported_as_reviewed(self):
        specification = self.specification()
        pins = preparation.validate_inputs(specification, checker)
        Path(specification["piper_model"]).write_bytes(b"changed after review")
        with self.assertRaisesRegex(ValueError, "Reviewed model changed"):
            preparation.stage_bundle(specification, self.root / "bundle", pins)

    def test_optional_model_cache_is_copied_not_fabricated(self):
        specification = self.specification()
        self.file("hf-cache/hub/models--reviewed/snapshot/data")
        specification["model_caches"] = {"huggingface": str(self.root / "hf-cache")}
        pins = preparation.validate_inputs(specification, checker)
        bundle = self.root / "bundle"
        preparation.stage_bundle(specification, bundle, pins)
        self.assertEqual(preparation.inventory(bundle / "models/huggingface"),
                         preparation.inventory(self.root / "hf-cache"))

    def test_copy_refuses_an_input_that_changes_during_copy(self):
        incoming = self.file("input/data", b"original")
        original_copy = preparation.shutil.copyfileobj

        def changed_copy(source, destination):
            incoming.write_bytes(b"changed")
            return original_copy(source, destination)

        with patch.object(preparation.shutil, "copyfileobj", side_effect=changed_copy):
            with self.assertRaisesRegex(ValueError, "changed while copying"):
                preparation.copy_file(incoming, self.root / "output/data")

    def test_existing_output_never_replaced(self):
        sentinel = self.file("output/sentinel")
        with self.assertRaisesRegex(ValueError, "overwrite"):
            preparation.new_output(self.root / "output", [])
        self.assertTrue(sentinel.is_file())

    def test_authorization_gate_precedes_reading_spec_or_host_details(self):
        with patch.object(preparation.platform, "freedesktop_os_release") as release:
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(preparation.main(["export", "--spec", "/missing/spec.json"]), 1)
            release.assert_not_called()
        self.assertIn("acknowledge-disposable", error.getvalue())

    def test_supported_disposable_os_and_root_gate(self):
        for system, version in (("debian", "13"), ("ubuntu", "26.04")):
            with patch.object(preparation.platform, "freedesktop_os_release", return_value={"ID": system, "VERSION_ID": version}), \
                    patch.object(preparation.os, "geteuid", return_value=0):
                preparation.authorize(True)
        with patch.object(preparation.platform, "freedesktop_os_release", return_value={"ID": "ubuntu", "VERSION_ID": "24.04"}):
            with self.assertRaisesRegex(ValueError, "Debian 13"):
                preparation.authorize(True)
        with patch.object(preparation.platform, "freedesktop_os_release", return_value={"ID": "debian", "VERSION_ID": "13"}), \
                patch.object(preparation.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(ValueError, "root"):
                preparation.authorize(True)


class AptCommandTests(unittest.TestCase):
    def test_subprocess_uses_argv_and_clean_environment_no_shell_or_network_config(self):
        with patch.object(preparation.subprocess, "run") as run:
            preparation.run_command(["apt-ftparchive", "packages", "pool"], cwd="/srv/apt/mirror")
        args, kwargs = run.call_args
        self.assertEqual(args, (["apt-ftparchive", "packages", "pool"],))
        self.assertEqual(kwargs["cwd"], "/srv/apt/mirror")
        self.assertEqual(kwargs["env"], {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"})
        self.assertTrue(kwargs["check"])
        self.assertNotIn("shell", kwargs)
    def test_signing_commands_export_public_only_and_sign_both_forms(self):
        fingerprint = "A" * 40
        commands = preparation.signing_commands(Path("/srv/ephemeral-key"), fingerprint,
                                                 Path("/srv/apt/mirror"), Path("/srv/apt/keyring.gpg"))
        self.assertEqual(len(commands), 3)
        self.assertEqual(commands[0][-2:], ["--export", fingerprint])
        self.assertEqual(commands[1][-2:], ["--detach-sign", "/srv/apt/mirror/Release"])
        self.assertEqual(commands[2][-2:], ["--clearsign", "/srv/apt/mirror/Release"])
        for command in commands:
            self.assertIn("--no-options", command)
            self.assertIn("--batch", command)
            self.assertIn("/srv/ephemeral-key", command)
            self.assertNotIn("--export-secret-keys", command)
            self.assertNotIn("--yes", command)
        for command in commands[1:]:
            self.assertIn(fingerprint + "!", command)
            self.assertIn("SHA256", command)

    def test_missing_local_apt_tools_fail_without_installation_or_subprocess(self):
        with patch.object(preparation.shutil, "which", return_value=None), \
                patch.object(preparation.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "Missing local mirror tools.*apt-ftparchive"):
                preparation.prepare_apt("/missing/debs", "/missing/output", "/missing/key", "A" * 40, "amd64")
            run.assert_not_called()

    def test_key_id_and_unsafe_architecture_rejected_before_execution(self):
        for fingerprint, architecture in (("operator@example.invalid", "amd64"), ("A" * 40, "i386")):
            with self.subTest(fingerprint=fingerprint, architecture=architecture), \
                    patch.object(preparation.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    preparation.prepare_apt("/missing/debs", "/missing/output", "/missing/key", fingerprint, architecture)
                run.assert_not_called()


class PlaybookTests(unittest.TestCase):
    def test_playbook_is_local_export_only_with_two_acknowledgements(self):
        playbook = yaml.safe_load((ROOT / "deploy/ansible/tests/prepare_airgap_fixture.yml").read_text())
        self.assertEqual(len(playbook), 1)
        play = playbook[0]
        self.assertEqual(play["hosts"], "localhost")
        self.assertEqual(play["connection"], "local")
        self.assertFalse(play["gather_facts"])
        self.assertFalse(play["become"])
        assertions = play["tasks"][0]["ansible.builtin.assert"]["that"]
        self.assertIn("stack_disposable_test_acknowledged | default(false) | bool", assertions)
        self.assertIn("airgap_fixture_prepare_acknowledged | default(false) | bool", assertions)
        command = play["tasks"][1]["ansible.builtin.command"]
        env = NativeEnvironment(undefined=StrictUndefined)
        env.filters["realpath"] = os.path.realpath
        context = {"playbook_dir": str(ROOT / "deploy/ansible/tests")}
        argv = [env.from_string(value).render(context) for value in command["argv"]]
        self.assertEqual(Path(argv[1]).resolve(), HELPER)
        self.assertEqual(argv[argv.index("--checker") + 1], str(CHECKER))
        self.assertEqual(argv[-3:], ["export", "--spec", "-"])


if __name__ == "__main__":
    unittest.main()