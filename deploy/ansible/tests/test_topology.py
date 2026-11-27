"""Exercise topology guards through Ansible using synthetic inputs only."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ANSIBLE = Path(__file__).resolve().parents[1]


class TopologyTests(unittest.TestCase):
    def preflight(self, overrides):
        variables = {
            "py_phone_caller_config": {"logs": {"log_level": "INFO"}},
            "py_phone_caller_topology": "standard",
            "py_phone_caller_ingress": "caddy",
            "py_phone_caller_tls_mode": "internal",
            "py_phone_caller_public_url": "https://caller.internal",
            "caddy_domain_name": "caller.internal",
        }
        variables.update(overrides)
        runtime = ANSIBLE / "tests/.runtime"
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="topology-", dir=runtime) as temporary:
            root = Path(temporary)
            play = root / "preflight.yml"
            play.write_text(yaml.safe_dump([{
                "name": "Read-only topology fixture", "hosts": "localhost",
                "connection": "local", "gather_facts": False, "vars": variables,
                "tasks": [{"ansible.builtin.include_role": {
                    "name": "deploy_py-phone-caller", "tasks_from": "topology",
                }}],
            }]))
            environment = dict(os.environ, ANSIBLE_CONFIG=str(ANSIBLE / "ansible.cfg"),
                               ANSIBLE_LOG_PATH=str(root / "ansible.log"), ANSIBLE_NOCOLOR="1")
            return subprocess.run(
                [sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(play)],
                cwd=ANSIBLE, env=environment, text=True, capture_output=True, timeout=40,
            )

    def test_supported_profiles_and_legacy_switches(self):
        cases = [
            {},
            {"py_phone_caller_topology": "enterprise"},
            {"py_phone_caller_topology": "enterprise", "py_phone_caller_ingress": "external",
             "py_phone_caller_tls_mode": "external"},
            {"py_phone_caller_tls_mode": "acme", "caddy_email": "ops@example.invalid"},
            {"py_phone_caller_tls_mode": "provided", "py_phone_caller_tls_certificate": "/etc/caller/server.pem",
             "py_phone_caller_tls_private_key": "/etc/caller/server.key"},
            {"py_phone_caller_topology": "legacy", "py_phone_caller_manage_gateway": True,
             "py_phone_caller_manage_reverse_proxy": False, "py_phone_caller_public_url": ""},
        ]
        for values in cases:
            with self.subTest(values=values):
                result = self.preflight(values)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("changed=0", result.stdout)

    def test_conflicts_fail_before_mutations(self):
        cases = [
            {"py_phone_caller_topology": "unknown"},
            {"py_phone_caller_manage_gateway": True},
            {"py_phone_caller_topology": "enterprise", "py_phone_caller_manage_gateway": False},
            {"py_phone_caller_manage_reverse_proxy": False},
            {"py_phone_caller_caddy_force": True},
            {"py_phone_caller_ingress": "external"},
            {"py_phone_caller_tls_mode": "acme"},
            {"py_phone_caller_tls_mode": "provided"},
            {"caddy_domain_name": "different.internal"},
            {"py_phone_caller_public_url": "http://caller.internal"},
            {"py_phone_caller_public_url": "https://user:secret@caller.internal"},
            {"py_phone_caller_public_url": "https://caller.internal/extra"},
            {"py_phone_caller_public_url": "https://caller.internal:99999"},
            {"py_phone_caller_public_url": "https://caller.internal:0", "caddy_domain_name": "caller.internal:0"},
            {"py_phone_caller_config": {"auth": {"provider": "keycloak"}}},
            {"py_phone_caller_config": {"auth": {"oauth2": {"enabled": True}}}},
            {"py_phone_caller_config": {"gateway": {"behind_gateway": True}}},
            {"py_phone_caller_config": {"py_phone_caller_ui": {"ui_listen_on_host": "0.0.0.0"}}},
            {"py_phone_caller_firewall_extra_ports": [8180]},
            {"py_phone_caller_firewall_ports": [80, 443, 5000]},
            {"py_phone_caller_connectivity": "airgapped", "py_phone_caller_tls_mode": "acme"},
            {"py_phone_caller_topology": "legacy", "py_phone_caller_connectivity": "airgapped"},
        ]
        for values in cases:
            with self.subTest(values=values):
                result = self.preflight(values)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("changed=0", result.stdout)

    def test_stack_validates_topology_before_component_installation(self):
        site, = yaml.safe_load((ANSIBLE / "site.yml").read_text())
        self.assertEqual(site["tasks"][0]["ansible.builtin.include_role"]["name"], "stack_preflight")
        tasks = yaml.safe_load((ANSIBLE / "roles/stack_preflight/tasks/python.yml").read_text())
        self.assertEqual(tasks[-2]["ansible.builtin.include_role"]["tasks_from"], "topology")
        self.assertEqual(tasks[-1]["ansible.builtin.include_role"]["tasks_from"], "topology_host")
        self.assertTrue(tasks[0]["no_log"])

    def test_external_keycloak_database_is_not_provisioned_by_application_role(self):
        tasks = yaml.safe_load((ANSIBLE / "roles/postgresql/tasks/database.yml").read_text())
        keycloak = [task for task in tasks if "Keycloak" in task["name"]]
        self.assertEqual(len(keycloak), 4)
        for task in keycloak:
            self.assertIn("== 'legacy'", task["when"])

    def test_allstarlink_offline_never_adds_public_source_or_fetches_key(self):
        tasks = yaml.safe_load((ANSIBLE / "roles/asterisk_py_phone_caller/tasks/install_allstarlink.yml").read_text())
        for name in ("Fetch reviewed AllStarLink repository key",
                     "Configure only the signed production repository for the managed architecture"):
            task = next(task for task in tasks if task["name"] == name)
            self.assertIn("!= 'airgapped'", task["when"])

    def test_enterprise_auth_does_not_silently_enable_local_fallback(self):
        tasks = yaml.safe_load((ANSIBLE / "roles/deploy_py-phone-caller/tasks/main.yml").read_text())
        inject = next(task for task in tasks if task["name"] == "Inject gateway and Keycloak auth parameters")
        self.assertIn("'local_fallback_enabled': py_phone_caller_topology == 'legacy'",
                      inject["ansible.builtin.set_fact"]["py_phone_caller_final_config"])


if __name__ == "__main__":
    unittest.main()