"""Full locked Python startup and rerun checks; explicitly authorized VMs only."""

import argparse
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ('python', 'combined', 'external', 'legacy-python', 'legacy-combined', 'git')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--provider', choices=('distro', 'allstarlink'), required=True)
    parser.add_argument('--uv-installer-sha256', required=True)
    parser.add_argument('--scenario', choices=SCENARIOS, default='python')
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--git-repo')
    parser.add_argument('--git-commit')
    parser.add_argument('--resume-rerun', action='store_true', help='Resume the unchanged check after a completed installation')
    parser.add_argument('--allow-disposable-changes', action='store_true', required=True)
    args = parser.parse_args()
    if not args.inventory.is_file() or not re.fullmatch(r'[A-Za-z0-9_-]+', args.host):
        parser.error('Provide an existing isolated inventory and a single host name')
    if not re.fullmatch(r'[a-f0-9]{64}', args.uv_installer_sha256):
        parser.error('Provide a reviewed uv installer SHA256')
    if args.scenario == 'combined' and not (args.bundle and args.bundle.is_file() and args.sha256):
        parser.error('Combined testing requires a trusted OpenAlert bundle and SHA256')
    if args.scenario == 'git' and not (args.git_repo and re.fullmatch(r'[a-f0-9]{40}', args.git_commit or '')):
        parser.error('Git testing requires a repository and immutable commit')
    pbx = ROOT / 'tests/.runtime/pbx' / args.host / args.provider / 'inputs.json'
    if not pbx.is_file():
        parser.error('First run the PBX disposable checks on this target')
    values = json.loads(pbx.read_text())
    values.update(yaml.safe_load((ROOT / 'tests/fixtures/python-runtime.yml').read_text()))
    values['py_phone_caller_config']['commons']['asterisk_user'] = values['ari_username']
    values['py_phone_caller_config_secrets']['commons']['asterisk_pass'] = values['ari_password']
    work = ROOT / 'tests/.runtime/python' / args.host / args.scenario
    work.mkdir(parents=True, exist_ok=True, mode=0o700)
    work.chmod(0o700)
    report = work / 'report.json'
    values.update({
        'stack_hosts': args.host, 'python_test_allow_changes': True,
        'python_test_report': str(report), 'py_phone_caller_verify_settle_seconds': 5,
        'stack_deploy_py_phone_caller': True, 'stack_deploy_asterisk': args.scenario == 'combined',
        'stack_deploy_openalert': args.scenario == 'combined',
        'py_phone_caller_local_src_path': str(ROOT.parents[1]),
        'py_phone_caller_uv_installer_checksum': 'sha256:' + args.uv_installer_sha256,
    })
    if args.scenario == 'combined':
        values['openalert_release'] = {'source': str(args.bundle.resolve()), 'sha256': args.sha256}
        values['openalert_instances'] = {
            name: {'service_name': unit, 'health_url': f'http://127.0.0.1:{port}/health', 'rest_port': port,
                   'config_template': str(ROOT / 'inventories/examples/templates/private.toml.j2')}
            for name, unit, port in (('hub', 'openalertd.service', 8090), ('public', 'openalertd-public.service', 8092))
        }
    if args.scenario == 'external':
        values.update(py_phone_caller_manage_postgresql=False, py_phone_caller_manage_database=False,
                      py_phone_caller_manage_local_postgres=False, py_phone_caller_manage_queue=False,
                      py_phone_caller_manage_firewall=False)
    if args.scenario == 'git':
        values.update(py_phone_caller_git_repo=args.git_repo, py_phone_caller_git_version=args.git_commit,
                      py_phone_caller_local_src_path='')
    inputs = work / 'inputs.json'
    inputs.touch(mode=0o600)
    inputs.chmod(0o600)
    inputs.write_text(json.dumps(values))
    env = {**os.environ, 'ANSIBLE_CONFIG': str(ROOT / 'ansible.cfg'),
           'ANSIBLE_NOCOLOR': '1', 'ANSIBLE_LOG_PATH': str(work / 'ansible.log'),
           'ANSIBLE_PLAYBOOK_VARS_ROOT': 'top'}
    protected = [values[key] for key in ('ari_password', 'local_sip_pass', 'local_iax_pass')]
    protected += ['SYNTHETIC_RUNTIME_DB_PASSWORD_NOT_FOR_DEPLOYMENT', 'SYNTHETIC_RUNTIME_UI_SECRET_NOT_FOR_DEPLOYMENT']

    def run(name, playbook, unchanged=False):
        command = [sys.executable, '-m', 'ansible.cli.playbook', '-i', str(args.inventory.resolve()),
                   str(ROOT / playbook), '--limit', args.host, '--diff', '-e', f'@{inputs}']
        with (work / f'{name}.log').open('w') as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, text=True, timeout=4500)
        output = (work / f'{name}.log').read_text()
        if any(secret in output for secret in protected):
            raise AssertionError('Secret leaked; output withheld')
        if result.returncode:
            raise AssertionError(f'{name} failed: inspect {work / (name + ".log")}')
        if unchanged and not re.search(r'changed=0\s+unreachable=0\s+failed=0', output):
            raise AssertionError(f'{name} changed resources')
        print(f'PASS {name}', flush=True)

    playbook = 'tests/python-disposable.yml'
    before_external = None
    if args.scenario == 'external' and not args.resume_rerun:
        run('before-external', 'tests/python-inspect.yml')
        before_external = json.loads(report.read_text())
    if args.scenario.startswith('legacy-'):
        values = copy.deepcopy(values)
        for key in ('stack_deploy_py_phone_caller', 'stack_deploy_asterisk', 'stack_deploy_openalert'):
            del values[key]
        inputs.write_text(json.dumps(values))
        playbook = ('tests/python-legacy-disposable.yml' if args.scenario == 'legacy-python'
                    else 'tests/combined-legacy-disposable.yml')
    if args.resume_rerun:
        if not report.is_file():
            parser.error('A completed installation report is required to resume')
    else:
        run('install', playbook)
        if args.scenario.startswith('legacy-'):
            run('inspect', 'tests/python-inspect.yml')
    first = json.loads(report.read_text())
    if before_external is not None:
        if before_external['dependency_files'] != first['dependency_files']:
            raise AssertionError('External dependency configuration was altered')
        for block in before_external['starts'].strip().split('\n\n'):
            if any(f'Id={unit}.service' in block for unit in ('postgresql', 'redis-server', 'asterisk', 'openalertd', 'openalertd-public')):
                if block not in first['starts']:
                    raise AssertionError('An unmanaged service changed state or restarted')
    run('unchanged', playbook, unchanged=True)
    if args.scenario.startswith('legacy-'):
        run('inspect-rerun', 'tests/python-inspect.yml')
    if first != json.loads(report.read_text()):
        raise AssertionError('Unchanged rerun altered service timestamps or runtime evidence')
    print('PASS zero-change rerun, identical service timestamps and protected output', flush=True)


if __name__ == '__main__':
    main()