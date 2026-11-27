"""Offline Tucny contracts; no downloads, RPM installs, live inventory or SSH."""

import configparser
import hashlib
import json
import os
import subprocess
import sys
import unittest

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml

import test_pbx_roles as pbx


class TucnyContractTests(unittest.TestCase):
    def test_tucny_loads_separately_built_module_dependencies(self):
        environment = NativeEnvironment(undefined=StrictUndefined)
        template = environment.from_string((pbx.ROLE / "templates/modules_allstarlink.conf.j2").read_text())
        for provider in ("allstarlink", "tucny"):
            rendered = template.render(asterisk_package_provider=provider,
                                       asterisk_sip_trunk_enabled=False, local_iax=True)
            for module in ("res_speech", "res_geolocation", "res_agi", "res_statsd", "res_crypto"):
                self.assertEqual(f"load={module}.so" in rendered, provider == "tucny")
            self.assertIn("autoload=no", rendered)
            self.assertIn("require=chan_pjsip.so", rendered)
            self.assertIn("require=chan_iax2.so", rendered)

    def test_reviewed_pins_and_vendored_key(self):
        defaults = pbx.load_yaml(pbx.ROLE / "defaults/main.yml")
        self.assertEqual(defaults["asterisk_package_provider"], "distro")
        self.assertEqual(defaults["asterisk_tucny_version"], "22.9.0-1.el10")
        self.assertEqual(defaults["asterisk_tucny_sounds_version"], "1.6.1-1.el10")
        self.assertEqual(hashlib.sha256((pbx.ROLE / "files/RPM-GPG-KEY-tucnyastrepo").read_bytes()).hexdigest(),
                         "f7864d4fefd63ebe56c997dfe8d6c716c8d524e7391de0aece1caee4b88ac011")
        install = pbx.tasks("install_tucny.yml")
        self.assertNotIn("ansible.builtin.rpm_key", str(install))
        key = next(t for t in install if "block" in t)
        self.assertEqual(key["when"], "not ansible_check_mode")
        assertions = [t["ansible.builtin.assert"]["that"] for t in key["block"]
                      if "ansible.builtin.assert" in t]
        self.assertEqual(len(assertions), 3)
        for conditions in assertions:
            self.assertIn("F323210FB8EAC82E8F2C5262EFE47D937C0C1849", str(conditions))
            self.assertIn("^pub:", str(conditions))
            self.assertIn("length == 1", str(conditions))
        for task in key["block"]:
            if "ansible.builtin.command" not in task:
                continue
            argv = task["ansible.builtin.command"]["argv"]
            if argv[:2] == ["rpmkeys", "--import"]:
                self.assertIn(".rc == 1", task["when"])
            else:
                self.assertIs(task["changed_when"], False)
                self.assertIn(argv[0], ("gpg", "rpm"))
                if argv[0] == "rpm":
                    self.assertEqual(argv, ["rpm", "-q", "gpg-pubkey-7c0c1849", "--qf", "%{DESCRIPTION}\n"])
        self.assertLess(install.index(key), next(i for i, t in enumerate(install) if "ansible.builtin.yum_repository" in t))

    def test_repositories_are_enabled_narrow_and_explicit_about_unsigned_metadata(self):
        task = next(t for t in pbx.tasks("install_tucny.yml") if "ansible.builtin.yum_repository" in t)
        repo = task["ansible.builtin.yum_repository"]
        for field in ("enabled", "gpgcheck", "sslverify"):
            self.assertIs(repo[field], True)
        self.assertIs(repo["repo_gpgcheck"], False)
        self.assertIs(repo["skip_if_unavailable"], False)
        self.assertEqual(repo["baseurl"], "https://ast.tucny.com/repo/{{ item.directory }}/el10/x86_64/")
        self.assertEqual([item["packages"] for item in task["loop"]], [
            ["asterisk", "asterisk-pjsip", "asterisk-curl", "asterisk-iax2"],
            ["asterisk-sounds-core-en", "asterisk-sounds-core-en-wav"],
        ])

    def test_dnf_exact_versions_dependencies_and_optional_iax_without_removal(self):
        installs = [t["ansible.builtin.dnf"] for t in pbx.tasks("install_tucny.yml") if "ansible.builtin.dnf" in t]
        bootstrap, install = installs
        self.assertEqual(bootstrap["enablerepo"], ["baseos", "appstream", "extras"])
        self.assertIn("epel-release", bootstrap["name"])
        self.assertIn("gnupg2", bootstrap["name"])
        for task in installs:
            self.assertEqual(task["state"], "present")
            self.assertEqual(task["disablerepo"], ["*"])
            self.assertIs(task["disable_gpg_check"], False)
            self.assertIs(task["sslverify"], True)
            self.assertIs(task["allowerasing"], False)
            self.assertIs(task["install_weak_deps"], False)
        self.assertIs(install["allow_downgrade"], False)
        self.assertIs(install["skip_broken"], False)
        environment = NativeEnvironment(undefined=StrictUndefined)
        defaults = pbx.load_yaml(pbx.ROLE / "defaults/main.yml")
        for enabled, installed, expected in ((False, {}, False), (True, {}, True),
                                              (False, {"asterisk-iax2": [{}]}, True)):
            packages = environment.from_string(install["name"]).render(defaults | {
                "local_iax": enabled, "ansible_facts": {"packages": installed},
            })
            self.assertIn("asterisk-22.9.0-1.el10.x86_64", packages)
            self.assertIn("asterisk-pjsip-22.9.0-1.el10.x86_64", packages)
            self.assertIn("asterisk-curl-22.9.0-1.el10.x86_64", packages)
            self.assertIn("asterisk-sounds-core-en-wav-1.6.1-1.el10.noarch", packages)
            self.assertEqual("asterisk-iax2-22.9.0-1.el10.x86_64" in packages, expected)
            self.assertEqual(len(packages), 6 if expected else 5)

    def test_legacy_copr_compiler_and_tarball_paths_cannot_run_for_tucny(self):
        main = pbx.tasks("main.yml")
        guard = next(i for i, t in enumerate(main) if t.get("ansible.builtin.import_tasks") == "provider_guard.yml")
        preflight = next(i for i, t in enumerate(main) if t.get("ansible.builtin.include_tasks") == "preflight.yml")
        self.assertLess(guard, preflight)
        self.assertEqual(pbx.tasks("install_tucny.yml")[0]["ansible.builtin.include_tasks"], "tucny_version_guard.yml")
        for task in pbx.tasks("install_RedHat.yml")[1:]:
            self.assertIn("asterisk_package_provider == 'distro'", task["when"])
        for filename in ("preflight.yml", "configure.yml"):
            for task in pbx.tasks(filename):
                if "standard_sounds_check" in str(task):
                    self.assertIn("asterisk_package_provider == 'distro'", task["when"])
        for filename in ("install_tucny.yml", "configure_tucny.yml"):
            text = (pbx.ROLE / "tasks" / filename).read_text()
            for forbidden in ("Development Tools", "-devel", "copr", "unarchive", "get_url", "ansible.builtin.user", "state: absent"):
                self.assertNotIn(forbidden, text)
        self.assertIn("/usr/share/asterisk/sounds/beep.wav", str(pbx.tasks("configure_tucny.yml")))

    def test_disposable_package_queries_retain_debian_and_add_rpm_evidence(self):
        selected = next(t for t in pbx.load_yaml(pbx.ANSIBLE / "tests/pbx-disposable.yml")[-1]["tasks"]
                        if t["name"] == "Read exact installed PBX package versions")
        environment = NativeEnvironment(undefined=StrictUndefined)
        query = environment.from_string(selected["ansible.builtin.command"]["argv"])
        for provider, command in (("distro", "dpkg-query"), ("allstarlink", "dpkg-query"), ("tucny", "rpm")):
            arguments = query.render(asterisk_package_provider=provider)
            self.assertEqual(arguments[0], command)
            if provider == "tucny":
                self.assertEqual(arguments[4:], ["asterisk", "asterisk-pjsip", "asterisk-curl", "asterisk-iax2",
                                                "asterisk-sounds-core-en", "asterisk-sounds-core-en-wav"])
            elif provider == "allstarlink":
                self.assertEqual(arguments[3:], ["asl3-asterisk", "asl3-asterisk-modules", "asl3-asterisk-config"])
            else:
                self.assertEqual(arguments[3:], ["asterisk", "asterisk-modules"])


class TucnyOfflineAnsibleTests(unittest.TestCase):
    setUp = pbx.PbxOfflineAnsibleTests.setUp
    run_playbook = pbx.PbxOfflineAnsibleTests.run_playbook

    def variables(self):
        return pbx.load_yaml(pbx.ROLE / "defaults/main.yml") | {
            "ansible_facts": {"os_family": "RedHat", "distribution": "Rocky",
                              "distribution_major_version": "10", "architecture": "x86_64", "packages": {}},
            "asterisk_package_provider": "tucny", "asterisk_http_bindaddr": "127.0.0.1",
            "asterisk_sip_trunk_enabled": False, "ari_password": "SYNTHETIC_TUCNY_ARI_SECRET",
            "asterisk_sounds_dir": str(self.root / "missing-sounds"),
        }

    def execute(self, selected, variables, succeeds=True, check=True):
        playbook = self.root / "tucny.yml"
        playbook.write_text(yaml.safe_dump([{
            "hosts": "all", "gather_facts": False, "vars": variables, "tasks": selected,
        }]))
        result = self.run_playbook(playbook, "--diff", *(["--check"] if check else []))
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode == 0, succeeds, output)
        for text in (output, (self.root / "ansible.log").read_text()):
            self.assertNotIn("SYNTHETIC_TUCNY_ARI_SECRET", text)
            self.assertNotIn("SYNTHETIC_TUCNY_IAX_SECRET", text)
        if check:
            self.assertRegex(output, r"changed=0\s")
        return output

    def test_real_preflight_platform_secrets_and_exact_versions(self):
        base = self.variables()
        facts = base["ansible_facts"]
        cases = [
            ({}, True),
            ({"asterisk_http_bindaddr": "::1"}, True),
            ({"local_iax": True, "local_iax_pass": "SYNTHETIC_TUCNY_IAX_SECRET"}, True),
            ({"ansible_facts": facts | {"architecture": "aarch64"}}, False),
            ({"ansible_facts": facts | {"distribution": "AlmaLinux"}}, True),
            ({"ansible_facts": facts | {"distribution": "Fedora"}}, False),
            ({"ansible_facts": facts | {"distribution_major_version": "9"}}, False),
            ({"ansible_facts": facts | {"distribution": "Ubuntu", "os_family": "Debian"}}, False),
            ({"py_phone_caller_connectivity": "airgapped"}, False),
            ({"asterisk_tucny_version": "latest"}, False),
            ({"asterisk_tucny_version": "22.*"}, False),
            ({"asterisk_tucny_version": "23.0.0-1.el10"}, False),
            ({"asterisk_tucny_version": "22.11.0-1.el10\n"}, False),
            ({"asterisk_tucny_sounds_version": "1.6.1"}, False),
            ({"asterisk_http_bindaddr": "0.0.0.0"}, False),
            ({"ari_password": "change_me"}, False),
            ({"ari_password": "secret-long;config-comment"}, False),
            ({"asterisk_sip_trunk_enabled": True}, False),
        ]
        for overrides, succeeds in cases:
            with self.subTest(overrides=overrides):
                self.execute([{"ansible.builtin.import_tasks": str(pbx.ROLE / "tasks/preflight.yml")}],
                             base | overrides, succeeds)

    def test_real_ownership_guards_reject_unmanaged_packages_paths_and_provider_switch(self):
        selected = [t for t in pbx.tasks("provider_guard.yml") if "ansible.builtin.package_facts" not in t]
        for task in selected:
            if "ansible.builtin.stat" in task:
                if "loop" in task:
                    task["loop"] = [str(self.root / "unmanaged" / path.lstrip("/")) for path in task["loop"]]
                else:
                    task["ansible.builtin.stat"]["path"] = str(self.root / "provider")
            if "ansible.builtin.slurp" in task:
                task["ansible.builtin.slurp"]["src"] = str(self.root / "provider")
        base = self.variables()
        cases = [
            (None, {}, "tucny", True),
            (None, {"asterisk": [{}]}, "tucny", False),
            (None, {"asterisk-pjsip": [{}]}, "tucny", False),
            (None, {"asl3-asterisk": [{}]}, "tucny", False),
            ("distro", {}, "tucny", False),
            ("tucny", {"asterisk": [{}]}, "tucny", True),
            ("tucny", {"asterisk": [{}]}, "distro", False),
            ("tucny", {}, "allstarlink", False),
        ]
        for marker, packages, provider, succeeds in cases:
            with self.subTest(marker=marker, packages=packages, provider=provider):
                if marker:
                    (self.root / "provider").write_text(marker + "\n")
                else:
                    (self.root / "provider").unlink(missing_ok=True)
                self.execute(selected, base | {"asterisk_package_provider": provider,
                                              "ansible_facts": base["ansible_facts"] | {"packages": packages}}, succeeds)
        (self.root / "provider").unlink()
        (self.root / "unmanaged/etc/asterisk").mkdir(parents=True)
        self.execute(selected, base, False)

    def test_real_version_guard_allows_explicit_upgrade_but_never_downgrade(self):
        base = self.variables()
        rpm = {"version": "22.9.0", "release": "1.el10", "epoch": None, "arch": "x86_64"}
        cases = [
            ({}, True),
            ({"asterisk": [rpm]}, True),
            ({"asterisk": [rpm | {"version": "22.8.2"}]}, True),
            ({"asterisk": [rpm | {"version": "22.10.1"}]}, False),
            ({"asterisk": [rpm | {"release": "2.el10"}]}, False),
            ({"asterisk": [rpm | {"epoch": 1}]}, False),
            ({"asterisk": [rpm | {"arch": "aarch64"}]}, False),
            ({"asterisk": [rpm | {"release": "1.el9"}]}, False),
            ({"asterisk-sounds-core-en-wav": [{"version": "1.6.2", "release": "1.el10", "arch": "noarch"}]}, False),
        ]
        for packages, succeeds in cases:
            with self.subTest(packages=packages):
                self.execute([{"ansible.builtin.import_tasks": str(pbx.ROLE / "tasks/tucny_version_guard.yml")}],
                             base | {"ansible_facts": base["ansible_facts"] | {"packages": packages}}, succeeds)

    def test_real_repository_render_is_idempotent_without_network(self):
        selected = [t for t in pbx.tasks("install_tucny.yml") if "ansible.builtin.yum_repository" in t]
        selected[0]["ansible.builtin.yum_repository"]["reposdir"] = str(self.root)
        for rerun in (False, True):
            output = self.execute(selected, self.variables(), check=False)
            if rerun:
                self.assertRegex(output, r"changed=0\s")
        config = configparser.ConfigParser()
        config.read(self.root / "py-phone-caller-tucny.repo")
        self.assertEqual(set(config.sections()), {"py-phone-caller-tucny-22", "py-phone-caller-tucny-common"})
        for section in config.values():
            if not section:
                continue
            self.assertTrue(section.getboolean("enabled"))
            self.assertTrue(section.getboolean("gpgcheck"))
            self.assertTrue(section.getboolean("sslverify"))
            self.assertFalse(section.getboolean("repo_gpgcheck"))
            self.assertNotIn("*", section["includepkgs"])

    def test_disposable_exact_rpm_assertions_reject_version_drift(self):
        selected = next(t for t in pbx.load_yaml(pbx.ANSIBLE / "tests/pbx-disposable.yml")[-1]["tasks"]
                        if t["name"] == "Require exact reviewed Tucny package versions and architectures")
        packages = {name: [{"version": "1.6.1" if name.startswith("asterisk-sounds-") else "22.9.0",
                           "release": "1.el10", "epoch": None,
                           "arch": "noarch" if name.startswith("asterisk-sounds-") else "x86_64"}]
                    for name in selected["loop"]}
        base = self.variables()
        base["ansible_facts"]["packages"] = packages
        base["asterisk_py_phone_caller_tucny_test_defaults"] = pbx.load_yaml(pbx.ROLE / "defaults/main.yml")
        self.execute([selected], base)
        packages["asterisk"][0]["version"] = "22.8.2"
        self.execute([selected], base, False)

    def test_real_private_roots_and_partials_are_idempotent_and_secret_safe(self):
        configuration = self.root / "asterisk"
        configuration.mkdir()
        selected = pbx.tasks("configure_tucny.yml")[:2]
        selected += [t for t in pbx.tasks("configure.yml") if t["name"] in (
            "Deploy Py-Phone-Caller partial configurations", "Inject Includes into main configuration files",
            "Configure HTTP Server settings", "Ensure ARI general configuration is enabled",
        )]
        for task in selected:
            task.pop("notify", None)
            if "ansible.builtin.template" in task:
                task["ansible.builtin.template"]["src"] = str(pbx.ROLE / "templates") + "/" + task["ansible.builtin.template"]["src"]
        variables = self.variables() | {
            "asterisk_conf_dir": str(configuration), "asterisk_user": str(os.getuid()), "asterisk_group": str(os.getgid()),
            "local_iax": True, "local_iax_exten": 2600, "local_iax_pass": "SYNTHETIC_TUCNY_IAX_SECRET",
        }
        for rerun in (False, True):
            output = self.execute(selected, variables, check=False)
            if rerun:
                self.assertRegex(output, r"changed=0\s")
        for name in ("extensions", "pjsip", "ari", "iax"):
            self.assertEqual((configuration / f"{name}.conf").read_text().count(f"#include {name}_py_phone_caller.conf"), 1)
            self.assertEqual((configuration / f"{name}_py_phone_caller.conf").stat().st_mode & 0o777, 0o640)
        self.assertIn("bindaddr=127.0.0.1", (configuration / "http.conf").read_text())
        self.assertIn("enabled=no", (configuration / "manager.conf").read_text())
        modules = (configuration / "modules.conf").read_text()
        self.assertIn("autoload=no", modules)
        self.assertIn("require=chan_iax2.so", modules)
        for forbidden in ("app_rpt", "chan_echolink", "res_pjsip_outbound_registration"):
            self.assertNotIn(forbidden, modules)


class TucnyKeyImportTests(unittest.TestCase):
    run_playbook = pbx.PbxOfflineAnsibleTests.run_playbook
    execute = TucnyOfflineAnsibleTests.execute

    def setUp(self):
        pbx.PbxOfflineAnsibleTests.setUp(self)
        self.key = self.root / "tucny-key"
        self.key.write_bytes((pbx.ROLE / "files/RPM-GPG-KEY-tucnyastrepo").read_bytes())
        self.gnupg = self.root / "gnupg"
        self.gnupg.mkdir(mode=0o700)
        self.database = self.root / "candidate-key"
        self.calls = self.root / "rpm-calls.jsonl"
        self.rpm = self.root / "rpm-fixture.py"
        self.rpm.write_text('''import json
from pathlib import Path
import sys

root = Path(__file__).parent
args = sys.argv[1:]
with (root / "rpm-calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\\n")
candidate = root / "candidate-key"
if args == ["rpm", "-q", "gpg-pubkey-7c0c1849", "--qf", "%{DESCRIPTION}\\n"]:
    if (root / "database-error").exists():
        print("RPM database error", file=sys.stderr)
        sys.exit(1)
    if candidate.exists():
        sys.stdout.buffer.write(candidate.read_bytes())
    else:
        print("package gpg-pubkey-7c0c1849 is not installed")
        sys.exit(1)
elif args == ["rpmkeys", "--import", str(root / "tucny-key")]:
    if not (root / "lost-import").exists():
        candidate.write_bytes((root / "tucny-key").read_bytes())
else:
    # Enumerating all keys would expose the unrelated unsupported Rocky V6 key.
    print("gpg: packet(6) with unknown version 6", file=sys.stderr)
    sys.exit(2)
''')
        self.selected = [next(t for t in pbx.tasks("install_tucny.yml") if "block" in t)]
        self.selected[0]["environment"] = {"GNUPGHOME": str(self.gnupg)}
        for task in self.selected[0]["block"]:
            command = task.get("ansible.builtin.command")
            if command:
                command["argv"] = [str(self.key) if arg == "/etc/pki/rpm-gpg/RPM-GPG-KEY-py-phone-caller-tucny"
                                   else arg for arg in command["argv"]]
                if command["argv"][0] in ("rpm", "rpmkeys"):
                    command["argv"] = [sys.executable, str(self.rpm)] + command["argv"]

    def commands(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def other_public_key(self):
        result = subprocess.run(["gpg", "--batch", "--homedir", str(self.gnupg), "--dearmor"],
                                input=self.key.read_bytes(), capture_output=True, check=True)
        data = bytearray(result.stdout)
        self.assertEqual(data[0], 0x99)
        self.assertEqual(data[3], 4)
        # Change the V4 public packet timestamp, giving a different full fingerprint.
        data[7] ^= 1
        return bytes(data)

    def test_unrelated_v6_keys_are_never_enumerated_and_rerun_does_not_import(self):
        output = self.execute(self.selected, {}, check=False)
        self.assertRegex(output, r"changed=1\s")
        self.assertEqual(self.database.read_bytes(), self.key.read_bytes())
        output = self.execute(self.selected, {}, check=False)
        self.assertRegex(output, r"changed=0\s")
        commands = self.commands()
        self.assertEqual(sum(args[0] == "rpmkeys" for args in commands), 1)
        self.assertEqual(sum(args[0] == "rpm" for args in commands), 4)
        self.assertTrue(all(args[2] == "gpg-pubkey-7c0c1849" for args in commands if args[0] == "rpm"))

    def test_wrong_vendored_full_fingerprint_prevents_any_rpm_operation(self):
        self.key.write_bytes(self.other_public_key())
        output = self.execute(self.selected, {}, succeeds=False, check=False)
        self.assertIn("The vendored Tucny key must contain only the reviewed primary fingerprint", output)
        self.assertEqual(self.commands(), [])

    def test_multiple_vendored_primary_keys_prevent_import(self):
        self.key.write_bytes(self.key.read_bytes() * 2)
        output = self.execute(self.selected, {}, succeeds=False, check=False)
        self.assertIn("The vendored Tucny key must contain only the reviewed primary fingerprint", output)
        self.assertEqual(self.commands(), [])

    def test_colliding_or_malformed_installed_candidates_fail_closed(self):
        for candidate in (self.other_public_key(), b"malformed key", self.key.read_bytes() * 2):
            with self.subTest(candidate=candidate[:20]):
                # RPM DESCRIPTION is armored text; encode the alternative public packet without importing it.
                if candidate[0] == 0x99:
                    result = subprocess.run(["gpg", "--batch", "--homedir", str(self.gnupg), "--enarmor"],
                                            input=candidate, capture_output=True, check=True)
                    candidate = result.stdout.replace(b"PGP ARMORED FILE", b"PGP PUBLIC KEY BLOCK")
                self.database.write_bytes(candidate)
                self.execute(self.selected, {}, succeeds=False, check=False)
                self.assertFalse(any(args[0] == "rpmkeys" for args in self.commands()))

    def test_postimport_verification_and_database_errors_fail_closed(self):
        (self.root / "lost-import").touch()
        self.execute(self.selected, {}, succeeds=False, check=False)
        self.assertEqual(sum(args[0] == "rpmkeys" for args in self.commands()), 1)
        self.calls.unlink()
        (self.root / "database-error").touch()
        self.execute(self.selected, {}, succeeds=False, check=False)
        self.assertFalse(any(args[0] == "rpmkeys" for args in self.commands()))


if __name__ == "__main__":
    unittest.main()