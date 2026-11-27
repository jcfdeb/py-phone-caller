"""Qualify one parent-provisioned disposable VM; never provision or select a VM.

Inputs are a parent-produced JSON extra-vars object (including the existing
python-runtime fixture and PBX inputs). The parent must join provisioning and
pin-import work, then set topology_test_parent_joined=true. Supply an absolute
target-side public CA certificate path as topology_test_tls_ca_path; no keys or
credentials belong in URLs. The public origin is https://caller.internal and
must resolve exclusively to loopback on the VM. Standard must be airgapped.

Only the parent invokes this runner, sequentially for each approved OS/profile.
Runtime artifacts are private under tests/.runtime/topology. Resume requires a
completed baseline from this harness and exactly the same inputs/inventory.
Raw subprocess output is discarded, including on failure; logs contain only
fixed messages. Discovery is NOT an authentication or authorization test.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
HOST = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')
LIMITATION = 'Actual authentication not performed; OIDC discovery is read-only support evidence only.'


class QualificationError(Exception):
    """Only fixed, nonsecret messages may cross the runner boundary."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise QualificationError('Invalid command arguments; consult --help.')


def parse_args(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--allow-disposable-changes', action='store_true', required=True)
    parser.add_argument('--resume-rerun', action='store_true')
    args = parser.parse_args(argv)
    if not HOST.fullmatch(args.host) or args.host in {'all', 'ungrouped', 'localhost'}:
        raise QualificationError('An explicit single disposable host is required.')
    if not args.inventory.is_file() or not args.inputs.is_file():
        raise QualificationError('Explicit inventory and input files are required.')
    return args


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise QualificationError('Duplicate JSON keys are not accepted.')
            result[key] = value
        return result

    return json.loads(path.read_text(), object_pairs_hook=unique)


def validate_inputs(values, host):
    if not isinstance(values, dict):
        raise QualificationError('Inputs must be a JSON object.')
    allowed = {'topology_test_parent_joined', 'topology_test_tls_ca_path', 'topology_test_allow_changes'}
    for key in values:
        if (key.startswith(('ansible_', '_', 'python_test_'))
                or (key.startswith('topology_test_') and key not in allowed)
                or key in {'stack_disposable_test_acknowledged', 'hostvars', 'groups', 'inventory_hostname',
                           'py_phone_caller_verify_endpoints', 'py_phone_caller_services',
                           'py_phone_caller_final_config', 'py_phone_caller_topology_config'}):
            raise QualificationError('Inputs override a protected harness or inventory variable.')
    if values.get('stack_hosts', host) != host:
        raise QualificationError('Inputs must target only the selected host.')
    if values.get('topology_test_parent_joined') is not True:
        raise QualificationError('Parent provisioning and pin-import work must be joined first.')
    if values.get('topology_test_allow_changes', True) is not True:
        raise QualificationError('Disposable changes were not authorized.')
    topology = values.get('py_phone_caller_topology')
    if topology not in {'standard', 'enterprise'}:
        raise QualificationError('Select an explicit supported topology.')
    if topology == 'standard' and values.get('py_phone_caller_connectivity') != 'airgapped':
        raise QualificationError('Standard qualification must be airgapped.')
    if values.get('py_phone_caller_public_url') != 'https://caller.internal':
        raise QualificationError('The disposable public origin must use the local test domain.')
    ca = values.get('topology_test_tls_ca_path', '')
    if not isinstance(ca, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+\.(?:crt|pem)', ca):
        raise QualificationError('Supply an explicit target-side public CA certificate path.')


def validate_inventory(inventory, host):
    hostvars = inventory.get('_meta', {}).get('hostvars', {})
    hosts = set(hostvars)
    for name, group in inventory.items():
        if name != '_meta' and isinstance(group, dict):
            hosts.update(group.get('hosts', []))
    if hosts != {host} or hostvars.get(host, {}).get('stack_disposable_test_acknowledged') is not True:
        raise QualificationError('Inventory must contain only the acknowledged disposable host.')


def parse_recap(output, host, unchanged=False):
    parts = re.split(r'^PLAY RECAP \*+\s*$', output, flags=re.MULTILINE)
    if len(parts) != 2:
        raise QualificationError('A single complete play recap is required.')
    rows = [line.strip() for line in parts[1].splitlines() if line.strip()]
    if len(rows) != 1:
        raise QualificationError('The play must report exactly one host.')
    match = re.fullmatch(r'([A-Za-z0-9_-]+)\s*:\s*(.*)', rows[0])
    if not match or match[1] != host:
        raise QualificationError('The play recap does not match the selected host.')
    fields = re.findall(r'([a-z]+)=(\d+)', match[2])
    if re.sub(r'[a-z]+=\d+\s*', '', match[2]).strip() or len(dict(fields)) != len(fields):
        raise QualificationError('The play recap is malformed.')
    counts = {key: int(value) for key, value in fields}
    if set(counts) != {'ok', 'changed', 'unreachable', 'failed', 'skipped', 'rescued', 'ignored'}:
        raise QualificationError('The play recap is incomplete.')
    if counts['ok'] == 0 or any(counts[key] for key in ('unreachable', 'failed', 'rescued', 'ignored')):
        raise QualificationError('The play did not complete cleanly.')
    if unchanged and counts['changed'] != 0:
        raise QualificationError('The unchanged run changed resources.')
    return counts


def private_write(path, value):
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o600), 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(value)


def environment():
    env = {key: value for key, value in os.environ.items() if not key.startswith('ANSIBLE_')}
    env.update(ANSIBLE_CONFIG=str(ROOT / 'ansible.cfg'), ANSIBLE_NOCOLOR='1',
               ANSIBLE_NO_LOG='true', ANSIBLE_LOG_PATH=os.devnull,
               ANSIBLE_STDOUT_CALLBACK='default', ANSIBLE_CALLBACKS_ENABLED='ansible.builtin.default',
               ANSIBLE_LOAD_CALLBACK_PLUGINS='false', ANSIBLE_DISPLAY_ARGS_TO_STDOUT='false',
               ANSIBLE_DIFF_ALWAYS='false', ANSIBLE_PLAYBOOK_VARS_ROOT='top',
               ANSIBLE_RETRY_FILES_ENABLED='false', ANSIBLE_CACHE_PLUGIN='memory')
    return env


def execute(command):
    # Never persist stdout/stderr or interpolate exceptions: they may contain secrets.
    result = subprocess.run(command, cwd=ROOT, env=environment(), capture_output=True,
                            text=True, timeout=4500, check=False)
    if result.returncode:
        known_names = set()

        def collect_names(value):
            if isinstance(value, list):
                for entry in value:
                    collect_names(entry)
            elif isinstance(value, dict):
                if isinstance(value.get('name'), str) and '{{' not in value['name']:
                    known_names.add(value['name'])
                for entry in value.values():
                    if isinstance(entry, (list, dict)):
                        collect_names(entry)

        for source in list((ROOT / 'roles').glob('*/tasks/*.yml')) + [
            ROOT / 'tests/topology-disposable.yml', ROOT / 'tests/topology-inspect.yml',
        ]:
            collect_names(yaml.safe_load(source.read_text()))
        labels = re.findall(r'(?m)^TASK \[([^\r\n]+)\] \*+\s*$', result.stdout)
        if labels:
            label = labels[-1].split(' : ', 1)[-1]
            if label in known_names:
                print('Last deployment task: ' + label, file=sys.stderr)
        # Report source locations only, never module arguments, results or URLs.
        for location in re.findall(r'(?m)^Origin: ([A-Za-z0-9_./-]+\.yml):(\d+):(\d+)\s*$',
                                   result.stdout + '\n' + result.stderr):
            try:
                relative = Path(location[0]).resolve().relative_to(ROOT)
            except ValueError:
                continue
            print(f'Ansible failure location: {relative}:{location[1]}:{location[2]}', file=sys.stderr)
        raise QualificationError('Ansible execution failed; raw output withheld.')
    return result.stdout


def validate_evidence(evidence):
    if not isinstance(evidence, dict) or evidence.get('schema') != 1:
        raise QualificationError('The runtime inspection did not finish.')
    topology = evidence.get('topology')
    if topology not in {'standard', 'enterprise'}:
        raise QualificationError('Runtime topology evidence is missing.')
    enterprise = topology == 'enterprise'
    if (len(evidence.get('starts', {})) != (17 if enterprise else 13)
            or len(evidence.get('network', {})) != 11 or not evidence.get('files')
            or not evidence.get('python', '').startswith('Python ')
            or evidence.get('api_health') != [200] * 7
            or evidence.get('https_health_home_login') not in
            ([200, 200, 302 if enterprise else 200], [200, 302, 302 if enterprise else 200])
            or evidence.get('oidc_discovery_validated') is not enterprise
            or evidence.get('private_gateway_listeners_validated') is not enterprise
            or evidence.get('actual_authentication_performed') is not False
            or LIMITATION not in evidence.get('limitations', [])):
        raise QualificationError('Runtime qualification evidence is incomplete.')


def baseline_matches(baseline, identity, evidence=None):
    if (not isinstance(baseline, dict) or baseline.get('identity') != identity
            or not isinstance(baseline.get('evidence'), dict) or not baseline['evidence']
            or baseline['evidence'].get('schema') != 1):
        raise QualificationError('A completed matching baseline is required.')
    validate_evidence(baseline['evidence'])
    if evidence is not None and baseline['evidence'] != evidence:
        raise QualificationError('Service timestamps, configuration hashes or runtime evidence changed.')


def qualify(args, work):
    values = read_json(args.inputs)
    validate_inputs(values, args.host)
    inventory_bytes = args.inventory.read_bytes()
    inventory = json.loads(execute([sys.executable, '-m', 'ansible.cli.inventory',
                                   '-i', str(args.inventory.resolve()), '--list']))
    validate_inventory(inventory, args.host)
    defaults = yaml.safe_load((ROOT / 'roles/deploy_py-phone-caller/defaults/main.yml').read_text())
    # Reports must not enter source synchronization and trigger their own rerun.
    excludes = values.get('py_phone_caller_sync_excludes', defaults['py_phone_caller_sync_excludes'])
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise QualificationError('Source exclusions must be an explicit list.')
    values['py_phone_caller_sync_excludes'] = list(dict.fromkeys([*excludes, '/deploy/ansible/tests/.runtime/']))
    report = work / 'report.json'
    values.update(stack_hosts=args.host, topology_test_host=args.host,
                  topology_test_allow_changes=True, topology_test_report=str(report))
    identity = {'schema': 1, 'host': args.host, 'inputs': digest(values),
                'inventory': hashlib.sha256(inventory_bytes).hexdigest(),
                'resolved_inventory': digest(inventory),
                'harness': {name: hashlib.sha256((ROOT / 'tests' / name).read_bytes()).hexdigest()
                            for name in ('run_topology_disposable.py', 'topology-disposable.yml',
                                         'topology-inspect.yml')}}
    baseline_path = work / 'baseline.json'
    if args.resume_rerun:
        baseline = read_json(baseline_path)
        baseline_matches(baseline, identity)
    else:
        # Invalidate a previous success before any new installation attempt.
        private_write(baseline_path, '{}\n')
    inputs = work / 'inputs.private.json'
    private_write(inputs, json.dumps(values))

    def run(stage, unchanged=False):
        if args.inventory.read_bytes() != inventory_bytes:
            raise QualificationError('The inventory changed during qualification.')
        # A stale inspection file must never satisfy a new run.
        private_write(report, '{}\n')
        command = [sys.executable, '-m', 'ansible.cli.playbook', '-i', str(args.inventory.resolve()),
                   str(ROOT / 'tests/topology-disposable.yml'), '--limit', args.host,
                   '--forks', '1', '-e', f'@{inputs}']
        log = work / f'{stage}.log'
        private_write(log, 'START runtime qualification; raw output withheld.\n')
        try:
            counts = parse_recap(execute(command), args.host, unchanged)
            evidence = read_json(report)
            validate_evidence(evidence)
        except Exception:
            private_write(log, 'FAIL runtime qualification; raw output withheld.\n')
            raise
        private_write(log, 'PASS runtime qualification.\n' + json.dumps(counts, sort_keys=True) + '\n')
        print('PASS ' + stage, flush=True)
        return evidence

    try:
        if not args.resume_rerun:
            baseline = {'identity': identity, 'evidence': run('install')}
            private_write(baseline_path, json.dumps(baseline, sort_keys=True))
        evidence = run('unchanged', unchanged=True)
        baseline_matches(baseline, identity, evidence)
        private_write(work / 'result.json', json.dumps({'qualified': True, 'changed': 0,
                      'identical_evidence': True, 'actual_authentication_performed': False,
                      'limitations': [LIMITATION]}))
        print('PASS unchanged rerun and identical runtime evidence. ' + LIMITATION, flush=True)
    finally:
        # The parent retains the original; this private snapshot is transient.
        inputs.unlink(missing_ok=True)


def main(argv=None):
    work = None
    try:
        args = parse_args(argv)
        values = read_json(args.inputs)
        validate_inputs(values, args.host)
        runtime = ROOT / 'tests/.runtime/topology'
        runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        runtime.chmod(0o700)
        with os.fdopen(os.open(runtime / 'runner.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'w') as lock:
            os.fchmod(lock.fileno(), 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            work = runtime / args.host / values['py_phone_caller_topology']
            work.mkdir(parents=True, exist_ok=True, mode=0o700)
            work.chmod(0o700)
            private_write(work / 'result.json', json.dumps({'qualified': False,
                          'actual_authentication_performed': False, 'limitations': [LIMITATION]}))
            qualify(args, work)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        if work is not None:
            try:
                private_write(work / 'runner.log', 'FAIL runtime qualification; details and raw output withheld.\n')
            except OSError:
                pass
        print('FAIL runtime qualification; details and raw output withheld. ' + LIMITATION, file=sys.stderr)
        if isinstance(error, QualificationError) and str(error) in {
            'Inputs override a protected harness or inventory variable.',
            'Inventory must contain only the acknowledged disposable host.',
            'Ansible execution failed; raw output withheld.',
            'The play did not complete cleanly.',
            'Runtime qualification evidence is incomplete.',
            'The unchanged run changed resources.',
            'Service timestamps, configuration hashes or runtime evidence changed.',
        }:
            print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())