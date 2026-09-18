# All-in-one deployment runbook: Asterisk PBX + py-phone-caller

A complete, step-by-step walkthrough from a freshly provisioned VM to a
working alerting platform: Asterisk with ARI, PostgreSQL, Redis/Valkey, and
the eleven Python services as systemd units.

Every step below states what to run, what you should see, and what to do when
you see something else. If you follow it in order you will not need to
improvise.

Roughly 45 minutes end to end, most of it waiting on `uv sync` to download
~3 GB of PyTorch and CUDA wheels.

> `openalertd` (`src/openalert/`) is a separate Rust daemon with its own
> packaging under `src/openalert/packaging/`. It is **not** deployed by these
> playbooks.

---

## Table of contents

- [Verification status](#verification-status)
- [0. What this builds](#0-what-this-builds)
- [1. Requirements](#1-requirements)
- [2. Step 1 — SSH access to the target](#2-step-1--ssh-access-to-the-target)
- [3. Step 2 — Prepare the control node](#3-step-2--prepare-the-control-node)
- [4. Step 3 — Write the inventory](#4-step-3--write-the-inventory)
- [5. Step 4 — Configure the application](#5-step-4--configure-the-application)
- [6. Step 5 — Generate the Ansible vars](#6-step-5--generate-the-ansible-vars)
- [7. Step 6 — Declare the deployment topology](#7-step-6--declare-the-deployment-topology)
- [8. Step 7 — Configure the SIP trunk](#8-step-7--configure-the-sip-trunk)
- [9. Step 8 — Preflight checks](#9-step-8--preflight-checks)
- [10. Step 9 — Run the deployment](#10-step-9--run-the-deployment)
- [11. Step 10 — Verify](#11-step-10--verify)
- [12. Step 11 — Publish the web UI](#12-step-11--publish-the-web-ui)
- [13. Step 12 — First admin login](#13-step-12--first-admin-login)
- [14. Step 13 — Place a test call](#14-step-13--place-a-test-call)
- [15. Day-2 operations](#15-day-2-operations)
- [16. Troubleshooting](#16-troubleshooting)
- [17. Appendix: what lands where](#17-appendix-what-lands-where)

---

## Verification status

This runbook was executed end to end against a real host, but not every path
in it has been. Treat the second table as "should work, unproven".

**Verified on Ubuntu 26.04 (all-in-one, on-premise SMS, existing NPM proxy):**

- Steps 1-11, including a second run reporting `changed=0`
- `verify.yml`: 11 units active, 7/7 health endpoints, UI HTTP 200
- Each of `--tags prereqs|source|install|database|config|systemd` in isolation
- PostgreSQL provisioned over the unix socket with peer authentication
- Piccolo migrations creating all 7 tables on first start
- ARI authenticating with the credentials derived from `settings.toml`, and the
  Stasis app registered
- The native SMS engine compiling, installing, importing, and reporting
  *Starting engine with 2 modem(s)* at runtime
- Every service port closed from the internet, with SSH as positive control
- The reverse-proxy conflict check firing correctly
- `host.containers.internal:5000` returning 200 from inside the NPM container

**Documented but not executed — verify these yourself:**

| Path | Why it is unproven |
| :--- | :--- |
| Caddy serving traffic | It installed on the test host but was NAT-diverted by an existing proxy, so it never handled a request. TLS, the internal CA and the domain matching are from Caddy's behaviour and its logs, not from a working request. |
| RHEL / Rocky / AlmaLinux | Never run. The OS-family variables and the `redis`/`valkey` and `crb`/`powertools` version logic were tested for their *values* only. EPEL is not packaged on RHEL proper (§16). |
| Let's Encrypt (`caddy_email`) | Not exercised; the test host used a `.lan` name. |
| A database on another host | The TCP + admin-password path was never run; only the local socket path. |
| `py_phone_caller_git_repo` | Source was always delivered by rsync from a checkout. |
| Twilio as the SMS carrier | The test host used `on_premise`. |
| An actual call or SMS (Step 13) | No working SIP trunk on the test host, so the `curl` commands were never seen to place a call. |
| `py_phone_caller_remove_build_deps` | Never run. |

If you hit something these steps do not cover, §16 is the first place to look
— every entry there is a failure that actually happened.

---

## 0. What this builds

Two plays run back to back against the same hosts:

| Play | Role | Installs |
| :--- | :--- | :--- |
| 1 | `asterisk_py_phone_caller` | Asterisk, PJSIP, ARI user, Stasis dialplan, alert prompts |
| 2 | `deploy_py-phone-caller` | PostgreSQL, Redis/Valkey, Python 3.14 venv, 11 systemd units, firewall, optional Caddy |

Use `deploy_all` when the PBX and the services share a machine. To deploy them
on separate hosts, run
[`../asterisk_py-phone-caller/deploy_asterisk.yml`](../asterisk_py-phone-caller/)
and
[`../on-vm_py-phone-caller/deploy_py-phone-caller.yml`](../on-vm_py-phone-caller/)
independently.

### One configuration, both plays

`ansible.cfg` in this directory points at
`../on-vm_py-phone-caller/inventory`, so **both** plays read the same
`group_vars/`. The Asterisk play derives its settings from the application
configuration instead of repeating them, so the two halves cannot drift:

| Asterisk role variable | Derived from `settings.toml` |
| :--- | :--- |
| `ari_username` | `commons.asterisk_user` |
| `ari_password` | `commons.asterisk_pass` (from `.secrets.toml`) |
| `ari_app_name` | `asterisk_ws_monitor.asterisk_stasis_app` |
| `asterisk_http_bindport` | `commons.asterisk_web_port` |
| `asterisk_context` | `asterisk_call.asterisk_context` |
| `asterisk_extension` | `asterisk_call.asterisk_extension` |
| `callback_service_url` | `call_register.call_register_http_scheme` + `_port` |

Only the SIP trunk has no counterpart in `settings.toml`; it is set separately
in [Step 7](#8-step-7--configure-the-sip-trunk).

---

## 1. Requirements

### Control node — the machine you run `ansible-playbook` from

| Requirement | Why | Check |
| :--- | :--- | :--- |
| `ansible-core` ≥ 2.15 | `apply:` on includes, `timeout:` task keyword | `ansible --version` |
| `rsync` | source delivery uses `ansible.posix.synchronize` | `command -v rsync` |
| Python ≥ 3.11 | `tomllib` for the config converter | `python3 -V` |
| `git` | the repository checkout is what gets deployed | `git --version` |
| The repository, checked out | rsync ships *this* working tree, not a tag | `ls pyproject.toml uv.lock` |

### Target host

| Requirement | Notes |
| :--- | :--- |
| Ubuntu 22.04+ / Debian 12+, or RHEL/Rocky/Alma 9+ | Verified on Ubuntu 26.04 with system Python 3.14.4 |
| 4 GB RAM | PyTorch and the TTS models are the constraint; 2 GB is the bare floor |
| **15 GB free disk** | ~7 GB venv, ~1.4 GB Cargo target, ~1 GB TTS models, plus the uv cache |
| 2+ vCPU | 4 recommended; TTS synthesis is CPU-bound |
| `rsync` and `sudo` installed | `synchronize` shells out to rsync over SSH |
| SSH as `root`, **or** a user with passwordless sudo | `synchronize` runs rsync as the connection user; without passwordless sudo it cannot elevate |
| Outbound HTTPS | PyPI, `astral.sh` (uv), Hugging Face (TTS models), Cloudsmith (Caddy) |

> **A note on disk**: the first `uv sync` downloads roughly 3 GB of wheels
> (`torch` 502 MB, `nvidia-cublas` 403 MB, `nvidia-cudnn` 349 MB, `triton`
> 189 MB, and ~40 more). They are cached under
> `/opt/py-phone-caller/.uv/cache`, which you can delete afterwards with
> `py_phone_caller_remove_build_deps: true`.

### Firewall reality check

The aiohttp services bind `0.0.0.0` on ports 8081-8087, regardless of the
`*_host` values in `settings.toml` — those are the addresses the services use
to reach *each other*, not bind addresses. The UI binds whatever
`py_phone_caller_ui.ui_listen_on_host` says.

**The firewall is therefore the only thing keeping them off the network.**
Leave `py_phone_caller_manage_firewall: true` unless you have another packet
filter in front. On a host with a public IP this is not optional.

---

## 2. Step 1 — SSH access to the target

The playbooks never prompt for a password, so key-based access has to work
first.

```bash
# 1. Copy your key if you have not already
ssh-copy-id root@<target-ip>

# 2. Confirm a non-interactive login works
ssh -o BatchMode=yes root@<target-ip> 'echo ok; id; uname -a'
```

Expected:

```
ok
uid=0(root) gid=0(root) groups=0(root)
Linux openalert 6.17.0-... x86_64 GNU/Linux
```

A convenient `~/.ssh/config` entry lets the inventory use a short name and
keeps a non-standard port out of the inventory file:

```sshconfig
Host openalert
    HostName 203.0.113.10
    User root
    Port 22022
    IdentityFile ~/.ssh/id_ed25519
```

If you connect as a non-root user, verify passwordless sudo **and** that rsync
can elevate:

```bash
ssh <user>@<target> 'sudo -n true && echo "passwordless sudo OK"'
ssh <user>@<target> 'sudo -n rsync --version | head -1'
```

Both must succeed. If `sudo -n` prompts, add a `NOPASSWD` rule or connect as
root.

---

## 3. Step 2 — Prepare the control node

```bash
git clone https://github.com/jcfdeb/py-phone-caller.git
cd py-phone-caller/assets/ansible/deploy_all

ansible-galaxy collection install -r requirements.yml
```

That installs three collections:

| Collection | Used for |
| :--- | :--- |
| `ansible.posix` | `synchronize` (source delivery), `firewalld` |
| `community.general` | `ufw`, `ini_file` (Asterisk `http.conf`/`ari.conf`) |
| `community.postgresql` | role, database, grants, extensions, `pg_hba` |

Confirm:

```bash
ansible-galaxy collection list | grep -E "ansible.posix|community.general|community.postgresql"
```

Expected — versions at or above these:

```
ansible.posix             2.2.2
community.general         13.3.0
community.postgresql      4.2.0
```

`ansible.cfg` in this directory already sets the inventory, both role paths,
privilege escalation and SSH multiplexing. **Run `ansible-playbook` from
inside this directory** so it is picked up — Ansible only reads `ansible.cfg`
from the current working directory.

---

## 4. Step 3 — Write the inventory

Edit `../on-vm_py-phone-caller/inventory`:

```ini
[app_servers]
openalert ansible_host=openalert ansible_user=root

[app_servers:vars]
ansible_python_interpreter=/usr/bin/python3
ansible_ssh_extra_args='-o StrictHostKeyChecking=no'
```

- The group **must** be `app_servers` — both plays target it, and the
  generated variables live in `group_vars/app_servers/`.
- `ansible_host=openalert` resolves through your `~/.ssh/config`. Use an IP
  address instead if you prefer.
- Do not put `ansible_become` here; escalation is configured in `ansible.cfg`.

Verify Ansible can reach the host and gather facts:

```bash
ansible app_servers -m ping
ansible app_servers -m setup -a 'filter=ansible_distribution*,ansible_os_family' | grep -E "distribution\"|distribution_major|os_family"
```

Expected:

```
openalert | SUCCESS => { "ping": "pong" }
        "ansible_distribution": "Ubuntu",
        "ansible_distribution_major_version": "26",
        "ansible_os_family": "Debian",
```

If `os_family` is anything other than `Debian` or `RedHat`, the role stops on
its first task with a clear message — nothing is changed.

---

## 5. Step 4 — Configure the application

`src/config/settings.toml` and `src/config/.secrets.toml` are the single
source of truth for the whole platform: the same files drive local
development, the container images, and this deployment. Edit them, not the
Ansible variables.

### 5.1 `src/config/settings.toml` — the settings that matter first

```toml
[commons]
asterisk_user = "py-phone-caller"     # becomes the ARI user in ari.conf
asterisk_host = "pbx.lan"             # where the services reach Asterisk
asterisk_web_port = "8088"            # ARI HTTP port
asterisk_ami_user = "admin"

[asterisk_call]
asterisk_context = "py-phone-caller"  # dialplan context created in extensions.conf
asterisk_extension = "3216"           # extension that enters the Stasis app
asterisk_chan_type = "PJSIP/py-phone-caller"   # how outbound calls are placed
asterisk_caller_id = "Py-Phone-Caller"

[generate_audio]
tts_engine = "kokoro_tts"             # kokoro_tts | piper_tts | facebook_mms | google_gtts | aws_polly
num_of_cpus = 2

[caller_sms]
caller_sms_carrier = "twilio"         # "twilio" or "on_premise"
twilio_sms_from = "+15551234567"

[database]
db_host = "postgresql.lan"
db_name = "py_phone_caller"
db_user = "py_phone_caller"

[queue]
queue_host = "redis.lan"
queue_url = "redis://redis.lan:6379/7"

[py_phone_caller_ui]
ui_listen_on_host = "0.0.0.0"         # bind address for gunicorn
ui_listen_on_port = 5000
ui_admin_user = "admin@example.com"   # the first admin account's e-mail
min_password_length = 17
```

Key choices:

- **`asterisk_chan_type`** decides how calls leave the PBX.
  `PJSIP/py-phone-caller` dials through the trunk endpoint the Asterisk role
  creates. `Local/{phone}@py-phone-caller` routes back through the dialplan,
  which is what you want with local handsets or a GSM gateway.
- **`tts_engine`** — `kokoro_tts` is the best offline default. All the
  local engines need `ffmpeg`, which the role installs.
- **`caller_sms_carrier`** — `on_premise` triggers extra work: the role
  installs the Rust toolchain, compiles the native modem engine, and adds the
  service account to the `dialout` group. It also **requires** at least one
  modem with a `port`:

  ```toml
  [[caller_sms.modems]]
  id = "primary_carrier"
  port = "/dev/ttyUSB2"
  baud_rate = 115200
  priority = 1
  ```

  > Use `udev` rules to pin stable symlinks such as `/dev/modem_primary`.
  > `/dev/ttyUSB*` numbering changes across reboots.

- **`db_host` / `queue_host`** — leave the names your container stack uses.
  [Step 6](#7-step-6--declare-the-deployment-topology) redirects them per
  host; you do not have to edit `settings.toml` for each environment.

### 5.2 `src/config/.secrets.toml` — credentials

```toml
[commons]
asterisk_pass = "<ARI password>"          # must be strong; Asterisk ARI is HTTP Basic
asterisk_ami_secret = "<AMI secret>"

[caller_sms]
twilio_account_sid = "AC..."
twilio_auth_token = "..."

[database]
db_password = "<PostgreSQL password>"

[py_phone_caller_ui]
ui_secret_key = "<Flask secret, e.g. uuidgen>"
```

Generate strong values:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
uuidgen
```

The role **refuses to deploy** while `db_password`, `ui_secret_key` or
`asterisk_pass` still read `change_me` or `super_secure_password`.

> This file is tracked in git with placeholder values. Keep your real values
> in the working tree and never `git add -A` here. Check
> `git status --porcelain src/config/` before committing.

---

## 6. Step 5 — Generate the Ansible vars

```bash
../tools/toml_to_ansible_vars.py
```

Expected:

```
Wrote .../assets/ansible/on-vm_py-phone-caller/group_vars/app_servers/config.yml
Wrote .../assets/ansible/on-vm_py-phone-caller/group_vars/app_servers/secrets.yml (0600, encrypt it with ansible-vault)
```

| File | Variable | Mode |
| :--- | :--- | :--- |
| `group_vars/app_servers/config.yml` | `py_phone_caller_config` | `0644` |
| `group_vars/app_servers/secrets.yml` | `py_phone_caller_config_secrets` | `0600` |

Both are git-ignored — they mirror your live configuration, credentials and
phone numbers. Committed samples live in
`../on-vm_py-phone-caller/examples/`.

> **`group_vars/app_servers/` has to stay a directory.** Ansible reads every
> file inside `group_vars/<group>/`, but auto-loads a *plain* file only when
> its stem is exactly the group name. A `group_vars/app_servers.secrets.yml`
> is skipped with no warning at all, and the play then fails much later on an
> undefined variable. Both playbooks assert that the variables actually
> arrived, so you get a clear error rather than a mystery.

Confirm Ansible sees them:

```bash
ansible-inventory --host openalert | python3 -c "
import json,sys
d=json.load(sys.stdin)
for k in ('py_phone_caller_config','py_phone_caller_config_secrets','py_phone_caller_config_overrides'):
    v=d.get(k); print(f'{k}: ' + ('MISSING' if v is None else f'{len(v)} sections'))"
```

Expected:

```
py_phone_caller_config: 14 sections
py_phone_caller_config_secrets: 4 sections
py_phone_caller_config_overrides: 3 sections
```

### Optional: encrypt the secrets

```bash
ansible-vault encrypt ../on-vm_py-phone-caller/group_vars/app_servers/secrets.yml
# then add --ask-vault-pass (or --vault-password-file) to every playbook run
```

Re-running the converter refuses to overwrite an encrypted file; decrypt it
first, or send the fresh copy elsewhere with `--secrets-output`.

---

## 7. Step 6 — Declare the deployment topology

`../on-vm_py-phone-caller/group_vars/all.yml` holds everything that describes
*this host* rather than the application. It is committed, and it is merged
**after** the generated files, so regenerating them never clobbers it.

The four configuration layers, later winning:

```
roles/deploy_py-phone-caller/defaults/main.yml  py_phone_caller_config_defaults
group_vars/app_servers/config.yml               py_phone_caller_config
group_vars/app_servers/secrets.yml              py_phone_caller_config_secrets
group_vars/all.yml                              py_phone_caller_config_overrides
```

### All-in-one host (this playbook's usual case)

```yaml
# group_vars/all.yml
py_phone_caller_config_overrides:
  commons:
    asterisk_host: "127.0.0.1"
  database:
    db_host: "127.0.0.1"
  queue:
    queue_host: "127.0.0.1"
    queue_url: "redis://127.0.0.1:6379/7"

# Safety net so any .lan name left in a config file still resolves.
py_phone_caller_hosts_entries:
  - address: "127.0.0.1"
    names:
      - "{{ caddy_domain_name }}"
      - pbx.lan
      - postgresql.lan
      - redis.lan
```

Pointing `database.db_host` at loopback is what makes provisioning
painless: the role installs PostgreSQL locally and creates the role, database,
grants and extensions over the **unix socket** as the `postgres` system user.
No admin password is needed.

### Database somewhere else

```yaml
py_phone_caller_config_overrides:
  database:
    db_host: "postgres.internal.example.com"

py_phone_caller_db_admin_user: "postgres"
py_phone_caller_db_admin_password: "{{ vault_pg_admin_password }}"
py_phone_caller_manage_queue: false          # Redis is elsewhere too
```

With a non-local `db_host` the role can only reach the server over TCP, so it
**requires** `py_phone_caller_db_admin_password`. Without it the play stops
during validation and tells you so. Alternatively set
`py_phone_caller_manage_database: false` and create the role and database
yourself:

```sql
CREATE ROLE py_phone_caller LOGIN PASSWORD '...' NOSUPERUSER NOCREATEDB;
CREATE DATABASE py_phone_caller OWNER py_phone_caller ENCODING 'UTF8';
\c py_phone_caller
GRANT ALL ON SCHEMA public TO py_phone_caller;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

The `GRANT ALL ON SCHEMA public` matters: PostgreSQL 15 revoked `CREATE` on
`public` from `PUBLIC`, and the Piccolo migrations need it.

### Reverse proxy

```yaml
caddy_domain_name: "alerts.example.com"
caddy_email: "ops@example.com"        # required for Let's Encrypt
```

A name ending in `.lan`, `.local`, `.internal` or `.test` gets Caddy's
internal CA automatically. Anything else goes to Let's Encrypt, which needs
`caddy_email` set and ports 80/443 reachable from the internet.

**If the host already runs a reverse proxy**, disable Caddy:

```yaml
py_phone_caller_manage_caddy: false
```

The role checks for this and refuses to install a second proxy, because the
failure is otherwise invisible: Caddy binds 80/443, starts cleanly, and never
receives a packet, because the incumbent's NAT `REDIRECT` rules divert them
first — loopback included. The only symptom is a TLS handshake failure. To
override the check anyway, set `py_phone_caller_caddy_force: true`.

[Step 11](#12-step-11--publish-the-web-ui) covers wiring an existing proxy.

---

## 8. Step 7 — Configure the SIP trunk

These have no equivalent in `settings.toml`. Put them in
`../on-vm_py-phone-caller/group_vars/all.yml`, or in a vaulted file:

```yaml
# Upstream SIP provider or GSM gateway
pbx_sip_provider_host: "sip.example.net"
pbx_sip_provider_port: 5061
pbx_sip_username: "trunk-user"
pbx_sip_password: "{{ vault_sip_password }}"
pbx_sip_contact_user: "trunk-user"

# Local extensions — useful on an isolated network or with local handsets
pbx_local_sip: true
pbx_local_sip_exten: 2500
pbx_local_sip_pass: "{{ vault_local_sip_password }}"
pbx_local_iax: false
pbx_local_iax_exten: 2600
pbx_local_iax_pass: "{{ vault_local_iax_password }}"
```

Left unset, they default to `CHANGE_ME` and Asterisk installs with a trunk
that cannot register. ARI, the dialplan and the Stasis app still work, so the
services come up healthy — you just cannot place outbound calls until the
trunk is real.

With a **GSM gateway** on the LAN instead of a cloud trunk, point
`pbx_sip_provider_host` at the gateway's IP and set
`caller_sms.caller_sms_carrier = "on_premise"` in `settings.toml`.

---

## 9. Step 8 — Preflight checks

Three checks that touch nothing.

**1. Render the configuration locally.** Merges all four layers, renders every
template, and diffs the resulting TOML against the merged configuration key by
key:

```bash
cd ../on-vm_py-phone-caller
ansible-playbook -i localhost, -c local render_check.yml
cd ../deploy_all
```

Expected:

```
"toml: 14 sections, 124 keys match",
"local postgres: True",
"db host: 127.0.0.1",
"queue: redis://127.0.0.1:6379/7",
"asterisk: 127.0.0.1",
"units: 11"
```

Rendered files are left in `/tmp/py-phone-caller-render` for inspection —
including the exact `settings.toml`, `.secrets.toml`, `Caddyfile` and eleven
unit files the target will receive.

**2. Syntax check both plays:**

```bash
ansible-playbook --syntax-check deploy_py-phone-caller_stack.yml
```

**3. Confirm the target has room and reach:**

```bash
ansible app_servers -m shell -a '
df -h / | tail -1
free -m | head -2
command -v rsync sudo curl git
curl -sS -o /dev/null -w "pypi:%{http_code} " https://pypi.org/simple/
curl -sS -o /dev/null -w "astral:%{http_code}\n" https://astral.sh/uv/install.sh'
```

You want ≥ 15 GB available, all four binaries present, and HTTP 200/301 from
both URLs.

---

## 10. Step 9 — Run the deployment

```bash
ansible-playbook deploy_py-phone-caller_stack.yml
```

To watch it without the wall of text, or to keep a log for later:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml 2>&1 | tee /tmp/ppc-deploy.log
```

### What happens, in order

**Play 1 — Asterisk** (2-5 minutes)

1. Asserts the generated group_vars are loaded.
2. Installs `asterisk`, `asterisk-dev`, `asterisk-modules`,
   `asterisk-core-sounds-en`.
3. Creates the `asterisk` user and its data directories.
4. Installs the alert prompts (`greeting-message.wav`,
   `press-4-for-acknowledgement.wav`).
5. Writes four partial configs — `extensions_py_phone_caller.conf`,
   `pjsip_py_phone_caller.conf`, `ari_py_phone_caller.conf`,
   `iax_py_phone_caller.conf` — and `#include`s them from the stock files, so
   your existing Asterisk configuration is left intact.
6. Disables `chan_sip` to free port 5060 for PJSIP.
7. Enables ARI on `commons.asterisk_web_port` and starts Asterisk.

**Play 2 — the services** (10-30 minutes, dominated by step 4)

| Phase | Tag | What it does |
| :--- | :--- | :--- |
| Validate | `always` | Six assertions: all config sections present, database settings set, no placeholder credentials, remote DB has an admin password, on-premise SMS has modems, `/etc/hosts` entries well formed |
| Prerequisites | `prereqs` | `/etc/hosts` block, OS packages, EPEL/CRB on RHEL, ffmpeg, Redis/Valkey, PostgreSQL server, Rust toolchain if on-premise SMS |
| Service account | `user` | `py-phone-caller` system user, `nologin`, home `/opt/py-phone-caller`; added to `dialout` for on-premise SMS |
| Source | `source` | rsync of the repository, preserving its layout; `--delete` protected against removing the venv, TTS models, rendered config and Cargo target |
| Python env | `install` | Installs `uv`, verifies it landed, `uv sync --frozen --all-packages --no-dev`, builds and installs the native SMS engine, **verifies it imports** |
| Database | `database` | pg_hba for loopback passwords, role, database, `ALL` on schema `public`, `uuid-ossp` + `pgcrypto` |
| Configuration | `config` | Renders `settings.toml` (0640) and `.secrets.toml` (0600), both validated with `tomllib` **before** being moved into place |
| Reverse proxy | `caddy` | Conflict check, then install and configure Caddy (skipped if disabled) |
| Firewall | `firewall` | firewalld or ufw: SSH plus 80/443 |
| systemd | `systemd` | Eleven units, all ordered after `caller-register`; removes units dropped from the list |

### Expected result

```
PLAY RECAP *********************************************************************
openalert : ok=86  changed=NN  unreachable=0  failed=0  skipped=26
```

`failed=0` is what matters. A **re-run reports `changed=0`** — the role is
idempotent, so there is no harm in running it repeatedly.

### If it fails

The play stops at the failing task and changes nothing after it. Nothing is
half-applied that a re-run will not converge. Jump to
[Troubleshooting](#16-troubleshooting) — every failure mode we have actually
hit is listed there with its exact error text.

---

## 11. Step 10 — Verify

```bash
ansible-playbook -i ../on-vm_py-phone-caller/inventory \
                 ../on-vm_py-phone-caller/verify.yml
```

This checks that every installed unit is `active`, probes all seven `/health`
endpoints with retries, and fetches the web UI.

Expected:

```
"units active: 11",
"health endpoints OK: 7",
"web UI direct: HTTP 200",
"web UI via Caddy: HTTP 200"
```

### Manual checks worth doing once

```bash
ssh openalert
```

**Units and restart counts** — a non-zero `NRestarts` means something is
crash-looping:

```bash
for u in $(systemctl list-unit-files 'py-phone-caller-*.service' --no-legend | awk '{print $1}' | sort); do
  printf '%-50s %-8s restarts=%s\n' "$u" "$(systemctl is-active $u)" "$(systemctl show -p NRestarts --value $u)"
done
```

**Database schema** — created by `caller_register` on first start:

```bash
sudo -u postgres psql -d py_phone_caller -c '\dt'
```

Expected: `address_book`, `asterisk_ws_events`, `calls`, `migration`,
`scheduled_calls`, `sms`, `users`.

**Asterisk ARI, using the credentials the services actually use:**

```bash
U=$(python3 -c 'import tomllib;print(tomllib.load(open("/opt/py-phone-caller/src/config/settings.toml","rb"))["commons"]["asterisk_user"])')
P=$(python3 -c 'import tomllib;print(tomllib.load(open("/opt/py-phone-caller/src/config/.secrets.toml","rb"))["commons"]["asterisk_pass"])')
curl -sS -u "$U:$P" http://127.0.0.1:8088/ari/asterisk/info | head -20
```

A JSON document means ARI is up and the password matches. `401` means the two
halves disagree — re-run the whole stack playbook rather than one play.

**Stasis registration** — proves `asterisk_ws_monitor` is connected:

```bash
asterisk -rx 'ari show apps'
asterisk -rx 'dialplan show py-phone-caller'
asterisk -rx 'pjsip show registrations'
```

`ari show apps` must list your `asterisk_stasis_app` (default
`py-phone-caller`).

**On-premise SMS engine**, if you selected it:

```bash
/opt/py-phone-caller/venv/bin/python -c 'import rust_engine; print(rust_engine.__file__)'
journalctl -u py-phone-caller-caller-sms | grep -i rust
```

You want `Rust SMS engine started successfully` and a line naming your modem
count and strategy. `Rust SMS engine not found` means the module is missing —
the role's import check should have caught that, so re-run with
`--tags install`.

**Confirm the services are not exposed.** From *another* machine:

```bash
for p in 5000 8081 8083 8085 8087 8088 5432 6379; do
  timeout 5 bash -c "</dev/tcp/<target-ip>/$p" 2>/dev/null && echo "$p OPEN <-- FIX THIS" || echo "$p closed"
done
# positive control: your SSH port must show OPEN, or the test proves nothing
timeout 5 bash -c "</dev/tcp/<target-ip>/22" && echo "22 OPEN (control)"
```

Every service port must be closed. Without the SSH positive control the
result is meaningless — a network that blocks everything looks identical to a
working firewall.

---

## 12. Step 11 — Publish the web UI

### With Caddy (the role's default)

Already done. Caddy terminates TLS on 443 and proxies to the UI. Browse to
`https://<caddy_domain_name>/`.

For a `.lan`-style name, the host needs to resolve it — the
`py_phone_caller_hosts_entries` block in Step 6 handles that on the target
itself, and you will want the same entry in your own `/etc/hosts` or LAN DNS.

> Caddy's `tls internal` needs SNI, so `curl -k https://127.0.0.1/` with a
> `Host:` header fails the handshake with `TLSV1_UNRECOGNIZED_NAME`. Always
> test by name.

Its certificate is signed by Caddy's local CA, so browsers warn. To trust it:

```bash
# Ask the host where Caddy keeps its CA - the path depends on Caddy's
# XDG_DATA_HOME, so do not hardcode it.
ssh openalert 'find /var/lib/caddy -name root.crt -path "*authorities/local*" 2>/dev/null'
# typically: /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt

scp openalert:<that-path> ppc-root.crt

# Debian/Ubuntu
sudo cp ppc-root.crt /usr/local/share/ca-certificates/ppc-root.crt && sudo update-ca-certificates
# RHEL/Rocky
sudo cp ppc-root.crt /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust
```

### With an existing reverse proxy

Set `py_phone_caller_manage_caddy: false` and point your proxy at the UI.

**Nginx Proxy Manager (rootless Podman)** — add a Proxy Host:

| Field | Value |
| :--- | :--- |
| Domain Names | `alerts.example.com` |
| Scheme | `http` |
| Forward Hostname / IP | `host.containers.internal` |
| Forward Port | `5000` |
| Websockets Support | **on** (the UI streams live call events) |
| Block Common Exploits | on |

`host.containers.internal` resolves to `169.254.1.2` inside rootless Podman
and reaches the host with no firewall change. `127.0.0.1` does **not** work
from a container's network namespace, and the bridge or public addresses are
blocked by ufw.

Verify from inside the container before blaming the proxy:

```bash
sudo -u <podman-user> XDG_RUNTIME_DIR=/run/user/$(id -u <podman-user>) \
  podman exec <npm-container> \
  curl -s -o /dev/null -w '%{http_code}\n' http://host.containers.internal:5000/
```

`200` means the upstream is reachable.

**Plain nginx on the host:**

```nginx
server {
    listen 443 ssl http2;
    server_name alerts.example.com;

    ssl_certificate     /etc/letsencrypt/live/alerts.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/alerts.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade    $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Keep `py_phone_caller_manage_firewall: true` either way. The services bind
`0.0.0.0`; only the firewall keeps 8081-8087, 5000, 5432 and 6379 private.

---

## 13. Step 12 — First admin login

The UI creates its admin account on first start and generates a random
password, which it writes to the journal. Ask for a fresh one:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml \
  -e py_phone_caller_ui_reset_password=true --tags systemd,config

ssh openalert 'journalctl -u py-phone-caller-py-phone-caller-ui -n 80 --no-pager' | grep -iA3 password
```

Log in with `py_phone_caller_ui.ui_admin_user` and that password, change it
immediately (`min_password_length` defaults to 17), then turn the flag off:

```yaml
# group_vars/all.yml
py_phone_caller_ui_reset_password: false
```

and re-run, otherwise the password is regenerated on every restart.

---

## 14. Step 13 — Place a test call

From the target host, so you do not need the ports open:

```bash
ssh openalert
```

**A voice call:**

```bash
curl -sS -X POST \
  'http://127.0.0.1:8081/place_call?phone=%2B15551234567&message=py-phone-caller+test+alert'
```

Replace `%2B` with a literal `+` only if your shell escapes it correctly —
URL-encoding is safer. Then watch the pipeline:

```bash
journalctl -u py-phone-caller-asterisk-caller -f          # the outbound leg
journalctl -u py-phone-caller-generate-audio -f           # TTS synthesis
journalctl -u py-phone-caller-asterisk-ws-monitor -f      # Stasis events
journalctl -u py-phone-caller-caller-register -f          # DB records
```

The first call with a local TTS engine is slow: the model downloads from
Hugging Face into
`/opt/py-phone-caller/src/generate_audio/pre_trained_models/`. Later calls
reuse it.

Confirm it was recorded:

```bash
sudo -u postgres psql -d py_phone_caller -c \
  'SELECT id, phone, asterisk_chan, heard, acknowledged, inserted_at FROM calls ORDER BY id DESC LIMIT 5;'
```

**An SMS:**

```bash
curl -sS -X POST \
  'http://127.0.0.1:8085/send_sms?phone=%2B15551234567&message=test+sms'
journalctl -u py-phone-caller-caller-sms -n 50 --no-pager
```

**The Alertmanager webhook**, exactly as Prometheus would send it:

```bash
curl -sS -X POST http://127.0.0.1:8084/call_only \
  -H 'Content-Type: application/json' \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"TestAlert","severity":"critical"},"annotations":{"description":"Synthetic test from the installation guide"}}]}'
```

---

## 15. Day-2 operations

### Change the configuration

```bash
vim ../../../src/config/settings.toml
../tools/toml_to_ansible_vars.py
ansible-playbook deploy_py-phone-caller_stack.yml --tags config
```

`--tags config` re-renders both TOML files and restarts the services through
a handler. Nothing else is touched.

### Deploy new code

```bash
git pull
ansible-playbook deploy_py-phone-caller_stack.yml --tags source,install,systemd
```

### Tags

| Tag | Scope |
| :--- | :--- |
| `prereqs` | OS packages, Redis/Valkey, PostgreSQL server, `/etc/hosts` |
| `user` | service account and directories |
| `source` | rsync the code |
| `install` | `uv sync`, native SMS engine |
| `database` | role, database, grants, extensions |
| `config` | render `settings.toml` and `.secrets.toml` |
| `caddy` | reverse proxy |
| `firewall` | firewalld / ufw |
| `systemd` | unit files, enable and start |
| `cleanup` | remove build dependencies (opt-in) |

Every tag is independently idempotent; each reports `changed=0` on a
converged host.

### Reclaim disk

```yaml
py_phone_caller_remove_build_deps: true
```

Removes the compilers and the uv download cache. Off by default because the
next dependency bump then needs `--tags prereqs` first, and package-manager
`autoremove` has a habit of taking shared libraries with it.

### Restart or stop everything

```bash
systemctl restart 'py-phone-caller-*'
systemctl stop    'py-phone-caller-*'
journalctl -u 'py-phone-caller-*' -f --no-pager
```

### Back up

```bash
sudo -u postgres pg_dump py_phone_caller | gzip > ppc-$(date +%F).sql.gz
tar -czf ppc-config-$(date +%F).tar.gz /opt/py-phone-caller/src/config /etc/asterisk
```

---

## 16. Troubleshooting

Every entry below is a failure we have actually hit on a real host.

### The play stops during validation

| Message | Cause and fix |
| :--- | :--- |
| `py_phone_caller_config / py_phone_caller_config_secrets are empty` | The converter has not run, or its output is not in `group_vars/app_servers/` **as a directory**. Run `../tools/toml_to_ansible_vars.py` and re-check with `ansible-inventory --host <host>`. |
| `Placeholder credentials are still in place` | `.secrets.toml` still says `change_me` / `super_secure_password`. Set real values, regenerate the vars. |
| `db_host ... is not local, so the role cannot use peer authentication` | Provide `py_phone_caller_db_admin_password`, or set `py_phone_caller_manage_database: false` and provision by hand. |
| `caller_sms_carrier is 'on_premise' but caller_sms.modems is empty` | Add at least one `[[caller_sms.modems]]` with a `port`. |
| `deploy_py-phone-caller supports Debian/Ubuntu and RHEL/Rocky only` | Unsupported `os_family`. Nothing was changed. |

### `Something else already owns the Caddy ports on this host`

The message lists the offending NAT rules or listeners. Another reverse proxy
is in front. Either set `py_phone_caller_manage_caddy: false` and point that
proxy at the UI ([Step 11](#12-step-11--publish-the-web-ui)), or remove it.
`py_phone_caller_caddy_force: true` installs Caddy anyway — it will bind
80/443 and never receive a request.

### `The uv installer reported success but /opt/py-phone-caller/bin/uv is missing`

The installer exited 0 without installing. Check outbound access to
`astral.sh`, then re-run with `--tags install -vvv`. To install by hand:

```bash
sudo -u py-phone-caller env HOME=/opt/py-phone-caller \
  UV_INSTALL_DIR=/opt/py-phone-caller/bin UV_NO_MODIFY_PATH=1 \
  sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
```

### `uv sync` fails building a package

Look for the `hint:` line at the end of the output — uv names the dependency
chain that pulled the package in.

A known one: `curated-tokenizers` 0.0.9 is sdist-only and Cython 3.1 crashes
compiling it on Python 3.14 (`TypeError: 'NoneType' object is unsliceable`).
It arrives via `generate-audio → kokoro → misaki[en] →
spacy-curated-transformers`. The repository's root `pyproject.toml` pins the
build compiler for exactly this reason:

```toml
[tool.uv]
build-constraint-dependencies = ["cython<3.1"]
```

If you hit a similar sdist build failure, add a constraint there and re-run
`uv lock` — build constraints do not change the resolution, so the lock diff
is a single line.

For an air-gapped site, point uv at your mirror:

```yaml
py_phone_caller_uv_extra_index_url: "https://pypi.internal.example.com/simple"
py_phone_caller_uv_insecure_host: "pypi.internal.example.com"   # plain HTTP only
```

### `uv sync` is killed, or the host runs out of disk

The wheel set is ~3 GB and the venv another ~7 GB. Check `df -h /` and
`free -m`. Raise `py_phone_caller_uv_sync_timeout` (default 3600 s) on a slow
link.

### PostgreSQL provisioning fails and the output is hidden

Credentials are passed to the `postgresql_*` modules, so the tasks use
`no_log`. To see the error:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml \
  --tags database -e py_phone_caller_db_no_log=false
```

Common causes: password authentication rejected from loopback (the role sets
`pg_hba` to `md5`, which negotiates SCRAM automatically when the stored
verifier is SCRAM — set `py_phone_caller_pg_hba_method: scram-sha-256` to
require it), or a `postgres` peer login that fails because
`py_phone_caller_pg_unix_socket` needs to be set explicitly.

### A unit restarts in a loop

Check `caller-register` first — everything is ordered after it, and it owns
the migrations:

```bash
journalctl -u py-phone-caller-caller-register -n 100 --no-pager
```

Then confirm the effective configuration is what you think:

```bash
sudo -u py-phone-caller /opt/py-phone-caller/venv/bin/python -c \
  'from py_phone_caller_utils.config import settings; print(settings.database.db_host, settings.queue.queue_url)'
```

Each unit gets `CALLER_CONFIG_DIR=/opt/py-phone-caller/src/config`, so
Dynaconf reads exactly those two TOML files.

### `Rust SMS engine not found` in the caller_sms log

The module did not make it into the service venv. Confirm and rebuild:

```bash
/opt/py-phone-caller/venv/bin/python -c 'import rust_engine'
ansible-playbook deploy_py-phone-caller_stack.yml --tags install
```

The role builds a wheel and installs it explicitly, then asserts the import,
so this should surface as a failed play rather than a runtime log line. Note
that `uv sync` runs with `--inexact` when on-premise SMS is selected — the
engine is compiled locally and is not in `uv.lock`, so an exact sync would
uninstall it on every run.

### ARI returns 401, or `ari show apps` is empty

The ARI user in `ari_py_phone_caller.conf` and
`commons.asterisk_pass` disagree. This happens if you regenerate the
group_vars between the two plays. Re-run the whole stack playbook:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml
```

### The web UI is unreachable

Work outwards:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5000/    # the UI itself
systemctl status caddy                                              # the proxy
curl -skS -o /dev/null -w '%{http_code}\n' https://<domain>/         # by name, not by IP
ufw status verbose            # or: firewall-cmd --list-all
```

`TLSV1_UNRECOGNIZED_NAME` means you connected by IP; Caddy's `tls internal`
needs SNI. Test by name.

### ffmpeg could not be installed (RHEL)

Expected, and not fatal. It only affects the TTS engines that post-process
audio with pydub. Enable RPM Fusion or install `ffmpeg` by hand, then re-run
`--tags prereqs`.

---

## 17. Appendix: what lands where

```
/opt/py-phone-caller/
├── pyproject.toml, uv.lock         uv workspace root
├── src/                            workspace members, installed editable
│   ├── config/
│   │   ├── settings.toml           rendered by Ansible, 0640
│   │   └── .secrets.toml           rendered by Ansible, 0600
│   └── generate_audio/
│       ├── audio/                  generated WAV cache
│       └── pre_trained_models/     downloaded TTS models
├── venv/                           the virtualenv uv builds
├── bin/uv
└── .uv/                            managed interpreters, cache, SMS wheels

/etc/systemd/system/py-phone-caller-*.service    11 units
/etc/asterisk/*_py_phone_caller.conf             4 partial configs, #included
/etc/caddy/Caddyfile                             if Caddy is managed
/var/log/py-phone-caller/                         log directory
```

The repository layout is reproduced verbatim, and `src/` **must** stay a real
directory: `uv sync` installs the workspace members as editable and records
those absolute paths inside the virtualenv. Renaming `src/` or replacing it
with a symlink breaks every import.

### The eleven units

```
py-phone-caller-caller-register              migrations + call registry
py-phone-caller-asterisk-caller              outbound call placement
py-phone-caller-asterisk-recaller            retries and backup callees
py-phone-caller-asterisk-ws-monitor          Stasis/ARI WebSocket events
py-phone-caller-caller-address-book          contacts and on-call solver
py-phone-caller-caller-prometheus-webhook    Alertmanager receiver
py-phone-caller-caller-scheduler             scheduled calls
py-phone-caller-caller-sms                   SMS gateway
py-phone-caller-generate-audio               neural TTS
py-phone-caller-py-phone-caller-ui           web dashboard (gunicorn)
py-phone-caller-celery-worker                background tasks
```

`caller-register` applies the Piccolo migrations at start, so every other unit
carries `After=py-phone-caller-caller-register.service`.

### Full variable reference

[`../on-vm_py-phone-caller/roles/deploy_py-phone-caller/README.md`](../on-vm_py-phone-caller/roles/deploy_py-phone-caller/README.md)

### Related documents

- [`../on-vm_py-phone-caller/README.md`](../on-vm_py-phone-caller/README.md) — services only, without the PBX
- [`../asterisk_py-phone-caller/README.md`](../asterisk_py-phone-caller/README.md) — the PBX on its own
- [`../tools/README.md`](../tools/README.md) — the TOML → Ansible vars converter
- [`../../../docs/OPERATOR_INSTALLATION_GUIDE.md`](../../../docs/OPERATOR_INSTALLATION_GUIDE.md) — the full operator guide, including the container deployment
