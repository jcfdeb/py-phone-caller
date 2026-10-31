"""Read-only compatibility contracts; never loads a deployment inventory."""

import configparser
from pathlib import Path
import unittest

import yaml


ANSIBLE = Path(__file__).resolve().parents[1]


class EntrypointTests(unittest.TestCase):
    def test_python_wrapper_retains_group_and_selection(self):
        play, = yaml.safe_load((ANSIBLE / "on-vm_py-phone-caller/deploy_py-phone-caller.yml").read_text())
        self.assertEqual(play["ansible.builtin.import_playbook"], "../site.yml")
        self.assertEqual(play["vars"]["stack_hosts"], "app_servers")
        self.assertTrue(play["vars"]["stack_deploy_py_phone_caller"])
        self.assertFalse(play["vars"]["stack_deploy_asterisk"])
        self.assertFalse(play["vars"]["stack_deploy_openalert"])

    def test_combined_wrapper_retains_group_and_selection(self):
        play, = yaml.safe_load((ANSIBLE / "deploy_all/deploy_py-phone-caller_stack.yml").read_text())
        self.assertEqual(play["ansible.builtin.import_playbook"], "../site.yml")
        self.assertEqual(play["vars"]["stack_hosts"], "app_servers")
        self.assertTrue(play["vars"]["stack_deploy_py_phone_caller"])
        self.assertTrue(play["vars"]["stack_deploy_asterisk"])
        self.assertFalse(play["vars"]["stack_deploy_openalert"])

    def test_legacy_commands_use_shared_roles_and_exact_collection_pins(self):
        expected = yaml.safe_load((ANSIBLE / "requirements.yml").read_text())
        for directory in ("on-vm_py-phone-caller", "deploy_all", "asterisk_py-phone-caller"):
            with self.subTest(directory=directory):
                config = configparser.ConfigParser()
                config.read(ANSIBLE / directory / "ansible.cfg")
                self.assertEqual(config["defaults"]["roles_path"], "../roles")
                self.assertEqual(yaml.safe_load((ANSIBLE / directory / "requirements.yml").read_text()), expected)

    def test_legacy_pbx_aliases_are_protected_and_opt_in(self):
        task, = yaml.safe_load((ANSIBLE / "tasks/pbx_aliases.yml").read_text())
        self.assertTrue(task["no_log"])
        self.assertEqual(task["when"], "item.source in vars")
        mapping = {item["source"]: item["destination"] for item in task["loop"]}
        self.assertEqual(mapping["pbx_sip_password"], "sip_password")
        self.assertEqual(mapping["pbx_sip_provider_host"], "sip_provider_host")
        self.assertEqual(mapping["pbx_local_iax_pass"], "local_iax_pass")

    def test_render_check_has_no_implicit_live_inventory(self):
        content = (ANSIBLE / "on-vm_py-phone-caller/render_check.yml").read_text()
        self.assertNotIn('"group_vars/all.yml"', content)
        self.assertNotIn("dir: group_vars/app_servers", content)
        self.assertIn("../tests/fixtures/python.yml", content)
        play, = yaml.safe_load(content)
        for task in play["tasks"]:
            if task["name"] in ("Render settings.toml", "Render .secrets.toml"):
                self.assertTrue(task["no_log"])
                self.assertFalse(task["diff"])

    def test_python_wrapper_no_longer_prints_credentials(self):
        content = (ANSIBLE / "on-vm_py-phone-caller/deploy_py-phone-caller.yml").read_text()
        self.assertNotIn("ansible.builtin.debug", content)
        self.assertNotIn("_ppc_keycloak", content)


if __name__ == "__main__":
    unittest.main()
