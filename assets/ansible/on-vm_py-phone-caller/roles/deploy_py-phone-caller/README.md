# Ansible role: `deploy_py-phone-caller`

Installs the py-phone-caller microservice stack as systemd units on
Debian/Ubuntu and RHEL/Rocky.

For the operational walkthrough (inventory, generating the vars, running the
playbook) see [`../../README.md`](../../README.md). This file is the variable
reference.

## What it does

1. **prereqs** — OS packages, EPEL/CRB on RHEL, Redis or Valkey, and the
   PostgreSQL server when the database is local.
2. **user** — a `nologin` system account owning `/opt/py-phone-caller`, added
   to the serial-device group when the on-premise SMS carrier is selected.
3. **source** — rsyncs the repository (or clones it) preserving the layout, so
   the uv workspace resolves as it does in development.
4. **install** — installs `uv`, then `uv sync --frozen --all-packages
   --no-dev`; builds the Rust SMS engine when needed.
5. **database** — pg_hba for loopback passwords, then role, database, schema
   grants and the `uuid-ossp`/`pgcrypto` extensions.
6. **config** — renders `settings.toml` and `.secrets.toml`, both validated
   with `tomllib` before they land.
7. **caddy** — reverse proxy with TLS.
8. **firewall** — firewalld or ufw, 80/443 by default.
9. **systemd** — one unit per service, ordered after `caller-register`.
10. **cleanup** — opt-in removal of the build toolchain.

Each step has a tag of the same name.

## Variables

### Layout

| Variable | Default | |
| --- | --- | --- |
| `py_phone_caller_user` / `_group` | `py-phone-caller` | service account |
| `py_phone_caller_service_prefix` | `py-phone-caller-` | unit name prefix |
| `py_phone_caller_install_dir` | `/opt/py-phone-caller` | uv workspace root |
| `py_phone_caller_src_dir` | `<install_dir>/src` | must stay a real directory |
| `py_phone_caller_config_dir` | `<src_dir>/config` | `CALLER_CONFIG_DIR` |
| `py_phone_caller_venv_dir` | `<install_dir>/venv` | |
| `py_phone_caller_log_dir` | `/var/log/py-phone-caller` | |

### Source

| Variable | Default | |
| --- | --- | --- |
| `py_phone_caller_local_src_path` | `""` | repository root on the control node |
| `py_phone_caller_git_repo` | `""` | clone instead of rsync |
| `py_phone_caller_git_version` | `main` | |
| `py_phone_caller_sync_excludes` | see defaults | development noise, including `src/openalert/` |
| `py_phone_caller_sync_protected` | see defaults | server-only state `--delete` must not touch |
| `py_phone_caller_sync_become` | `ansible_user != root` | `synchronize` needs become for a non-root SSH user |

One of `py_phone_caller_local_src_path` or `py_phone_caller_git_repo` is
required.

### Python toolchain

| Variable | Default | |
| --- | --- | --- |
| `py_phone_caller_python_version` | `"3.14"` | passed to `uv sync --python` |
| `py_phone_caller_uv_installer_url` | `https://astral.sh/uv/install.sh` | |
| `py_phone_caller_uv_extra_index_url` | `""` | internal PyPI mirror |
| `py_phone_caller_uv_insecure_host` | `""` | for a plain-HTTP mirror |
| `py_phone_caller_uv_sync_timeout` | `3600` | seconds |

### Configuration

| Variable | Default | |
| --- | --- | --- |
| `py_phone_caller_config_defaults` | full tree | mirrors `src/config/settings.toml` |
| `py_phone_caller_config` | `{}` | generated from `settings.toml` |
| `py_phone_caller_config_secrets` | `{}` | generated from `.secrets.toml` |
| `py_phone_caller_config_overrides` | `{}` | host-specific last word |
| `py_phone_caller_secret_paths` | six dotted paths | which keys go to `.secrets.toml` |

### Feature switches

| Variable | Default | |
| --- | --- | --- |
| `py_phone_caller_manage_queue` | `true` | install and start Redis/Valkey |
| `py_phone_caller_manage_database` | `true` | provision the role and database |
| `py_phone_caller_manage_caddy` | `true` | |
| `py_phone_caller_manage_firewall` | `true` | |
| `py_phone_caller_manage_services` | `true` | |
| `py_phone_caller_remove_build_deps` | `false` | see below |
| `py_phone_caller_ui_reset_password` | `false` | generate the initial admin password |

`py_phone_caller_remove_build_deps` is off by default on purpose: dropping the
compilers means the next dependency bump cannot build a native wheel until
`--tags prereqs` runs again.

### Database

| Variable | Default | |
| --- | --- | --- |
| `py_phone_caller_manage_local_postgres` | derived from `database.db_host` | |
| `py_phone_caller_db_admin_user` | `postgres` | remote provisioning only |
| `py_phone_caller_db_admin_password` | `""` | required when the database is remote |
| `py_phone_caller_pg_unix_socket` | `""` | empty lets libpq choose |
| `py_phone_caller_pg_hba_method` | `md5` | negotiates SCRAM when the stored verifier is SCRAM |
| `py_phone_caller_db_no_log` | `true` | set to `false` to debug provisioning |

`md5` rather than `scram-sha-256` because RHEL 9 still ships PostgreSQL 13,
whose default `password_encryption` is md5. PostgreSQL 10+ upgrades an `md5`
pg_hba line to SCRAM automatically when the role's password is SCRAM-hashed.

### Proxy, firewall, hosts

| Variable | Default | |
| --- | --- | --- |
| `caddy_domain_name` | `py-phone-caller.lan` | `.lan/.local/.internal/.test` use Caddy's internal CA |
| `caddy_email` | `""` | needed for Let's Encrypt |
| `py_phone_caller_firewall_ports` | `[80, 443]` | |
| `py_phone_caller_firewall_extra_ports` | `[]` | |
| `py_phone_caller_hosts_entries` | `[]` | managed `/etc/hosts` block |

### Services

`py_phone_caller_services` lists the units. Entries take:

```yaml
- name: caller_register            # unit becomes py-phone-caller-caller-register
  description: "..."
  module: "caller_register.caller_register"   # python -m <module>
  first: true                                 # others are ordered After= this
- name: py_phone_caller_ui
  type: gunicorn                              # bind comes from the UI config
  workers: 4
- name: celery_worker
  type: celery
  celery_app: "py_phone_caller_utils.tasks.celery_task"
```

Units removed from this list are stopped, disabled and deleted on the next
run.

## Notes

* No `PYTHONPATH` is set. `uv sync` installs every workspace member into the
  virtualenv as an editable install pointing at `<install_dir>/src`, which is
  why that path must not move.
* `PrivateTmp` is deliberately off: `caller_sms` and `celery_worker` share the
  on-premise SMS SQLite database under `/tmp`.
* Migrations are not run from Ansible. `caller_register` applies them at
  startup, exactly as in the container and Kubernetes stacks, so there is one
  implementation rather than two.
