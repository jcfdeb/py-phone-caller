# Deploying py-phone-caller on a VM

Installs the eleven py-phone-caller microservices as systemd units behind a
Caddy reverse proxy, with PostgreSQL and Redis/Valkey provisioning, on
Debian/Ubuntu or RHEL/Rocky.

`openalertd` (`src/openalert/`) is **not** part of this deployment; it ships
separately through `src/openalert/packaging/`.

---

## Layout

```
on-vm_py-phone-caller/
├── ansible.cfg                        inventory, roles_path, become, ssh
├── inventory                          [app_servers]
├── requirements.yml                   required collections
├── deploy_py-phone-caller.yml         the deployment
├── verify.yml                         post-deployment checks
├── render_check.yml                   render templates locally, no target
├── group_vars/
│   ├── all.yml                        deployment topology (in git)
│   └── app_servers/                   generated, git-ignored
│       ├── config.yml                 from src/config/settings.toml
│       └── secrets.yml                from src/config/.secrets.toml
├── examples/                          committed samples of the two above
└── roles/deploy_py-phone-caller/
```

`group_vars/app_servers/` is a **directory**, not two `app_servers*.yml`
files. Ansible reads every file inside a `group_vars/<group>/` directory, but
auto-loads a plain file only when its stem is exactly the group name — a
`group_vars/app_servers.secrets.yml` is skipped without a warning.

Its contents are git-ignored: they mirror the live configuration, credentials
and phone numbers included.

---

## Requirements

**Control node**

* `ansible-core` 2.15+ and the collections in `requirements.yml`
* `rsync` (the role ships the code with `ansible.posix.synchronize`)
* Python 3.11+ for `../tools/toml_to_ansible_vars.py`

**Target**

* Debian 12+/Ubuntu 22.04+ or RHEL/Rocky 9+
* SSH as `root`, or as a user with **passwordless** sudo — `synchronize` runs
  rsync over SSH as the connection user
* `rsync` and `sudo` installed
* 2 GB RAM and ~6 GB free disk: the workspace pulls in PyTorch and the TTS
  models
* Outbound HTTPS for PyPI, astral.sh (uv) and Hugging Face, unless you point
  `py_phone_caller_uv_extra_index_url` at an internal mirror

---

## Configuration flow

`src/config/*.toml` is the single source of truth. Nothing is retyped into
Ansible by hand:

```
src/config/settings.toml   ──┐
src/config/.secrets.toml   ──┴─▶ tools/toml_to_ansible_vars.py
                                          │
            group_vars/app_servers/config.yml   (py_phone_caller_config)
            group_vars/app_servers/secrets.yml  (py_phone_caller_config_secrets)
                                          │
                                 deploy_py-phone-caller.yml
                                          │
                    /opt/py-phone-caller/src/config/settings.toml   (0640)
                    /opt/py-phone-caller/src/config/.secrets.toml   (0600)
```

Four layers are merged, later wins:

| Layer | Where | For |
| --- | --- | --- |
| `py_phone_caller_config_defaults` | `roles/.../defaults/main.yml` | fallbacks for every key |
| `py_phone_caller_config` | `group_vars/app_servers/config.yml` | generated from `settings.toml` |
| `py_phone_caller_config_secrets` | `group_vars/app_servers/secrets.yml` | generated from `.secrets.toml` |
| `py_phone_caller_config_overrides` | `group_vars/all.yml` | facts about *this* host |

The overrides layer is what keeps regeneration safe: `settings.toml` can keep
saying `postgresql.lan` for the container stack while `all.yml` redirects the
VM to loopback.

At runtime each unit gets `CALLER_CONFIG_DIR=/opt/py-phone-caller/src/config`,
so Dynaconf reads exactly those two files — no guessing from `__file__` or the
working directory.

---

## Deploying

```bash
cd assets/ansible/on-vm_py-phone-caller

# 1. Collections (once)
ansible-galaxy collection install -r requirements.yml

# 2. Configuration -> group_vars
../tools/toml_to_ansible_vars.py

# 3. Optional: check the rendering without touching the server
ansible-playbook -i localhost, -c local render_check.yml

# 4. Reachability
ansible app_servers -m ping

# 5. Deploy
ansible-playbook deploy_py-phone-caller.yml

# 6. Check
ansible-playbook verify.yml
```

To encrypt the credentials:

```bash
ansible-vault encrypt group_vars/app_servers/secrets.yml
ansible-playbook deploy_py-phone-caller.yml --ask-vault-pass
```

### Tags

| Tag | Does |
| --- | --- |
| `prereqs` | OS packages, Redis/Valkey, PostgreSQL server |
| `user` | service account and directories |
| `source` | rsync the code to `/opt/py-phone-caller` |
| `install` | `uv sync`, native SMS engine |
| `database` | role, database, schema grants, extensions |
| `config` | render `settings.toml` and `.secrets.toml` |
| `caddy` | reverse proxy |
| `firewall` | firewalld / ufw |
| `systemd` | unit files, enable and start |
| `cleanup` | remove build dependencies (opt-in) |

A configuration-only push:

```bash
../tools/toml_to_ansible_vars.py
ansible-playbook deploy_py-phone-caller.yml --tags config
```

### First admin password

```bash
ansible-playbook deploy_py-phone-caller.yml -e py_phone_caller_ui_reset_password=true
ssh openalert journalctl -u py-phone-caller-py-phone-caller-ui -n 50
```

Then run again without the flag.

---

## On the target

```
/opt/py-phone-caller/
├── pyproject.toml, uv.lock      uv workspace root
├── src/                         workspace members, installed editable
│   ├── config/                  settings.toml, .secrets.toml
│   └── generate_audio/          audio/ and pre_trained_models/ live here
├── venv/                        the virtualenv uv builds
├── bin/uv
└── .uv/                         managed interpreters and cache
```

The repository layout is reproduced verbatim, and `src/` is a real directory.
`uv sync` installs the workspace members as editable and records those paths
inside the virtualenv, so renaming `src/` or replacing it with a symlink
breaks every import. `rsync --delete` protects `venv/`, `bin/`, `.uv/`, the
rendered configuration and the downloaded TTS models
(`py_phone_caller_sync_protected`).

Units are `py-phone-caller-<name>.service`:

```
caller-register        asterisk-caller        asterisk-recaller
asterisk-ws-monitor    caller-address-book    caller-prometheus-webhook
caller-scheduler       caller-sms             generate-audio
py-phone-caller-ui     celery-worker
```

`caller-register` applies the Piccolo migrations at startup, so every other
unit is ordered `After=` it.

---

## Networking

The aiohttp microservices bind `0.0.0.0` on ports 8081-8087 regardless of the
`*_host` values in `settings.toml` — those are the addresses the services use
to call *each other*, not bind addresses. The UI binds whatever
`py_phone_caller_ui.ui_listen_on_host` says.

What keeps them private is therefore the firewall, not the bind address: only
80 and 443 are opened, and Caddy terminates TLS and proxies to the UI. If you
turn off `py_phone_caller_manage_firewall`, those ports are exposed.

To expose a service directly — for example so a remote Alertmanager can post
to the webhook — add its port:

```yaml
# group_vars/all.yml
py_phone_caller_firewall_extra_ports: [8084]
```

A `caddy_domain_name` ending in `.lan`, `.local`, `.internal` or `.test` gets
Caddy's internal CA. Anything else goes to Let's Encrypt and needs
`caddy_email` plus reachable ports 80 and 443.

### Fronting with an existing reverse proxy

If the host already has one, set `py_phone_caller_manage_caddy: false` and
point that proxy at the UI. The role refuses to install Caddy alongside
another proxy anyway: it checks for NAT rules diverting 80/443 and for
foreign listeners on those ports, because Caddy would bind them, start
cleanly, and never receive a packet — the only symptom being a TLS handshake
failure.

`openalert` is set up this way. It runs Nginx Proxy Manager as a rootless
Podman container (published on 8080/8181/8443, with iptables `REDIRECT`
sending 80/443 to it), so `py_phone_caller_manage_caddy` is `false` in
`group_vars/all.yml` and the UI is published through NPM:

| NPM proxy host field | Value |
| --- | --- |
| Domain | `py-phone-caller.lan` (or a real name) |
| Scheme | `http` |
| Forward hostname | `host.containers.internal` |
| Forward port | `5000` |

`host.containers.internal` resolves to `169.254.1.2` inside rootless Podman
containers and reaches the host without any firewall change — verified
returning HTTP 200 from inside the `npm` container. The container network
cannot use `127.0.0.1`, and the bridge/public addresses are blocked by ufw.

Keep `py_phone_caller_manage_firewall: true` in this setup. The services bind
`0.0.0.0`, and on a host with a public address ufw is the only thing keeping
8081-8087, 5000, 5432 and 6379 off the internet.

---

## Troubleshooting

```bash
systemctl list-units 'py-phone-caller-*'
journalctl -u py-phone-caller-caller-register -n 100 --no-pager

sudo -u py-phone-caller cat /opt/py-phone-caller/src/config/settings.toml
sudo -u py-phone-caller /opt/py-phone-caller/venv/bin/python -c \
  'from py_phone_caller_utils.config import settings; print(settings.database.db_host)'
```

| Symptom | Cause |
| --- | --- |
| `Placeholder credentials are still in place` | `.secrets.toml` still says `change_me`/`super_secure_password`; set real values and regenerate the group_vars |
| `db_host ... is not local` | the database is remote, so set `py_phone_caller_db_admin_password` or `py_phone_caller_manage_database: false` |
| PostgreSQL provisioning fails and the output is hidden | set `py_phone_caller_db_no_log: false` and re-run with `--tags database` |
| `uv sync` fails offline | point `py_phone_caller_uv_extra_index_url` at your mirror, and `py_phone_caller_uv_insecure_host` if it is plain HTTP |
| ffmpeg missing on RHEL | expected; only affects the TTS engines that post-process with pydub. Enable RPM Fusion and re-run `--tags prereqs` |
| A unit restarts in a loop | check the database first: `journalctl -u py-phone-caller-caller-register` |
| `https://<caddy_domain_name>/` fails on the target itself | the name has to resolve there: Caddy's `tls internal` needs SNI, so a `Host:` header against `https://127.0.0.1/` fails the handshake. Keep the domain in `py_phone_caller_hosts_entries`. |

---

## Also here

* `../asterisk_py-phone-caller/` — Asterisk PBX on its own
* `../deploy_all/` — Asterisk **and** the services in one run, sharing this
  inventory and these group_vars
* `../tools/README.md` — the configuration converter
