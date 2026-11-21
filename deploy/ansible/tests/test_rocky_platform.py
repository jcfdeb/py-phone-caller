"""Offline platform boundaries; does not load inventories or start services."""

from pathlib import Path
import unittest

from ansible.plugins.filter.core import FilterModule
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml


ANSIBLE = Path(__file__).resolve().parents[1]


def load_tasks(relative):
    return yaml.safe_load((ANSIBLE / relative).read_text())


def evaluate(expression, values):
    environment = NativeEnvironment(undefined=StrictUndefined)
    default_filter = environment.filters["default"]
    environment.filters.update(FilterModule().filters())
    environment.filters["default"] = default_filter
    return environment.from_string("{{ " + expression + " }}").render(values)


class RockyPlatformTests(unittest.TestCase):
    def test_native_platform_bounds(self):
        task = next(item for item in load_tasks("roles/stack_preflight/tasks/main.yml")
                    if item["name"] == "Validate native platform and selected components")
        for distribution, version, architecture, accepted in (
            ("Rocky", "10.2", "x86_64", True),
            ("Rocky", "10.2", "aarch64", False),
            ("Rocky", "9.6", "x86_64", False),
            ("AlmaLinux", "10.2", "x86_64", False),
            ("Debian", "13", "aarch64", True),
            ("Ubuntu", "26.04", "x86_64", True),
            ("Ubuntu", "24.04", "x86_64", False),
        ):
            with self.subTest(distribution=distribution, version=version, architecture=architecture):
                values = {
                    "stack_deploy_py_phone_caller": True,
                    "stack_deploy_asterisk": True,
                    "stack_deploy_openalert": False,
                    "ansible_facts": {
                        "distribution": distribution,
                        "distribution_version": version,
                        "distribution_major_version": version.split(".")[0],
                        "architecture": architecture,
                        "os_family": "RedHat" if distribution in ("Rocky", "AlmaLinux") else "Debian",
                        "service_mgr": "systemd",
                    },
                }
                self.assertEqual(all(evaluate(item, values) for item in task["ansible.builtin.assert"]["that"]), accepted)

    def test_rocky10_caddy_uses_distribution_repositories(self):
        task = next(item for item in load_tasks("roles/reverse_proxy/tasks/main.yml")
                    if item["name"] == "Enable the Caddy COPR repository (RHEL/Rocky)")
        for major, expected in (("10", False), ("9", True)):
            values = {"py_phone_caller_connectivity": "online", "ansible_facts": {
                "os_family": "RedHat", "distribution": "Rocky", "distribution_major_version": major}}
            self.assertEqual(all(evaluate(item, values) for item in task["when"]), expected)

    def test_explicit_profiles_do_not_ignore_missing_audio_dependencies(self):
        task = next(item for item in load_tasks("roles/deploy_py-phone-caller/tasks/prereqs.yml")
                    if item["name"] == "Install ffmpeg")
        expression = task["ignore_errors"].removeprefix("{{").removesuffix("}}").strip()
        for profile in ("legacy", "standard", "enterprise"):
            for connectivity in ("online", "airgapped"):
                with self.subTest(profile=profile, connectivity=connectivity):
                    self.assertEqual(evaluate(expression, {
                        "py_phone_caller_topology": profile,
                        "py_phone_caller_connectivity": connectivity,
                    }), profile == "legacy" and connectivity == "online")


if __name__ == "__main__":
    unittest.main()