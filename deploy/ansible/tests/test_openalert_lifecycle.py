"""Offline lifecycle fixtures; no daemon, service, SSH or hardware execution."""

import contextlib as openalert_contextlib
import grp as openalert_grp
import importlib.util as openalert_importlib
import json as openalert_json
import os as openalert_os
from pathlib import Path as openalert_Path
import pwd as openalert_pwd
import sqlite3 as openalert_sqlite3
import tempfile as openalert_tempfile
import unittest as openalert_unittest

import yaml as openalert_yaml


openalert_ansible = openalert_Path(__file__).resolve().parents[1]
openalert_helper = openalert_ansible / 'roles/openalert/files/openalert_lifecycle.py'
openalert_spec = openalert_importlib.spec_from_file_location('openalert_lifecycle', openalert_helper)
openalert_lifecycle = openalert_importlib.module_from_spec(openalert_spec)
openalert_spec.loader.exec_module(openalert_lifecycle)
openalert_snapshot_helper = openalert_ansible / 'roles/stack_lifecycle/files/stack_snapshot.py'


class openalert_LifecycleTests(openalert_unittest.TestCase):
    def setUp(self):
        self.openalert_temporary = openalert_tempfile.TemporaryDirectory(
            prefix='openalert-lifecycle-', dir=openalert_Path(__file__).parent)
        self.addCleanup(self.openalert_temporary.cleanup)
        self.openalert_base = openalert_Path(self.openalert_temporary.name).resolve()

    def openalert_fixture(self, openalert_name='hub', openalert_external_templates=True):
        openalert_base = self.openalert_base / openalert_name
        openalert_base.mkdir()
        openalert_user = openalert_pwd.getpwuid(openalert_os.getuid())
        if openalert_user.pw_uid == 0:
            openalert_user = openalert_pwd.getpwnam('nobody')
        openalert_group = openalert_grp.getgrgid(openalert_user.pw_gid)
        openalert_instance = {
            'name': openalert_name, 'service_name': 'openalertd-' + openalert_name + '.service',
            'user': openalert_user.pw_name, 'group': openalert_group.gr_name,
            'config_path': str(openalert_base / 'config/openalertd.toml'),
            'state_dir': str(openalert_base / 'state'),
            'openalert_schema': {'current': 'sqlite-v1', 'target': 'sqlite-v1'},
        }
        openalert_state = openalert_Path(openalert_instance['state_dir'])
        openalert_templates = openalert_base / 'custom-templates' if openalert_external_templates else openalert_state / 'templates'
        openalert_instance['openalert_templates_dir'] = str(openalert_templates)
        openalert_request = {
            'instance': openalert_instance, 'candidate_dir': str(openalert_base / 'candidate'),
            'checkpoint_dir': str(openalert_base / 'checkpoints'),
            'active_record': str(openalert_base / 'active.json'),
            'owner_record': str(openalert_base / 'owner.json'),
            'templates_dir': str(openalert_templates), 'release': 'b' * 64,
            'unit_dir': str(openalert_base / 'units'), 'legacy': {},
        }
        for openalert_directory in (openalert_state, openalert_templates,
                                   openalert_Path(openalert_instance['config_path']).parent,
                                   openalert_Path(openalert_request['candidate_dir']),
                                   openalert_Path(openalert_request['checkpoint_dir']),
                                   openalert_Path(openalert_request['unit_dir'])):
            openalert_directory.mkdir(parents=True, exist_ok=True)
        (openalert_templates / 'custom.json').write_text('{"message":"custom preserved template"}\n')
        openalert_rest = '0.0.0.0' if openalert_name == 'hub' else '127.0.0.1'
        (openalert_state / 'keys.json').write_text('{"private_key":"fixture-private-identity"}\n')
        openalert_config = (
            f'[rest]\nlisten_host = "{openalert_rest}"\nlisten_port = 8080\nauth_token = "fixture-secret-key"\n'
            f'[templates]\ntemplate_dir = "{openalert_templates}"\n'
            '[routing]\nprimary = "sms"\nfallback = ["webhook"]\n'
            '[sms]\nenabled = true\nport = "/dev/ttyUSB0"\n'
        )
        openalert_pairs = openalert_lifecycle.openalert_assets(openalert_request)
        for (openalert_candidate, openalert_active), openalert_content in zip(
                openalert_pairs, (openalert_config, '[Service]\nExecStart=/old/openalertd\n',
                                  '[Service]\nUser=' + openalert_instance['user'] + '\n')):
            openalert_candidate.parent.mkdir(parents=True, exist_ok=True)
            openalert_active.parent.mkdir(parents=True, exist_ok=True)
            openalert_candidate.write_text(openalert_content)
            openalert_active.write_text(openalert_content)
        openalert_pairs[1][0].write_text('[Service]\nExecStart=/new/openalertd\n')
        openalert_database = openalert_sqlite3.connect(openalert_state / 'events.sqlite')
        self.addCleanup(openalert_database.close)
        openalert_database.execute('PRAGMA journal_mode=WAL')
        openalert_database.execute('CREATE TABLE events (message TEXT)')
        openalert_database.execute('INSERT INTO events VALUES (?)', ('preserve dispatch state',))
        openalert_database.commit()
        openalert_binary = openalert_base / 'openalertd'
        openalert_binary.write_bytes(b'fixture binary, never executed')
        openalert_legacy = {
            **openalert_lifecycle.openalert_identity(openalert_instance),
            'unit_path': str(openalert_pairs[1][1]), 'binary_path': str(openalert_binary),
            'templates_dir': str(openalert_templates),
        }
        return openalert_request, openalert_legacy, openalert_database

    def test_openalert_equivalence_preserves_hub_and_field_configuration(self):
        for openalert_name, openalert_external in (('hub', True), ('field', False)):
            with self.subTest(layout=openalert_name):
                openalert_request, openalert_legacy, _ = self.openalert_fixture(openalert_name, openalert_external)
                openalert_candidate = openalert_lifecycle.openalert_assets(openalert_request)[0][0]
                self.assertTrue(openalert_lifecycle.openalert_equivalent(
                    openalert_request['instance'], openalert_legacy, str(openalert_candidate))['equivalent'])
                openalert_candidate.write_text('# harmless formatting\n' + openalert_candidate.read_text())
                self.assertTrue(openalert_lifecycle.openalert_equivalent(
                    openalert_request['instance'], openalert_legacy, str(openalert_candidate))['equivalent'])

    def test_openalert_failed_candidates_leave_legacy_files_unchanged(self):
        openalert_request, openalert_legacy, _ = self.openalert_fixture()
        openalert_pairs = openalert_lifecycle.openalert_assets(openalert_request)
        openalert_before = {openalert_path: openalert_path.read_bytes()
                           for _, openalert_path in openalert_pairs}
        openalert_config = openalert_pairs[0][0].read_text()
        for openalert_old, openalert_new in (('fixture-secret-key', 'changed-key'),
                                             ('8080', '8099'), ('sms', 'email')):
            with self.subTest(change=openalert_old):
                openalert_pairs[0][0].write_text(openalert_config.replace(openalert_old, openalert_new))
                with self.assertRaisesRegex(ValueError, 'complete parsed configuration'):
                    openalert_lifecycle.openalert_equivalent(
                        openalert_request['instance'], openalert_legacy, str(openalert_pairs[0][0]))
                self.assertEqual(openalert_before, {openalert_path: openalert_path.read_bytes()
                                                  for _, openalert_path in openalert_pairs})
        self.assertEqual(list(openalert_Path(openalert_request['checkpoint_dir']).iterdir()), [])

    def test_openalert_unchanged_needs_no_checkpoint_or_schema_declaration(self):
        openalert_request, _, _ = self.openalert_fixture()
        for openalert_candidate, openalert_active in openalert_lifecycle.openalert_assets(openalert_request):
            openalert_candidate.write_bytes(openalert_active.read_bytes())
        del openalert_request['instance']['openalert_schema']
        self.assertEqual(openalert_lifecycle.openalert_inspect(openalert_request), {'changed': False, 'existing': True})
        with self.assertRaisesRegex(ValueError, 'checkpoint only applies'):
            openalert_lifecycle.openalert_checkpoint(openalert_request, str(openalert_snapshot_helper))

    def test_openalert_changed_requires_current_and_target_schema(self):
        openalert_request, _, _ = self.openalert_fixture()
        for openalert_schema in ({}, {'current': 'sqlite-v1'}, {'target': 'sqlite-v1'}):
            with self.subTest(schema=openalert_schema):
                openalert_request['instance']['openalert_schema'] = openalert_schema
                with self.assertRaisesRegex(ValueError, 'schema compatibility'):
                    openalert_lifecycle.openalert_inspect(openalert_request)

    def test_openalert_unsafe_state_is_rejected_before_stop(self):
        openalert_request, _, _ = self.openalert_fixture()
        openalert_link = openalert_Path(openalert_request['instance']['state_dir']) / 'unsafe'
        openalert_link.symlink_to(openalert_request['candidate_dir'], target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'linked path'):
            openalert_lifecycle.openalert_inspect(openalert_request)

    def test_openalert_fresh_install_does_not_require_schema_inventory(self):
        openalert_request, _, openalert_database = self.openalert_fixture()
        openalert_database.close()
        for _, openalert_active in openalert_lifecycle.openalert_assets(openalert_request):
            openalert_active.unlink()
        (openalert_Path(openalert_request['instance']['state_dir']) / 'events.sqlite').unlink()
        (openalert_Path(openalert_request['instance']['state_dir']) / 'keys.json').unlink()
        del openalert_request['instance']['openalert_schema']
        self.assertEqual(openalert_lifecycle.openalert_inspect(openalert_request), {'changed': True, 'existing': False})

    def openalert_properties(self, openalert_request, openalert_legacy):
        openalert_instance = openalert_request['instance']
        return {
            'FragmentPath': openalert_legacy['unit_path'], 'DropInPaths': openalert_legacy['unit_path'] + '.d/instance.conf',
            'User': openalert_instance['user'], 'Group': openalert_instance['group'],
            'WorkingDirectory': openalert_instance['state_dir'], 'Environment': 'RUST_LOG=info',
            'EnvironmentFiles': '', 'RootDirectory': '', 'RootImage': '', 'DynamicUser': 'no',
            'ExecStartPre': '', 'ExecStartPost': '', 'ExecStop': '', 'ExecStopPost': '',
            'ExecCondition': '', 'BindPaths': '', 'BindReadOnlyPaths': '',
            'ExecStart': '{ path=' + openalert_legacy['binary_path'] + ' ; argv[]='
                         + openalert_legacy['binary_path'] + ' ' + openalert_instance['config_path']
                         + ' ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }',
        }

    def test_openalert_adoption_checks_real_files_and_account_identity(self):
        for openalert_name, openalert_external in (('hub', True), ('field', False)):
            with self.subTest(layout=openalert_name):
                openalert_request, openalert_legacy, _ = self.openalert_fixture(openalert_name, openalert_external)
                openalert_properties = self.openalert_properties(openalert_request, openalert_legacy)
                self.assertEqual(openalert_lifecycle.openalert_adoption(
                    openalert_request['instance'], openalert_legacy,
                    '\n'.join(openalert_key + '=' + openalert_value for openalert_key, openalert_value in openalert_properties.items()),
                    openalert_request['unit_dir']), {'approved': True})
                openalert_request['legacy'] = openalert_legacy
                self.assertTrue(openalert_lifecycle.openalert_inspect(openalert_request)['changed'])

    def test_openalert_adoption_rejects_unsupported_effective_units(self):
        openalert_request, openalert_legacy, _ = self.openalert_fixture()
        for openalert_key, openalert_value in (
                ('FragmentPath', '/usr/lib/systemd/system/other.service'),
                ('DropInPaths', '/etc/systemd/system/extra.conf'), ('User', 'root'),
                ('EnvironmentFiles', '/etc/secret.env'), ('Environment', 'OPENALERT_REST_PORT=9999'),
                ('ExecStart', '{ path=/bin/sh ; argv[]=/bin/sh -c daemon ; ignore_errors=no ; }'),
                ('ExecStartPre', '{ path=/bin/migrate ; }'), ('BindPaths', '/old:/new'),
                ('RootDirectory', '/container'), ('WorkingDirectory', '/different/state')):
            with self.subTest(property=openalert_key):
                openalert_properties = self.openalert_properties(openalert_request, openalert_legacy)
                openalert_properties[openalert_key] = openalert_value
                with self.assertRaises(ValueError):
                    openalert_lifecycle.openalert_adoption(
                        openalert_request['instance'], openalert_legacy,
                        '\n'.join(openalert_key + '=' + openalert_value for openalert_key, openalert_value in openalert_properties.items()),
                        openalert_request['unit_dir'])

    def test_openalert_adoption_rejects_identity_migration_and_schema_migration(self):
        openalert_request, openalert_legacy, _ = self.openalert_fixture()
        openalert_properties = '\n'.join(openalert_key + '=' + openalert_value for openalert_key, openalert_value in
                                         self.openalert_properties(openalert_request, openalert_legacy).items())
        for openalert_key in ('service_name', 'user', 'group', 'config_path', 'state_dir'):
            with self.subTest(identity=openalert_key):
                openalert_other = dict(openalert_legacy, **{openalert_key: 'different'})
                with self.assertRaisesRegex(ValueError, 'identical identities'):
                    openalert_lifecycle.openalert_adoption(openalert_request['instance'], openalert_other,
                                                          openalert_properties, openalert_request['unit_dir'])
        openalert_request['instance']['openalert_schema']['target'] = 'sqlite-v2'
        with self.assertRaisesRegex(ValueError, 'schema migration cannot be combined'):
            openalert_lifecycle.openalert_adoption(openalert_request['instance'], openalert_legacy,
                                                  openalert_properties, openalert_request['unit_dir'])

    def test_openalert_checkpoint_recovery_preserves_keys_templates_and_live_state(self):
        for openalert_name, openalert_external in (('hub', True), ('field', False)):
            with self.subTest(layout=openalert_name):
                openalert_request, openalert_legacy, openalert_database = self.openalert_fixture(openalert_name, openalert_external)
                openalert_request['legacy'] = openalert_legacy
                openalert_pairs = openalert_lifecycle.openalert_assets(openalert_request)
                openalert_original = {openalert_active: openalert_active.read_bytes() for _, openalert_active in openalert_pairs}
                openalert_original_mode = openalert_pairs[0][1].stat().st_mode
                openalert_checkpoint = openalert_lifecycle.openalert_checkpoint(openalert_request, str(openalert_snapshot_helper))
                openalert_transaction = openalert_Path(openalert_checkpoint['transaction'])
                self.assertEqual(openalert_transaction.stat().st_mode & 0o777, 0o700)
                self.assertEqual((openalert_transaction / 'recovery.json').stat().st_mode & 0o777, 0o600)
                for openalert_candidate, openalert_active in openalert_pairs:
                    openalert_active.write_bytes(openalert_candidate.read_bytes() + b'# failed release\n')
                openalert_database.execute('INSERT INTO events VALUES (?)', ('new runtime state',))
                openalert_database.commit()
                openalert_database.close()
                openalert_result = openalert_lifecycle.openalert_recover(str(openalert_transaction), str(openalert_snapshot_helper))
                self.assertEqual(openalert_result, {'recovered': True, 'state_restored': False})
                self.assertEqual(openalert_original, {openalert_active: openalert_active.read_bytes() for _, openalert_active in openalert_pairs})
                self.assertEqual(openalert_pairs[0][1].stat().st_mode, openalert_original_mode)
                with openalert_contextlib.closing(openalert_sqlite3.connect(
                        openalert_Path(openalert_request['instance']['state_dir']) / 'events.sqlite')) as openalert_check:
                    self.assertEqual(openalert_check.execute('SELECT message FROM events').fetchall(),
                                     [('preserve dispatch state',), ('new runtime state',)])
                openalert_full = openalert_json.loads((openalert_transaction / 'full.json').read_text())
                openalert_restore = self.openalert_base / (openalert_name + '-restore')
                openalert_restore.mkdir()
                openalert_mapping = {openalert_root: str(openalert_restore / str(openalert_index))
                                     for openalert_index, openalert_root in enumerate(openalert_full['paths'])}
                openalert_mapping_file = openalert_restore / 'mapping.json'
                openalert_mapping_file.write_text(openalert_json.dumps(openalert_mapping))
                openalert_lifecycle.openalert_snapshot(
                    str(openalert_snapshot_helper), 'restore', '--snapshot', str(openalert_transaction / 'full'),
                    '--plan', str(openalert_transaction / 'full.json'), '--mapping', str(openalert_mapping_file))
                openalert_restored_state = openalert_Path(openalert_mapping[openalert_request['instance']['state_dir']])
                with openalert_contextlib.closing(openalert_sqlite3.connect(openalert_restored_state / 'events.sqlite')) as openalert_check:
                    self.assertEqual(openalert_check.execute('SELECT message FROM events').fetchall(), [('preserve dispatch state',)])
                self.assertEqual((openalert_restored_state / 'keys.json').read_bytes(),
                                 (openalert_Path(openalert_request['instance']['state_dir']) / 'keys.json').read_bytes())
                openalert_restored_templates = (openalert_Path(openalert_mapping[openalert_legacy['templates_dir']])
                                               if openalert_external else openalert_restored_state / 'templates')
                self.assertEqual((openalert_restored_templates / 'custom.json').read_bytes(),
                                 (openalert_Path(openalert_legacy['templates_dir']) / 'custom.json').read_bytes())

    def test_openalert_schema_mismatch_refuses_assets_and_data_rollback(self):
        openalert_request, _, _ = self.openalert_fixture()
        openalert_request['instance']['openalert_schema']['target'] = 'sqlite-v2'
        openalert_transaction = openalert_lifecycle.openalert_checkpoint(openalert_request, str(openalert_snapshot_helper))['transaction']
        openalert_pairs = openalert_lifecycle.openalert_assets(openalert_request)
        for _, openalert_active in openalert_pairs:
            openalert_active.write_text('failed v2 assets')
        with self.assertRaisesRegex(ValueError, 'schema mismatch'):
            openalert_lifecycle.openalert_recover(openalert_transaction, str(openalert_snapshot_helper))
        self.assertTrue(all(openalert_active.read_text() == 'failed v2 assets' for _, openalert_active in openalert_pairs))

    def test_openalert_checkpoint_uses_previous_templates_not_candidate_release(self):
        openalert_request, openalert_legacy, _ = self.openalert_fixture()
        openalert_request['templates_dir'] = str(self.openalert_base / 'new-release-templates')
        openalert_transaction = openalert_Path(openalert_lifecycle.openalert_checkpoint(
            openalert_request, str(openalert_snapshot_helper))['transaction'])
        self.assertIn(openalert_legacy['templates_dir'], openalert_json.loads((openalert_transaction / 'full.json').read_text())['paths'])

    def test_openalert_metadata_mismatch_refuses_recovery(self):
        openalert_request, _, _ = self.openalert_fixture()
        openalert_transaction = openalert_Path(openalert_lifecycle.openalert_checkpoint(
            openalert_request, str(openalert_snapshot_helper))['transaction'])
        openalert_plan = openalert_json.loads((openalert_transaction / 'assets.json').read_text())
        openalert_plan['metadata']['instance'] = 'another-instance'
        (openalert_transaction / 'assets.json').write_text(openalert_json.dumps(openalert_plan))
        with self.assertRaisesRegex(ValueError, 'metadata mismatch'):
            openalert_lifecycle.openalert_recover(str(openalert_transaction), str(openalert_snapshot_helper))

    def test_openalert_absent_dropin_is_quarantined_not_deleted(self):
        openalert_request, _, _ = self.openalert_fixture()
        openalert_dropin = openalert_lifecycle.openalert_assets(openalert_request)[2][1]
        openalert_dropin.unlink()
        openalert_dropin.parent.rmdir()
        openalert_transaction = openalert_lifecycle.openalert_checkpoint(openalert_request, str(openalert_snapshot_helper))['transaction']
        openalert_dropin.parent.mkdir()
        openalert_dropin.write_text('failed new dropin')
        openalert_lifecycle.openalert_recover(openalert_transaction, str(openalert_snapshot_helper))
        self.assertFalse(openalert_dropin.parent.exists())
        openalert_retained = list(openalert_dropin.parent.parent.glob(openalert_dropin.parent.name + '.openalert-failed-*'))
        self.assertEqual(len(openalert_retained), 1)
        self.assertEqual((openalert_retained[0] / 'instance.conf').read_text(), 'failed new dropin')

    def openalert_relocated_fixture(self, openalert_name='hub', openalert_root_legacy=True,
                                    openalert_external_templates=True):
        openalert_base = self.openalert_base / ('relocate-' + openalert_name)
        openalert_base.mkdir()
        openalert_target_user = openalert_pwd.getpwuid(openalert_os.getuid())
        if openalert_target_user.pw_uid == 0:
            openalert_target_user = openalert_pwd.getpwnam('nobody')
        openalert_target_group = openalert_grp.getgrgid(openalert_target_user.pw_gid)
        openalert_legacy_user = 'root' if openalert_root_legacy else openalert_target_user.pw_name
        openalert_legacy_group = 'root' if openalert_root_legacy else openalert_target_group.gr_name
        openalert_service = ('openalertd.service' if openalert_name == 'hub'
                             else 'openalertd-' + openalert_name + '.service')
        openalert_legacy_config = openalert_base / 'legacy-etc' / (openalert_name + '.toml')
        openalert_legacy_state = openalert_base / ('root-state' if openalert_root_legacy else 'home-state')
        openalert_legacy_templates = (openalert_base / 'legacy-templates'
                                      if openalert_external_templates
                                      else openalert_legacy_state / 'templates')
        openalert_target_config = openalert_base / 'etc/openalert' / openalert_name / 'openalertd.toml'
        openalert_target_state = openalert_base / 'var/lib/openalert' / openalert_name
        openalert_target_templates = (openalert_base / 'etc/openalert' / (openalert_name + '-templates')
                                      if openalert_external_templates
                                      else openalert_target_state / 'templates')
        for openalert_dir in (openalert_legacy_config.parent, openalert_legacy_state,
                              openalert_legacy_templates, openalert_target_config.parent,
                              openalert_target_state, openalert_base / 'candidate' / (openalert_service + '.d'),
                              openalert_base / 'checkpoints', openalert_base / 'units'):
            openalert_dir.mkdir(parents=True, exist_ok=True)
        (openalert_legacy_templates / 'custom.json').write_text('{"message":"relocated template"}\n')
        (openalert_legacy_state / 'keys.json').write_text('{"private_key":"relocated-identity"}\n')
        openalert_database = openalert_sqlite3.connect(openalert_legacy_state / 'openalert.db')
        self.addCleanup(openalert_database.close)
        openalert_database.execute('PRAGMA journal_mode=WAL')
        openalert_database.execute('CREATE TABLE events (message TEXT)')
        openalert_database.execute('INSERT INTO events VALUES (?)', ('relocated wal row',))
        openalert_database.commit()
        openalert_legacy_toml = (
            '[rest]\nlisten_host = "127.0.0.1"\nlisten_port = 8080\nauth_token = "relocate-secret"\n'
            f'[templates]\ntemplate_dir = "{openalert_legacy_templates}"\n'
            f'[storage]\nenabled = true\npath = "{openalert_legacy_state / "openalert.db"}"\n'
            '[routing]\nprimary = "sms"\nfallback = ["webhook"]\n'
        )
        openalert_candidate_toml = (
            '[rest]\nlisten_host = "127.0.0.1"\nlisten_port = 8080\nauth_token = "relocate-secret"\n'
            f'[templates]\ntemplate_dir = "{openalert_target_templates}"\n'
            f'[storage]\nenabled = true\npath = "{openalert_target_state / "openalert.db"}"\n'
            '[routing]\nprimary = "sms"\nfallback = ["webhook"]\n'
        )
        openalert_legacy_config.write_text(openalert_legacy_toml)
        (openalert_base / 'candidate/openalertd.toml').write_text(openalert_candidate_toml)
        (openalert_base / 'candidate' / openalert_service).write_text('[Service]\nExecStart=/opt/openalert/bin/openalertd\n')
        (openalert_base / 'candidate' / (openalert_service + '.d') / 'instance.conf').write_text(
            '[Service]\nUser=' + openalert_target_user.pw_name + '\n')
        openalert_unit_path = openalert_base / 'units' / openalert_service
        openalert_unit_path.write_text('[Service]\nExecStart=/usr/local/bin/openalertd\n')
        openalert_binary = openalert_base / 'legacy-openalertd'
        openalert_binary.write_bytes(b'legacy binary fixture')
        openalert_instance = {
            'name': openalert_name, 'service_name': openalert_service,
            'user': openalert_target_user.pw_name, 'group': openalert_target_group.gr_name,
            'config_path': str(openalert_target_config), 'state_dir': str(openalert_target_state),
            'openalert_templates_dir': str(openalert_target_templates),
            'openalert_schema': {'current': 'sqlite-v1', 'target': 'sqlite-v1'},
        }
        openalert_legacy = {
            'relocate': True, 'service_name': openalert_service,
            'user': openalert_legacy_user, 'group': openalert_legacy_group,
            'config_path': str(openalert_legacy_config), 'state_dir': str(openalert_legacy_state),
            'unit_path': str(openalert_unit_path), 'binary_path': str(openalert_binary),
            'templates_dir': str(openalert_legacy_templates),
        }
        openalert_request = {
            'instance': openalert_instance, 'candidate_dir': str(openalert_base / 'candidate'),
            'checkpoint_dir': str(openalert_base / 'checkpoints'),
            'active_record': str(openalert_base / 'active.json'),
            'owner_record': str(openalert_base / 'owner.json'),
            'templates_dir': str(openalert_target_templates), 'release': 'c' * 64,
            'unit_dir': str(openalert_base / 'units'), 'legacy': openalert_legacy,
        }
        openalert_props = {
            'FragmentPath': str(openalert_unit_path), 'DropInPaths': '',
            'User': '' if openalert_root_legacy else openalert_legacy_user,
            'Group': '' if openalert_root_legacy else openalert_legacy_group,
            'WorkingDirectory': str(openalert_legacy_state), 'Environment': 'RUST_LOG=info',
            'EnvironmentFiles': '', 'RootDirectory': '', 'RootImage': '', 'DynamicUser': 'no',
            'ExecStartPre': '', 'ExecStartPost': '', 'ExecStop': '', 'ExecStopPost': '',
            'ExecCondition': '', 'BindPaths': '', 'BindReadOnlyPaths': '',
            'ExecStart': '{ path=' + str(openalert_binary) + ' ; argv[]='
                         + str(openalert_binary) + ' ' + str(openalert_legacy_config)
                         + ' ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }',
        }
        return openalert_request, openalert_legacy, openalert_props, openalert_database

    def test_openalert_relocated_adoption_supports_root_vps_and_home_field_layouts(self):
        for openalert_name, openalert_root_legacy, openalert_external in (
                ('hub', True, True), ('public', True, True), ('field', False, False)):
            with self.subTest(layout=openalert_name):
                openalert_request, openalert_legacy, openalert_props, openalert_db = self.openalert_relocated_fixture(
                    openalert_name, openalert_root_legacy, openalert_external)
                openalert_props_text = '\n'.join(k + '=' + v for k, v in openalert_props.items())
                self.assertEqual(openalert_lifecycle.openalert_adoption(
                    openalert_request['instance'], openalert_legacy, openalert_props_text,
                    openalert_request['unit_dir']), {'approved': True})
                self.assertEqual(openalert_lifecycle.openalert_stage_templates(
                    openalert_request['instance'], openalert_legacy), {'staged': True})
                self.assertEqual(openalert_lifecycle.openalert_inspect(openalert_request),
                                 {'changed': True, 'existing': True})
                openalert_checkpoint = openalert_lifecycle.openalert_checkpoint(
                    openalert_request, str(openalert_snapshot_helper))
                openalert_transaction = openalert_Path(openalert_checkpoint['transaction'])
                openalert_target_state = openalert_Path(openalert_request['instance']['state_dir'])
                self.assertEqual((openalert_target_state / 'keys.json').read_text(),
                                 '{"private_key":"relocated-identity"}\n')
                with openalert_contextlib.closing(
                        openalert_sqlite3.connect(openalert_target_state / 'openalert.db')) as openalert_conn:
                    self.assertEqual(openalert_conn.execute('SELECT message FROM events').fetchall(),
                                     [('relocated wal row',)])
                openalert_target_templates = openalert_Path(openalert_request['instance']['openalert_templates_dir'])
                self.assertEqual((openalert_target_templates / 'custom.json').read_text(),
                                 '{"message":"relocated template"}\n')
                # Simulate failed candidate installation and verify recovery restores legacy unit/config and quarantines target paths
                openalert_pairs = openalert_lifecycle.openalert_assets(openalert_request)
                for openalert_cand, openalert_act in openalert_pairs:
                    openalert_act.parent.mkdir(parents=True, exist_ok=True)
                    openalert_act.write_bytes(openalert_cand.read_bytes())
                openalert_db.close()
                openalert_result = openalert_lifecycle.openalert_recover(
                    str(openalert_transaction), str(openalert_snapshot_helper))
                self.assertEqual(openalert_result, {'recovered': True, 'state_restored': False})
                self.assertFalse(openalert_pairs[0][1].exists())
                self.assertFalse(openalert_target_state.exists())
                self.assertEqual(openalert_pairs[1][1].read_text(), '[Service]\nExecStart=/usr/local/bin/openalertd\n')
                self.assertTrue(openalert_Path(openalert_legacy['config_path']).exists())
                self.assertTrue((openalert_Path(openalert_legacy['state_dir']) / 'keys.json').exists())

    def test_openalert_relocated_adoption_rejects_overlapping_paths_and_config_drift(self):
        openalert_request, openalert_legacy, openalert_props, _ = self.openalert_relocated_fixture('hub', True, True)
        openalert_props_text = '\n'.join(k + '=' + v for k, v in openalert_props.items())
        # Reject overlapping state_dir
        openalert_overlapping = dict(openalert_request['instance'], state_dir=openalert_legacy['state_dir'])
        with self.assertRaisesRegex(ValueError, 'disjoint'):
            openalert_lifecycle.openalert_adoption(
                openalert_overlapping, openalert_legacy, openalert_props_text, openalert_request['unit_dir'])
        # Reject target user == root
        openalert_root_target = dict(openalert_request['instance'], user='root', group='root')
        with self.assertRaisesRegex(ValueError, 'target account cannot be root'):
            openalert_lifecycle.openalert_adoption(
                openalert_root_target, openalert_legacy, openalert_props_text, openalert_request['unit_dir'])
        # Reject changed storage relative filename or changed auth token
        openalert_cand_file = openalert_lifecycle.openalert_assets(openalert_request)[0][0]
        openalert_cand_text = openalert_cand_file.read_text()
        openalert_cand_file.write_text(openalert_cand_text.replace('openalert.db', 'other.db'))
        with self.assertRaisesRegex(ValueError, 'relative database path'):
            openalert_lifecycle.openalert_equivalent(
                openalert_request['instance'], openalert_legacy, str(openalert_cand_file))
        openalert_cand_file.write_text(openalert_cand_text.replace('relocate-secret', 'tampered-secret'))
        with self.assertRaisesRegex(ValueError, 'complete parsed configuration'):
            openalert_lifecycle.openalert_equivalent(
                openalert_request['instance'], openalert_legacy, str(openalert_cand_file))


class openalert_TaskTests(openalert_unittest.TestCase):
    def openalert_tasks(self, openalert_name):
        return openalert_yaml.safe_load((openalert_ansible / 'roles/openalert/tasks' / openalert_name).read_text())

    def test_openalert_lock_surrounds_preflight_stage_and_activation(self):
        openalert_main = self.openalert_tasks('main.yml')
        self.assertEqual(openalert_main[2]['ansible.builtin.command']['argv'],
                         ['mkdir', '--mode=0700', '--', '/run/lock/py-phone-caller-lifecycle'])
        self.assertEqual(openalert_main[3]['block'][0]['ansible.builtin.import_tasks'], 'run.yml')
        self.assertEqual(openalert_main[3]['always'][0]['ansible.builtin.file'],
                         {'path': '/run/lock/py-phone-caller-lifecycle', 'state': 'absent'})
        openalert_run = self.openalert_tasks('run.yml')
        openalert_includes = [openalert_task['ansible.builtin.include_tasks'] for openalert_task in openalert_run
                             if 'ansible.builtin.include_tasks' in openalert_task]
        self.assertEqual(openalert_includes, ['stage.yml', 'plan.yml', 'activate.yml', 'health.yml'])
        self.assertEqual(openalert_run[-3]['ansible.builtin.meta'], 'flush_handlers')
        openalert_prepare = [openalert_task['ansible.builtin.include_role'] for openalert_task in openalert_run
                            if 'ansible.builtin.include_role' in openalert_task]
        self.assertEqual(openalert_prepare, [{'name': 'stack_lifecycle', 'tasks_from': 'prepare.yml'}])

    def test_openalert_unchanged_cannot_stop_restart_or_checkpoint(self):
        openalert_tasks = self.openalert_tasks('activate.yml')
        self.assertEqual(len(openalert_tasks), 2)
        self.assertEqual(openalert_tasks[0]['ansible.builtin.set_fact'], {
            'openalert_activation_plan': '{{ openalert_activation_plans[openalert_instance.name] }}',
            'openalert_checkpoint_transaction': '',
            'openalert_activation_installed': False,
        })
        self.assertNotIn('when', openalert_tasks[1])
        self.assertEqual(openalert_tasks[1]['ansible.builtin.include_tasks'], 'activate_changed.yml')
        self.assertNotIn('block', openalert_tasks[1])
        openalert_run = self.openalert_tasks('run.yml')
        self.assertEqual(openalert_run[-1]['when'], 'not openalert_activation_plans[openalert_instance.name].changed')
        self.assertEqual(openalert_run[-1]['ansible.builtin.include_tasks'], 'health.yml')
        self.assertEqual(openalert_run[-4]['changed_when'], 'openalert_pending_activation | length > 0')
        self.assertIn("selectattr('value.changed')", openalert_run[-4]['ansible.builtin.set_fact']['openalert_pending_activation'])
        self.assertEqual(openalert_run[-4]['notify'], 'Apply planned OpenAlert transactions')
        self.assertEqual(openalert_run[-2]['loop'], '{{ openalert_pending_activation }}')
        self.assertEqual(openalert_run[-2]['loop_control']['loop_var'], 'openalert_instance')
        self.assertEqual(openalert_run[-2]['ansible.builtin.include_tasks'], 'activate.yml')
        openalert_handlers = openalert_yaml.safe_load((openalert_ansible / 'roles/openalert/handlers/main.yml').read_text())
        self.assertEqual(openalert_handlers[0]['name'], openalert_run[-4]['notify'])
        openalert_transaction = self.openalert_tasks(openalert_tasks[1]['ansible.builtin.include_tasks'])
        self.assertEqual(len(openalert_transaction), 1)
        self.assertNotIn('when', openalert_transaction[0])
        self.assertIn('rescue', openalert_transaction[0])
        openalert_changed = openalert_transaction[0]['block']
        self.assertEqual(openalert_changed[0]['ansible.builtin.systemd_service']['state'], 'stopped')
        self.assertEqual(openalert_changed[0]['when'], 'openalert_activation_plan.existing')
        self.assertIn('checkpoint', openalert_changed[1]['ansible.builtin.command']['argv'])
        self.assertEqual(openalert_changed[1]['when'], 'openalert_activation_plan.existing')
        self.assertEqual(openalert_changed[3]['ansible.builtin.include_tasks'], 'install.yml')

    def test_openalert_adoption_does_not_mutate_legacy_before_validation(self):
        for openalert_task in self.openalert_tasks('stage.yml'):
            if (any(openalert_module in openalert_task for openalert_module in ('ansible.builtin.group', 'ansible.builtin.user'))
                    or openalert_task.get('ansible.builtin.file', {}).get('path') in (
                        '{{ openalert_instance.state_dir }}', '{{ openalert_instance.config_path | dirname }}')
                    or '/owners/' in openalert_task.get('ansible.builtin.copy', {}).get('dest', '')):
                self.assertEqual(openalert_task['when'], 'openalert_instance.name not in openalert_approved_adoptions and openalert_instance.name not in openalert_existing_instances')
        openalert_relocate = self.openalert_tasks('relocate_stage.yml')
        self.assertFalse(any('/owners/' in openalert_task.get('ansible.builtin.copy', {}).get('dest', '')
                             for openalert_task in openalert_relocate))
        openalert_owner = self.openalert_tasks('ownership.yml')
        openalert_adoption = next(openalert_task for openalert_task in openalert_owner
                                 if openalert_task.get('ansible.builtin.include_tasks') == 'adoption.yml')
        self.assertIn('openalert_instance.name in openalert_legacy_instances', openalert_adoption['when'])
        self.assertIn('openalert_adopt', openalert_adoption['when'])


if __name__ == '__main__':
    openalert_unittest.main()