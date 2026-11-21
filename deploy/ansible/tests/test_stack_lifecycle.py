"""Lifecycle guard and task contracts; never accesses a deployment inventory."""

import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ANSIBLE = Path(__file__).resolve().parents[1]
ROLE = ANSIBLE / "roles/stack_lifecycle"


class LifecycleTests(unittest.TestCase):
    def tasks(self, name):
        return yaml.safe_load((ROLE / "tasks" / name).read_text())

    def run_preflight(self, overrides, check=False):
        variables = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        variables.update({
            "stack_lifecycle_action": "backup",
            "stack_lifecycle_acknowledged": True,
            "stack_lifecycle_maintenance_window": "synthetic isolated fixture",
            "stack_lifecycle_snapshot_id": "fixture-001",
            "stack_lifecycle_paths": ["/etc/openalert/hub", "/var/lib/openalert/hub"],
            "stack_lifecycle_units": ["openalertd-hub.service"],
            "stack_lifecycle_schema_id": "reviewed-schema-v1",
            "stack_lifecycle_release_id": "reviewed-release-v1",
            "ansible_facts": {
                "service_mgr": "systemd", "architecture": "x86_64",
                "distribution": "Debian", "distribution_major_version": "13",
                "distribution_version": "13",
                "python": {"version": {"major": 3, "minor": 13}},
            },
        })
        variables.update(copy.deepcopy(overrides))
        runtime = ANSIBLE / "tests/.runtime"
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="lifecycle-preflight-", dir=runtime) as temporary:
            root = Path(temporary)
            playbook = root / "preflight.yml"
            playbook.write_text(yaml.safe_dump([{
                "name": "Read-only lifecycle fixture",
                "hosts": "localhost", "gather_facts": False,
                "connection": "local", "vars": variables,
                "tasks": [{"ansible.builtin.import_tasks": str(ROLE / "tasks/preflight.yml")}],
            }]))
            environment = dict(os.environ, ANSIBLE_CONFIG=str(ANSIBLE / "ansible.cfg"),
                               ANSIBLE_LOG_PATH=str(root / "ansible.log"), ANSIBLE_NOCOLOR="1")
            command = [sys.executable, "-m", "ansible.cli.playbook", "-i", "localhost,", str(playbook)]
            if check:
                command.append("--check")
            return subprocess.run(command, cwd=ANSIBLE, env=environment, text=True,
                                  capture_output=True, timeout=40)

    def test_valid_maintenance_requests(self):
        cases = [
            {},
            {"stack_lifecycle_paths": ["/root/openalert-hub", "/usr/share/openalert/templates"]},
            {"stack_lifecycle_action": "rollback", "stack_lifecycle_kind": "assets",
             "stack_lifecycle_paths": ["/etc/openalert/hub", "/opt/openalert/releases/fixture-v1"]},
            {"stack_lifecycle_action": "restore", "stack_lifecycle_postgresql_databases": ["fixture"],
             "stack_lifecycle_database_restore_acknowledged": True,
             "stack_lifecycle_snapshot_schema_id": "old-schema"},
            {"stack_lifecycle_units": [], "stack_lifecycle_quiesced": True},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                result = self.run_preflight(overrides)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_invalid_requests_fail_without_host_changes(self):
        cases = [
            {"stack_lifecycle_acknowledged": False},
            {"stack_lifecycle_acknowledged": "true"},
            {"stack_lifecycle_maintenance_window": ""},
            {"stack_lifecycle_snapshot_schema_id": "incorrect-backup-schema"},
            {"stack_lifecycle_snapshot_id": "../escape"},
            {"stack_lifecycle_paths": ["/etc"]},
            {"stack_lifecycle_paths": ["/root"]},
            {"stack_lifecycle_paths": ["/root/.ssh"]},
            {"stack_lifecycle_paths": ["/usr/share"]},
            {"stack_lifecycle_paths": ["/var/lib/postgresql/18/main"]},
            {"stack_lifecycle_paths": ["/etc/app/../shadow"]},
            {"stack_lifecycle_units": ["openalert*.service"]},
            {"stack_lifecycle_units": []},
            {"stack_lifecycle_action": "rollback", "stack_lifecycle_kind": "full"},
            {"stack_lifecycle_action": "rollback", "stack_lifecycle_kind": "assets",
             "stack_lifecycle_paths": ["/etc/openalert/hub"],
             "stack_lifecycle_snapshot_schema_id": "incompatible-v0"},
            {"stack_lifecycle_action": "rollback", "stack_lifecycle_kind": "assets"},
            {"stack_lifecycle_kind": "assets", "stack_lifecycle_postgresql_databases": ["fixture"]},
            {"stack_lifecycle_action": "restore", "stack_lifecycle_postgresql_databases": ["fixture"]},
            {"stack_lifecycle_postgresql_databases": ["postgres; touch /tmp/unwanted"]},
            {"stack_lifecycle_postgresql_databases": ["fixture"],
             "stack_lifecycle_units": ["postgresql.service"]},
            {"stack_lifecycle_health_urls": ["https://example.invalid/dispatch"]},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                result = self.run_preflight(overrides)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("changed=0", result.stdout)

    def test_check_mode_cannot_claim_validation(self):
        result = self.run_preflight({}, check=True)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("changed=0", result.stdout)

    def test_recovery_verification_precedes_service_changes(self):
        tasks = next(task["block"] for task in self.tasks("main.yml") if "block" in task)
        names = [task["name"] for task in tasks]
        self.assertLess(names.index("Verify every recovery artifact before stopping services or writing active paths"),
                        names.index("Restore with services stopped on failure"))
        verification = next(task for task in tasks if task.get("register") == "stack_lifecycle_verified")
        self.assertTrue(verification["no_log"])
        self.assertFalse(verification["changed_when"])

    def test_lock_is_acquired_outside_cleanup_block(self):
        tasks = self.tasks("main.yml")
        self.assertEqual(tasks[1]["ansible.builtin.command"]["argv"],
                         ["mkdir", "/run/lock/py-phone-caller-lifecycle"])
        self.assertNotIn("failed_when", tasks[1])
        release, = tasks[2]["always"]
        self.assertEqual(release["ansible.builtin.command"]["argv"],
                         ["rmdir", "/run/lock/py-phone-caller-lifecycle"])

    def test_backup_resumes_only_previously_active_units_even_on_failure(self):
        task, = self.tasks("backup.yml")
        resume, = task["always"]
        self.assertEqual(resume["when"], "item.stdout | trim == 'active'")
        self.assertEqual(resume["ansible.builtin.systemd_service"]["state"], "started")
        self.assertNotIn("enabled", resume["ansible.builtin.systemd_service"])
        dump = task["block"][1]
        self.assertTrue(dump["no_log"])
        self.assertIn("pg_dump --format=custom", dump["ansible.builtin.shell"]["cmd"])
        self.assertIn("umask 077", dump["ansible.builtin.shell"]["cmd"])

    def test_restore_is_not_automatic_database_rollback_or_dispatch(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertFalse(defaults["stack_lifecycle_start_after_restore"])
        self.assertFalse(defaults["stack_lifecycle_database_restore_acknowledged"])
        tasks = self.tasks("restore.yml")
        restore = next(task for task in tasks if "ansible.builtin.shell" in task)
        self.assertIn("--single-transaction", restore["ansible.builtin.shell"]["cmd"])
        self.assertIn("--exit-on-error", restore["ansible.builtin.shell"]["cmd"])
        self.assertTrue(restore["no_log"])
        health = next(task for task in tasks if "ansible.builtin.uri" in task)
        self.assertEqual(health["ansible.builtin.uri"]["method"], "GET")
        self.assertEqual(health["when"], "stack_lifecycle_start_after_restore")
        self.assertTrue(health["no_log"])

    def test_entrypoints_are_explicit_and_serial(self):
        for action in ("backup", "restore", "rollback"):
            with self.subTest(action=action):
                play, = yaml.safe_load((ANSIBLE / f"playbooks/{action}.yml").read_text())
                self.assertEqual(play["serial"], 1)
                task, = play["tasks"]
                self.assertEqual(task["vars"]["stack_lifecycle_action"], action)
                self.assertEqual(task["ansible.builtin.include_role"]["name"], "stack_lifecycle")
                self.assertNotIn("vars_files", play)


if __name__ == "__main__":
    unittest.main()