"""Opt-in PJSIP/IAX2 checks on one authorized disposable Debian or Ubuntu VM."""

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--provider", choices=("allstarlink", "distro"), default="allstarlink")
    parser.add_argument("--allow-disposable-changes", action="store_true", required=True)
    args = parser.parse_args()
    if not args.inventory.is_file() or not re.fullmatch(r"[A-Za-z0-9_-]+", args.host):
        parser.error("Provide an existing isolated inventory and a single host name")
    work = ROOT / "tests/.runtime/pbx" / args.host / args.provider
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    work.chmod(0o700)
    credential = work / "credential"
    if not credential.exists():
        credential.touch(mode=0o600)
        credential.write_text(secrets.token_urlsafe(32))
    credential.chmod(0o600)
    password = credential.read_text()
    endpoint_credentials = {}
    for protocol in ("sip", "iax"):
        private = work / f"{protocol}-credential"
        if not private.exists():
            private.touch(mode=0o600)
            private.write_text(secrets.token_urlsafe(32))
        private.chmod(0o600)
        endpoint_credentials[f"local_{protocol}_pass"] = private.read_text()
    report = work / "report.json"
    variables = {
        "pbx_test_host": args.host, "pbx_test_allow_changes": True,
        "pbx_test_report": str(report),
        "stack_deploy_py_phone_caller": False, "stack_deploy_openalert": False,
        "stack_deploy_asterisk": True, "asterisk_package_provider": args.provider,
        "asterisk_http_bindaddr": "127.0.0.1", "asterisk_http_bindport": 8088,
        "asterisk_sip_bindaddr": "127.0.0.1:5060", "asterisk_sip_trunk_enabled": False,
        "asterisk_iax_bindaddr": "127.0.0.1", "asterisk_iax_bindport": 4569,
        "local_sip": True, "local_sip_exten": 2500,
        "local_iax": True, "local_iax_exten": 2600, "ari_username": "pbx-test",
        "ari_password": password, "custom_audio_files": [],
        **endpoint_credentials,
    }
    inputs = work / "inputs.json"
    inputs.touch(mode=0o600)
    inputs.chmod(0o600)
    inputs.write_text(json.dumps(variables))
    env = {**os.environ, "ANSIBLE_CONFIG": str(ROOT / "ansible.cfg"),
           "ANSIBLE_NOCOLOR": "1", "ANSIBLE_LOG_PATH": str(work / "ansible.log")}

    def run(name, overrides=None, fails=False):
        inputs.write_text(json.dumps(variables | (overrides or {})))
        result = subprocess.run(
            [sys.executable, "-m", "ansible.cli.playbook", "-i", str(args.inventory.resolve()),
             str(ROOT / "tests/pbx-disposable.yml"), "--limit", args.host, "--diff", "-e", f"@{inputs}"],
            env=env, capture_output=True, text=True, timeout=600,
        )
        output = result.stdout + result.stderr
        captured = output + (work / "ansible.log").read_text()
        if report.exists():
            captured += report.read_text()
        if any(secret in captured for secret in (password, *endpoint_credentials.values())):
            raise AssertionError("PBX credential leaked; output withheld")
        (work / f"{name}.log").write_text(output)
        if (result.returncode != 0) != fails:
            raise AssertionError(f"{name}: unexpected exit {result.returncode}; see {work / (name + '.log')}")
        return output

    run("install")
    first = json.loads(report.read_text())
    print("PASS installation, authenticated ARI, PJSIP/IAX2 configuration and radio exclusion", flush=True)
    output = run("unchanged")
    if not re.search(r"changed=0\s+unreachable=0\s+failed=0", output):
        raise AssertionError("Unchanged rerun modified resources")
    second = json.loads(report.read_text())
    if first != second:
        raise AssertionError("Unchanged rerun altered service starts, modules or versions")
    print("PASS unchanged rerun: zero changes and identical service timestamps", flush=True)
    output = run("provider-conflict", {
        "asterisk_package_provider": "distro" if args.provider == "allstarlink" else "allstarlink",
    }, fails=True)
    if not any(message in output for message in (
        "Existing PBX provider conflicts", "AllStarLink requires Debian 13",
    )) or not re.search(r"changed=0\s+unreachable=0\s+failed=1", output):
        raise AssertionError("Provider conflict did not fail safely before changes")
    print("PASS conflicting provider rejected without changes; credential absent from diff/logs", flush=True)
    inputs.write_text(json.dumps(variables))


if __name__ == "__main__":
    main()
