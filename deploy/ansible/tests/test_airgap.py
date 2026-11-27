"""Local fixtures only: no inventory, package installation, SSH or service changes."""

import copy
import grp
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ANSIBLE = Path(__file__).resolve().parents[1]
HELPERS_SPEC = importlib.util.spec_from_file_location("airgap_test_helpers", ANSIBLE / "tests/test_python_roles.py")
HELPERS = importlib.util.module_from_spec(HELPERS_SPEC)
HELPERS_SPEC.loader.exec_module(HELPERS)
evaluate = HELPERS.evaluate
task_entries = HELPERS.task_entries
ROLE = ANSIBLE / "roles/stack_airgap"
PYTHON_ROLE = ANSIBLE / "roles/deploy_py-phone-caller"
SPEC = importlib.util.spec_from_file_location("stack_airgap_check", ROLE / "library/stack_airgap_check.py")
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class AirgapFixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="airgap-test-", dir=ANSIBLE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        self.manifest_path = self.root / "manifest.json"
        self.apt = self.root / "apt"
        (self.apt / "sources.list.d").mkdir(parents=True)
        self.mirror = self.root / "mirror"
        self.mirror.mkdir()
        self.key = self.root / "archive.gpg"
        self.key.write_bytes(b"fixture-keyring-not-used-for-package-installation")
        self.classic = f"deb [signed-by={self.key}] file:{self.mirror} trixie main\n"
        self.deb822 = (f"Types: deb deb-src\nURIs: file:{self.mirror}\nSuites: trixie\n"
                       f"Components: main\nSigned-By: {self.key}\n")

    def write_artifact(self, name, content=b"fixture", executable=False):
        path = self.bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o755 if executable else 0o644)
        return path

    def seal(self, **metadata):
        files, symlinks = {}, {}
        for directory, directories, filenames in os.walk(self.bundle):
            for name in directories + filenames:
                path = Path(directory) / name
                relative = str(path.relative_to(self.bundle))
                if path.is_symlink():
                    symlinks[relative] = os.readlink(path)
                elif path.is_file():
                    files[relative] = CHECK.digest(path)
        manifest = {"version": 1, "files": files, "symlinks": symlinks, **metadata}
        self.manifest_path.write_text(json.dumps(manifest))
        return "sha256:" + CHECK.digest(self.manifest_path)

    def verify(self, checksum):
        return CHECK.verify_manifest(self.bundle, self.manifest_path, checksum)

    def test_signed_classic_and_deb822_are_both_checked(self):
        (self.apt / "sources.list").write_text(self.classic)
        (self.apt / "sources.list.d/local.sources").write_text(self.deb822)
        self.assertEqual(CHECK.verify_apt(self.apt, 'Dir "/";', {}), 3)
        (self.apt / "sources.list.d/extra.list").write_text("deb https://example.invalid trixie main\n")
        with self.assertRaises(ValueError):
            CHECK.verify_apt(self.apt, "", {})

    def test_public_and_nonlocal_uri_variants_fail(self):
        for uri in ("http://example.invalid", "https://example.invalid", "ftp://example.invalid",
                    "file://server/mirror", "file:/missing-mirror", f"file:{self.mirror}?x=1"):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                CHECK.classic_sources(self.classic.replace(f"file:{self.mirror}", uri))

    def test_every_uri_in_deb822_is_checked_including_continuations(self):
        for separator in (" ", "\n "):
            with self.subTest(separator=separator), self.assertRaises(ValueError):
                CHECK.deb822_sources(self.deb822.replace(f"file:{self.mirror}",
                                                        f"file:{self.mirror}{separator}https://example.invalid"))

    def test_disabled_sources_do_not_enable_downloads(self):
        self.assertEqual(CHECK.classic_sources("# deb https://example.invalid trixie main\n"), 0)
        self.assertEqual(CHECK.deb822_sources("Enabled: no\nURIs: https://example.invalid\n"), 0)
        with self.assertRaisesRegex(ValueError, "No active"):
            CHECK.verify_apt(self.apt, "", {})

    def test_unsigned_trusted_or_unknown_source_options_fail(self):
        for options in ("", "trusted=yes", "allow-insecure=yes", "check-valid-until=no", "unknown=yes"):
            line = self.classic.replace(f"signed-by={self.key}", options)
            with self.subTest(options=options), self.assertRaises(ValueError):
                CHECK.classic_sources(line)
        for field in ("Trusted: yes", "Allow-Insecure: yes", "Check-Valid-Until: no", "Signed-By: /other"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                CHECK.deb822_sources(self.deb822 + field + "\n")

    def test_proxy_hooks_overrides_and_weak_signatures_fail(self):
        for line in ('Acquire::http::Proxy "http://proxy.invalid";',
                     'DPkg::Pre-Install-Pkgs:: "curl https://example.invalid";',
                     'APT::Update::Post-Invoke:: "anything";',
                     'Dir::Etc::sourceparts "other-sources";', 'Dir::Etc "/other";',
                     'Dir::Bin::Methods "/other";', 'RootDir "/other";',
                     'Acquire::AllowInsecureRepositories "true";',
                     'APT::Get::AllowUnauthenticated "true";', 'Acquire::Check-Valid-Until "false";',
                     'DPkg::Options:: "--force-all";'):
            with self.subTest(line=line), self.assertRaises(ValueError):
                CHECK.apt_configuration(line, {})
        for env in ({"APT_CONFIG": "/other"}, {"https_proxy": "http://proxy"}, {"ALL_PROXY": "socks://proxy"}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                CHECK.apt_configuration("", env)

    def test_current_apt_default_solver_paths_and_signature_policy(self):
        CHECK.apt_configuration('\n'.join([
            'Dir "/";', 'Dir::Etc "etc/apt";', 'Dir::Etc::sourcelist "sources.list";',
            'Dir::Bin "";', 'Dir::Bin::methods "/usr/lib/apt/methods";',
            'Dir::Bin::solvers "";', 'Dir::Bin::solvers:: "/usr/lib/apt/solvers";',
            'Dir::Bin::planners "";', 'Dir::Bin::planners:: "/usr/lib/apt/planners";',
            'Dir::Bin::gzip "/bin/gzip";', 'Dir::Bin::zstd "/usr/bin/zstd";', 'Dir::Bin::lzma "/usr/bin/xz";',
            'APT::Key::Assert-Pubkey-Algo ">=rsa2048,ed25519,ed448";',
            'Acquire::AllowInsecureRepositories "0";', 'Acquire::AllowWeakRepositories "0";',
        ]), {})

    def test_manifest_requires_pin_and_all_bytes_match(self):
        artifact = self.write_artifact("bin/uv")
        checksum = self.seal()
        self.assertEqual(self.verify(checksum)["files"]["bin/uv"], hashlib.sha256(b"fixture").hexdigest())
        for pin in ("", "sha256:" + "0" * 64):
            with self.subTest(pin=pin), self.assertRaises(ValueError):
                self.verify(pin)
        artifact.write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Artifact checksum mismatch"):
            self.verify(checksum)

    def test_missing_manifest_and_missing_or_unlisted_artifacts_fail(self):
        artifact = self.write_artifact("bin/uv")
        checksum = self.seal()
        artifact.unlink()
        with self.assertRaisesRegex(ValueError, "missing artifacts"):
            self.verify(checksum)
        self.write_artifact("bin/uv")
        self.write_artifact("uv-cache/unreviewed")
        with self.assertRaisesRegex(ValueError, "Unlisted file"):
            self.verify(checksum)
        self.manifest_path.unlink()
        with self.assertRaisesRegex(ValueError, "Manifest is missing"):
            self.verify(checksum)

    def test_relative_internal_cache_symlinks_work_but_escaping_links_fail(self):
        self.write_artifact("uv-cache/data")
        link = self.bundle / "uv-cache/link"
        link.symlink_to("data")
        self.verify(self.seal())
        link.unlink()
        link.symlink_to("../../archive.gpg")
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.verify(self.seal())

    def test_duplicate_keys_and_traversal_fail(self):
        self.write_artifact("bin/uv")
        self.manifest_path.write_text('{"version":1,"version":1,"files":{"x":"' + "0" * 64 + '"}}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.verify("sha256:" + CHECK.digest(self.manifest_path))
        self.seal()
        manifest = json.loads(self.manifest_path.read_text())
        manifest["files"]["../escape"] = "0" * 64
        self.manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "relative paths"):
            self.verify("sha256:" + CHECK.digest(self.manifest_path))

    def test_model_assets_cover_selected_language_and_all_preloads(self):
        for language in ("en_US", "it_IT"):
            for suffix in ("onnx", "onnx.json"):
                self.write_artifact(f"models/piper/{language}/{language}.{suffix}")
        manifest = self.verify(self.seal())
        audio = {"piper_language_code": "en_US", "preload": {"piper_tts": ["it_IT"]}}
        CHECK.verify_models(self.bundle, manifest, audio, "piper_tts", "piper")
        (self.bundle / "models/piper/it_IT/it_IT.onnx").unlink()
        with self.assertRaisesRegex(ValueError, "model/preload"):
            CHECK.verify_models(self.bundle, manifest, audio, "piper_tts", "piper")

    def test_bundle_checks_architecture_versions_cloud_carriers_and_models(self):
        toolchain = "1.85.0-x86_64-unknown-linux-gnu"
        for name in ("bin/uv", "python/bin/python3.14", "cargo/bin/cargo", "cargo/bin/rustc",
                     "rustup/toolchains/" + toolchain + "/bin/rustc"):
            self.write_artifact(name, executable=True)
        self.write_artifact("build-constraints.txt", b"setuptools==80.9.0\n")
        self.write_artifact("models/piper/en_US/en_US.onnx")
        self.write_artifact("models/piper/en_US/en_US.onnx.json")
        for directory in ("uv-cache", "models/huggingface", "models/torch", "models/cache"):
            (self.bundle / directory).mkdir(parents=True)
        manifest = self.verify(self.seal(architecture="x86_64", python_version="3.14.5", uv_version="0.11.15"))
        config = {"caller_sms": {"caller_sms_carrier": "on_premise"}, "generate_audio": {
            "tts_engine": "piper_tts", "pre_trained_models_folder": str(self.bundle / "models"),
            "piper_models_folder": "piper", "piper_language_code": "en_US"}}
        arguments = [self.bundle, manifest, "x86_64", "3.14.5", "0.11.15", toolchain, config, ["setuptools==80.9.0"]]
        CHECK.verify_bundle(*arguments)
        for index, value in ((2, "aarch64"), (3, "3.13.5"), (4, "0.11.16"), (5, "stable")):
            changed = copy.deepcopy(arguments)
            changed[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                CHECK.verify_bundle(*changed)
        config["caller_sms"]["caller_sms_carrier"] = "twilio"
        with self.assertRaisesRegex(ValueError, "cloud carriers"):
            CHECK.verify_bundle(*arguments)
        config["caller_sms"]["caller_sms_carrier"] = "on_premise"
        config["generate_audio"]["tts_engine"] = "google_gtts"
        with self.assertRaisesRegex(ValueError, "cloud provider"):
            CHECK.verify_bundle(*arguments)

    def test_source_build_inputs_must_be_pinned_in_project_metadata(self):
        project = self.write_artifact("pyproject.toml", b"[project]\nname='fixture'\n")
        with self.assertRaisesRegex(ValueError, "build-constraint-dependencies"):
            CHECK.source_build_constraints(self.bundle)
        project.write_text('[tool.uv]\nbuild-constraint-dependencies=["setuptools==80.9.0"]\n')
        self.assertEqual(CHECK.source_build_constraints(self.bundle), ["setuptools==80.9.0"])
        project.write_text('[tool.uv]\nbuild-constraint-dependencies=["setuptools>=80"]\n')
        with self.assertRaises(ValueError):
            CHECK.source_build_constraints(self.bundle)

    def test_only_canonical_private_networks_with_exact_isolation_are_accepted(self):
        networks = ["10.10.0.0/24", "172.16.4.0/24", "192.168.4.0/24", "fd00:1::/64"]
        CHECK.private_networks(networks, ["any"], ["localhost", *networks])
        for network in ("0.0.0.0/0", "::/0", "8.8.8.0/24", "100.64.0.0/10", "127.0.0.0/8",
                        "169.254.0.0/16", "10.0.0.0/7", "10.0.0.1/24", "localhost", "10.0.0.0/8\nIPAddressAllow=any"):
            with self.subTest(network=network), self.assertRaises(ValueError):
                CHECK.private_networks([network], ["any"], ["localhost", network])
        for deny, allow in (([], ["localhost"]), (["any"], ["any"]), (["any"], ["localhost", "8.8.8.8"])):
            with self.subTest(deny=deny, allow=allow), self.assertRaises(ValueError):
                CHECK.private_networks([], deny, allow)

    def test_real_uv_empty_cache_fails_without_downloading(self):
        uv = shutil.which("uv")
        self.assertIsNotNone(uv, "The configured uv package manager is required for the offline negative fixture")
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith(("UV_", "PIP_")) and not key.lower().endswith("_proxy")}
        environment.update(UV_CACHE_DIR=str(self.root / "empty-cache"), UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never")
        result = subprocess.run([uv, "--offline", "--no-config", "pip", "install", "--python", sys.executable,
                                 "--target", str(self.root / "installed"), "airgap-missing-fixture==0.0.0"],
                                env=environment, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("network", result.stderr.lower())
        self.assertIn("cache", result.stderr.lower())
        self.assertFalse((self.root / "installed/airgap_missing_fixture").exists())

    def test_real_frozen_workspace_sync_cannot_fill_a_missing_cache(self):
        uv = shutil.which("uv")
        self.assertIsNotNone(uv)
        (self.root / "pyproject.toml").write_text(
            '[project]\nname="airgap-workspace-fixture"\nversion="0.0.0"\n'
            'requires-python=">=3.14"\ndependencies=["airgap-missing-fixture==0.0.0"]\n'
            '[tool.uv]\npackage=false\nbuild-constraint-dependencies=["setuptools==80.9.0"]\n')
        (self.root / "uv.lock").write_text(
            'version=1\nrevision=3\nrequires-python=">=3.14"\n'
            '[[package]]\nname="airgap-workspace-fixture"\nversion="0.0.0"\nsource={virtual="."}\n'
            'dependencies=[{name="airgap-missing-fixture"}]\n'
            '[package.metadata]\nrequires-dist=[{name="airgap-missing-fixture",specifier="==0.0.0"}]\n'
            '[[package]]\nname="airgap-missing-fixture"\nversion="0.0.0"\n'
            'source={registry="https://pypi.org/simple"}\n'
            'sdist={url="https://files.pythonhosted.org/packages/airgap-missing-fixture.tar.gz",'
            'hash="sha256:' + "0" * 64 + '",size=123}\n')
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith(("UV_", "PIP_")) and not key.lower().endswith("_proxy")}
        environment.update(UV_CACHE_DIR=str(self.root / "empty-cache"), UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never")
        result = subprocess.run([uv, "--offline", "--no-config", "sync", "--frozen", "--all-packages", "--no-dev",
                                 "--inexact", "--python", sys.executable, "--no-python-downloads"], cwd=self.root,
                                env=environment, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("network", result.stderr.lower())
        self.assertIn("cache", result.stderr.lower())
        self.assertIn("airgap-missing-fixture", result.stderr)

    def test_real_frozen_dependency_free_workspace_succeeds_without_downloads(self):
        uv = shutil.which("uv")
        self.assertIsNotNone(uv)
        (self.root / "pyproject.toml").write_text(
            '[project]\nname="airgap-local-fixture"\nversion="0.0.0"\nrequires-python=">=3.14"\n'
            '[tool.uv]\npackage=false\n')
        lock = self.root / "uv.lock"
        lock.write_text('version=1\nrevision=3\nrequires-python=">=3.14"\n[[package]]\n'
                        'name="airgap-local-fixture"\nversion="0.0.0"\nsource={virtual="."}\n')
        checksum = CHECK.digest(lock)
        environment = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith(("UV_", "PIP_")) and not key.lower().endswith("_proxy")}
        environment.update(UV_CACHE_DIR=str(self.root / "empty-cache"), UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never")
        result = subprocess.run([uv, "--offline", "--no-config", "sync", "--frozen", "--all-packages", "--no-dev",
                                 "--python", sys.executable, "--no-python-downloads"], cwd=self.root,
                                env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / ".venv/bin/python").is_file())
        self.assertEqual(CHECK.digest(lock), checksum)

    def test_real_ansible_module_fails_closed_on_invalid_network_policy(self):
        arguments = {"ANSIBLE_MODULE_ARGS": {"operation": "policy", "networks": ["0.0.0.0/0"],
                                             "deny": ["any"], "allow": ["localhost", "0.0.0.0/0"]}}
        result = subprocess.run([sys.executable, str(ROLE / "library/stack_airgap_check.py")],
                                input=json.dumps(arguments), capture_output=True, text=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        response = json.loads(result.stdout)
        self.assertTrue(response["failed"])
        self.assertIn("RFC1918/ULA", response["msg"])


class AirgapInstallTransactions(unittest.TestCase):
    """Production Ansible cache/stamp tasks, harmless UV command boundary, real Python import.

    This is not a Rust/UV integration test. Root-only bundle policy is tested above;
    here only that include is omitted and file ownership is mapped to the test user.
    No namespace privileges, installation, SSH or network access are needed.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="airgap-install-test-", dir=ANSIBLE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.source = self.root / "source"
        self.native = self.source / "src/py-phone-caller-utils/py_phone_caller_utils/sms/rust_engine"
        self.native.mkdir(parents=True)
        (self.native / "Cargo.toml").write_text('[package]\nname="fixture"\nversion="1.0.0"\n')
        (self.native / "Cargo.lock").write_text("version = 4\n")
        (self.native / "lib.rs").write_text("// boundary fixture, not compiled\n")
        (self.source / "pyproject.toml").write_text('[tool.uv]\nbuild-constraint-dependencies=["setuptools==80.9.0"]\n')
        (self.source / "uv.lock").write_text("version = 1\n")
        (self.source / "ui.html").write_text("initial UI\n")
        self.install = self.root / "installed"
        self.install.mkdir()
        self.venv = self.install / ".venv"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(self.venv)], check=True, timeout=30)
        self.site_packages = Path(subprocess.check_output(
            [str(self.venv / "bin/python"), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True).strip())
        self.events = self.root / "events"
        for directory in ("bin", "python/bin", "uv-cache", "cargo", "rustup"):
            (self.bundle / directory).mkdir(parents=True)
        (self.bundle / "python/bin/python3.14").symlink_to(sys.executable)
        for directory in ("uv-cache", "cargo", "rustup"):
            (self.bundle / directory / "reviewed-input").write_text("reviewed\n")
        self.boundary = self.bundle / "bin/uv"
        self.boundary.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, subprocess, sys\n"
            f"root = pathlib.Path({str(self.root)!r})\n"
            "args = sys.argv[1:]\n"
            "event = 'build' if 'build' in args else 'install' if 'install' in args else 'sync'\n"
            "with (root / 'events').open('a') as stream:\n"
            "    stream.write(event + '\\n')\n"
            "if (root / ('fail-' + event)).exists():\n"
            "    sys.exit(19)\n"
            "if event == 'build':\n"
            "    out = pathlib.Path(args[args.index('--out') + 1])\n"
            "    out.mkdir(parents=True, exist_ok=True)\n"
            "    (out / 'sms_rust_backend-fixture.whl').write_text('command boundary, not a Rust wheel')\n"
            "if event == 'install':\n"
            "    interpreter = args[args.index('--python') + 1]\n"
            "    site = subprocess.check_output([interpreter, '-I', '-c', \"import sysconfig; print(sysconfig.get_path('purelib'))\"], text=True).strip()\n"
            "    module = pathlib.Path(site) / 'rust_engine.py'\n"
            "    module.write_text(\"raise ImportError('fixture failure')\\n\" if (root / 'fail-import').exists() else 'VALUE = 1\\n')\n"
            "    if (root / 'fail-install-after-write').exists():\n"
            "        sys.exit(19)\n"
            "    print('Installed fixture module')\n"
        )
        self.boundary.chmod(0o755)
        self.state = self.install / ".uv/airgap"
        self.cache = self.install / ".uv/cache"
        self.variables = {
            "ansible_python_interpreter": sys.executable,
            "py_phone_caller_user": pwd.getpwuid(os.getuid()).pw_name,
            "py_phone_caller_group": grp.getgrgid(os.getgid()).gr_name,
            "py_phone_caller_install_dir": str(self.install),
            "py_phone_caller_venv_dir": str(self.venv),
            "py_phone_caller_local_src_path": str(self.source),
            "py_phone_caller_airgap_source_manifest_path": str(self.root / "source.json"),
            "py_phone_caller_airgap_bundle_dir": str(self.bundle),
            "py_phone_caller_uv_cache_dir": str(self.cache),
            "py_phone_caller_uv_bin": str(self.install / "uv"),
            "py_phone_caller_uv_sync_timeout": 30,
            "py_phone_caller_maturin_version": "1.8.2",
            "py_phone_caller_airgap_rust_toolchain": "1.85.0-x86_64-unknown-linux-gnu",
            "py_phone_caller_final_config": {"generate_audio": {"tts_engine": "piper_tts"}},
            "_ppc_sms_engine_dir": str(self.install / self.native.relative_to(self.source)),
            "_ppc_sms_wheel_dir": str(self.install / ".uv/sms-wheels"),
            "_ppc_airgap_state_dir": str(self.state),
            "_ppc_airgap_build_environment": {"UV_OFFLINE": "1", "CARGO_NET_OFFLINE": "true"},
            "_ppc_airgap_command_prefix": ["/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "UV_OFFLINE=1"],
        }

    def run_install(self, success=True):
        files = {str(path.relative_to(self.source)): CHECK.digest(path)
                 for path in self.source.rglob("*") if path.is_file()}
        manifest = self.root / "source.json"
        manifest.write_text(json.dumps({"version": 1, "files": files}))
        self.variables["py_phone_caller_airgap_source_manifest_checksum"] = "sha256:" + CHECK.digest(manifest)
        CHECK.verify_manifest(self.source, manifest, self.variables["py_phone_caller_airgap_source_manifest_checksum"])
        # Model/artifact policy and full UV behavior have separate tests; this identity
        # covers the harmless executable and cache inputs used by this boundary fixture.
        bundle_files = {str(path.relative_to(self.bundle)): CHECK.digest(path)
                        for path in self.bundle.rglob("*") if path.is_file()}
        self.variables["py_phone_caller_airgap_manifest_checksum"] = "sha256:" + hashlib.sha256(
            json.dumps(bundle_files, sort_keys=True).encode()).hexdigest()
        shutil.copytree(self.source, self.install, dirs_exist_ok=True)
        tasks = yaml.safe_load((PYTHON_ROLE / "tasks/install_offline.yml").read_text())
        tasks = [task for task in tasks if "ansible.builtin.include_role" not in task]

        def map_ownership(entries):
            for task in entries:
                for section in ("block", "always", "rescue"):
                    map_ownership(task.get(section, []))
                for module in ("ansible.builtin.file", "ansible.builtin.copy"):
                    if module in task:
                        for key, variable in (("owner", "py_phone_caller_user"), ("group", "py_phone_caller_group")):
                            if task[module].get(key) == "root":
                                task[module][key] = self.variables[variable]

        map_ownership(tasks)
        tasks.append({"name": "Record fixture readiness", "ansible.builtin.copy": {
            "content": "{{ _ppc_airgap_install_ready | default(false) | string }}",
            "dest": str(self.root / "ready"), "mode": "0600"}})
        playbook = self.root / "playbook.yml"
        playbook.write_text(yaml.safe_dump([{
            "hosts": "localhost", "connection": "local", "gather_facts": False,
            "vars": self.variables, "tasks": tasks,
            "handlers": [{"name": "Restart py-phone-caller services", "ansible.builtin.copy": {
                "content": "restarted", "dest": str(self.root / "restart"), "mode": "0600"}}],
        }], sort_keys=False))
        environment = dict(os.environ, ANSIBLE_LOCAL_TEMP=str(self.root / "ansible-tmp"),
                           ANSIBLE_ROLES_PATH=str(ANSIBLE / "roles"), ANSIBLE_LIBRARY=str(ROLE / "library"),
                           ANSIBLE_NOCOLOR="1", ANSIBLE_STDOUT_CALLBACK="default")
        for marker in ("ready", "restart"):
            (self.root / marker).unlink(missing_ok=True)
        result = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(playbook)],
                                env=environment, capture_output=True, text=True, timeout=120)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((self.root / "ready").read_text(), "True")
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse((self.root / "ready").exists())
            self.assertFalse((self.root / "restart").exists())
        return result

    def event_counts(self):
        events = self.events.read_text().splitlines()
        return tuple(events.count(event) for event in ("sync", "build", "install"))

    def test_unchanged_native_install_and_ui_edits_preserve_mutable_caches(self):
        self.run_install()
        self.assertEqual(self.event_counts(), (1, 1, 1))
        for directory in (self.cache, self.state / "cargo", self.state / "rustup"):
            (directory / "reviewed-input").write_text("mutated by build\n")
            (directory / "generated").write_text("keep\n")
        native_output = Path(self.variables["_ppc_sms_engine_dir"]) / "target"
        native_output.mkdir()
        (native_output / "generated").write_text("compiler output must not affect input identity")
        self.run_install()
        self.assertEqual(self.event_counts(), (2, 1, 1))
        self.assertFalse((self.root / "restart").exists())
        (self.source / "ui.html").write_text("unrelated UI edit\n")
        self.run_install()
        self.assertEqual(self.event_counts(), (3, 1, 1))
        self.assertFalse((self.root / "restart").exists())
        for directory in (self.cache, self.state / "cargo", self.state / "rustup"):
            self.assertEqual((directory / "reviewed-input").read_text(), "mutated by build\n")
            self.assertEqual((directory / "generated").read_text(), "keep\n")

    def test_native_and_bundle_changes_rebuild_but_only_bundle_reseeds(self):
        self.run_install()
        (self.cache / "generated").write_text("keep until bundle changes")
        (self.native / "lib.rs").write_text("// changed native input\n")
        self.run_install()
        self.assertEqual(self.event_counts(), (2, 2, 2))
        self.assertTrue((self.cache / "generated").exists())
        previous_metadata = (self.cache / "reviewed-input").stat()
        (self.bundle / "uv-cache/reviewed-input").write_text("replaced\n")
        os.utime(self.bundle / "uv-cache/reviewed-input", ns=(previous_metadata.st_atime_ns, previous_metadata.st_mtime_ns))
        self.run_install()
        self.assertEqual(self.event_counts(), (3, 3, 3))
        self.assertFalse((self.cache / "generated").exists())
        self.assertEqual((self.cache / "reviewed-input").read_text(), "replaced\n")

    def test_failed_candidates_preserve_previous_native_stamp(self):
        self.run_install()
        stamp = self.state / "stamps/native.sha256"
        original = stamp.read_bytes()
        for failure in ("build", "install", "import"):
            with self.subTest(failure=failure):
                (self.native / "lib.rs").write_text("// candidate " + failure + "\n")
                control = self.root / ("fail-" + failure)
                control.touch()
                self.run_install(success=False)
                self.assertEqual(stamp.read_bytes(), original)
                self.assertTrue((self.state / "stamps/native.pending").exists())
                control.unlink()
        self.run_install()
        self.assertNotEqual(stamp.read_bytes(), original)
        self.assertFalse((self.state / "stamps/native.pending").exists())
        self.assertEqual(stamp.stat().st_mode & 0o777, 0o600)
        self.assertEqual(stamp.parent.stat().st_mode & 0o777, 0o700)

    def test_matching_stamp_does_not_accept_a_broken_import(self):
        self.run_install()
        (self.site_packages / "rust_engine.py").write_text("raise ImportError('broken installed module')\n")
        self.run_install()
        self.assertEqual(self.event_counts(), (2, 2, 2))
        self.assertTrue((self.root / "restart").exists())

    def test_toolchain_maturin_and_interpreter_changes_rebuild_without_reseeding(self):
        self.run_install()
        (self.cache / "generated").write_text("preserve mutable cache")
        stamp = self.state / "stamps/native.sha256"
        identities = {stamp.read_bytes()}
        alternate = self.install / ".venv-alternate"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(alternate)], check=True, timeout=30)
        # Preserve a real importable installed module so the interpreter identity,
        # not an import failure, must trigger the third rebuild.
        alternate_site = Path(subprocess.check_output(
            [str(alternate / "bin/python"), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True).strip())
        shutil.copy2(self.site_packages / "rust_engine.py", alternate_site / "rust_engine.py")
        for count, (variable, value) in enumerate((
                ("py_phone_caller_airgap_rust_toolchain", "1.86.0-x86_64-unknown-linux-gnu"),
                ("py_phone_caller_maturin_version", "1.9.0"),
                ("py_phone_caller_venv_dir", str(alternate))), start=2):
            with self.subTest(variable=variable):
                self.variables[variable] = value
                self.run_install()
                self.assertEqual(self.event_counts(), (count, count, count))
                self.assertTrue((self.cache / "generated").exists())
                identities.add(stamp.read_bytes())
        self.assertEqual(len(identities), 4)

    def test_interrupted_install_cannot_reuse_previous_success_after_source_rollback(self):
        original_source = (self.native / "lib.rs").read_text()
        self.run_install()
        stamp = self.state / "stamps/native.sha256"
        original = stamp.read_bytes()
        (self.native / "lib.rs").write_text("// interrupted candidate\n")
        (self.root / "fail-install-after-write").touch()
        self.run_install(success=False)
        self.assertEqual(stamp.read_bytes(), original)
        (self.root / "fail-install-after-write").unlink()
        (self.native / "lib.rs").write_text(original_source)
        self.run_install()
        self.assertEqual(self.event_counts(), (3, 3, 3))
        self.assertEqual(stamp.read_bytes(), original)
        self.assertFalse((self.state / "stamps/native.pending").exists())

    def test_first_failed_build_never_publishes_a_native_success_stamp(self):
        (self.root / "fail-build").touch()
        self.run_install(success=False)
        self.assertFalse((self.state / "stamps/native.sha256").exists())
        self.assertTrue((self.state / "stamps/cache.sha256").is_file())
        (self.cache / "generated").write_text("do not reseed after a build failure")
        (self.root / "fail-build").unlink()
        self.run_install()
        self.assertEqual(self.event_counts(), (2, 2, 1))
        self.assertTrue((self.cache / "generated").exists())

    def test_failed_cache_seed_preserves_previous_seed_stamp_and_stops_before_sync(self):
        self.run_install()
        stamp = self.state / "stamps/cache.sha256"
        original = stamp.read_bytes()
        (self.bundle / "uv-cache/reviewed-input").write_text("new reviewed bundle\n")
        shutil.rmtree(self.state / "cargo")
        (self.state / "cargo").write_text("not a directory, rsync must fail")
        self.run_install(success=False)
        self.assertEqual(stamp.read_bytes(), original)
        self.assertEqual(self.event_counts(), (1, 1, 1))
        (self.state / "cargo").unlink()
        self.run_install()
        self.assertNotEqual(stamp.read_bytes(), original)
        self.assertEqual(self.event_counts(), (2, 2, 2))


class AirgapTaskContracts(unittest.TestCase):
    def test_all_online_install_commands_are_guarded_and_legacy_is_the_default(self):
        tasks = list(task_entries(yaml.safe_load((PYTHON_ROLE / "tasks/install.yml").read_text())))
        values = {"_ppc_uv": {"stat": {"exists": False}}, "_ppc_sms_on_premise": True,
                  "py_phone_caller_final_config": {"generate_audio": {"tts_engine": "kokoro_tts"}}}
        for task in tasks:
            if not any(key in task for key in ("ansible.builtin.command", "ansible.builtin.shell", "ansible.builtin.get_url")):
                continue
            conditions = task["when"]
            if isinstance(conditions, str):
                conditions = [conditions]
            guard = next(condition for condition in conditions if "py_phone_caller_connectivity" in condition)
            with self.subTest(task=task["name"]):
                self.assertFalse(evaluate("{{ " + guard + " }}", {**values, "py_phone_caller_connectivity": "airgapped"}))
                self.assertTrue(evaluate("{{ " + guard + " }}", values))

    def test_offline_build_uses_full_frozen_workspace_and_clean_no_network_environment(self):
        tasks = list(task_entries(yaml.safe_load((PYTHON_ROLE / "tasks/install_offline.yml").read_text())))
        build = next(task for task in tasks if "entire frozen workspace" in task["name"])
        command = build["ansible.builtin.command"]["argv"]
        for flag in ("--offline", "--frozen", "--all-packages", "--no-python-downloads"):
            self.assertIn(flag, command)
        self.assertNotIn("--build-constraint", command)
        self.assertNotIn("--no-deps", command)
        variables = yaml.safe_load((ROLE / "vars/main.yml").read_text())
        environment = variables["_ppc_airgap_build_environment"]
        for key, value in {"UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never", "CARGO_NET_OFFLINE": "true",
                           "RUSTUP_AUTO_INSTALL": "0", "PIP_NO_INDEX": "1"}.items():
            self.assertEqual(environment[key], value)
        prefix = variables["_ppc_airgap_command_prefix"]
        for fragment in ("/usr/bin/unshare", "--net", "/usr/sbin/runuser", "/usr/bin/env", "-i"):
            self.assertIn(fragment, prefix)
        rendered = evaluate(prefix, {"py_phone_caller_user": "fixture",
                                     "_ppc_airgap_build_environment": {"UV_OFFLINE": "1"},
                                     "py_phone_caller_airgap_runtime_environment": {"HF_HUB_OFFLINE": "1"}})
        self.assertEqual(rendered[:9], ["/usr/bin/unshare", "--net", "--", "/usr/sbin/runuser", "-u",
                                       "fixture", "--", "/usr/bin/env", "-i"])
        self.assertEqual(set(rendered[9:]), {"UV_OFFLINE=1", "HF_HUB_OFFLINE=1"})
        for task in tasks:
            self.assertNotIn("ansible.builtin.get_url", task)
            self.assertNotIn("ansible.builtin.shell", task)
            if "ansible.builtin.command" in task and "rsync" not in str(task):
                self.assertIn("_ppc_airgap_command_prefix", task["ansible.builtin.command"]["argv"])
        self.assertTrue(tasks[-1]["ansible.builtin.set_fact"]["_ppc_airgap_install_ready"])
        self.assertFalse(any("notify" in task for task in tasks[:-1]))

    def test_manifest_verification_precedes_binary_execution_and_preflight_uses_topology_config(self):
        tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
        verification = next(index for index, task in enumerate(tasks) if task.get("ansible.builtin.import_tasks") == "bundle.yml")
        execution = next(index for index, task in enumerate(tasks) if "ansible.builtin.command" in task)
        self.assertLess(verification, execution)
        bundle = yaml.safe_load((ROLE / "tasks/bundle.yml").read_text())[0]
        self.assertEqual(bundle["stack_airgap_check"]["config"], "{{ py_phone_caller_topology_config }}")


if __name__ == "__main__":
    unittest.main()
