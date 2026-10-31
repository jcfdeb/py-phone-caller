"""Regression scenarios on an explicitly authorized disposable systemd host."""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "openalert-ansible-phase2"
SENTINEL = "OPENALERT_SYNTHETIC_SECRET_74fd31f6632046819bcfb8bcb1ec6eda"
SCENARIOS = (
    "fresh-two-instance", "unchanged-rerun", "one-instance-change", "missing-asset",
    "duplicate-listener", "wrong-checksum", "openalert-only-omitted-instance",
    "unsafe-exposure", "secret-redaction", "unmanaged-unit", "duplicate-unit",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--inventory", type=Path, help="Explicit inventory for an authorized disposable VM")
    parser.add_argument("--host", help="Single disposable VM inventory host (required with --inventory)")
    parser.add_argument("--allow-disposable-changes", required=True, action="store_true")
    parser.add_argument("--scenario", action="append", choices=SCENARIOS,
                        help="Run only selected scenarios (repeatable); always establish a safe two-instance baseline")
    args = parser.parse_args()
    if not args.bundle.is_file():
        parser.error("--bundle must name an existing controller-local archive")
    if args.inventory and (not args.host or not re.fullmatch(r"[A-Za-z0-9_-]+", args.host)):
        parser.error("--inventory requires a single --host")
    if not args.inventory:
        label = subprocess.check_output(
            ["podman", "inspect", "--format", '{{index .Config.Labels "openalert.ansible-test"}}', CONTAINER], text=True,
        ).strip()
        if label != "true":
            parser.error("Refusing to operate without the explicit disposable-host label")
    logs = ROOT / "tests/.runtime"
    logs.mkdir(exist_ok=True, mode=0o700)
    playbook = Path(sys.executable).parent / "ansible-playbook"
    env = {**os.environ, "ANSIBLE_CONFIG": str(ROOT / "ansible.cfg"), "ANSIBLE_NOCOLOR": "1",
           "ANSIBLE_LOG_PATH": str(logs / "ansible.log")}
    inventory = str(args.inventory.resolve()) if args.inventory else str(ROOT / "tests/disposable.yml")
    target = args.host or CONTAINER
    selected = set(args.scenario or SCENARIOS)
    passed = []
    instances = {
        name: {"service_name": unit, "health_url": f"http://127.0.0.1:{port}/health", "rest_port": port,
               "synthetic_secret_sentinel": SENTINEL,
               "config_template": str(ROOT / "inventories/examples/templates/private.toml.j2")}
        for name, unit, port in (("hub", "openalertd.service", 8090), ("public", "openalertd-public.service", 8092))
    }
    variables = {"openalert_release": {"source": str(args.bundle.resolve()), "sha256": args.sha256},
                 "openalert_instances": instances}

    def audit_logs():
        for path in logs.glob("*.log"):
            if SENTINEL in path.read_text(errors="replace"):
                raise AssertionError(f"Synthetic secret leaked to {path.name}; output withheld")

    def execute(name, arguments, data=None, timeout=300):
        try:
            result = subprocess.run(
                [str(playbook), "-i", inventory, *arguments, "--limit", target], input=data,
                env=env, text=True, capture_output=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            for stream in ("stdout", "stderr"):
                output = getattr(error, stream) or b""
                if isinstance(output, bytes):
                    output = output.decode(errors="replace")
                (logs / f"{name}.{stream}.log").write_text(output)
            audit_logs()
            raise AssertionError(f"{name}: timed out; see captured logs") from None
        for stream in ("stdout", "stderr"):
            (logs / f"{name}.{stream}.log").write_text(getattr(result, stream))
        audit_logs()
        return result

    def run(name, overrides=None, succeeds=True, unchanged=False, failure_task=None, no_changes=False):
        values = {**variables, **(overrides or {})}
        result = execute(name, [str(ROOT / "site.yml"), "--diff", "-e", json.dumps(values)])
        if (result.returncode == 0) != succeeds:
            raise AssertionError(f"{name}: unexpected exit {result.returncode}; see captured logs")
        if unchanged and not re.search(r"changed=0\s+unreachable=0\s+failed=0", result.stdout):
            raise AssertionError(f"{name}: unchanged rerun modified resources; see its log")
        if no_changes and not re.search(r"changed=0\s+unreachable=0\s+failed=1", result.stdout):
            raise AssertionError(f"{name}: rejection was not mutation-free; see its log")
        if failure_task:
            failures = [task for task, output in re.findall(
                r"^TASK \[([^\n]+)\][^\n]*\n(.*?)(?=^TASK \[|^PLAY RECAP|\Z)",
                result.stdout, re.MULTILINE | re.DOTALL,
            ) if re.search(r"^(?:fatal: .*FAILED!|failed: \[)", output, re.MULTILINE)]
            if not failures or not all(task.endswith(failure_task) for task in failures):
                raise AssertionError(f"{name}: failed outside the expected safety check; see its log")

    def success(name):
        passed.append(name)
        print(f"PASS {name}", flush=True)

    inspections = 0
    def inspect():
        nonlocal inspections
        inspections += 1
        record = logs / "inspection.json"
        result = execute(
            f"inspection-{inspections}", [str(ROOT / "tests/inspect.yml"),
             "-e", json.dumps({"test_record_path": str(record), "test_expected_host": target})], timeout=60,
        )
        if result.returncode:
            raise AssertionError("Disposable host inspection failed; see captured logs")
        return json.loads(record.read_text())

    def service_starts():
        starts = inspect()["starts"]
        assert all(value.isdigit() and int(value) > 0 for value in starts.values()), "Both services must have started"
        return starts

    def probe(name, tasks, extra=None):
        checks = [{"name": "Require authorized single disposable target", "ansible.builtin.assert": {"that": [
            "stack_disposable_test_acknowledged | default(false) | bool",
            "inventory_hostname == test_expected_host", "ansible_play_hosts | length == 1",
        ]}}, *tasks]
        data = json.dumps([{"name": name, "hosts": "stack", "gather_facts": False, "become": True,
                            "tasks": checks}])
        result = execute(name, ["/dev/stdin", "--diff", "-e", json.dumps({
            "test_expected_host": target, **(extra or {}),
        })], data=data, timeout=60)
        if result.returncode:
            raise AssertionError(f"{name}: safety evidence check failed; see captured logs")

    def rendered_secret(name):
        probe(name, [
            {"name": "Read rendered synthetic configurations privately", "ansible.builtin.slurp": {"src": "{{ item }}"},
             "loop": [f"{base}/{instance}/openalertd.toml" for instance in instances
                      for base in ("/etc/openalert", "/var/lib/openalert-installer/candidates")],
             "register": "test_configs", "no_log": True},
            {"name": "Require sentinel in every rendered configuration", "ansible.builtin.assert": {
                "that": "test_sentinel in (item.content | b64decode)"},
             "loop": "{{ test_configs.results }}", "no_log": True},
        ], {"test_sentinel": SENTINEL})

    def ssh_snapshot(name):
        record = logs / f"{name}.json"
        probe(name, [
            {"name": "Read unmanaged SSH identity without modifying it", "ansible.builtin.command": {"argv": [
                "systemctl", "show", "ssh.service", "--property=LoadState,ActiveState,SubState,"
                "ExecMainStartTimestampMonotonic,FragmentPath,DropInPaths",
            ]}, "register": "test_ssh", "changed_when": False},
            {"name": "Require an existing active unmanaged SSH service", "ansible.builtin.assert": {"that": [
                "'LoadState=loaded' in test_ssh.stdout_lines", "'ActiveState=active' in test_ssh.stdout_lines",
            ]}},
            {"name": "Require conflict-test paths to remain absent", "ansible.builtin.stat": {"path": "{{ item }}"},
             "loop": ["/etc/openalert/conflictprobe", "/var/lib/openalert/conflictprobe",
                      "/var/lib/openalert-installer/owners/conflictprobe.json",
                      "/var/lib/openalert-installer/candidates/conflictprobe"], "register": "test_conflict_paths"},
            {"name": "Check conflict did not reserve state", "ansible.builtin.assert": {
                "that": "test_conflict_paths.results | selectattr('stat.exists') | list | length == 0"}},
            {"name": "Read conflict-test account without changing it", "ansible.builtin.getent": {
                "database": "passwd", "key": "oa-conflictprobe", "fail_key": False}},
            {"name": "Check conflict did not create an account", "ansible.builtin.assert": {
                "that": "ansible_facts.getent_passwd['oa-conflictprobe'] is none"}},
            {"name": "Record nonsecret SSH evidence", "ansible.builtin.copy": {
                "content": "{{ test_ssh.stdout_lines | to_json }}", "dest": str(record), "mode": "0600"},
             "delegate_to": "localhost", "become": False, "diff": False},
        ])
        return json.loads(record.read_text())

    def negative(name, overrides, failure_task, no_changes=False):
        starts = service_starts()
        try:
            run(name, overrides, succeeds=False, failure_task=failure_task, no_changes=no_changes)
        finally:
            assert service_starts() == starts, f"{name}: rejected candidate disturbed services"

    inspect()

    run("fresh-two-instance" if "fresh-two-instance" in selected else "setup-two-instance")
    service_starts()
    rendered_secret("baseline-rendered-secret")
    if "fresh-two-instance" in selected:
        success("fresh-two-instance")

    if "unchanged-rerun" in selected:
        starts = service_starts()
        run("unchanged-rerun", unchanged=True)
        assert service_starts() == starts, "An unchanged rerun restarted a service"
        success("unchanged-rerun")

    if "one-instance-change" in selected:
        starts = service_starts()
        changed = copy.deepcopy(variables["openalert_instances"])
        changed["hub"]["log_level"] = "warn"
        run("one-instance-change", {"openalert_instances": changed})
        after = service_starts()
        assert after["openalertd.service"] != starts["openalertd.service"], "Changed instance did not restart"
        assert after["openalertd-public.service"] == starts["openalertd-public.service"], "Unaffected instance restarted"
        variables["openalert_instances"] = changed
        success("one-instance-change")

    if "missing-asset" in selected:
        missing = copy.deepcopy(variables["openalert_instances"])
        missing["hub"]["default_template"] = "missing.json.tera"
        negative("missing-asset", {"openalert_instances": missing},
                 "Check assets, state, permissions and exposure as service account")
        success("missing-asset")

    if "duplicate-listener" in selected:
        duplicate = copy.deepcopy(variables["openalert_instances"])
        duplicate["public"].update(rest_port=8090, health_url="http://127.0.0.1:8090/health")
        negative("duplicate-listener", {"openalert_instances": duplicate}, "Reject conflicting listeners before activation")
        success("duplicate-listener")

    if "wrong-checksum" in selected:
        negative("wrong-checksum", {"openalert_release": {**variables["openalert_release"], "sha256": "0" * 64}},
                 "Reject absent or corrupt controller-local archive", no_changes=True)
        success("wrong-checksum")

    if "openalert-only-omitted-instance" in selected:
        starts = service_starts()
        run("openalert-only-omitted-instance", {"openalert_instances": {"hub": variables["openalert_instances"]["hub"]}})
        assert service_starts() == starts, "Omitting an instance changed its service"
        success("openalert-only-omitted-instance")

    if "secret-redaction" in selected:
        starts = service_starts()
        run("secret-redaction")
        rendered_secret("verify-rendered-secret")
        assert service_starts() == starts, "Secret-redaction check restarted services"
        success("secret-redaction")

    if "unsafe-exposure" in selected:
        unsafe = copy.deepcopy(variables["openalert_instances"])
        unsafe["hub"]["rest_host"] = "0.0.0.0"
        negative("unsafe-exposure", {"openalert_instances": unsafe},
                 "Check assets, state, permissions and exposure as service account")
        success("unsafe-exposure")

    if "unmanaged-unit" in selected:
        before = ssh_snapshot("ssh-before")
        conflict = copy.deepcopy(variables["openalert_instances"])
        conflict["conflictprobe"] = {**instances["hub"], "service_name": "ssh.service", "rest_port": 8094,
                                     "health_url": "http://127.0.0.1:8094/health"}
        negative("unmanaged-unit", {"openalert_instances": conflict},
                 "Refuse to overwrite unmanaged units or state", no_changes=True)
        assert ssh_snapshot("ssh-after") == before, "Unmanaged SSH service changed"
        success("unmanaged-unit")

    if "duplicate-unit" in selected:
        duplicate = copy.deepcopy(variables["openalert_instances"])
        duplicate["public"]["service_name"] = duplicate["hub"]["service_name"]
        negative("duplicate-unit", {"openalert_instances": duplicate},
                 "Reject duplicate service identities and paths", no_changes=True)
        success("duplicate-unit")

    state = inspect()
    assert not re.search(r"^(asterisk|postgresql|redis-server|valkey-server)(-|$)", state["packages"], re.MULTILINE)
    assert not state["python_workspace"], "OpenAlert-only deployment installed the Python workspace"
    audit_logs()
    assert set(passed) == selected, "Not all selected scenarios ran"
    print(f"PASS {len(passed)} scenarios, log redaction, isolation and restart assertions; no dispatch requests were sent",
          flush=True)


if __name__ == "__main__":
    main()