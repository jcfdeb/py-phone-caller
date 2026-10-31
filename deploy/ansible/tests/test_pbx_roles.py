"""Offline PBX role contracts; never load a live inventory or contact a PBX."""

import configparser
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from ansible.plugins.filter.core import regex_escape
from ansible.plugins.test.core import search
from jinja2 import Environment, FileSystemLoader, StrictUndefined
import yaml


ANSIBLE = Path(__file__).resolve().parents[1]
ROLE = ANSIBLE / "roles" / "asterisk_py_phone_caller"
LEGACY = ANSIBLE / "asterisk_py-phone-caller"


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def tasks(filename):
    return load_yaml(ROLE / "tasks" / filename)


def walk_tasks(items):
    for task in items:
        yield task
        for key in ("block", "rescue", "always"):
            yield from walk_tasks(task.get(key, []))


class PbxCompatibilityTests(unittest.TestCase):
    def test_wrapper_preserves_hosts_and_selects_only_pbx(self):
        plays = load_yaml(LEGACY / "deploy_asterisk.yml")
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0]["ansible.builtin.import_playbook"], "../site.yml")
        variables = plays[0]["vars"]
        self.assertEqual(variables["stack_hosts"], "pbx_servers:all")
        self.assertIs(variables["stack_deploy_asterisk"], True)
        self.assertIs(variables["stack_deploy_python"], False)
        self.assertIs(variables["stack_deploy_openalert"], False)
        self.assertIs(variables["stack_legacy_platform"], True)
        self.assertNotIn("vars_files", plays[0])
        self.assertNotIn("roles", plays[0])
        self.assertNotIn("python_config", str(plays))

    def test_legacy_vault_mapping_and_local_extensions_are_preserved(self):
        variables = load_yaml(LEGACY / "deploy_asterisk.yml")[0]["vars"]
        expected = {
            "ari_password": "{{ vault_ari_password | default('change_me') }}",
            "sip_username": "{{ vault_sip_username | default('py-phone-caller') }}",
            "sip_password": "{{ vault_sip_password | default('py-phone-caller') }}",
            "local_sip": True,
            "local_sip_exten": 2500,
            "local_sip_pass": "{{ vault_local_sip_pass | default('change_me') }}",
            "local_iax": True,
            "local_iax_exten": 2600,
            "local_iax_pass": "{{ vault_local_iax_pass | default('change_me') }}",
        }
        for key, value in expected.items():
            self.assertEqual(variables[key], value)

    def test_config_uses_shared_roles_without_an_implicit_inventory(self):
        config = configparser.ConfigParser()
        config.read(LEGACY / "ansible.cfg")
        self.assertEqual(config["defaults"]["roles_path"], "../roles")
        self.assertNotIn("inventory", config["defaults"])
        self.assertIn("../.collections", config["defaults"]["collections_path"])
        self.assertTrue(config["defaults"].getboolean("host_key_checking"))
        self.assertEqual(config["defaults"]["vars_plugins_enabled"], "host_group_vars,pbx_legacy_vars")

    def test_legacy_requirements_match_root_pins(self):
        requirements = load_yaml(LEGACY / "requirements.yml")
        self.assertEqual(requirements, load_yaml(ANSIBLE / "requirements.yml"))
        for collection in requirements["collections"]:
            self.assertRegex(collection["version"], r"^\d+\.\d+\.\d+$")


class PbxRoleTests(unittest.TestCase):
    def setUp(self):
        self.defaults = load_yaml(ROLE / "defaults" / "main.yml")
        self.environment = Environment(
            loader=FileSystemLoader(ROLE / "templates"), undefined=StrictUndefined
        )

    def test_templates_render_using_only_pbx_defaults(self):
        for local in (False, True):
            variables = self.defaults | {"local_sip": local, "local_iax": local}
            for name in self.environment.list_templates():
                with self.subTest(local=local, template=name):
                    self.assertTrue(self.environment.get_template(name).render(variables).strip() or name == "iax.conf.j2")

    def test_configured_context_flows_to_local_endpoints_and_dialplan(self):
        variables = self.defaults | {
            "asterisk_context": "isolated-pbx",
            "asterisk_extension": "4567",
            "ari_app_name": "isolated-ari",
            "callback_service_url": "http://127.0.0.1:9999",
            "local_sip": True,
            "local_iax": True,
        }
        for name in ("pjsip.conf.j2", "iax.conf.j2"):
            rendered = self.environment.get_template(name).render(variables)
            self.assertIn("context=isolated-pbx", rendered)
            self.assertNotIn("context=py-phone-caller", rendered)
        dialplan = self.environment.get_template("extensions.conf.j2").render(variables)
        self.assertIn("[isolated-pbx]", dialplan)
        self.assertIn("exten => 4567,1", dialplan)
        self.assertIn("Stasis(isolated-ari)", dialplan)
        self.assertIn("http://127.0.0.1:9999/heard", dialplan)
        self.assertIn("http://127.0.0.1:9999/ack", dialplan)

    def test_role_has_no_python_or_other_role_dependencies(self):
        self.assertEqual(load_yaml(ROLE / "meta" / "main.yml")["dependencies"], [])
        for path in (ROLE / "tasks").iterdir():
            text = path.read_text()
            self.assertNotIn("settings.toml", text)
            self.assertNotIn("python_config", text)
            self.assertNotIn("vars_files", text)

    def test_disabled_trunk_has_no_registration_or_external_peer(self):
        rendered = self.environment.get_template("pjsip.conf.j2").render(
            self.defaults | {"asterisk_sip_trunk_enabled": False, "local_sip": True}
        )
        self.assertNotIn("type=registration", rendered)
        self.assertNotIn(self.defaults["sip_provider_host"], rendered)
        self.assertIn("type=endpoint", rendered)
        self.assertIn("context=py-phone-caller", rendered)

    def test_partial_includes_remain_non_destructive(self):
        include = next(t for t in tasks("configure.yml") if t.get("ansible.builtin.lineinfile", {}).get("line", "").startswith("#include"))
        expected = {"extensions.conf", "pjsip.conf", "ari.conf", "iax.conf"}
        self.assertEqual({item["file"] for item in include["loop"]}, expected)
        self.assertIs(include["diff"], False)
        self.assertIs(include["no_log"], True)
        template = next(t for t in tasks("configure.yml") if "ansible.builtin.template" in t)
        self.assertEqual({item["dest"] for item in template["loop"]}, {name.replace(".conf", "_py_phone_caller.conf") for name in expected})

    def test_credentials_are_never_logged_or_diffed(self):
        for task in tasks("configure.yml"):
            if "ansible.builtin.template" in task or "community.general.ini_file" in task or task.get("ansible.builtin.lineinfile", {}).get("line", "").startswith("#include"):
                with self.subTest(task=task["name"]):
                    self.assertIs(task.get("no_log"), True)
                    self.assertIs(task.get("diff"), False)
            if "community.general.ini_file" in task:
                self.assertEqual(task["community.general.ini_file"]["mode"], "0640")
                self.assertIs(task["community.general.ini_file"]["backup"], False)

    def test_sounds_pin_is_validated_before_mutation(self):
        main = tasks("main.yml")
        includes = [t["ansible.builtin.include_tasks"] for t in main if "ansible.builtin.include_tasks" in t]
        self.assertEqual(includes[0], "preflight.yml")
        preflight = tasks("preflight.yml")
        assertions = [t for t in preflight if "ansible.builtin.assert" in t]
        pin = next(t for t in assertions if "asterisk_core_sounds_sha256" in str(t))
        self.assertIn("asterisk_core_sounds_version", str(pin))
        self.assertIn("[0-9a-fA-F]{64}", str(pin))
        self.assertIn("not standard_sounds_check.stat.exists", str(pin))
        self.assertEqual(self.defaults["asterisk_core_sounds_sha256"], "")
        for task in preflight:
            self.assertTrue(any(module in task for module in ("ansible.builtin.assert", "ansible.builtin.stat")))

    def test_remote_downloads_are_versioned_https_and_verified(self):
        downloads = []
        for path in (ROLE / "tasks").iterdir():
            for task in walk_tasks(load_yaml(path)):
                if "ansible.builtin.get_url" in task:
                    downloads.append(task["ansible.builtin.get_url"])
                if "ansible.builtin.unarchive" in task:
                    self.assertNotIn("://", task["ansible.builtin.unarchive"]["src"])
                    self.assertNotIn("ignore_errors", task)
        self.assertTrue(downloads)
        for download in downloads:
            self.assertTrue(download["url"].startswith("https://"))
            self.assertNotIn("current", download["url"])
            if download["url"] == "https://repo.allstarlink.org/public/allstarlink.asc":
                self.assertEqual(download["checksum"], "sha256:88bd5cb1f27cd1ccc3fc60e85f636bb072b2351c33437822f9b0a9edc737d7e7")
            else:
                self.assertIn("asterisk_core_sounds_version", download["url"])
                self.assertEqual(download["checksum"], "sha256:{{ asterisk_core_sounds_sha256 }}")

    def test_allstarlink_uses_exact_packages_scoped_key_and_no_autostart(self):
        provider = tasks("install_allstarlink.yml")
        install = next(t["ansible.builtin.apt"] for t in provider if "name" in t.get("ansible.builtin.apt", {}))
        self.assertEqual(install["policy_rc_d"], 101)
        self.assertFalse(install["install_recommends"])
        self.assertFalse(install["allow_unauthenticated"])
        self.assertFalse(install["allow_downgrade"])
        self.assertTrue(install["fail_on_autoremove"])
        self.assertEqual(install["name"], [
            "asl3-asterisk={{ asterisk_allstarlink_version }}",
            "asl3-asterisk-modules={{ asterisk_allstarlink_version }}",
            "asl3-asterisk-config={{ asterisk_allstarlink_version }}",
            "asterisk-core-sounds-en-wav",
        ])
        source = next(t["ansible.builtin.copy"]["content"] for t in provider if t.get("ansible.builtin.copy", {}).get("dest", "").endswith(".sources"))
        self.assertIn("Signed-By: /etc/apt/keyrings/py-phone-caller-allstarlink.asc", source)
        self.assertIn("Components: main\n", source)
        self.assertIn("ansible_facts['architecture']", source)
        self.assertNotIn("trusted=yes", source)
        pin = next(t["ansible.builtin.copy"]["content"] for t in provider if "/preferences.d/" in t.get("ansible.builtin.copy", {}).get("dest", ""))
        self.assertIn("Package: *\nPin: origin repo.allstarlink.org\nPin-Priority: -1", pin)

    def test_allstarlink_module_list_excludes_radio_and_optional_network_transports(self):
        rendered = self.environment.get_template("modules_allstarlink.conf.j2").render(
            self.defaults | {"asterisk_sip_trunk_enabled": False, "local_iax": False}
        )
        self.assertIn("autoload=no", rendered)
        self.assertIn("load=res_websocket_client.so", rendered)
        for module in ("app_rpt", "chan_simpleusb", "res_usbradio", "res_rpt", "chan_echolink", "chan_iax2", "res_pjsip_outbound_registration"):
            self.assertNotIn(module, rendered)
        for module in ("chan_pjsip", "app_stasis", "res_ari_asterisk"):
            self.assertIn(f"require={module}.so", rendered)

    def test_provider_conflicts_are_checked_before_any_debian_install(self):
        first = tasks("install_Debian.yml")[0]
        self.assertEqual(first["ansible.builtin.include_tasks"], "provider_guard.yml")
        for task in tasks("provider_guard.yml"):
            self.assertTrue(any(module in task for module in (
                "ansible.builtin.assert", "ansible.builtin.stat", "ansible.builtin.slurp", "ansible.builtin.package_facts"
            )))
        guard = str(tasks("provider_guard.yml"))
        self.assertIn("'asterisk' not in ansible_facts.packages", guard)
        self.assertIn("'asl3-asterisk' not in ansible_facts.packages", guard)
        self.assertIn("/etc/asterisk", guard)
        self.assertIn("/usr/local/sbin/asterisk", guard)

    def test_allstarlink_module_configuration_has_only_one_writer(self):
        change = next(t for t in tasks("configure.yml") if t.get("ansible.builtin.lineinfile", {}).get("line") == "noload => chan_sip.so")
        self.assertIn("asterisk_package_provider == 'distro'", change["when"])

    def test_iax_is_explicit_private_and_requires_its_module(self):
        self.assertFalse(self.defaults["local_iax"])
        self.assertEqual(self.defaults["asterisk_iax_bindaddr"], "127.0.0.1")
        self.assertEqual(self.defaults["asterisk_iax_bindport"], 4569)
        variables = self.defaults | {
            "local_iax": True, "local_iax_exten": 2600,
            "local_iax_pass": "SYNTHETIC_IAX_SECRET_1234",
        }
        rendered = self.environment.get_template("iax.conf.j2").render(variables)
        self.assertIn("[2600]", rendered)
        self.assertIn("secret=SYNTHETIC_IAX_SECRET_1234", rendered)
        self.assertIn("requirecalltoken=yes", rendered)
        self.assertNotIn("register", rendered)
        modules = self.environment.get_template("modules_allstarlink.conf.j2").render(variables)
        self.assertIn("require=chan_iax2.so", modules)
        self.assertNotIn("secret=", self.environment.get_template("iax.conf.j2").render(self.defaults))

    def test_distro_checks_candidates_before_apt_and_suppresses_autostart(self):
        install = tasks("install_Debian.yml")
        check = next(i for i, task in enumerate(install)
                     if task.get("ansible.builtin.include_tasks") == "distro_package_check.yml")
        apt = next(i for i, task in enumerate(install) if "ansible.builtin.apt" in task)
        self.assertLess(check, apt)
        self.assertEqual(install[apt]["ansible.builtin.apt"]["policy_rc_d"], 101)
        probe = tasks("distro_package_check.yml")[0]
        self.assertEqual(probe["ansible.builtin.command"]["argv"], ["apt-cache", "policy", "{{ item }}"])
        self.assertFalse(probe["changed_when"])

    def test_iax_verification_is_read_only_and_secret_safe(self):
        verification = tasks("verify_iax.yml")
        self.assertIn("iax2 show peer", str(verification))
        self.assertIn("chan_iax2", str(verification))
        self.assertIn("asterisk_iax_bindaddr", str(verification))
        for task in verification:
            if "ansible.builtin.command" in task:
                self.assertFalse(task["changed_when"])
                self.assertNotIn("originate", str(task["ansible.builtin.command"]))
            if "peer" in task.get("name", "").lower():
                self.assertTrue(task["no_log"])

    def test_check_mode_never_forces_host_mutations(self):
        for path in (ROLE / "tasks").iterdir():
            for task in walk_tasks(load_yaml(path)):
                if task.get("check_mode") is False:
                    self.assertIn("ansible.builtin.command", task, task["name"])
                    self.assertIs(task["changed_when"], False)
                    self.assertEqual(task["ansible.builtin.command"]["argv"][:2], ["apt-cache", "policy"])

    def test_handlers_are_change_driven_and_failures_are_visible(self):
        for task in tasks("main.yml"):
            self.assertNotIn("notify", task)
        for handler in load_yaml(ROLE / "handlers" / "main.yml"):
            self.assertNotIn("ignore_errors", handler)
        for task in tasks("configure.yml"):
            if "community.general.seport" in task:
                self.assertNotIn("notify", task)


class PbxDisposableAssertionTests(unittest.TestCase):
    def setUp(self):
        playbook = load_yaml(ANSIBLE / "tests" / "pbx-disposable.yml")
        task = next(task for task in playbook[-1]["tasks"]
                    if task["name"] == "Require the loaded PJSIP endpoint and configured context")
        self.assertTrue(task["no_log"])
        self.assertEqual(len(task["ansible.builtin.assert"]["that"]), 2)
        environment = Environment(undefined=StrictUndefined)
        environment.tests["search"] = search
        environment.filters["regex_escape"] = regex_escape
        self.assertions = [environment.compile_expression(expression)
                           for expression in task["ansible.builtin.assert"]["that"]]

    def test_pjsip_endpoint_cli_formats_and_strict_boundary(self):
        cases = [
            ("without-caller-id", 2500,
             "Endpoint:  2500                                                 Unavailable   0 of inf", True),
            ("with-caller-id", 2500, "Endpoint:  2500/2500     Unavailable   0 of inf", True),
            ("longer-extension", 2500, "Endpoint:  25001     Unavailable   0 of inf", False),
            ("longer-extension-with-caller-id", 2500, "Endpoint:  25001/2500     Unavailable   0 of inf", False),
            ("adjacent-suffix", 2500, "Endpoint:  2500-other     Unavailable   0 of inf", False),
            ("wrong-extension", 2500, "Endpoint:  2600/2500     Unavailable   0 of inf", False),
            ("missing-endpoint", 2500, "Unable to find object 2500.", False),
            ("literal-endpoint", "local.2500", "Endpoint:  local.2500     Unavailable   0 of inf", True),
            ("not-a-regex", "local.2500", "Endpoint:  localX2500/2500     Unavailable   0 of inf", False),
        ]
        for name, extension, endpoint, succeeds in cases:
            with self.subTest(case=name):
                variables = {
                    "local_sip_exten": extension,
                    "pbx_test_pjsip": {"stdout": endpoint + "\n context : py-phone-caller\n"},
                }
                self.assertEqual(self.assertions[0](**variables), succeeds)
                self.assertTrue(self.assertions[1](**variables))

    def test_pjsip_context_must_still_match(self):
        for context, succeeds in (("py-phone-caller", True), ("other", False), ("py-phone-caller-other", False)):
            with self.subTest(context=context):
                variables = {
                    "local_sip_exten": 2500,
                    "pbx_test_pjsip": {"stdout": f"Endpoint:  2500/2500     Unavailable   0 of inf\n context : {context}\n"},
                }
                self.assertTrue(self.assertions[0](**variables))
                self.assertEqual(self.assertions[1](**variables), succeeds)


class PbxOfflineAnsibleTests(unittest.TestCase):
    """Run real Ansible locally; configuration edits target disposable fixtures only."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".pbx-offline-", dir=ROLE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.inventory = self.root / "inventory" / "hosts.yml"
        self.inventory.parent.mkdir()
        self.inventory.write_text(yaml.safe_dump({
            "all": {"hosts": {"pbx-offline": {
                "ansible_connection": "local",
                "ansible_python_interpreter": sys.executable,
            }}}
        }))
        self.config = self.root / "ansible.cfg"
        self.config.write_text(
            "[defaults]\n"
            f"roles_path = {ANSIBLE / 'roles'}\n"
            f"collections_path = {ANSIBLE / '.collections'}\n"
            "host_key_checking = True\n"
            "retry_files_enabled = False\n"
        )
        self.environment = {key: value for key, value in os.environ.items() if not key.startswith("ANSIBLE_")}
        self.environment.update({
            "ANSIBLE_CONFIG": str(self.config),
            "ANSIBLE_LOCAL_TEMP": str(self.root / "local-tmp"),
            "ANSIBLE_REMOTE_TEMP": str(self.root / "remote-tmp"),
            "ANSIBLE_LOG_PATH": str(self.root / "ansible.log"),
            "ANSIBLE_NOCOLOR": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        })

    def run_playbook(self, playbook, *arguments):
        return subprocess.run(
            [sys.executable, "-B", "-m", "ansible.cli.playbook", "-i", str(self.inventory), str(playbook), *arguments],
            cwd=self.root, env=self.environment, capture_output=True, text=True, timeout=45,
        )

    def test_real_preflight_accepts_valid_pins_and_rejects_missing_or_malformed_pins(self):
        defaults = load_yaml(ROLE / "defaults" / "main.yml")
        cases = [
            ("missing", "RedHat", "1.6.1", "", False, False),
            ("malformed", "RedHat", "1.6.1", "not-a-digest", False, False),
            ("wrong-type", "RedHat", "1.6.1", 123, False, False),
            ("mutable", "RedHat", "current", "a" * 64, False, False),
            ("valid", "RedHat", "1.6.1", "a" * 64, False, True),
            ("installed", "RedHat", "1.6.1", "", True, True),
            ("debian", "Debian", "1.6.1", "", False, True),
        ]
        for name, family, version, checksum, installed, succeeds in cases:
            with self.subTest(case=name):
                sounds = self.root / name
                sounds.mkdir()
                if installed:
                    (sounds / "beep.wav").write_bytes(b"synthetic fixture, not real audio")
                playbook = self.root / f"{name}.yml"
                playbook.write_text(yaml.safe_dump([{
                    "name": "Validate synthetic PBX inputs without host changes",
                    "hosts": "all", "gather_facts": False,
                    "vars": defaults | {
                        "ansible_facts": {"os_family": family},
                        "asterisk_sounds_dir": str(sounds),
                        "asterisk_core_sounds_version": version,
                        "asterisk_core_sounds_sha256": checksum,
                    },
                    "tasks": [{"ansible.builtin.import_tasks": str(ROLE / "tasks" / "preflight.yml")}],
                }]))
                result = self.run_playbook(playbook, "--check", "--diff")
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode == 0, succeeds, output)
                self.assertRegex(output, r"changed=0\s")
                if not succeeds:
                    self.assertIn("Require a pinned verified core sounds release", output)

    def test_allstarlink_preflight_contract(self):
        defaults = load_yaml(ROLE / "defaults" / "main.yml")
        facts = {"os_family": "Debian", "distribution": "Debian", "distribution_major_version": "13", "architecture": "x86_64"}
        base = defaults | {"ansible_facts": facts, "asterisk_package_provider": "allstarlink",
                           "asterisk_http_bindaddr": "127.0.0.1", "ari_password": "PBX_SYNTHETIC_PREFLIGHT_SECRET"}
        cases = [
            ({}, True),
            ({"ansible_facts": facts | {"architecture": "aarch64"}}, True),
            ({"ansible_facts": facts | {"architecture": "armv7l"}}, False),
            ({"ansible_facts": facts | {"distribution": "Ubuntu"}}, False),
            ({"ansible_facts": facts | {"distribution_major_version": "12"}}, False),
            ({"asterisk_package_provider": "automatic"}, False),
            ({"asterisk_allstarlink_version": "latest"}, False),
            ({"asterisk_allstarlink_version": 22}, False),
            ({"asterisk_http_bindaddr": "0.0.0.0"}, False),
            ({"ari_password": "CHANGE_ME"}, False),
            ({"ari_password": "PBX_SYNTHETIC\nINJECTION"}, False),
        ]
        for number, (overrides, succeeds) in enumerate(cases):
            with self.subTest(case=number):
                playbook = self.root / "allstarlink-preflight.yml"
                playbook.write_text(yaml.safe_dump([{
                    "name": "Validate AllStarLink inputs without host changes",
                    "hosts": "all", "gather_facts": False, "vars": base | overrides,
                    "tasks": [{"ansible.builtin.import_tasks": str(ROLE / "tasks/preflight.yml")}],
                }]))
                result = self.run_playbook(playbook, "--check", "--diff")
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode == 0, succeeds, output)
                self.assertRegex(output, r"changed=0\s")
                self.assertNotIn("PBX_SYNTHETIC", output)

    def test_all_pbx_task_files_pass_real_ansible_syntax_check(self):
        playbook = self.root / "syntax.yml"
        playbook.write_text(yaml.safe_dump([{
            "name": "Syntax check PBX tasks only", "hosts": "all", "gather_facts": False,
            "vars": {"ansible_facts": {"os_family": "Debian"}},
            "roles": ["asterisk_py_phone_caller"],
            "tasks": [{"ansible.builtin.import_tasks": str(path)} for path in sorted((ROLE / "tasks").iterdir()) if path.name != "main.yml"],
        }]))
        result = self.run_playbook(playbook, "--syntax-check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ubuntu_2604_iax_preflight_and_render(self):
        defaults = load_yaml(ROLE / "defaults/main.yml")
        base = defaults | {
            "ansible_facts": {"os_family": "Debian", "distribution": "Ubuntu",
                              "distribution_version": "26.04", "distribution_major_version": "26",
                              "architecture": "x86_64"},
            "local_iax": True, "local_iax_exten": 2600,
            "local_iax_pass": "SYNTHETIC_IAX_SECRET_1234",
            "asterisk_iax_bindaddr": "127.0.0.1", "asterisk_iax_bindport": 4569,
            "asterisk_sip_trunk_enabled": False,
        }
        cases = [
            ({}, True),
            ({"asterisk_iax_bindaddr": "10.20.30.40", "asterisk_iax_bindport": 14569}, True),
            ({"asterisk_iax_bindaddr": "172.16.1.5"}, True),
            ({"asterisk_iax_bindaddr": "192.168.1.5"}, True),
            ({"asterisk_iax_bindaddr": "0.0.0.0"}, False),
            ({"asterisk_iax_bindaddr": "8.8.8.8"}, False),
            ({"asterisk_iax_bindaddr": "172.32.0.1"}, False),
            ({"asterisk_iax_bindaddr": "10.0.0.999"}, False),
            ({"asterisk_iax_bindaddr": "10.0.0.001"}, False),
            ({"asterisk_iax_bindport": 65536}, False),
            ({"asterisk_iax_bindport": "4569\nbindaddr=0.0.0.0"}, False),
            ({"local_iax": "true"}, False),
            ({"local_iax_pass": "change_me"}, False),
            ({"local_iax_pass": "SYNTHETIC_IAX_SECRET\n[general]"}, False),
            ({"local_iax_pass": "SYNTHETIC_IAX_SECRET;comment"}, False),
            ({"local_iax_exten": "2600\n[general]"}, False),
            ({"asterisk_package_provider": "allstarlink"}, False),
        ]
        for number, (overrides, succeeds) in enumerate(cases):
            with self.subTest(case=number):
                playbook = self.root / "ubuntu-preflight.yml"
                playbook.write_text(yaml.safe_dump([{
                    "name": "Validate Ubuntu and IAX without host changes",
                    "hosts": "all", "gather_facts": False, "vars": base | overrides,
                    "tasks": [{"ansible.builtin.import_tasks": str(ROLE / "tasks/preflight.yml")}, {
                        "name": "Render both protocol partials without writing configuration",
                        "ansible.builtin.assert": {"that": [
                            "'secret=SYNTHETIC_IAX_SECRET_1234' in lookup('template', '" + str(ROLE / "templates/iax.conf.j2") + "')",
                            "'protocol=udp' in lookup('template', '" + str(ROLE / "templates/pjsip.conf.j2") + "')",
                        ]}, "no_log": True,
                    }],
                }]))
                result = self.run_playbook(playbook, "--check", "--diff")
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode == 0, succeeds, output)
                self.assertRegex(output, r"changed=0\s")
                self.assertNotIn("SYNTHETIC_IAX_SECRET", output)
                self.assertNotIn("SYNTHETIC_IAX_SECRET", (self.root / "ansible.log").read_text())
                if not succeeds:
                    self.assertNotIn("TASK [Render both protocol partials", output)

    def test_distro_missing_package_fails_without_mutation(self):
        assertion = tasks("distro_package_check.yml")[-1]
        for policy, succeeds in [
            ("asterisk:\n  Installed: (none)\n  Candidate: 1:22.5.2~dfsg+~cs6.15.60671435-1\n", True),
            ("asterisk:\n  Installed: (none)\n  Candidate: (none)\n", False),
            ("", False),
        ]:
            with self.subTest(policy=policy):
                playbook = self.root / "package-policy.yml"
                playbook.write_text(yaml.safe_dump([{
                    "name": "Validate synthetic APT metadata only", "hosts": "all", "gather_facts": False,
                    "vars": {"asterisk_py_phone_caller_distro_candidates": {
                        "results": [{"item": "asterisk", "rc": 0, "stdout": policy}]}},
                    "tasks": [assertion],
                }]))
                result = self.run_playbook(playbook, "--check", "--diff")
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode == 0, succeeds, output)
                self.assertRegex(output, r"changed=0\s")
                if not succeeds:
                    self.assertIn("externally managed PBX", output)

    def test_distro_iax_configuration_preserves_includes_and_is_idempotent(self):
        defaults = load_yaml(ROLE / "defaults/main.yml")
        configuration = self.root / "asterisk"
        configuration.mkdir()
        for name in ("extensions", "pjsip", "ari", "iax"):
            (configuration / f"{name}.conf").write_text(
                "[general]\n; preserve this administrator comment\n"
                "[unrelated]\nsecret=SYNTHETIC_EXISTING_SECRET\n"
            )
        (configuration / "modules.conf").write_text("[modules]\nautoload=yes\nnoload => chan_iax2.so\n")
        selected = []
        for task in tasks("configure.yml"):
            if task["name"] in (
                "Deploy Py-Phone-Caller partial configurations",
                "Inject Includes into main configuration files",
                "Select IAX2 explicitly without replacing distribution module configuration",
                "Configure the private distribution IAX listener before service startup",
            ):
                selected.append({key: value for key, value in task.items() if key != "notify"})
        selected[0]["ansible.builtin.template"]["src"] = str(ROLE / "templates") + "/{{ item.src }}"
        playbook = self.root / "configure-iax.yml"
        playbook.write_text(yaml.safe_dump([{
            "name": "Edit temporary PBX fixtures only; never invoke service handlers",
            "hosts": "all", "gather_facts": False,
            "vars": defaults | {
                "local_sip": True, "local_sip_exten": 2500,
                "local_sip_pass": "SYNTHETIC_SIP_SECRET_1234",
                "local_iax": True, "local_iax_exten": 2600,
                "local_iax_pass": "SYNTHETIC_IAX_SECRET_1234",
                "asterisk_sip_trunk_enabled": False,
                "asterisk_iax_bindaddr": "10.20.30.40", "asterisk_iax_bindport": 14569,
                "asterisk_conf_dir": str(configuration),
                "asterisk_user": str(os.getuid()), "asterisk_group": str(os.getgid()),
                "modules_conf_stat": {"stat": {"exists": True}},
            }, "tasks": selected,
        }]))
        for rerun in (False, True):
            result = self.run_playbook(playbook, "--diff")
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            if rerun:
                self.assertRegex(output, r"changed=0\s")
            for secret in ("SYNTHETIC_EXISTING_SECRET", "SYNTHETIC_SIP_SECRET_1234", "SYNTHETIC_IAX_SECRET_1234"):
                self.assertNotIn(secret, output)
                self.assertNotIn(secret, (self.root / "ansible.log").read_text())
        for name in ("extensions", "pjsip", "ari", "iax"):
            content = (configuration / f"{name}.conf").read_text()
            self.assertEqual(content.count(f"#include {name}_py_phone_caller.conf"), 1)
            self.assertIn("secret=SYNTHETIC_EXISTING_SECRET", content)
            self.assertIn("; preserve this administrator comment", content)
            self.assertEqual((configuration / f"{name}_py_phone_caller.conf").stat().st_mode & 0o777, 0o640)
        iax = (configuration / "iax.conf").read_text()
        self.assertIn("bindaddr=10.20.30.40", iax)
        self.assertIn("bindport=14569", iax)
        self.assertIn("\nload => chan_iax2.so\n", (configuration / "modules.conf").read_text())
        self.assertNotIn("noload => chan_iax2.so", (configuration / "modules.conf").read_text())
        for rerun in (False, True):
            result = self.run_playbook(playbook, "--diff", "-e", '{"local_iax": false}')
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            if rerun:
                self.assertRegex(output, r"changed=0\s")
        self.assertNotIn("secret=", (configuration / "iax_py_phone_caller.conf").read_text())
        self.assertIn("noload => chan_iax2.so", (configuration / "modules.conf").read_text())

    def test_wrapper_keeps_inventory_and_playbook_adjacent_group_vars(self):
        config = configparser.ConfigParser()
        config.read(LEGACY / "ansible.cfg")
        plugins = self.root / "roles" / "asterisk_py_phone_caller" / "vars_plugins"
        plugins.mkdir(parents=True)
        (plugins / "pbx_legacy_vars.py").write_text((ROLE / "vars_plugins" / "pbx_legacy_vars.py").read_text())
        with self.config.open("a") as stream:
            stream.write(f"vars_plugins = {plugins}\n")
            stream.write(f"vars_plugins_enabled = {config['defaults']['vars_plugins_enabled']}\n")
        legacy = self.root / "asterisk_py-phone-caller"
        legacy.mkdir()
        wrapper = legacy / "deploy_asterisk.yml"
        wrapper.write_text((LEGACY / "deploy_asterisk.yml").read_text())
        (legacy / "group_vars").mkdir()
        (legacy / "group_vars" / "all.yml").write_text(yaml.safe_dump({
            "vault_ari_password": "synthetic-pbx-ari-sentinel",
        }))
        (legacy / "group_vars" / "unrelated.yml").write_text(yaml.safe_dump({
            "vault_ari_password": "wrong-group-must-not-load",
        }))
        (legacy / "host_vars").mkdir()
        (legacy / "host_vars" / "pbx-offline.yml").write_text(yaml.safe_dump({
            "vault_local_sip_pass": "synthetic-local-sip-sentinel",
        }))
        (self.inventory.parent / "group_vars").mkdir()
        (self.inventory.parent / "group_vars" / "all.yml").write_text(yaml.safe_dump({
            "vault_sip_password": "synthetic-pbx-sip-sentinel",
        }))
        (self.root / "site.yml").write_text(yaml.safe_dump([{
            "name": "Verify only the wrapper contract", "hosts": "{{ stack_hosts }}", "gather_facts": False,
            "tasks": [{
                "name": "Check synthetic wrapper variables",
                "ansible.builtin.assert": {"that": [
                    "stack_deploy_asterisk", "not stack_deploy_python", "not stack_deploy_openalert",
                    "stack_legacy_platform", "local_sip", "local_iax",
                    "local_sip_exten == 2500", "local_iax_exten == 2600",
                    "ari_password == 'synthetic-pbx-ari-sentinel'",
                    "sip_password == 'synthetic-pbx-sip-sentinel'",
                    "local_sip_pass == 'synthetic-local-sip-sentinel'",
                    "python_config is undefined",
                ]},
                "no_log": True,
            }],
        }]))
        result = self.run_playbook(wrapper, "--check", "--diff")
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertRegex(output, r"changed=0\s")
        self.assertNotIn("synthetic-pbx-ari-sentinel", output)
        self.assertNotIn("synthetic-pbx-sip-sentinel", output)
        self.assertNotIn("synthetic-local-sip-sentinel", output)
        log = (self.root / "ansible.log").read_text()
        for sentinel in ("synthetic-pbx-ari-sentinel", "synthetic-pbx-sip-sentinel", "synthetic-local-sip-sentinel"):
            self.assertNotIn(sentinel, log)


if __name__ == "__main__":
    unittest.main()