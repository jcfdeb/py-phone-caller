"""Offline parser contracts and a read-only localhost Ansible startup check."""

import copy
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from ansible.parsing.dataloader import DataLoader
from ansible.playbook.play import Play
from ansible.plugins.filter.core import FilterModule
from ansible.plugins.filter.urlsplit import FilterModule as URLFilters
from ansible.plugins.loader import init_plugin_loader
from ansible.plugins.test.core import TestModule
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment
import yaml

import run_topology_disposable as runner

# This imported Ansible plugin is not a pytest test container.
TestModule.__test__ = False


HERE = Path(__file__).resolve().parent
HOST = 'ppc-qual-debian-enterprise-20261101'


def inputs(topology='enterprise'):
    return {'py_phone_caller_topology': topology,
            'py_phone_caller_connectivity': 'online' if topology == 'enterprise' else 'airgapped',
            'py_phone_caller_public_url': 'https://caller.internal',
            'topology_test_parent_joined': True,
            'topology_test_tls_ca_path': '/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt'}


def recap(**overrides):
    counts = {'ok': 100, 'changed': 0, 'unreachable': 0, 'failed': 0, 'skipped': 10, 'rescued': 0, 'ignored': 0}
    counts.update(overrides)
    return 'TASK [redacted] ***\nPLAY RECAP ************\n' + HOST + ' : ' + ' '.join(
        f'{key}={value}' for key, value in counts.items()) + '\n'


def evidence(topology='enterprise'):
    # Parser data, not a simulated runtime qualification or fake API response.
    enterprise = topology == 'enterprise'
    return {'schema': 1, 'topology': topology,
            'starts': {str(index): 'timestamp' for index in range(17 if enterprise else 13)},
            'network': {str(index): 'policy' for index in range(11)},
            'files': {'config': {'sha256': 'a' * 64}}, 'python': 'Python 3.14.5',
            'api_health': [200] * 7, 'https_health_home_login': [200, 200, 302 if enterprise else 200],
            'oidc_discovery_validated': enterprise, 'private_gateway_listeners_validated': enterprise,
            'actual_authentication_performed': False, 'limitations': [runner.LIMITATION]}


def environment():
    env = NativeEnvironment(undefined=StrictUndefined)
    default_filter = env.filters['default']
    env.filters.update(FilterModule().filters())
    env.filters.update(URLFilters().filters())
    env.filters['default'] = default_filter
    env.tests.update(TestModule().tests())
    return env


class RunnerParserTests(unittest.TestCase):
    def test_hardened_environment_starts_a_real_read_only_playbook(self):
        runtime = HERE / '.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='runner-environment-', dir=runtime) as directory:
            playbook = Path(directory) / 'check.yml'
            playbook.write_text(yaml.safe_dump([{
                'name': 'Read-only startup fixture', 'hosts': 'localhost',
                'connection': 'local', 'gather_facts': False,
                'tasks': [{'name': 'Verify fixture startup', 'ansible.builtin.assert': {'that': True}}],
            }]))
            result = subprocess.run([sys.executable, '-m', 'ansible.cli.playbook', '-i', 'localhost,',
                                     str(playbook)], cwd=runner.ROOT, env=runner.environment(),
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('changed=0', result.stdout)

    def test_explicit_cli_and_resume(self):
        args = runner.parse_args(['--inventory', __file__, '--inputs', __file__, '--host', HOST,
                                  '--allow-disposable-changes', '--resume-rerun'])
        self.assertEqual(args.host, HOST)
        self.assertTrue(args.resume_rerun)

    def test_reject_missing_authorization_and_host_patterns(self):
        base = ['--inventory', __file__, '--inputs', __file__, '--host', HOST]
        with self.assertRaises(runner.QualificationError):
            runner.parse_args(base)
        for host in ('all', 'localhost', 'ungrouped', '*', 'a:b', 'a,b', '../vm', '-vm', 'a\nb'):
            with self.subTest(host=host), self.assertRaises(runner.QualificationError):
                runner.parse_args(base[:-1] + [host, '--allow-disposable-changes'])

    def test_parser_failures_do_not_echo_arguments(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = runner.main(['--secret-url=https://user:PRIVATE@invalid/'])
        self.assertEqual(result, 1)
        self.assertEqual(out.getvalue(), '')
        self.assertNotIn('PRIVATE', err.getvalue())
        self.assertNotIn('https://', err.getvalue())
        self.assertIn('Actual authentication not performed', err.getvalue())

    def test_supported_profiles_and_explicit_parent_join(self):
        for topology in ('standard', 'enterprise'):
            runner.validate_inputs(inputs(topology), HOST)
        for value in (False, None, 'true', 1):
            values = inputs()
            values['topology_test_parent_joined'] = value
            with self.subTest(value=value), self.assertRaises(runner.QualificationError):
                runner.validate_inputs(values, HOST)

    def test_input_safety_boundaries(self):
        changes = [
            {'py_phone_caller_topology': 'legacy'},
            {'py_phone_caller_topology': 'standard', 'py_phone_caller_connectivity': 'online'},
            {'py_phone_caller_public_url': 'https://user:PRIVATE@caller.internal'},
            {'py_phone_caller_public_url': 'https://external.invalid'},
            {'topology_test_tls_ca_path': 'root.crt'},
            {'topology_test_tls_ca_path': '/etc/tls/server.key'},
            {'topology_test_allow_changes': False},
            {'stack_hosts': 'all'}, {'stack_disposable_test_acknowledged': True},
            {'ansible_connection': 'local'}, {'topology_test_report': '/tmp/other'},
            {'topology_test_health_ports': []}, {'py_phone_caller_services': []},
            {'py_phone_caller_final_config': {}},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(runner.QualificationError):
                runner.validate_inputs(inputs() | change, HOST)

    def test_inventory_must_acknowledge_exactly_one_host(self):
        inventory = {'_meta': {'hostvars': {HOST: {'stack_disposable_test_acknowledged': True}}},
                     'test': {'hosts': [HOST]}}
        runner.validate_inventory(inventory, HOST)
        for value in (False, 'true', 1, None):
            invalid = copy.deepcopy(inventory)
            invalid['_meta']['hostvars'][HOST]['stack_disposable_test_acknowledged'] = value
            with self.subTest(value=value), self.assertRaises(runner.QualificationError):
                runner.validate_inventory(invalid, HOST)
        for invalid in ({}, inventory | {'other': {'hosts': ['production']}}):
            with self.assertRaises(runner.QualificationError):
                runner.validate_inventory(invalid, HOST)

    def test_recap_accepts_only_clean_single_host_completion(self):
        self.assertEqual(runner.parse_recap(recap(), HOST, unchanged=True)['changed'], 0)
        self.assertEqual(runner.parse_recap(recap(changed=25), HOST)['changed'], 25)
        for field in ('changed', 'unreachable', 'failed', 'rescued', 'ignored'):
            with self.subTest(field=field), self.assertRaises(runner.QualificationError):
                runner.parse_recap(recap(**{field: 1}), HOST, unchanged=True)

    def test_recap_rejects_nohosts_truncated_duplicate_and_wrong_host(self):
        invalid = ['', 'skipping: no hosts matched', recap(ok=0), recap().replace(HOST, 'other'),
                   recap().replace(' ignored=0', ''), recap() + 'other : ok=1 changed=0\n',
                   recap() + 'changed=0 unreachable=0 failed=0\n', recap() + recap(),
                   recap().replace('changed=0', 'changed=0 changed=1'),
                   recap().replace('changed=0', 'changed=-1'), recap().replace('ok=100', 'ok=100SECRET')]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(runner.QualificationError):
                runner.parse_recap(value, HOST, unchanged=True)

    def test_resume_requires_identical_inputs_and_complete_evidence(self):
        identity = {'inputs': 'a', 'inventory': 'b', 'host': HOST}
        baseline = {'identity': identity, 'evidence': evidence()}
        runner.baseline_matches(baseline, identity, copy.deepcopy(baseline['evidence']))
        for invalid in ({}, baseline | {'identity': identity | {'inputs': 'new'}},
                        baseline | {'evidence': {'schema': 1}}):
            with self.assertRaises(runner.QualificationError):
                runner.baseline_matches(invalid, identity)
        for key, value in [('starts', {}), ('files', {'different': 'hash'}), ('network', {}),
                           ('https_health_home_login', [200, 200, 200])]:
            with self.subTest(key=key), self.assertRaises(runner.QualificationError):
                runner.baseline_matches(baseline, identity, baseline['evidence'] | {key: value})

    def test_evidence_never_claims_authentication(self):
        for topology in ('standard', 'enterprise'):
            values = evidence(topology)
            runner.validate_evidence(values)
            for change in ({'actual_authentication_performed': True}, {'limitations': []},
                           {'api_health': [200]}, {'oidc_discovery_validated': 'true'}):
                with self.assertRaises(runner.QualificationError):
                    runner.validate_evidence(values | change)

    def test_private_writes_restrict_existing_files_and_refuse_symlinks(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / 'private.log'
            path.touch(mode=0o644)
            runner.private_write(path, 'fixed message\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            link = Path(directory) / 'link'
            link.symlink_to(path)
            with self.assertRaises(OSError):
                runner.private_write(link, 'must not write')
            self.assertEqual(path.read_text(), 'fixed message\n')

    def test_duplicate_json_keys_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / 'inputs.json'
            runner.private_write(path, '{"nested": {"flag": true, "flag": false}}')
            with self.assertRaises(runner.QualificationError):
                runner.read_json(path)

    def test_environment_disables_raw_logs_diff_and_extra_callbacks(self):
        with patch.dict('os.environ', {'ANSIBLE_LOG_PATH': '/secret/log', 'ANSIBLE_CALLBACKS_ENABLED': 'custom',
                                      'ANSIBLE_DEBUG': 'true', 'ANSIBLE_DIFF_ALWAYS': 'true'}):
            env = runner.environment()
        self.assertEqual(env['ANSIBLE_LOG_PATH'], runner.os.devnull)
        self.assertEqual(env['ANSIBLE_CALLBACKS_ENABLED'], 'ansible.builtin.default')
        self.assertEqual(env['ANSIBLE_NO_LOG'], 'true')
        self.assertEqual(env['ANSIBLE_DIFF_ALWAYS'], 'false')
        self.assertNotIn('ANSIBLE_DEBUG', env)


class PlaybookParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wrapper = yaml.safe_load((HERE / 'topology-disposable.yml').read_text())
        cls.inspect = yaml.safe_load((HERE / 'topology-inspect.yml').read_text())[0]
        cls.env = environment()

    def test_real_site_import_and_no_implicit_hosts(self):
        self.assertEqual(self.wrapper[1]['ansible.builtin.import_playbook'], '../site.yml')
        self.assertEqual(self.wrapper[2]['ansible.builtin.import_playbook'], 'topology-inspect.yml')
        for play in (self.wrapper[0], self.inspect):
            self.assertIn('topology-disposable-unselected', play['hosts'])
            self.assertTrue(play['no_log'])
            self.assertFalse(play['gather_facts'])
        self.assertIn('topology-disposable-unselected', self.wrapper[1]['vars']['stack_hosts'])

    def test_ansible_parses_plays_without_inventory_or_execution(self):
        init_plugin_loader()
        loader = DataLoader()
        loader.set_basedir(str(HERE))
        for data in (self.wrapper[0], self.inspect):
            play = Play.load(copy.deepcopy(data), loader=loader)
            self.assertTrue(play.get_tasks())

    def test_all_inspection_http_is_get_no_proxy_no_redirect_and_trusted_tls(self):
        requests = [task['ansible.builtin.uri'] for task in self.inspect['tasks'] if 'ansible.builtin.uri' in task]
        self.assertEqual(len(requests), 3)
        for request in requests:
            self.assertEqual(request['method'], 'GET')
            self.assertEqual(request['follow_redirects'], 'none')
            self.assertFalse(request['use_proxy'])
            self.assertFalse(request['use_netrc'])
            self.assertNotIn('url_password', request)
            if 'py_phone_caller_public_url' in request['url']:
                self.assertTrue(request['validate_certs'])
                self.assertEqual(request['ca_path'], '{{ topology_test_tls_ca_path }}')
            else:
                self.assertEqual(request['url'], 'http://127.0.0.1:{{ item }}/health')

    def test_inspection_only_writes_nonsecret_controller_report(self):
        allowed = {'ansible.builtin.assert', 'ansible.builtin.wait_for', 'ansible.builtin.command',
                   'ansible.builtin.uri', 'ansible.builtin.stat', 'ansible.builtin.find',
                   'ansible.builtin.set_fact', 'ansible.builtin.copy'}
        for task in self.inspect['tasks']:
            actions = {key for key in task if key.startswith('ansible.builtin.')}
            self.assertEqual(len(actions), 1)
            self.assertTrue(actions <= allowed)
            if 'ansible.builtin.command' in task:
                self.assertFalse(task['changed_when'])
            if 'ansible.builtin.copy' in task:
                self.assertEqual(task['delegate_to'], 'localhost')
                self.assertFalse(task['become'])
                self.assertEqual(task['ansible.builtin.copy']['mode'], '0600')
                self.assertNotIn('topology_test_discovery.json', task['ansible.builtin.copy']['content'])

    def test_jinja_syntax_for_every_template_and_assertion(self):
        def walk(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    if key == 'that':
                        for assertion in child:
                            self.env.parse('{{ ' + assertion + ' }}')
                    else:
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
            elif isinstance(value, str) and '{{' in value:
                self.env.parse(value)
        walk(self.wrapper)
        walk(self.inspect)

    def test_effective_config_assertions_reject_secret_and_override_layer_bypasses(self):
        defaults = yaml.safe_load((HERE.parent / 'roles/deploy_py-phone-caller/defaults/main.yml').read_text())
        fixture = yaml.safe_load((HERE / 'fixtures/python-runtime.yml').read_text())
        merge = self.wrapper[0]['tasks'][1]['ansible.builtin.set_fact']['topology_test_config']
        assertions = self.wrapper[0]['tasks'][2]['ansible.builtin.assert']['that']
        values = defaults | fixture | inputs('standard')

        def safe(data):
            config = self.env.from_string(merge).render(data)
            return all(self.env.from_string('{{ ' + expression + ' }}').render(
                data | {'topology_test_config': config}) is True for expression in assertions)

        self.assertTrue(safe(values))
        for layer in ('py_phone_caller_config_secrets', 'py_phone_caller_config_overrides'):
            for unsafe in ({'queue': {'queue_url': 'redis://127.0.0.1:6379/0'}},
                           {'database': {'db_name': 'production'}},
                           {'caller_sms': {'modems': ['/dev/ttyUSB0']}},
                           {'caller_prometheus_webhook': {'prometheus_webhook_receivers': ['real']}},
                           {'asterisk_recaller': {'times_to_dial': 1}}):
                data = copy.deepcopy(values)
                data[layer] = unsafe
                with self.subTest(layer=layer, unsafe=unsafe):
                    self.assertFalse(safe(data))

    def test_listener_assertions_reject_wildcard_bindings(self):
        task = next(task for task in self.inspect['tasks'] if task['name'].startswith('Require every gateway listener'))
        for address, expected in [('127.0.0.1', True), ('0.0.0.0', False), ('[::]', False), ('192.0.2.1', False)]:
            output = f'LISTEN 0 128 {address}:9080 0.0.0.0:*'
            values = {'item': 9080, 'topology_test_listeners': {'stdout': output, 'stdout_lines': [output]}}
            self.assertEqual(all(self.env.from_string('{{ ' + expression + ' }}').render(values)
                                 for expression in task['ansible.builtin.assert']['that']), expected)

    def listener_assertions_pass(self, rows, topology='enterprise'):
        prefix = 'Require every gateway listener' if topology == 'enterprise' else 'Require no gateway listeners'
        task = next(task for task in self.inspect['tasks'] if task['name'].startswith(prefix))
        values = {'topology_test_listeners': {'stdout': '\n'.join(rows), 'stdout_lines': rows}}
        return all(self.env.from_string('{{ ' + expression + ' }}').render(values | {'item': port}) is True
                   for port in task.get('loop', [None]) for expression in task['ansible.builtin.assert']['that'])

    def test_listener_assertions_accept_debian_reuseport_and_java_mapped_loopback(self):
        rows = '''LISTEN 0 4096 127.0.0.1:2379 0.0.0.0:*
LISTEN 0 4096 127.0.0.1:2380 0.0.0.0:*
LISTEN 0 4096 [::ffff:127.0.0.1]:8180 *:*
LISTEN 0 4096 127.0.0.1:9001 0.0.0.0:*
LISTEN 0 4096 [::ffff:127.0.0.1]:9009 *:*
LISTEN 0 511 127.0.0.1:9080 0.0.0.0:*
LISTEN 0 511 127.0.0.1:9080 0.0.0.0:*
LISTEN 0 511 127.0.0.1:9080 0.0.0.0:*
LISTEN 0 511 127.0.0.1:9080 0.0.0.0:*
LISTEN 0 511 127.0.0.1:9091 0.0.0.0:*
LISTEN 0 511 127.0.0.1:9180 0.0.0.0:*'''.splitlines()
        self.assertTrue(self.listener_assertions_pass(rows))

    def test_listener_assertions_accept_loopback_families_and_duplicates(self):
        ports = (2379, 2380, 8180, 9001, 9009, 9080, 9091, 9180)
        for address in ('127.0.0.1', '[::ffff:127.0.0.1]', '[::1]'):
            rows = [f'LISTEN 0 128 {address}:{port} *:*' for port in ports]
            with self.subTest(address=address):
                self.assertTrue(self.listener_assertions_pass(rows))
                self.assertTrue(self.listener_assertions_pass(rows * 4))

    def test_listener_assertions_reject_missing_required_ports(self):
        ports = (2379, 2380, 8180, 9001, 9009, 9080, 9091, 9180)
        self.assertFalse(self.listener_assertions_pass([]))
        for missing in ports:
            rows = [f'LISTEN 0 128 127.0.0.1:{port} *:*' for port in ports if port != missing]
            with self.subTest(missing=missing):
                self.assertFalse(self.listener_assertions_pass(rows))

    def test_listener_assertions_reject_mixed_loopback_and_exposed_endpoints(self):
        ports = (2379, 2380, 8180, 9001, 9009, 9080, 9091, 9180)
        rows = [f'LISTEN 0 128 127.0.0.1:{port} *:*' for port in ports]
        for port in ports:
            for address in ('0.0.0.0', '[::]', '*', '192.0.2.1', '10.0.0.1',
                            '[::ffff:192.0.2.1]', '[::ffff:0.0.0.0]'):
                with self.subTest(port=port, address=address):
                    self.assertFalse(self.listener_assertions_pass(
                        rows + [f'LISTEN 0 128 {address}:{port} *:*']))

    def test_listener_assertions_reject_legacy_tls_and_cluster_ports(self):
        rows = [f'LISTEN 0 128 127.0.0.1:{port} *:*'
                for port in (2379, 2380, 8180, 9001, 9009, 9080, 9091, 9180)]
        for port in (7800, 8443, 9443):
            for address in ('127.0.0.1', '[::1]', '0.0.0.0', '[::]'):
                with self.subTest(port=port, address=address):
                    self.assertFalse(self.listener_assertions_pass(
                        rows + [f'LISTEN 0 128 {address}:{port} *:*']))

    def test_standard_listener_assertions_reject_gateway_and_cluster_ports(self):
        self.assertTrue(self.listener_assertions_pass(['LISTEN 0 128 *:443 *:*'], 'standard'))
        for port in (2379, 2380, 7800, 8180, 8443, 9001, 9009, 9080, 9091, 9180, 9443):
            with self.subTest(port=port):
                self.assertFalse(self.listener_assertions_pass(
                    [f'LISTEN 0 128 127.0.0.1:{port} *:*'], 'standard'))

    def test_all_python_gateway_caddy_and_pbx_units_are_included(self):
        defaults = yaml.safe_load((HERE.parent / 'roles/deploy_py-phone-caller/defaults/main.yml').read_text())
        for topology, count in [('enterprise', 17), ('standard', 13)]:
            values = defaults | inputs(topology)
            for key in ('topology_test_python_units', 'topology_test_gateway_units', 'topology_test_units'):
                values[key] = self.env.from_string(self.inspect['vars'][key]).render(values)
            self.assertEqual(len(values['topology_test_python_units']), 11)
            self.assertEqual(len(set(values['topology_test_units'])), count)
            self.assertIn('asterisk.service', values['topology_test_units'])
            self.assertIn('caddy.service', values['topology_test_units'])

    def test_hash_paths_include_loaded_units_and_dropins(self):
        task = next(task for task in self.inspect['tasks'] if task['name'].startswith('Hash dependency configurations'))
        values = {'topology_test_dependency_paths': {'files': [{'path': '/etc/redis/redis.conf'}]},
                  'topology_test_starts': {'results': [{'stdout_lines': [
                      'FragmentPath=/usr/lib/systemd/system/caddy.service',
                      'DropInPaths=/etc/systemd/system/caddy.service.d/tls.conf /etc/systemd/system/caddy.service.d/limits.conf'
                  ]}]}}
        paths = self.env.from_string(task['loop']).render(values)
        self.assertIn('/etc/redis/redis.conf', paths)
        self.assertIn('/usr/lib/systemd/system/caddy.service', paths)
        self.assertIn('/etc/systemd/system/caddy.service.d/tls.conf', paths)
        self.assertIn('/etc/systemd/system/caddy.service.d/limits.conf', paths)


if __name__ == '__main__':
    unittest.main()