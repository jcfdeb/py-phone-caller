"""Offline regressions for the shared Python/infrastructure roles.

Run directly with the controller interpreter; never contacts inventory hosts.
"""

import ast
import base64
import getpass
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml


ROLES = Path(__file__).resolve().parents[1] / "deploy/ansible/roles"
PYTHON_ROLE = ROLES / "deploy_py-phone-caller"


def tasks(path):
    return yaml.safe_load(path.read_text())


def render(value, context):
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters["bool"] = bool
    env.filters["b64decode"] = lambda text: base64.b64decode(text).decode()
    return env.from_string(value).render(context)


def walk_tasks(sequence):
    for task in sequence:
        yield task
        for key in ("block", "rescue", "always"):
            yield from walk_tasks(task.get(key, []))


class SourceLayoutTests(unittest.TestCase):
    def test_git_checkout_is_not_the_live_workspace(self):
        source = tasks(PYTHON_ROLE / "tasks/source.yml")
        clone = next(task["ansible.builtin.git"] for task in source if "ansible.builtin.git" in task)
        self.assertNotEqual(clone["dest"], "{{ py_phone_caller_install_dir }}")
        self.assertTrue(any("ansible.builtin.slurp" in task for task in source),
                        "Git metadata must come from the remote checkout, not the controller")

    def test_git_does_not_delete_checkout_or_state(self):
        source = tasks(PYTHON_ROLE / "tasks/source.yml")
        removed = [task["ansible.builtin.file"]["path"] for task in source
                   if task.get("ansible.builtin.file", {}).get("state") == "absent"]
        self.assertEqual(removed, [], "Migration must preserve legacy src, models and state")

    def test_both_metadata_paths_preserve_workspace_dependencies(self):
        source = tasks(PYTHON_ROLE / "tasks/source.yml")
        metadata = next(task for task in source if task["name"].startswith("Deliver Git workspace"))
        for text in ('members = ["src/foo", "src/py-phone-caller-utils"]\n',
                     'source = { editable = "src/foo" }\n',
                     "dependency = { path = 'src/py-phone-caller-utils' }\n"):
            context = {"item": {"content": base64.b64encode(text.encode()).decode()}}
            result = render(metadata["ansible.builtin.copy"]["content"], context)
            self.assertNotIn("src/", result)
            self.assertIn("app/", result)

    def test_synthetic_git_and_local_delivery_and_second_run(self):
        with tempfile.TemporaryDirectory(prefix=".python-role-", dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            fixture = root / "checkout"
            fixture.mkdir()
            (fixture / "src/caller_sms").mkdir(parents=True)
            (fixture / "src/py-phone-caller-utils").mkdir()
            (fixture / "src/caller_sms/service.py").write_text("# fixture code\n")
            (fixture / "src/py-phone-caller-utils/helper.py").write_text("# shared code\n")
            (fixture / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["src/caller_sms", "src/py-phone-caller-utils"]\n')
            (fixture / "uv.lock").write_text('version = 1\nsource = { editable = "src/caller_sms" }\n')
            for filename in ("README.md", "LICENSE", "babel.cfg"):
                (fixture / filename).write_text("fixture\n")
            for args in (("init", "-q"), ("add", "."),
                         ("-c", "user.name=Fixture", "-c", "user.email=fixture@invalid", "commit", "-qm", "fixture",
                          "--trailer", "Co-authored-by: Junie <junie@jetbrains.com>")):
                subprocess.run(["git", "-C", str(fixture), *args], check=True, capture_output=True)
            commit = subprocess.check_output(["git", "-C", str(fixture), "rev-parse", "HEAD"], text=True).strip()
            (root / "ansible.cfg").write_text("[defaults]\n")
            env = dict(os.environ, ANSIBLE_CONFIG=str(root / "ansible.cfg"), ANSIBLE_ROLES_PATH=str(ROLES),
                       ANSIBLE_COLLECTIONS_PATH=os.environ.get("ANSIBLE_COLLECTIONS_PATH", os.pathsep.join(
                           [str(path / ".collections") for path in (ROLES.parents[2], ROLES.parent)]
                           + ["~/.ansible/collections", "/usr/share/ansible/collections"])),
                       ANSIBLE_LOCAL_TEMP=str(root / "ansible-local"),
                       ANSIBLE_REMOTE_TEMP=str(root / "ansible-remote"), ANSIBLE_NOCOLOR="1")
            delivered = []
            for method in ("git", "local"):
                target = root / method
                (target / "app").mkdir(parents=True)
                protected = ["data/sentinel", "src/sentinel", "pre_trained_models/sentinel",
                             "app/config/sentinel", "app/generate_audio/audio/sentinel",
                             "app/generate_audio/pre_trained_models/sentinel", "app/data/sentinel"]
                for name in protected:
                    path = target / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("persistent\n")
                variables = {
                    "py_phone_caller_install_dir": str(target),
                    "py_phone_caller_git_repo": str(fixture) if method == "git" else "",
                    "py_phone_caller_git_version": commit,
                    "py_phone_caller_local_src_path": str(fixture) if method == "local" else "",
                    "py_phone_caller_user": getpass.getuser(),
                    "py_phone_caller_group": subprocess.check_output(["id", "-gn"], text=True).strip(),
                    "py_phone_caller_sync_become": False,
                    "py_phone_caller_services": [{"name": "caller_sms"}],
                }
                play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
                         "vars": tasks(PYTHON_ROLE / "defaults/main.yml") | tasks(PYTHON_ROLE / "vars/main.yml") | variables,
                         "tasks": [{"ansible.builtin.include_tasks": str(PYTHON_ROLE / "tasks/source.yml")}],
                         "handlers": [{"name": name, "ansible.builtin.debug": {"msg": "recorded notification"}}
                                      for name in ("Restart py-phone-caller services", "Restart affected Python services")]}]
                playbook = root / "source.yml"
                playbook.write_text(yaml.safe_dump(play))
                for run in range(2):
                    result = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(playbook)],
                                            env=env, capture_output=True, text=True, timeout=90)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    if run:
                        self.assertRegex(result.stdout, r"changed=0\s", result.stdout)
                for name in protected:
                    self.assertEqual((target / name).read_text(), "persistent\n")
                self.assertTrue((target / "app/caller_sms/service.py").is_file())
                delivered.append([(target / filename).read_text().strip() for filename in ("pyproject.toml", "uv.lock")])
            self.assertEqual(*delivered)


class ResponsibilityTests(unittest.TestCase):
    def test_ansible_syntax_for_all_scoped_tasks(self):
        with tempfile.TemporaryDirectory(prefix=".python-role-", dir=Path(__file__).parent) as tmp:
            root = Path(tmp)
            (root / "ansible.cfg").write_text("[defaults]\n")
            role_names = ("deploy_py-phone-caller", "postgresql", "queue", "gateway", "reverse_proxy", "firewall")
            imports = [{"ansible.builtin.import_tasks": str(path)} for role in role_names
                       for path in sorted((ROLES / role / "tasks").glob("*.yml"))]
            play = [{"hosts": "localhost", "gather_facts": False, "tasks": imports}]
            playbook = root / "syntax.yml"
            playbook.write_text(yaml.safe_dump(play))
            env = dict(os.environ, ANSIBLE_CONFIG=str(root / "ansible.cfg"), ANSIBLE_ROLES_PATH=str(ROLES),
                       ANSIBLE_COLLECTIONS_PATH=os.environ.get("ANSIBLE_COLLECTIONS_PATH", os.pathsep.join(
                           [str(path / ".collections") for path in (ROLES.parents[2], ROLES.parent)]
                           + ["~/.ansible/collections", "/usr/share/ansible/collections"])),
                       ANSIBLE_LOCAL_TEMP=str(root / "ansible-local"))
            result = subprocess.run([sys.executable, "-m", "ansible.cli.playbook", "--syntax-check",
                                     "-i", "localhost,", str(playbook)], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_external_services_do_not_create_systemd_dependencies(self):
        defaults = tasks(PYTHON_ROLE / "defaults/main.yml")
        context = defaults | {
            "py_phone_caller_final_config": {"queue": {"queue_host": "remote.invalid"}},
            "py_phone_caller_src_dir": "/opt/example/app",
            "py_phone_caller_manage_queue": False,
            "py_phone_caller_manage_postgresql": False,
            "py_phone_caller_manage_local_postgres": False,
            "item": {"name": "caller_sms", "description": "fixture", "module": "caller_sms.caller_sms", "first": True},
        }
        result = render((PYTHON_ROLE / "templates/service.j2").read_text(), context)
        self.assertNotIn("postgresql.service", result)
        self.assertNotIn("redis-server.service", result)
        self.assertNotIn("Requires=", result)
        self.assertIn("-m caller_sms.caller_sms", result)

    def test_source_changes_select_only_affected_services(self):
        task = next(task for task in tasks(PYTHON_ROLE / "tasks/source.yml")
                    if task["name"].startswith("Record services affected"))
        expression = "{{ " + task["when"] + " }}"
        for service, changed, expected in (("caller_sms", "caller_sms/service.py", True),
                                           ("generate_audio", "caller_sms/service.py", False),
                                           ("generate_audio", "py-phone-caller-utils/shared.py", True),
                                           ("caller_sms", "", False)):
            context = {"item": {"name": service}, "_ppc_source_changes": changed}
            self.assertIs(render(expression, context), expected)

    def test_roles_are_explicit_and_conditionally_managed(self):
        main = tasks(PYTHON_ROLE / "tasks/main.yml")
        includes = {task["ansible.builtin.include_role"]["name"]: task
                    for task in main if "ansible.builtin.include_role" in task}
        self.assertEqual(set(includes), {"postgresql", "queue", "gateway", "reverse_proxy", "firewall"})
        for role, task in includes.items():
            self.assertIn("py_phone_caller_manage_" + role, str(task["when"]))
        prereqs = (PYTHON_ROLE / "tasks/prereqs.yml").read_text()
        self.assertNotIn("py_phone_caller_postgres_packages", prereqs)
        self.assertNotIn("py_phone_caller_queue_packages", prereqs)

    def test_external_database_and_queue_skip_all_management(self):
        defaults = tasks(PYTHON_ROLE / "defaults/main.yml")
        context = dict(defaults, py_phone_caller_final_config={
            "database": {"db_host": "external.invalid"}, "queue": {"queue_host": "external.invalid"}})
        context["py_phone_caller_manage_local_postgres"] = render(defaults["py_phone_caller_manage_local_postgres"], context)
        for selector in ("py_phone_caller_manage_postgresql", "py_phone_caller_manage_queue"):
            self.assertFalse(render(defaults[selector], context))
        for role in ("postgresql", "queue"):
            block = tasks(ROLES / role / "tasks/main.yml")[0]
            self.assertIn("block", block)
            self.assertIn("when", block)

    def test_unit_operations_never_discover_or_delete_by_prefix(self):
        for filename in ("tasks/systemd.yml", "handlers/main.yml"):
            for task in tasks(PYTHON_ROLE / filename):
                self.assertNotIn("ansible.builtin.find", task)
                self.assertNotEqual(task.get("ansible.builtin.file", {}).get("state"), "absent")
        handler = (PYTHON_ROLE / "handlers/main.yml").read_text()
        self.assertIn("py_phone_caller_services", handler)
        self.assertIn("py_phone_caller_manage_services | bool", handler)

    def test_sensitive_templates_hide_output_and_diff(self):
        for role, filename in (("deploy_py-phone-caller", "tasks/config.yml"),
                               ("deploy_py-phone-caller", "tasks/credentials.yml"),
                               ("gateway", "tasks/main.yml")):
            for task in walk_tasks(tasks(ROLES / role / filename)):
                template = task.get("ansible.builtin.template", {}).get("src", "")
                if template in {"settings.toml.j2", "credentials.env.j2", "apisix_config.yaml.j2",
                                "apisix_dashboard_conf.yaml.j2", "keycloak.env.j2"}:
                    self.assertTrue(task.get("no_log"), task["name"])
                    self.assertIs(task.get("diff"), False, task["name"])
        unit = (ROLES / "gateway/templates/service-keycloak.j2").read_text()
        self.assertNotIn("_password", unit)
        self.assertIn("--env-file", unit)

    def test_gateway_helpers_never_print_credentials(self):
        for filename in ("setup_keycloak.py", "setup_apisix_routes.py"):
            tree = ast.parse((ROLES / "gateway/files" / filename).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                    names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
                    self.assertFalse(names & {"M2M_SECRET", "USER_ADMIN_PASS", "USER_OPERATOR_PASS",
                                              "USER_VIEWER_PASS", "ADMIN_PASS", "DASHBOARD_PASS", "token", "headers"})
        source = (ROLES / "gateway/files/setup_keycloak.py").read_text()
        self.assertNotIn("Password123!", source)
        self.assertNotIn("192.168.101", source)

    def test_downloads_and_builds_are_pinned(self):
        install = (PYTHON_ROLE / "tasks/install.yml").read_text()
        self.assertNotIn("| sh", install)
        self.assertIn("--frozen --all-packages", install)
        self.assertIn("maturin==", install)
        self.assertIn("build --release --locked", install)
        for role, filename in (("deploy_py-phone-caller", "tasks/install.yml"), ("reverse_proxy", "tasks/main.yml")):
            for task in tasks(ROLES / role / filename):
                if "ansible.builtin.get_url" in task:
                    self.assertIn("checksum", task["ansible.builtin.get_url"])
        self.assertIn("@sha256:", (ROLES / "gateway/tasks/main.yml").read_text())

    def test_native_and_legacy_package_branches_remain(self):
        for family in ("Debian", "RedHat"):
            values = tasks(PYTHON_ROLE / f"vars/{family}.yml")
            self.assertIn("py_phone_caller_postgres_packages", values)
            self.assertIn("py_phone_caller_queue_packages", values)
        self.assertIn("postgresql-setup --initdb", (ROLES / "postgresql/tasks/main.yml").read_text())
        self.assertIn("ansible.posix.firewalld", (ROLES / "firewall/tasks/main.yml").read_text())


if __name__ == "__main__":
    unittest.main()