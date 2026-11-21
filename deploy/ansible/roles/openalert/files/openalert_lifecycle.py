#!/usr/bin/env python3
"""Offline lifecycle guards and snapshot orchestration; never controls services."""

import argparse as openalert_argparse
import grp as openalert_grp
import hashlib as openalert_hashlib
import json as openalert_json
import os as openalert_os
from pathlib import Path as openalert_Path
import pwd as openalert_pwd
import re as openalert_re
import stat as openalert_stat
import subprocess as openalert_subprocess
import sys as openalert_sys
import tomllib as openalert_tomllib
import uuid as openalert_uuid


def openalert_require(openalert_condition, openalert_message):
    if not openalert_condition:
        raise ValueError(openalert_message)


def openalert_path(openalert_value, openalert_exists=True):
    openalert_result = openalert_Path(openalert_value)
    openalert_require(openalert_result.is_absolute() and '..' not in openalert_result.parts
                      and str(openalert_result) == openalert_value and openalert_value != '/',
                      'unsafe path')
    for openalert_part in [*reversed(openalert_result.parents), openalert_result]:
        openalert_require(not openalert_part.is_symlink(), 'linked path')
    if openalert_exists:
        openalert_info = openalert_result.stat()
        openalert_require(openalert_stat.S_ISDIR(openalert_info.st_mode)
                          or (openalert_stat.S_ISREG(openalert_info.st_mode)
                              and openalert_info.st_nlink == 1), 'special or hard-linked path')
    return openalert_result


def openalert_tree(openalert_value):
    openalert_root = openalert_path(openalert_value)
    if openalert_root.is_dir():
        for openalert_parent, openalert_dirs, openalert_files in openalert_os.walk(openalert_root):
            for openalert_name in openalert_dirs + openalert_files:
                openalert_path(str(openalert_Path(openalert_parent) / openalert_name))
    return openalert_root


def openalert_identity(openalert_instance):
    return {openalert_key: openalert_instance[openalert_key] for openalert_key in
            ('service_name', 'user', 'group', 'config_path', 'state_dir')}


def openalert_disjoint(openalert_first, openalert_second):
    openalert_left = openalert_Path(openalert_first)
    openalert_right = openalert_Path(openalert_second)
    return (openalert_left != openalert_right
            and not openalert_left.is_relative_to(openalert_right)
            and not openalert_right.is_relative_to(openalert_left))


def openalert_adoption(openalert_instance, openalert_legacy, openalert_properties,
                      openalert_unit_dir='/etc/systemd/system'):
    """In-place adoption (default) or explicit account/path relocation (relocate: true)."""
    openalert_relocate = openalert_legacy.get('relocate', False)
    openalert_require(isinstance(openalert_relocate, bool), 'relocate must be a boolean')
    openalert_unit = openalert_unit_dir + '/' + openalert_instance['service_name']
    openalert_require(openalert_legacy['unit_path'] == openalert_unit, 'unsupported legacy unit location')
    openalert_properties = dict(openalert_line.split('=', 1) for openalert_line in
                               openalert_properties.splitlines() if '=' in openalert_line)
    for openalert_key, openalert_value in {
        'FragmentPath': openalert_unit,
        'EnvironmentFiles': '', 'RootDirectory': '', 'RootImage': '', 'DynamicUser': 'no',
        'ExecStartPre': '', 'ExecStartPost': '', 'ExecStop': '', 'ExecStopPost': '',
        'ExecCondition': '', 'BindPaths': '', 'BindReadOnlyPaths': '',
    }.items():
        openalert_require(openalert_properties.get(openalert_key, '') == openalert_value,
                          'unsupported effective legacy unit')
    openalert_require(openalert_properties.get('Environment', '') in ('', 'RUST_LOG=info'),
                      'legacy environment overrides are unsupported')
    openalert_dropin = openalert_unit + '.d/instance.conf'
    openalert_require(openalert_properties.get('DropInPaths', '') in ('', openalert_dropin),
                      'unsupported legacy drop-ins')
    if not openalert_relocate:
        openalert_require(openalert_identity(openalert_instance) == openalert_identity(openalert_legacy),
                          'adoption requires identical identities and paths')
        for openalert_key, openalert_value in {
            'User': openalert_instance['user'],
            'Group': openalert_instance['group'],
            'WorkingDirectory': openalert_instance['state_dir'],
        }.items():
            openalert_require(openalert_properties.get(openalert_key) == openalert_value,
                              'unsupported effective legacy unit')
        openalert_exec = openalert_properties.get('ExecStart', '')
        openalert_binary = str(openalert_path(openalert_legacy['binary_path']))
        openalert_require(openalert_exec.count('{') == 1 and openalert_exec.count('}') == 1
                          and openalert_re.search(r'\{ path=' + openalert_re.escape(openalert_binary)
                                                  + r' ; argv\[\]=' + openalert_re.escape(openalert_binary
                                                  + ' ' + openalert_instance['config_path'])
                                                  + r' ; ignore_errors=no ;', openalert_exec),
                          'unsupported legacy command')
        openalert_user = openalert_pwd.getpwnam(openalert_instance['user'])
        openalert_group = openalert_grp.getgrnam(openalert_instance['group'])
        openalert_require(openalert_user.pw_uid != 0 and openalert_group.gr_gid != 0
                          and openalert_user.pw_gid == openalert_group.gr_gid, 'legacy account mismatch')
        for openalert_value in (openalert_unit, openalert_instance['config_path'],
                               openalert_instance['state_dir'], openalert_legacy['templates_dir']):
            openalert_tree(openalert_value)
        openalert_require(openalert_instance.get('openalert_templates_dir') == openalert_legacy['templates_dir'],
                          'explicit legacy template path required')
    else:
        openalert_require(openalert_legacy.get('service_name') == openalert_instance['service_name'],
                          'relocated adoption requires matching service_name')
        openalert_require(openalert_identity(openalert_instance) != openalert_identity(openalert_legacy),
                          'relocated adoption requires changed account or path mapping')
        openalert_require(openalert_instance['user'] != 'root' and openalert_instance['group'] != 'root',
                          'target account cannot be root')
        openalert_require(openalert_disjoint(openalert_instance['config_path'], openalert_instance['state_dir']),
                          'target config and state paths must be disjoint')
        for openalert_legacy_key in ('config_path', 'state_dir', 'templates_dir'):
            openalert_require(openalert_disjoint(openalert_instance['config_path'], openalert_legacy[openalert_legacy_key]),
                              'relocated config path must be disjoint from legacy paths')
            openalert_require(openalert_disjoint(openalert_instance['state_dir'], openalert_legacy[openalert_legacy_key]),
                              'relocated state_dir must be disjoint from legacy paths')
        openalert_target_config = openalert_path(openalert_instance['config_path'], False)
        openalert_require(not openalert_target_config.exists(), 'relocated target config already exists')
        openalert_target_state = openalert_path(openalert_instance['state_dir'], False)
        if openalert_target_state.exists():
            openalert_tree(str(openalert_target_state))
            openalert_require(not any(openalert_target_state.iterdir()), 'relocated target state_dir must be empty')
        openalert_legacy_user_name = openalert_legacy['user']
        openalert_legacy_group_name = openalert_legacy['group']
        openalert_require((openalert_legacy_user_name == 'root') == (openalert_legacy_group_name == 'root'),
                          'legacy root user/group mismatch')
        if openalert_legacy_user_name == 'root':
            openalert_require(openalert_properties.get('User', '') in ('', 'root')
                              and openalert_properties.get('Group', '') in ('', 'root'),
                              'unsupported effective legacy unit')
        else:
            openalert_require(openalert_properties.get('User') == openalert_legacy_user_name
                              and openalert_properties.get('Group') == openalert_legacy_group_name,
                              'unsupported effective legacy unit')
        openalert_require(openalert_properties.get('WorkingDirectory') == openalert_legacy['state_dir'],
                          'unsupported effective legacy unit')
        openalert_exec = openalert_properties.get('ExecStart', '')
        openalert_binary = str(openalert_path(openalert_legacy['binary_path']))
        openalert_require(openalert_exec.count('{') == 1 and openalert_exec.count('}') == 1
                          and openalert_re.search(r'\{ path=' + openalert_re.escape(openalert_binary)
                                                  + r' ; argv\[\]=' + openalert_re.escape(openalert_binary
                                                  + ' ' + openalert_legacy['config_path'])
                                                  + r' ; ignore_errors=no ;', openalert_exec),
                          'unsupported legacy command')
        openalert_legacy_user = openalert_pwd.getpwnam(openalert_legacy_user_name)
        openalert_legacy_group = openalert_grp.getgrnam(openalert_legacy_group_name)
        if openalert_legacy_user_name == 'root':
            openalert_require(openalert_legacy_user.pw_uid == 0 and openalert_legacy_group.gr_gid == 0,
                              'legacy account mismatch')
        else:
            openalert_require(openalert_legacy_user.pw_uid != 0 and openalert_legacy_group.gr_gid != 0
                              and openalert_legacy_user.pw_gid == openalert_legacy_group.gr_gid,
                              'legacy account mismatch')
        for openalert_value in (openalert_unit, openalert_legacy['config_path'],
                               openalert_legacy['state_dir'], openalert_legacy['templates_dir']):
            openalert_tree(openalert_value)
        openalert_target_templates = openalert_instance.get('openalert_templates_dir')
        openalert_require(isinstance(openalert_target_templates, str) and bool(openalert_target_templates),
                          'explicit target template path required')
        openalert_target_templates_path = openalert_path(openalert_target_templates, False)
        if openalert_unit_dir == '/etc/systemd/system':
            openalert_require(not openalert_target_templates_path.is_relative_to('/root')
                              and not openalert_target_templates_path.is_relative_to('/home'),
                              'target templates cannot remain under /root or /home')
        openalert_legacy_templates_path = openalert_Path(openalert_legacy['templates_dir'])
        if openalert_legacy_templates_path.is_relative_to(openalert_legacy['state_dir']):
            openalert_require(openalert_target_templates != openalert_legacy['templates_dir'],
                              'templates inside legacy state_dir must be relocated')
        if openalert_target_templates != openalert_legacy['templates_dir']:
            openalert_require(openalert_disjoint(openalert_target_templates, openalert_legacy['config_path'])
                              and openalert_disjoint(openalert_target_templates, openalert_legacy['state_dir'])
                              and openalert_disjoint(openalert_target_templates, openalert_legacy['templates_dir'])
                              and openalert_disjoint(openalert_target_templates, openalert_instance['config_path']),
                              'relocated templates path must be disjoint from legacy paths and target config')
            if (openalert_target_templates_path.exists()
                    and not openalert_target_templates_path.is_relative_to(openalert_instance['state_dir'])):
                openalert_tree(openalert_target_templates)
                openalert_require(not any(openalert_target_templates_path.iterdir()),
                                  'relocated target templates_dir must be empty')
    openalert_dropdir = openalert_path(openalert_unit + '.d', False)
    if openalert_dropdir.exists():
        openalert_tree(str(openalert_dropdir))
        openalert_require({openalert_item.name for openalert_item in openalert_dropdir.iterdir()}
                          <= {'instance.conf'}, 'unrecognized legacy drop-in')
    openalert_schema(openalert_instance, True)
    openalert_require(openalert_instance['openalert_schema']['current']
                      == openalert_instance['openalert_schema']['target'],
                      'adoption and schema migration cannot be combined')
    return {'approved': True}


def openalert_schema(openalert_instance, openalert_existing):
    openalert_schema_value = openalert_instance.get('openalert_schema', {})
    if not openalert_existing and not openalert_schema_value:
        return {}
    for openalert_key in (('current', 'target') if openalert_existing else ('target',)):
        openalert_require(isinstance(openalert_schema_value.get(openalert_key), str)
                          and openalert_re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',
                                                    openalert_schema_value[openalert_key]),
                          'explicit schema compatibility inventory required')
    return openalert_schema_value


def openalert_resolve_config_dir(openalert_config, openalert_section, openalert_key,
                                 openalert_default, openalert_state_dir):
    openalert_raw = openalert_config.get(openalert_section, {}).get(openalert_key, openalert_default)
    openalert_require(isinstance(openalert_raw, str) and bool(openalert_raw), 'invalid config path')
    openalert_resolved = openalert_Path(openalert_raw)
    if not openalert_resolved.is_absolute():
        openalert_resolved = openalert_Path(openalert_state_dir) / openalert_resolved
    openalert_require('..' not in openalert_resolved.parts, 'unsafe config path')
    return openalert_resolved


def openalert_equivalent(openalert_instance, openalert_legacy, openalert_candidate):
    with openalert_path(openalert_legacy['config_path']).open('rb') as openalert_stream:
        openalert_original = openalert_tomllib.load(openalert_stream)
    with openalert_path(openalert_candidate).open('rb') as openalert_stream:
        openalert_proposed = openalert_tomllib.load(openalert_stream)
    openalert_relocate = openalert_legacy.get('relocate', False)
    openalert_require(isinstance(openalert_relocate, bool), 'relocate must be a boolean')
    if not openalert_relocate:
        openalert_require(openalert_original == openalert_proposed,
                          'adoption must preserve the complete parsed configuration')
        openalert_templates = openalert_resolve_config_dir(
            openalert_original, 'templates', 'template_dir', 'templates', openalert_instance['state_dir'])
        openalert_require(str(openalert_templates) == openalert_legacy['templates_dir'],
                          'legacy templates do not match declared mapping')
        openalert_tree(str(openalert_templates))
        return {'equivalent': True}
    openalert_legacy_templates = openalert_resolve_config_dir(
        openalert_original, 'templates', 'template_dir', 'templates', openalert_legacy['state_dir'])
    openalert_require(str(openalert_legacy_templates) == openalert_legacy['templates_dir'],
                      'legacy templates do not match declared mapping')
    openalert_tree(str(openalert_legacy_templates))
    openalert_target_templates = openalert_resolve_config_dir(
        openalert_proposed, 'templates', 'template_dir', 'templates', openalert_instance['state_dir'])
    openalert_require(str(openalert_target_templates) == openalert_instance.get('openalert_templates_dir'),
                      'candidate templates do not match declared target mapping')
    if 'storage' in openalert_original or 'storage' in openalert_proposed:
        openalert_require(isinstance(openalert_original.get('storage'), dict)
                          and isinstance(openalert_proposed.get('storage'), dict),
                          'adoption must preserve the complete parsed configuration')
        if 'path' in openalert_original['storage'] or 'path' in openalert_proposed['storage']:
            openalert_require('path' in openalert_original['storage']
                              and 'path' in openalert_proposed['storage'],
                              'adoption must preserve the complete parsed configuration')
            openalert_legacy_storage = openalert_resolve_config_dir(
                openalert_original, 'storage', 'path', '', openalert_legacy['state_dir'])
            openalert_target_storage = openalert_resolve_config_dir(
                openalert_proposed, 'storage', 'path', '', openalert_instance['state_dir'])
            openalert_require(openalert_legacy_storage.is_relative_to(openalert_legacy['state_dir'])
                              and openalert_target_storage.is_relative_to(openalert_instance['state_dir'])
                              and (openalert_legacy_storage.relative_to(openalert_legacy['state_dir'])
                                   == openalert_target_storage.relative_to(openalert_instance['state_dir'])),
                              'relocated storage path must preserve relative database path inside state_dir')
    openalert_original_normalized = openalert_json.loads(openalert_json.dumps(openalert_original))
    openalert_proposed_normalized = openalert_json.loads(openalert_json.dumps(openalert_proposed))
    if isinstance(openalert_original_normalized.get('templates'), dict):
        openalert_original_normalized['templates'].pop('template_dir', None)
        if not openalert_original_normalized['templates']:
            openalert_original_normalized.pop('templates', None)
    if isinstance(openalert_proposed_normalized.get('templates'), dict):
        openalert_proposed_normalized['templates'].pop('template_dir', None)
        if not openalert_proposed_normalized['templates']:
            openalert_proposed_normalized.pop('templates', None)
    if isinstance(openalert_original_normalized.get('storage'), dict):
        openalert_original_normalized['storage'].pop('path', None)
        if not openalert_original_normalized['storage']:
            openalert_original_normalized.pop('storage', None)
    if isinstance(openalert_proposed_normalized.get('storage'), dict):
        openalert_proposed_normalized['storage'].pop('path', None)
        if not openalert_proposed_normalized['storage']:
            openalert_proposed_normalized.pop('storage', None)
    openalert_require(openalert_original_normalized == openalert_proposed_normalized,
                      'adoption must preserve the complete parsed configuration')
    return {'equivalent': True}


def openalert_copy_staged_tree(openalert_source_dir, openalert_target_dir, openalert_uid, openalert_gid):
    openalert_source_root = openalert_tree(str(openalert_source_dir))
    openalert_target_root = openalert_path(str(openalert_target_dir), False)
    openalert_target_root.mkdir(parents=True, exist_ok=True)
    openalert_os.chmod(openalert_target_root, 0o750)
    if openalert_os.geteuid() == 0:
        openalert_os.chown(openalert_target_root, openalert_uid, openalert_gid)
    for openalert_parent, openalert_dirs, openalert_files in openalert_os.walk(openalert_source_root):
        openalert_rel = openalert_Path(openalert_parent).relative_to(openalert_source_root)
        openalert_dest_parent = openalert_target_root / openalert_rel
        for openalert_dir_name in sorted(openalert_dirs):
            openalert_dest_dir = openalert_dest_parent / openalert_dir_name
            openalert_dest_dir.mkdir(exist_ok=True)
            openalert_os.chmod(openalert_dest_dir, 0o750)
            if openalert_os.geteuid() == 0:
                openalert_os.chown(openalert_dest_dir, openalert_uid, openalert_gid)
        for openalert_file_name in sorted(openalert_files):
            openalert_src_file = openalert_Path(openalert_parent) / openalert_file_name
            openalert_dest_file = openalert_dest_parent / openalert_file_name
            openalert_src_mode = openalert_stat.S_IMODE(openalert_src_file.stat().st_mode)
            openalert_safe_mode = (openalert_src_mode & 0o660) or 0o640
            openalert_dest_file.write_bytes(openalert_src_file.read_bytes())
            openalert_os.chmod(openalert_dest_file, openalert_safe_mode)
            if openalert_os.geteuid() == 0:
                openalert_os.chown(openalert_dest_file, openalert_uid, openalert_gid)


def openalert_stage_templates(openalert_instance, openalert_legacy):
    openalert_require(openalert_legacy.get('relocate', False) is True, 'stage-templates requires relocate: true')
    openalert_target_templates = openalert_instance.get('openalert_templates_dir')
    openalert_require(isinstance(openalert_target_templates, str) and bool(openalert_target_templates),
                      'explicit target template path required')
    if openalert_target_templates == openalert_legacy['templates_dir']:
        openalert_tree(openalert_target_templates)
        return {'staged': False}
    openalert_user = openalert_pwd.getpwnam(openalert_instance['user'])
    openalert_group = openalert_grp.getgrnam(openalert_instance['group'])
    openalert_copy_staged_tree(openalert_legacy['templates_dir'], openalert_target_templates,
                               openalert_user.pw_uid, openalert_group.gr_gid)
    return {'staged': True}


def openalert_assets(openalert_request):
    openalert_instance = openalert_request['instance']
    openalert_candidate = openalert_path(openalert_request['candidate_dir'])
    openalert_unit = openalert_request.get('unit_dir', '/etc/systemd/system')
    return [
        (openalert_candidate / 'openalertd.toml', openalert_Path(openalert_instance['config_path'])),
        (openalert_candidate / openalert_instance['service_name'],
         openalert_Path(openalert_unit) / openalert_instance['service_name']),
        (openalert_candidate / (openalert_instance['service_name'] + '.d') / 'instance.conf',
         openalert_Path(openalert_unit) / (openalert_instance['service_name'] + '.d') / 'instance.conf'),
    ]


def openalert_digest(openalert_file):
    with openalert_file.open('rb') as openalert_stream:
        return openalert_hashlib.file_digest(openalert_stream, 'sha256').hexdigest()


def openalert_roots(openalert_request):
    openalert_pairs = openalert_assets(openalert_request)
    openalert_legacy = openalert_request.get('legacy') or {}
    if openalert_legacy.get('relocate', False):
        openalert_legacy_config = str(openalert_path(openalert_legacy['config_path']))
        openalert_unit_file = str(openalert_pairs[1][1])
        openalert_dropin_dir = str(openalert_pairs[2][1].parent)
        openalert_roots_value = [openalert_legacy_config, openalert_unit_file]
        openalert_absent = [str(openalert_pairs[0][1])]
        if openalert_path(openalert_dropin_dir, False).exists():
            openalert_roots_value.append(openalert_dropin_dir)
        else:
            openalert_absent.append(openalert_dropin_dir)
        for openalert_rec in (openalert_request['active_record'], openalert_request.get('owner_record')):
            if openalert_rec:
                if openalert_path(openalert_rec, False).exists():
                    openalert_roots_value.append(openalert_rec)
                else:
                    openalert_absent.append(openalert_rec)
        openalert_data_roots = [*openalert_roots_value, openalert_legacy['state_dir']]
        openalert_templates = openalert_Path(openalert_legacy['templates_dir'])
        openalert_tree(str(openalert_templates))
        if not openalert_templates.is_relative_to(openalert_legacy['state_dir']):
            openalert_data_roots.append(str(openalert_templates))
    else:
        openalert_roots_value = [str(openalert_active) for _, openalert_active in openalert_pairs[:2]]
        openalert_roots_value.extend((str(openalert_pairs[2][1].parent), openalert_request['active_record']))
        if openalert_request.get('owner_record'):
            openalert_roots_value.append(openalert_request['owner_record'])
        openalert_absent = [openalert_root for openalert_root in openalert_roots_value
                           if not openalert_path(openalert_root, False).exists()]
        openalert_roots_value = [openalert_root for openalert_root in openalert_roots_value
                                if openalert_root not in openalert_absent]
        openalert_data_roots = [*openalert_roots_value, openalert_request['instance']['state_dir']]
        with openalert_pairs[0][1].open('rb') as openalert_stream:
            openalert_config = openalert_tomllib.load(openalert_stream)
        openalert_templates = openalert_Path(openalert_config.get('templates', {}).get('template_dir', 'templates'))
        if not openalert_templates.is_absolute():
            openalert_templates = openalert_Path(openalert_request['instance']['state_dir']) / openalert_templates
        openalert_tree(str(openalert_templates))
        if not openalert_templates.is_relative_to(openalert_request['instance']['state_dir']):
            openalert_data_roots.append(str(openalert_templates))
    for openalert_root in openalert_data_roots:
        openalert_tree(openalert_root)
        for openalert_other in openalert_data_roots:
            openalert_require(openalert_root == openalert_other
                              or not openalert_Path(openalert_root).is_relative_to(openalert_other),
                              'overlapping checkpoint roots')
        for openalert_work in (openalert_request['checkpoint_dir'], openalert_request['candidate_dir']):
            openalert_require(not openalert_Path(openalert_work).is_relative_to(openalert_root)
                              and not openalert_Path(openalert_root).is_relative_to(openalert_work),
                              'checkpoint and staging must be outside source trees')
    openalert_require(len(set(openalert_data_roots)) == len(openalert_data_roots), 'duplicate checkpoint roots')
    return openalert_roots_value, openalert_data_roots, openalert_absent


def openalert_inspect(openalert_request):
    openalert_pairs = openalert_assets(openalert_request)
    openalert_legacy = openalert_request.get('legacy') or {}
    openalert_relocate = bool(openalert_legacy.get('relocate', False))
    openalert_changed = bool(openalert_legacy)
    for openalert_candidate, openalert_active in openalert_pairs:
        openalert_path(str(openalert_candidate))
        openalert_path(str(openalert_active), False)
        openalert_require(openalert_candidate.is_file(), 'candidate must be a regular file')
        if not openalert_active.exists():
            openalert_changed = True
            continue
        openalert_path(str(openalert_active))
        openalert_require(openalert_active.is_file(), 'active asset must be a regular file')
        openalert_info = openalert_active.stat()
        openalert_expected = openalert_candidate.stat()
        openalert_changed |= (openalert_digest(openalert_candidate) != openalert_digest(openalert_active)
                              or (openalert_info.st_uid, openalert_info.st_gid, openalert_info.st_mode)
                              != (openalert_expected.st_uid, openalert_expected.st_gid, openalert_expected.st_mode))
    if openalert_relocate:
        openalert_require(not openalert_pairs[0][1].exists(),
                          'relocated target config already exists before activation')
        openalert_require(openalert_path(openalert_legacy['config_path']).is_file()
                          and openalert_pairs[1][1].is_file(),
                          'partial legacy installation requires explicit recovery')
        openalert_existing = True
    else:
        openalert_existing = any(openalert_active.exists() for _, openalert_active in openalert_pairs)
        openalert_state = openalert_path(openalert_request['instance']['state_dir'])
        openalert_existing |= any(
            openalert_item.name != '.ansible' for openalert_item in openalert_state.iterdir()
        )
        if openalert_existing:
            openalert_require(all(openalert_active.is_file() for _, openalert_active in openalert_pairs[:2]),
                              'partial existing installation requires explicit recovery')
    if openalert_changed:
        openalert_schema_value = openalert_schema(openalert_request['instance'], openalert_existing)
        openalert_record = openalert_path(openalert_request['active_record'], False)
        if openalert_record.exists():
            openalert_require(openalert_json.loads(openalert_record.read_text())['schema_id']
                              == openalert_schema_value.get('current'), 'current schema inventory mismatch')
        if openalert_existing:
            openalert_roots(openalert_request)
    if openalert_legacy:
        openalert_equivalent(openalert_request['instance'], openalert_legacy,
                             str(openalert_pairs[0][0]))
    return {'changed': bool(openalert_changed), 'existing': bool(openalert_existing)}


def openalert_write(openalert_path_value, openalert_value):
    openalert_fd = openalert_os.open(openalert_path_value, openalert_os.O_WRONLY | openalert_os.O_CREAT
                                    | openalert_os.O_EXCL, 0o600)
    with openalert_os.fdopen(openalert_fd, 'w', encoding='utf-8') as openalert_stream:
        openalert_json.dump(openalert_value, openalert_stream, sort_keys=True)


def openalert_snapshot(openalert_helper, *openalert_arguments):
    openalert_result = openalert_subprocess.run(
        [openalert_sys.executable, openalert_helper, *openalert_arguments], check=True,
        capture_output=True, text=True)
    return openalert_result.stdout


def openalert_materialize_snapshot_root(openalert_snapshot_dir, openalert_source_root,
                                        openalert_target_root, openalert_uid, openalert_gid):
    openalert_manifest = openalert_json.loads((openalert_snapshot_dir / 'manifest.json').read_text())
    openalert_index = openalert_manifest['paths'].index(str(openalert_source_root))
    openalert_entries = sorted(
        [openalert_entry for openalert_entry in openalert_manifest['entries']
         if openalert_entry['root'] == openalert_index],
        key=lambda openalert_item: (0 if openalert_item['path'] == ''
                                    else len(openalert_Path(openalert_item['path']).parts),
                                    openalert_item['path']))
    openalert_target = openalert_path(str(openalert_target_root), False)
    for openalert_entry in openalert_entries:
        openalert_rel = openalert_entry['path']
        openalert_dest = openalert_target if openalert_rel == '' else openalert_target / openalert_rel
        if openalert_entry['type'] == 'directory':
            openalert_dest.mkdir(parents=(openalert_rel == ''), exist_ok=True)
            openalert_os.chmod(openalert_dest, 0o750)
            if openalert_os.geteuid() == 0:
                openalert_os.chown(openalert_dest, openalert_uid, openalert_gid)
        else:
            openalert_artifact = (openalert_snapshot_dir / 'tree' / str(openalert_index)
                                  if openalert_rel == ''
                                  else openalert_snapshot_dir / 'tree' / str(openalert_index) / openalert_rel)
            openalert_require(openalert_digest(openalert_artifact) == openalert_entry['sha256'],
                              'snapshot digest mismatch during relocation')
            openalert_safe_mode = (openalert_entry['mode'] & 0o660) or 0o600
            openalert_dest.write_bytes(openalert_artifact.read_bytes())
            openalert_os.chmod(openalert_dest, openalert_safe_mode)
            if openalert_os.geteuid() == 0:
                openalert_os.chown(openalert_dest, openalert_uid, openalert_gid)
            openalert_os.utime(openalert_dest, ns=(openalert_entry['mtime_ns'], openalert_entry['mtime_ns']))


def openalert_checkpoint(openalert_request, openalert_helper):
    openalert_status = openalert_inspect(openalert_request)
    openalert_require(openalert_status['changed'] and openalert_status['existing'],
                      'checkpoint only applies to changed existing instances')
    openalert_instance = openalert_request['instance']
    openalert_legacy = openalert_request.get('legacy') or {}
    openalert_parent = openalert_path(openalert_request['checkpoint_dir'])
    openalert_transaction = openalert_parent / openalert_uuid.uuid4().hex
    openalert_transaction.mkdir(mode=0o700)
    openalert_asset_roots, openalert_data_roots, openalert_absent = openalert_roots(openalert_request)
    openalert_schema_value = openalert_schema(openalert_instance, True)
    openalert_metadata = {
        'component': 'openalert', 'instance': openalert_instance['name'],
        'identity': openalert_identity(openalert_instance),
        'schema_id': openalert_schema_value['current'],
        'candidate_schema_id': openalert_schema_value['target'],
        'candidate_release': openalert_request['release'],
    }
    if openalert_legacy.get('relocate', False):
        openalert_metadata['legacy_identity'] = openalert_identity(openalert_legacy)
    openalert_assets_plan = {'paths': openalert_asset_roots, 'metadata': openalert_metadata}
    openalert_full_plan = {'paths': openalert_data_roots, 'metadata': openalert_metadata}
    for openalert_name, openalert_plan in (('full', openalert_full_plan), ('assets', openalert_assets_plan)):
        openalert_write(openalert_transaction / (openalert_name + '.json'), openalert_plan)
        openalert_snapshot(openalert_helper, 'create', '--plan', str(openalert_transaction / (openalert_name + '.json')),
                           '--destination', str(openalert_transaction / openalert_name))
        openalert_snapshot(openalert_helper, 'verify', '--plan', str(openalert_transaction / (openalert_name + '.json')),
                           '--snapshot', str(openalert_transaction / openalert_name))
    if openalert_legacy.get('relocate', False):
        openalert_user = openalert_pwd.getpwnam(openalert_instance['user'])
        openalert_group = openalert_grp.getgrnam(openalert_instance['group'])
        openalert_absent = [*openalert_absent, openalert_instance['state_dir']]
        openalert_target_templates = openalert_instance.get('openalert_templates_dir')
        if (openalert_target_templates
                and openalert_target_templates != openalert_legacy['templates_dir']
                and not openalert_Path(openalert_target_templates).is_relative_to(openalert_instance['state_dir'])):
            openalert_absent.append(openalert_target_templates)
        openalert_write(openalert_transaction / 'recovery.json', {'absent': openalert_absent, 'metadata': openalert_metadata})
        openalert_materialize_snapshot_root(openalert_transaction / 'full', openalert_legacy['state_dir'],
                                            openalert_instance['state_dir'], openalert_user.pw_uid, openalert_group.gr_gid)
        if (openalert_target_templates
                and openalert_target_templates != openalert_legacy['templates_dir']
                and not openalert_Path(openalert_target_templates).is_relative_to(openalert_instance['state_dir'])):
            openalert_materialize_snapshot_root(openalert_transaction / 'full', openalert_legacy['templates_dir'],
                                                openalert_target_templates, openalert_user.pw_uid, openalert_group.gr_gid)
    else:
        openalert_write(openalert_transaction / 'recovery.json', {'absent': openalert_absent, 'metadata': openalert_metadata})
    return {'transaction': str(openalert_transaction)}


def openalert_recover(openalert_transaction_value, openalert_helper):
    openalert_transaction = openalert_path(openalert_transaction_value)
    openalert_recovery = openalert_json.loads((openalert_transaction / 'recovery.json').read_text())
    openalert_metadata = openalert_recovery['metadata']
    openalert_require(openalert_metadata['schema_id'] == openalert_metadata['candidate_schema_id'],
                      'schema mismatch: keep service stopped and use explicit recovery')
    for openalert_name in ('full', 'assets'):
        openalert_plan = openalert_transaction / (openalert_name + '.json')
        openalert_require(openalert_json.loads(openalert_plan.read_text())['metadata'] == openalert_metadata,
                          'recovery metadata mismatch')
        openalert_snapshot(openalert_helper, 'verify', '--plan', str(openalert_plan),
                           '--snapshot', str(openalert_transaction / openalert_name))
    openalert_snapshot(openalert_helper, 'restore', '--plan', str(openalert_transaction / 'assets.json'),
                       '--snapshot', str(openalert_transaction / 'assets'))
    for openalert_value in openalert_recovery['absent']:
        openalert_missing = openalert_path(openalert_value, False)
        if openalert_missing.exists():
            openalert_tree(openalert_value)
            openalert_missing.rename(openalert_missing.with_name(
                openalert_missing.name + '.openalert-failed-' + openalert_uuid.uuid4().hex))
    return {'recovered': True, 'state_restored': False}


def openalert_main():
    try:
        openalert_parser = openalert_argparse.ArgumentParser(description=__doc__)
        openalert_parser.add_argument('command', choices=[
            'adoption', 'equivalent', 'stage-templates', 'inspect', 'checkpoint', 'recover'])
        openalert_parser.add_argument('--request')
        openalert_parser.add_argument('--instance')
        openalert_parser.add_argument('--legacy')
        openalert_parser.add_argument('--properties')
        openalert_parser.add_argument('--candidate')
        openalert_parser.add_argument('--transaction')
        openalert_parser.add_argument('--helper')
        openalert_args = openalert_parser.parse_args()
        if openalert_args.command == 'adoption':
            openalert_result = openalert_adoption(openalert_json.loads(openalert_args.instance),
                                                  openalert_json.loads(openalert_args.legacy), openalert_args.properties)
        elif openalert_args.command == 'equivalent':
            openalert_result = openalert_equivalent(openalert_json.loads(openalert_args.instance),
                                                    openalert_json.loads(openalert_args.legacy), openalert_args.candidate)
        elif openalert_args.command == 'stage-templates':
            openalert_result = openalert_stage_templates(openalert_json.loads(openalert_args.instance),
                                                         openalert_json.loads(openalert_args.legacy))
        elif openalert_args.command == 'recover':
            openalert_result = openalert_recover(openalert_args.transaction, openalert_args.helper)
        else:
            openalert_request = openalert_json.loads(openalert_path(openalert_args.request).read_text())
            openalert_result = (openalert_inspect(openalert_request) if openalert_args.command == 'inspect'
                                else openalert_checkpoint(openalert_request, openalert_args.helper))
        print(openalert_json.dumps(openalert_result, sort_keys=True))
        return 0
    except Exception:
        print('{"error":"OpenAlert lifecycle refused; retain checkpoint for explicit recovery"}', file=openalert_sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(openalert_main())