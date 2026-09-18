# `toml_to_ansible_vars.py`

Turns the TOML configuration under `src/config/` into the Ansible vars files
that the `deploy_py-phone-caller` role reads.

`src/config/settings.toml` and `src/config/.secrets.toml` stay the single
source of truth for the platform: the same values drive local development, the
container images and the systemd deployment. This tool is the bridge to the
last one.

```
src/config/settings.toml  ─┐
src/config/.secrets.toml  ─┴─▶ toml_to_ansible_vars.py ─▶ group_vars/*.yml
                                                             │
                                            ansible-playbook ▼
                                     /opt/py-phone-caller/src/config/*.toml
```

The role re-renders TOML on the target, so a value written in
`src/config/settings.toml` reaches the server unchanged — there is a
round-trip test for exactly that (see *Verifying* below).

## Usage

```bash
# From anywhere: writes both files with their defaults
assets/ansible/tools/toml_to_ansible_vars.py
```

| Written file | Variable | Mode |
| --- | --- | --- |
| `assets/ansible/on-vm_py-phone-caller/group_vars/app_servers/config.yml` | `py_phone_caller_config` | `0644` |
| `assets/ansible/on-vm_py-phone-caller/group_vars/app_servers/secrets.yml` | `py_phone_caller_config_secrets` | `0600` |

`group_vars/app_servers/` must be a **directory**. Ansible reads every file
inside `group_vars/<group>/`, but auto-loads a plain file only when its stem
is exactly the group name, so a `group_vars/app_servers.secrets.yml` would be
skipped silently and the secrets would never reach the play.

The directory is git-ignored: it mirrors the live configuration, phone
numbers and credentials included. Committed samples live in
`assets/ansible/on-vm_py-phone-caller/examples/`.

### Options

```
-i, --input TOML         TOML file to read; repeatable, later files win.
                         Default: src/config/settings.toml src/config/.secrets.toml
-o, --output PATH        Vars file to write.
    --secrets-output PATH
    --var-name NAME      Default: py_phone_caller_config
    --secrets-var-name NAME
    --secret SECTION.KEY Extra dotted path to treat as a secret; repeatable.
    --no-default-secrets Drop the built-in secret list.
    --no-split-secrets   One file, secrets included.
    --stdout             Print instead of writing.
    --ignore-missing     Skip inputs that do not exist.
```

Paths treated as secrets by default:

```
commons.asterisk_pass          caller_sms.twilio_account_sid
commons.asterisk_ami_secret    caller_sms.twilio_auth_token
database.db_password           py_phone_caller_ui.ui_secret_key
```

### With `ansible-vault`

```bash
assets/ansible/tools/toml_to_ansible_vars.py
ansible-vault encrypt assets/ansible/on-vm_py-phone-caller/group_vars/app_servers/secrets.yml
ansible-playbook deploy_py-phone-caller.yml --ask-vault-pass
```

Re-running the tool refuses to overwrite an already-encrypted secrets file;
decrypt it first, or send the new one somewhere else with
`--secrets-output`.

## How the role merges the layers

```
roles/deploy_py-phone-caller/defaults/main.yml  : py_phone_caller_config_defaults
group_vars/app_servers/config.yml               : py_phone_caller_config
group_vars/app_servers/secrets.yml              : py_phone_caller_config_secrets
group_vars/all.yml                              : py_phone_caller_config_overrides
```

Merged in that order (recursive, later wins) into
`py_phone_caller_final_config`, which is what gets written to the target.

`py_phone_caller_config_overrides` is the layer for facts about *this*
deployment rather than about the application — "PostgreSQL is on loopback
here". Keeping it separate means regenerating the two files from
`src/config/*.toml` never wipes out the topology.

## Notes on the output

* Strings are always double-quoted, so `%(asctime)s`, `+393349246425`,
  `Local/{phone}@py-phone-caller` and `yes` survive YAML's type guessing.
* Keys are emitted bare unless they need quoting.
* TOML dates and times become ISO-8601 strings.
* Only the standard library is used: any Python 3.11+ works (3.10 and older
  need `tomli`).

## Verifying

The generated vars are checked end to end — TOML in, YAML out, back through
Ansible's own parser and through the role's `settings.toml.j2`, comparing the
result with the source:

```bash
# TOML -> YAML -> PyYAML round trip, hostile scalars, secret isolation
pytest assets/ansible/tools/test_toml_to_ansible_vars.py
# ...or without the dev dependencies:
python3 assets/ansible/tools/test_toml_to_ansible_vars.py

# Render the role templates locally and diff the result against the merged
# configuration, key by key. No target host is contacted.
cd assets/ansible/on-vm_py-phone-caller
ansible-playbook -i localhost, -c local render_check.yml
```
