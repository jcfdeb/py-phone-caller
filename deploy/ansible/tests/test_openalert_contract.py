"""Offline deployment-contract tests; no daemon, devices, services or network."""

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock


HELPER = Path(__file__).resolve().parents[1] / "roles/openalert/files/openalert_contract.py"
SPEC = importlib.util.spec_from_file_location("openalert_contract", HELPER)
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def elf(architecture="amd64", libraries=("libc.so.6",), glibc="2.31"):
    _, machine, interpreter, _ = contract.ARCHITECTURES[architecture]
    data = bytearray(1024)
    data[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HHI", data, 16, 3, machine, 1)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HHH", data, 52, 64, 56, 3)
    raw_interpreter = interpreter.encode() + b"\x00"
    data[256:256 + len(raw_interpreter)] = raw_interpreter
    strings = b"\x00"
    offsets = []
    for name in libraries:
        offsets.append(len(strings))
        strings += name.encode() + b"\x00"
    strings += b"GLIBC_" + glibc.encode() + b"\x00"
    data[640:640 + len(strings)] = strings
    entries = [(5, 640), (10, len(strings)), *((1, offset) for offset in offsets), (0, 0)]
    for index, entry in enumerate(entries):
        struct.pack_into("<qQ", data, 384 + index * 16, *entry)
    for index, values in enumerate(((1, 5, 0, 0, 0, len(data), len(data), 4096),
                                    (3, 4, 256, 256, 0, len(raw_interpreter), len(raw_interpreter), 1),
                                    (2, 4, 384, 384, 0, len(entries) * 16, len(entries) * 16, 8))):
        struct.pack_into("<IIQQQQQQ", data, 64 + index * 56, *values)
    return bytes(data)


def metadata(architecture="amd64", binary=None):
    binary = elf(architecture) if binary is None else binary
    return {
        "schema_version": 1, "package": "openalertd", "version": "1.0.0",
        "release_id": "1.0.0-test", "source_revision": "abc123", "source_dirty": False,
        "architecture": architecture, "target": contract.ARCHITECTURES[architecture][0],
        "build": {"rustc_version": "rustc 1.90", "baseline": "debian11", "prebuilt": False, "cargo_locked": True},
        "runtime": {"libc": "glibc", "minimum_glibc": "2.31",
                    "interpreter": contract.ARCHITECTURES[architecture][2], "needed_libraries": ["libc.so.6"]},
        "binary": {"path": "bin/openalertd", "sha256": hashlib.sha256(binary).hexdigest()},
    }


class TemporaryCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="contract-test-", dir=Path(__file__).parent)
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()


class ArchiveTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        self.archive = self.base / "release.tar.gz"
        self.destination = self.base / "installed"
        self.root = "openalertd-1.0.0-x86_64-unknown-linux-gnu"
        self.addCleanup(mock.patch.stopall)
        # Temp fixtures are user-owned under the checkout, not a root-owned install tree.
        self.secure = mock.patch.object(contract, "secure_directory").start()
        self.runtime = mock.patch.object(contract, "validate_runtime").start()

    def bundle(self, architecture="amd64", changed_metadata=None, extras=(), missing=(), binary=None):
        binary = elf(architecture) if binary is None else binary
        record = metadata(architecture, binary) if changed_metadata is None else changed_metadata
        files = {"release.json": json.dumps(record).encode(), "bin/openalertd": binary,
                 "templates/" + contract.DEFAULT_TEMPLATE: b"{}",
                 "systemd/openalertd.service": b"[Service]\n", "profiles/local.toml": b"[rest]\n"}
        with tarfile.open(self.archive, "w:gz") as bundle:
            for name, content in files.items():
                if name in missing:
                    continue
                entry = tarfile.TarInfo(self.root + "/" + name)
                entry.size = len(content)
                entry.mode = 0o755 if name == "bin/openalertd" else 0o644
                bundle.addfile(entry, io.BytesIO(content))
            for entry in extras:
                bundle.addfile(entry, io.BytesIO(b"x" * entry.size))
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def install(self, checksum, architecture="amd64"):
        return contract.archive_contract(self.archive, checksum, architecture, self.destination)

    def test_both_architectures_and_verified_cache(self):
        for architecture in contract.ARCHITECTURES:
            with self.subTest(architecture=architecture):
                self.destination = self.base / architecture
                result = self.install(self.bundle(architecture), architecture)
                self.assertTrue(result["changed"])
                self.assertEqual(result["release_dir"], str(self.destination / self.root))
                self.assertEqual((Path(result["release_dir"]) / "bin/openalertd").read_bytes(), elf(architecture))
                self.assertFalse(self.install(hashlib.sha256(self.archive.read_bytes()).hexdigest(), architecture)["changed"])
                self.runtime.assert_called_with(result["metadata"], architecture)

    def test_trusted_hash_checked_before_tar_parsing(self):
        self.bundle()
        with mock.patch.object(contract.tarfile, "open") as parse:
            with self.assertRaisesRegex(contract.ContractError, "checksum"):
                self.install("0" * 64)
            parse.assert_not_called()
        self.assertFalse(self.destination.exists())

    def test_fresh_empty_destination(self):
        self.destination.mkdir()
        self.assertTrue(self.install(self.bundle())["changed"])

    def test_corrupt_tar_is_not_extracted(self):
        self.archive.write_bytes(b"not a tar")
        with self.assertRaises(tarfile.TarError):
            self.install(hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertFalse(self.destination.exists())

    def test_wrong_architecture_and_binary_hash(self):
        with self.assertRaisesRegex(contract.ContractError, "architecture"):
            self.install(self.bundle("arm64"))
        record = metadata()
        record["binary"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(contract.ContractError, "checksum"):
            self.install(self.bundle(changed_metadata=record))

    def test_unsafe_archive_members(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE),
                           (self.root + "/a/../../escape", tarfile.REGTYPE),
                           (self.root + "/a//b", tarfile.REGTYPE),
                           (self.root + "/./a", tarfile.REGTYPE),
                           (self.root + "/link", tarfile.SYMTYPE),
                           (self.root + "/hard", tarfile.LNKTYPE),
                           (self.root + "/fifo", tarfile.FIFOTYPE),
                           (self.root + "/dev", tarfile.CHRTYPE),
                           (self.root + "/release.json", tarfile.REGTYPE),
                           ("other/file", tarfile.REGTYPE),
                           (self.root + "/bin", tarfile.REGTYPE)):
            with self.subTest(name=name, kind=kind):
                entry = tarfile.TarInfo(name)
                entry.type = kind
                entry.linkname = "/etc/passwd" if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE) else ""
                with self.assertRaises(contract.ContractError):
                    self.install(self.bundle(extras=[entry]))
                self.assertFalse(self.destination.exists())

    def test_required_assets(self):
        for name in ("templates/" + contract.DEFAULT_TEMPLATE, "systemd/openalertd.service", "profiles/local.toml"):
            with self.subTest(name=name), self.assertRaisesRegex(contract.ContractError, "missing release"):
                self.install(self.bundle(missing=[name]))

    def test_cache_is_not_a_marker_trust(self):
        checksum = self.bundle()
        result = self.install(checksum)
        binary = Path(result["release_dir"]) / "bin/openalertd"
        binary.write_bytes(b"tampered")
        with self.assertRaisesRegex(contract.ContractError, "cached release checksum"):
            self.install(checksum)

    def test_cache_rejects_extra_missing_links_and_writable_assets(self):
        checksum = self.bundle()
        for corruption in ("extra", "missing", "symlink", "hardlink", "mode"):
            with self.subTest(corruption=corruption):
                self.destination = self.base / corruption
                root = Path(self.install(checksum)["release_dir"])
                path = root / "templates" / contract.DEFAULT_TEMPLATE
                if corruption == "extra":
                    (root / "unexpected").write_text("x")
                elif corruption == "missing":
                    path.unlink()
                elif corruption == "symlink":
                    path.unlink()
                    path.symlink_to(root / "release.json")
                elif corruption == "hardlink":
                    os.link(path, self.base / "hardlink-copy")
                else:
                    path.chmod(0o666)
                with self.assertRaises(contract.ContractError):
                    self.install(checksum)

    def test_runtime_failure_leaves_no_destination(self):
        self.runtime.side_effect = contract.ContractError("incompatible runtime")
        with self.assertRaises(contract.ContractError):
            self.install(self.bundle())
        self.assertFalse(self.destination.exists())


class MetadataTests(unittest.TestCase):
    def test_malformed_metadata(self):
        for section, key, value in ((None, "schema_version", True), (None, "schema_version", 2),
                                    (None, "source_dirty", "false"), (None, "version", []),
                                    ("build", "prebuilt", 1), ("build", "baseline", {}),
                                    ("runtime", "libc", "musl"), ("runtime", "minimum_glibc", 2.31),
                                    ("runtime", "minimum_glibc", "2.1"),
                                    ("runtime", "needed_libraries", "libc.so.6"),
                                    ("runtime", "needed_libraries", []),
                                    ("runtime", "needed_libraries", ["libc.so.6", "libc.so.6"]),
                                    ("runtime", "needed_libraries", ["../libc.so.6"]),
                                    ("runtime", "needed_libraries", ["libother.so.1"]),
                                    ("runtime", "interpreter", "/evil/loader")):
            record = metadata()
            (record if section is None else record[section])[key] = value
            with self.subTest(section=section, key=key, value=value), self.assertRaises(contract.ContractError):
                contract.validate_metadata(record, "amd64", elf())

    def test_elf_is_checked_independently_of_metadata(self):
        for data in (b"not ELF", elf("arm64"), elf()[:100]):
            with self.subTest(data=data[:20]), self.assertRaises(contract.ContractError):
                contract.validate_metadata(metadata(binary=data), "amd64", data)

    def test_duplicate_json_fields(self):
        with self.assertRaises(contract.ContractError):
            contract.load_json('{"schema_version":1,"schema_version":1}')


class RuntimeTests(TemporaryCase):
    def test_both_architecture_runtime_paths_and_missing_dependencies(self):
        for architecture in contract.ARCHITECTURES:
            _, machine, interpreter, host = contract.ARCHITECTURES[architecture]
            path = self.base / architecture
            path.write_bytes(elf(architecture))
            original = contract.compatible_library
            with self.subTest(architecture=architecture), \
                    mock.patch.object(contract.platform, "system", return_value="Linux"), \
                    mock.patch.object(contract.platform, "machine", return_value=host), \
                    mock.patch.object(contract, "host_glibc", return_value=(2, 36, 0)) as glibc, \
                    mock.patch.object(contract.os, "access", return_value=True), \
                    mock.patch.object(contract, "library_candidates", return_value={"libc.so.6": [path]}), \
                    mock.patch.object(contract, "compatible_library",
                                      side_effect=lambda file, arch: original(path if str(file) == interpreter else file, arch)):
                contract.validate_runtime(metadata(architecture), architecture)
                glibc.return_value = (2, 30, 0)
                with self.assertRaisesRegex(contract.ContractError, "too old"):
                    contract.validate_runtime(metadata(architecture), architecture)
                glibc.return_value = (2, 36, 0)
                path.write_bytes(elf("arm64" if architecture == "amd64" else "amd64"))
                with self.assertRaisesRegex(contract.ContractError, "interpreter"):
                    contract.validate_runtime(metadata(architecture), architecture)
            self.assertFalse(contract.compatible_library(self.base / "absent", machine))

    def test_wrong_host_and_missing_library(self):
        with mock.patch.object(contract.platform, "machine", return_value="aarch64"):
            with self.assertRaisesRegex(contract.ContractError, "architecture"):
                contract.validate_runtime(metadata(), "amd64")
        with mock.patch.object(contract.platform, "system", return_value="Linux"), \
                mock.patch.object(contract.platform, "machine", return_value="x86_64"), \
                mock.patch.object(contract, "host_glibc", return_value=(2, 36, 0)), \
                mock.patch.object(contract.os, "access", return_value=True), \
                mock.patch.object(contract, "compatible_library", side_effect=lambda path, machine: str(path).startswith("/lib64/")), \
                mock.patch.object(contract, "library_candidates", return_value={"libc.so.6": [Path("/missing")]}):
            with self.assertRaisesRegex(contract.ContractError, "library"):
                contract.validate_runtime(metadata(), "amd64")

    def test_getconf_and_ctypes_fallback(self):
        completed = subprocess.CompletedProcess([], 0, stdout="glibc 2.36\n")
        with mock.patch.object(contract.subprocess, "run", return_value=completed) as run:
            self.assertEqual(contract.host_glibc(), (2, 36, 0))
            self.assertEqual(run.call_args.args[0], ["/usr/bin/getconf", "GNU_LIBC_VERSION"])
        libc = mock.Mock()
        libc.gnu_get_libc_version.return_value = b"2.35"
        with mock.patch.object(contract.subprocess, "run", side_effect=FileNotFoundError), \
                mock.patch.object(contract.ctypes, "CDLL", return_value=libc) as load:
            self.assertEqual(contract.host_glibc(), (2, 35, 0))
            load.assert_called_once_with(None)

    def test_ldconfig_soname_map_and_fallback_paths(self):
        completed = subprocess.CompletedProcess([], 0, stdout=" libssl.so.3 (libc6,x86-64) => /lib/x86_64-linux-gnu/libssl.so.3\n")
        with mock.patch.object(contract.subprocess, "run", return_value=completed) as run:
            paths = contract.library_candidates(["libssl.so.3"], "amd64")
            self.assertIn(Path("/lib/x86_64-linux-gnu/libssl.so.3"), paths["libssl.so.3"])
            self.assertEqual(run.call_args.args[0], ["/sbin/ldconfig", "-p"])
        with mock.patch.object(contract.subprocess, "run", side_effect=FileNotFoundError):
            paths = contract.library_candidates(["libc.so.6"], "arm64")
            self.assertIn(Path("/lib/aarch64-linux-gnu/libc.so.6"), paths["libc.so.6"])

    def test_secure_destination_rejects_writable_symlink_and_wrong_owner(self):
        for mode, owner in ((stat.S_IFDIR | 0o777, 0), (stat.S_IFLNK | 0o755, 0),
                            (stat.S_IFDIR | 0o755, 1000)):
            info = mock.Mock(st_mode=mode, st_uid=owner)
            with mock.patch.object(contract.os, "geteuid", return_value=0), \
                    mock.patch.object(Path, "lstat", return_value=info), self.assertRaises(contract.ContractError):
                contract.secure_directory(Path("/opt/releases"))


class ConfigTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        self.state = self.base / "state"
        self.state.mkdir()
        self.templates = self.base / "templates"
        self.templates.mkdir()
        (self.templates / contract.DEFAULT_TEMPLATE).write_text("{}")
        self.config = self.base / "candidate.toml"
        self.options = {"config": self.config, "state_dir": self.state, "templates_dir": self.templates,
                        "health_url": "http://127.0.0.1:8090/health", "capabilities": [], "device_paths": [],
                        "allow_unauthenticated_nonloopback": False, "exposure_policy": ""}
        environment = mock.patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def write(self, extra="", host="127.0.0.1", template=None):
        self.config.write_text(f'[rest]\nlisten_host = "{host}"\n[templates]\ntemplate_dir = {json.dumps(str(self.templates))}\n'
                               + (f'default_template = {json.dumps(template)}\n' if template else "") + extra)

    def check(self):
        return contract.config_contract(**self.options)

    def test_minimal_safe_config_uses_real_defaults(self):
        self.write()
        self.assertEqual(self.check(), {"listeners": [{"host": "127.0.0.1", "port": 8090, "protocol": "tcp"}]})
        self.assertFalse((self.state / "data").exists())

    def test_missing_template_and_static_dependency(self):
        self.write(template="missing.tera")
        with self.assertRaises(contract.ContractError):
            self.check()
        self.write()
        (self.templates / contract.DEFAULT_TEMPLATE).write_text('{% include "missing.tera" %}')
        with self.assertRaises(contract.ContractError):
            self.check()
        (self.templates / "missing.tera").write_text("okay")
        self.check()

    def test_template_mismatch_and_escape(self):
        self.write()
        self.options["templates_dir"] = self.state
        with self.assertRaisesRegex(contract.ContractError, "mismatch"):
            self.check()
        self.options["templates_dir"] = self.templates
        self.write(template="../candidate.toml")
        with self.assertRaises(contract.ContractError):
            self.check()

    def test_storage_and_identity_state_escape(self):
        for path in ("../outside.db", str(self.base / "outside.db"), "file:/outside.db"):
            self.write(f'[storage]\npath = {json.dumps(path)}\n')
            with self.subTest(path=path), self.assertRaisesRegex(contract.ContractError, "escapes"):
                self.check()
        self.write()
        (self.state / "data").symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(contract.ContractError, "escapes"):
            self.check()

    def test_identity_file_symlink_escape(self):
        (self.state / "data").mkdir()
        (self.base / "private-key").write_text("identity")
        (self.state / "data/nostr.key").symlink_to(self.base / "private-key")
        self.write()
        with self.assertRaisesRegex(contract.ContractError, "escapes"):
            self.check()

    def test_identity_hardlink_is_rejected(self):
        (self.state / "data").mkdir()
        (self.base / "private-key").write_text("identity")
        os.link(self.base / "private-key", self.state / "data/nostr.key")
        self.write()
        with self.assertRaisesRegex(contract.ContractError, "escapes"):
            self.check()

    def test_existing_database_symlink_escape(self):
        (self.state / "data").mkdir()
        (self.base / "outside.db").write_bytes(b"")
        (self.state / "data/openalert.db").symlink_to(self.base / "outside.db")
        self.write()
        with self.assertRaisesRegex(contract.ContractError, "escapes"):
            self.check()

    def test_unwritable_state(self):
        self.write()
        with mock.patch.object(contract.os, "access", return_value=False), self.assertRaises(contract.ContractError):
            self.check()

    def test_nonloopback_exception_requires_explicit_policy(self):
        self.write(host="0.0.0.0")
        with self.assertRaisesRegex(contract.ContractError, "exposure"):
            self.check()
        self.options["allow_unauthenticated_nonloopback"] = True
        with self.assertRaisesRegex(contract.ContractError, "policy"):
            self.check()
        self.options["exposure_policy"] = "Isolated emergency VLAN; ingress ACL managed externally."
        self.check()

    def test_rest_auth_does_not_protect_dashboard_or_sos(self):
        rest = '[rest.auth]\ntype = "bearer"\ntoken_hash = "' + "a" * 64 + '"\n'
        dashboard = '[dashboard.auth]\nenabled = true\nusername = "admin"\npassword_hash = "' + "b" * 64 + '"\n'
        self.write(rest, host="0.0.0.0")
        with self.assertRaisesRegex(contract.ContractError, "HTTP exposure"):
            self.check()
        self.write(rest + dashboard, host="0.0.0.0")
        with self.assertRaisesRegex(contract.ContractError, "SOS exposure"):
            self.check()
        self.write(rest + dashboard + '[sos]\nenabled = false\n', host="0.0.0.0")
        self.check()

    def test_malformed_auth_and_config(self):
        for extra in ('[rest.auth]\ntype = "bearer"\ntoken_hash = "bad"\n',
                      '[dashboard.auth]\nenabled = "false"\n', '[storage]\nenabled = "false"\n'):
            self.write(extra)
            with self.subTest(extra=extra), self.assertRaises(contract.ContractError):
                self.check()
        self.config.write_text('secret = "DO-NOT-PRINT"\nbroken = [')
        with self.assertRaises(ValueError):
            self.check()

    def test_health_url_consistency(self):
        self.write()
        for url in ("http://127.0.0.1:8091/health", "https://127.0.0.1:8090/health",
                    "http://192.0.2.1:8090/health", "http://[::1]:8090/health",
                    "http://user:secret@127.0.0.1:8090/health", "http://127.0.0.1:8090/health?secret=1"):
            self.options["health_url"] = url
            with self.subTest(url=url), self.assertRaises(contract.ContractError):
                self.check()

    def test_relay_and_peering_listeners(self):
        self.write('[nostr.relay_server]\nenabled = true\nbind_address = "[::1]:8088"\n'
                   '[peering]\nenabled = true\nshared_key = "' + "a" * 64 + '"\n'
                   '[peering.time_sync]\nstep_system_clock = false\n')
        result = self.check()
        self.assertEqual(result["listeners"][1], {"host": "::1", "port": 8088, "protocol": "tcp"})
        self.assertEqual(result["listeners"][2], {"host": "0.0.0.0", "port": 9876, "protocol": "udp"})

    def test_clock_and_ble_require_declarations(self):
        for extra, capabilities in (('[peering]\nenabled = true\nshared_key = "' + "a" * 64 + '"\n', ["CAP_SYS_TIME"]),
                                    ('[bitchat]\nenabled = true\n', ["CAP_NET_ADMIN", "CAP_NET_RAW"])):
            self.write(extra)
            self.options["capabilities"] = []
            with self.assertRaises(contract.ContractError):
                self.check()
            self.options["capabilities"] = capabilities
            self.check()

    def test_serial_features_require_declared_accessible_character_devices(self):
        extras = ('[sms]\nenabled = true\nport = "/dev/ttyUSB2"\n',
                  '[peering]\nenabled = true\nshared_key = "' + "a" * 64 + '"\n'
                  '[peering.time_sync]\nstep_system_clock = false\n'
                  '[[peering.nodes]]\nname = "radio"\nlink_type = "lora_serial"\nserial_device = "/dev/ttyUSB2"\n')
        for extra in extras:
            self.write(extra)
            self.options["device_paths"] = []
            with self.assertRaisesRegex(contract.ContractError, "declared"):
                self.check()
            self.options["device_paths"] = ["/dev/ttyUSB2"]
            original = Path.stat
            device_stat = mock.Mock(st_mode=stat.S_IFCHR | 0o660)
            with mock.patch.object(Path, "stat", autospec=True,
                                   side_effect=lambda path, **kw: device_stat if str(path) == "/dev/ttyUSB2" else original(path, **kw)), \
                    mock.patch.object(contract.os, "access", return_value=True):
                self.check()
                device_stat.st_mode = stat.S_IFREG | 0o660
                with self.assertRaisesRegex(contract.ContractError, "inaccessible"):
                    self.check()

    def test_environment_overrides_are_rejected(self):
        self.write()
        with mock.patch.dict(os.environ, {"OPENALERT_REST__LISTEN_HOST": "0.0.0.0"}):
            with self.assertRaisesRegex(contract.ContractError, "environment"):
                self.check()

    def test_config_cli_api(self):
        self.write()
        args = ["config"]
        for name, value in self.options.items():
            args.extend(["--" + name.replace("_", "-"), json.dumps(value) if isinstance(value, (list, bool)) else str(value)])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(contract.main(args), 0)
        self.assertEqual(json.loads(output.getvalue()), self.check())

    def test_malformed_toml_cli_does_not_disclose_secrets(self):
        self.config.write_text('password = "DO-NOT-PRINT"\nbroken = [')
        args = ["config"]
        for name, value in self.options.items():
            args.extend(["--" + name.replace("_", "-"), json.dumps(value) if isinstance(value, (list, bool)) else str(value)])
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(contract.main(args), 1)
        self.assertEqual(json.loads(errors.getvalue()), {"error": "deployment contract validation failed"})


class ListenerTests(unittest.TestCase):
    def records(self, *listeners):
        return [{"listeners": [contract.listener(host, port, protocol)]} for host, port, protocol in listeners]

    def test_conflicts_include_ipv6_and_localhost(self):
        for a, b in (("127.0.0.1", "127.0.0.1"), ("0.0.0.0", "127.0.0.1"),
                     ("::", "::1"), ("::", "127.0.0.1"), ("::1", "localhost"),
                     ("localhost", "127.0.0.1"), ("::ffff:127.0.0.1", "127.0.0.1")):
            with self.subTest(a=a, b=b), self.assertRaisesRegex(contract.ContractError, "conflict"):
                contract.listeners_contract(self.records((a, 8090, "tcp"), (b, 8090, "tcp")))

    def test_distinct_ports_addresses_and_protocols(self):
        records = self.records(("127.0.0.1", 8090, "tcp"), ("127.0.0.1", 8091, "tcp"),
                               ("127.0.0.1", 8090, "udp"), ("127.0.0.2", 8090, "tcp"),
                               ("::1", 8090, "tcp"))
        self.assertEqual(len(contract.listeners_contract(records)["listeners"]), 5)

    def test_invalid_listener_input(self):
        for value in ({}, ["secret"], [{"listeners": "secret"}], [{"listeners": [{}]}],
                      [{"listeners": [{"host": "host.example", "port": 8090, "protocol": "tcp"}]}],
                      [{"listeners": [{"host": "127.0.0.1", "port": True, "protocol": "tcp"}]}]):
            with self.subTest(value=value), self.assertRaises(contract.ContractError):
                contract.listeners_contract(value)


class CliTests(TemporaryCase):
    def test_listeners_input_api(self):
        path = self.base / "listeners.json"
        path.write_text('[{"listeners":[{"host":"127.0.0.1","port":8090,"protocol":"tcp"}]}]')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(contract.main(["listeners", "--input", str(path)]), 0)
        self.assertEqual(json.loads(output.getvalue())["listeners"][0]["port"], 8090)

    def test_cli_errors_are_generic_and_do_not_echo_inputs(self):
        for args in (["config", "--secret-password"], ["listeners", "--input", "SECRET-PATH"],
                     ["archive", "--archive", "SECRET", "--sha256", "bad", "--architecture", "amd64",
                      "--destination", "relative"]):
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                self.assertEqual(contract.main(args), 1)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(json.loads(errors.getvalue()), {"error": "deployment contract validation failed"})


class DisposableRunnerTests(TemporaryCase):
    def setUp(self):
        super().setUp()
        path = Path(__file__).with_name("run_disposable.py")
        spec = importlib.util.spec_from_file_location("run_disposable", path)
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)
        (self.base / "tests").mkdir()
        self.bundle = self.base / "bundle.tar.gz"
        self.bundle.touch()
        self.starts = {"openalertd.service": "100", "openalertd-public.service": "200"}
        self.level = "info"
        self.failure_override = None
        self.loop_failure = False
        self.bad_restart = False
        self.bad_mutation = False
        self.leak = None
        self.deployments = []

    def command(self, arguments, **kwargs):
        values = json.loads(arguments[arguments.index("-e") + 1])
        output, errors, rc, changed = "", "", 0, 0
        if str(self.base / "site.yml") in arguments:
            self.deployments.append(values)
            instances = values["openalert_instances"]
            failure = None
            if "conflictprobe" in instances:
                failure = "Refuse to overwrite unmanaged units or state"
            elif len({item["service_name"] for item in instances.values()}) != len(instances):
                failure = "Reject duplicate service identities and paths"
            elif values["openalert_release"]["sha256"] == "0" * 64:
                failure = "Reject absent or corrupt controller-local archive"
            elif instances["hub"].get("rest_host") or instances["hub"].get("default_template"):
                failure = "Check assets, state, permissions and exposure as service account"
            elif len({item["rest_port"] for item in instances.values()}) != len(instances):
                failure = "Reject conflicting listeners before activation"
            if failure:
                rc = 2
                changed = int(self.bad_mutation)
                status = "failed: [test] (item=service_name) => {}" if self.loop_failure else "fatal: [test]: FAILED! => {}"
                output = f"TASK [openalert : {self.failure_override or failure}] ****\n{status}\n"
                if self.bad_restart:
                    self.starts["openalertd-public.service"] = "999"
            else:
                level = instances["hub"].get("log_level", "info")
                if level != self.level:
                    self.starts["openalertd.service"] = "300"
                    self.level = level
        elif str(self.base / "tests/inspect.yml") in arguments:
            Path(values["test_record_path"]).write_text(json.dumps({
                "starts": self.starts, "packages": "libc6\n", "python_workspace": False,
            }))
        elif "/dev/stdin" in arguments:
            for task in json.loads(kwargs["input"])[0]["tasks"]:
                if "ansible.builtin.copy" in task:
                    Path(task["ansible.builtin.copy"]["dest"]).write_text('["LoadState=loaded", "ActiveState=active"]')
        else:
            self.fail("Unexpected subprocess invocation")
        output += f"PLAY RECAP ****\ntest : ok=1 changed={changed} unreachable=0 failed={int(rc != 0)}\n"
        if self.leak == "stdout":
            output += self.runner.SENTINEL
        elif self.leak == "stderr":
            errors += self.runner.SENTINEL
        elif self.leak == "ansible.log":
            Path(kwargs["env"]["ANSIBLE_LOG_PATH"]).write_text(self.runner.SENTINEL)
        return subprocess.CompletedProcess(arguments, rc, output, errors)

    def invoke(self, *scenarios):
        arguments = ["run_disposable.py", "--bundle", str(self.bundle), "--sha256", "1" * 64,
                     "--inventory", str(self.base / "inventory.yml"), "--host", "test", "--allow-disposable-changes"]
        for scenario in scenarios:
            arguments.extend(["--scenario", scenario])
        output = io.StringIO()
        with mock.patch.object(self.runner, "ROOT", self.base), mock.patch.object(self.runner.sys, "argv", arguments), \
                mock.patch.object(self.runner.subprocess, "run", side_effect=self.command), contextlib.redirect_stdout(output):
            self.runner.main()
        return output.getvalue()

    def test_selected_scenarios_do_not_run_core_suite(self):
        output = self.invoke("unsafe-exposure", "secret-redaction", "unmanaged-unit", "duplicate-unit", "duplicate-unit")
        self.assertIn("PASS 4 scenarios", output)
        self.assertEqual(len(self.deployments), 5)
        self.assertNotIn("PASS one-instance-change", output)
        for values in self.deployments:
            self.assertTrue(all(item["synthetic_secret_sentinel"] == self.runner.SENTINEL
                                for item in values["openalert_instances"].values()))

    def test_default_preserves_all_eleven_scenarios(self):
        output = self.invoke()
        self.assertIn("PASS 11 scenarios", output)
        self.assertEqual(len(self.deployments), 11)
        for scenario in self.runner.SCENARIOS:
            self.assertIn(f"PASS {scenario}\n", output)

    def test_leaks_in_stdout_stderr_and_ansible_log_fail(self):
        for stream in ("stdout", "stderr", "ansible.log"):
            self.leak = stream
            with self.subTest(stream=stream), self.assertRaisesRegex(AssertionError, "Synthetic secret leaked"):
                self.invoke("secret-redaction")
            for path in (self.base / "tests/.runtime").glob("*.log"):
                path.unlink()

    def test_unrelated_failure_is_not_accepted_as_safety_rejection(self):
        self.failure_override = "Some unrelated task"
        with self.assertRaisesRegex(AssertionError, "outside the expected safety check"):
            self.invoke("duplicate-unit")

    def test_loop_task_failure_is_accepted_only_at_expected_safety_check(self):
        self.loop_failure = True
        self.assertIn("PASS duplicate-unit", self.invoke("duplicate-unit"))
        self.failure_override = "Some unrelated task"
        with self.assertRaisesRegex(AssertionError, "outside the expected safety check"):
            self.invoke("duplicate-unit")

    def test_negative_case_detects_restart_of_either_service(self):
        self.bad_restart = True
        with self.assertRaisesRegex(AssertionError, "disturbed services"):
            self.invoke("unsafe-exposure")

    def test_unmanaged_conflict_requires_mutation_free_rejection(self):
        self.bad_mutation = True
        with self.assertRaisesRegex(AssertionError, "not mutation-free"):
            self.invoke("unmanaged-unit")


if __name__ == "__main__":
    unittest.main()