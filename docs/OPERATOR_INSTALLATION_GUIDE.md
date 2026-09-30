# 📖 py-phone-caller Operator Installation Guide (A to Z)

Welcome to the comprehensive, step-by-step installation and operations guide for **py-phone-caller**. This document is designed for system administrators, DevOps engineers, and Site Reliability Engineers (SREs) who are deploying **py-phone-caller** for the first time.

Whether you are deploying onto bare-metal servers, virtual machines with native systemd services, or containerized environments using Docker/Podman Compose, this guide walks you through every single step from A to Z.

---

## 📑 Table of Contents

1. [Architectural Overview & The Big Picture](#1-architectural-overview--the-big-picture)
2. [Prerequisites & System Sizing](#2-prerequisites--system-sizing)
3. [Network Topology, Ports & Security](#3-network-topology-ports--security)
4. [Method A: Automated Deployment with Ansible (On-VM / Systemd)](#4-method-a-automated-deployment-with-ansible-on-vm--systemd)
   - [4.1 Choosing an Entry Point](#41-choosing-an-entry-point)
   - [4.2 Preparing the Control Node](#42-preparing-the-control-node)
   - [4.3 SSH Access and Inventory](#43-ssh-access-and-inventory)
   - [4.4 Configuring the Application (`src/config/*.toml`)](#44-configuring-the-application-srcconfigtoml)
   - [4.5 Generating the Ansible Variables](#45-generating-the-ansible-variables)
   - [4.6 Declaring the Deployment Topology](#46-declaring-the-deployment-topology)
   - [4.7 Preflight Checks](#47-preflight-checks)
   - [4.8 Deploying Asterisk PBX](#48-deploying-asterisk-pbx)
   - [4.9 Deploying the py-phone-caller Services](#49-deploying-the-py-phone-caller-services)
   - [4.10 Verifying the Deployment](#410-verifying-the-deployment)
   - [4.11 Publishing the Web UI](#411-publishing-the-web-ui)
   - [4.12 Day-2 Operations and Tags](#412-day-2-operations-and-tags)
5. [Method B: Containerized Deployment with Docker / Podman Compose](#5-method-b-containerized-deployment-with-docker--podman-compose)
   - [5.1 Host Prerequisites & Container Engine](#51-host-prerequisites--container-engine)
   - [5.2 Building or Pulling Container Images](#52-building-or-pulling-container-images)
   - [5.3 Generating Cloud-Native Dynaconf Environment Files](#53-generating-cloud-native-dynaconf-environment-files)
   - [5.4 Starting the Compose Stack](#54-starting-the-compose-stack)
   - [5.5 First-Time Admin Account Bootstrap](#55-first-time-admin-account-bootstrap)
6. [Post-Installation Verification & Smoke Testing](#6-post-installation-verification--smoke-testing)
   - [6.1 Automated Health & Metric Verification Script](#61-automated-health--metric-verification-script)
   - [6.2 Navigating the Web UI](#62-navigating-the-web-ui)
   - [6.3 Configuring On-Call Contacts](#63-configuring-on-call-contacts)
   - [6.4 Triggering Your First Incident Call](#64-triggering-your-first-incident-call)
   - [6.5 Triggering Your First SMS Notification](#65-triggering-your-first-sms-notification)
7. [Monitoring Integrations (Alertmanager, Nagios, Zabbix)](#7-monitoring-integrations-alertmanager-nagios-zabbix)
   - [7.1 Prometheus Alertmanager Webhook](#71-prometheus-alertmanager-webhook)
   - [7.2 Nagios Event Handler Script](#72-nagios-event-handler-script)
   - [7.3 Zabbix Alert Script](#73-zabbix-alert-script)
8. [Air-Gapped & Offline Deployments](#8-air-gapped--offline-deployments)
9. [Troubleshooting & Operational Runbook](#9-troubleshooting--operational-runbook)

---

## 1. Architectural Overview & The Big Picture

**py-phone-caller** is an enterprise-grade automated voice call and SMS incident dispatch platform. It bridges monitoring systems (Prometheus, Nagios, Zabbix, Grafana) with telephony systems (Asterisk PBX, SIP Trunks, GSM modems, Twilio) to reliably alert on-call staff during critical infrastructure outages.

### The 11 Microservices Stack

```text
                                  +-----------------------+
                                  | Prometheus / Nagios / |
                                  | Zabbix Alert Systems  |
                                  +-----------------------+
                                              |
                                              v
                               +-----------------------------+
                               |  caller_prometheus_webhook  |
                               +-----------------------------+
                                     |               |
             +-----------------------+               +-----------------------+
             | (Enqueues Calls)                              | (Dispatches SMS)
             v                                               v
+-------------------------+                       +-------------------------+
|     asterisk_caller     |                       |       caller_sms        |
|  (Manages Call Queue)   |                       | (Twilio / Rust Engine)  |
+-------------------------+                       +-------------------------+
    |                 |                                       |
    | (ARI Outbound)  | (Queries On-Call)                     | (Writes SMS log)
    v                 v                                       v
+--------------+  +---------------------+         +-------------------------+
| Asterisk PBX |  | caller_address_book |         |  PostgreSQL 17 Database |
| (SIP Trunk / |  |   (Contacts Table)  |         | (Calls, Users, Contacts,|
| Stasis App)  |  +---------------------+         |  SMS, Events, Schedules)|
+--------------+              |                   +-------------------------+
    | (WS Events)             |                               ^
    v                         v                               |
+---------------------+   +---------------------+             |
| asterisk_ws_monitor |-->|   caller_register   |-------------+
+---------------------+   | (Central DB Schema) |
    |                     +---------------------+
    | (TTS Audio Req)                 ^
    v                                 |
+---------------------+   +---------------------+   +---------------------+
|   generate_audio    |   |  asterisk_recaller  |   |  caller_scheduler   |
| (Kokoro/MMS/Piper)  |   | (Auto-Retry Engine) |   |   & celery_worker   |
+---------------------+   +---------------------+   +---------------------+
                                                              ^
                                                              |
                                                    +-------------------+
                                                    |  Redis 7 / Valkey |
                                                    +-------------------+
```

### Domain-Driven Data Model
- **`caller_register`**: Central orchestrator for database migrations and schema reconciliation via Piccolo ORM. Manages the `calls`, `scheduled_calls`, and `asterisk_ws_events` tables.
- **`caller_address_book`**: Manages on-call personnel availability, rotations, and phone numbers (`address_book` table).
- **`caller_sms`**: Manages outbound SMS dispatch and message tracking (`sms` table).
- **`py_phone_caller_ui`**: Backend-For-Frontend web console providing real-time call dashboards, DTMF acknowledgment logs, SMS history, and user authentication (`users` table).

---

## 2. Prerequisites & System Sizing

### Minimum System Specifications

| Component | Minimum Spec | Recommended Production Spec |
| :--- | :--- | :--- |
| **CPU** | 2 vCPUs | 4+ vCPUs (faster TTS speech synthesis) |
| **RAM** | 4 GB | 8 GB (TTS ML models require ~1.5 GB in memory) |
| **Disk** | 20 GB SSD | 50 GB SSD (for audio caching and PostgreSQL data) |
| ↳ *native install breakdown* | ~7 GB virtualenv (PyTorch + CUDA wheels), ~3 GB uv download cache, ~1.4 GB Cargo target (on-premise SMS only), ~1 GB TTS models | Plus PostgreSQL data and the generated audio cache |
| **Operating System** | Ubuntu 22.04 / 24.04 / 26.04 LTS<br>Debian 12<br>RHEL / Rocky Linux 9 / 10<br>AlmaLinux 9 / 10 | Ubuntu 24.04 LTS or Rocky Linux 9/10 |

### Software Prerequisites on Target Host

- **For Native Ansible Setup**:
  - **Python 3.14** — the workspace pins `requires-python = ">=3.14, <3.15"`.
    The role passes `--python 3.14` to `uv sync`, so `uv` downloads and manages
    a private interpreter when the distribution does not ship one. No system
    Python 3.14 is required.
  - `rsync` and `sudo` — the role delivers source with
    `ansible.posix.synchronize`, which shells out to rsync over SSH and needs
    sudo to elevate when the connection user is not root.
  - `git`, `curl`, `ca-certificates`.
- **For Containerized Setup**:
  - Docker Engine 24.0+ with Docker Compose v2 (`docker compose`), **OR**
  - Podman 4.5+ with Podman Compose (`podman compose`).
- **Python Workspace Tooling**: `uv`. The Ansible role installs it into
  `/opt/py-phone-caller/bin/uv` itself; you only need it by hand for local
  development.

### Telephony & Infrastructure Requirements
- **Asterisk PBX (v18+ / v20+) / FreePBX**:
  - SIP/PJSIP trunk configured to dial outbound landlines and mobile numbers.
  - ARI enabled (`ari.conf`) with HTTP/WebSocket listeners (default port `8088`), username `py-phone-caller`, and password.
  - Stasis application context registered in `extensions.conf`.
- **PostgreSQL (v15+ / v17+)**: Relational store for calls, schedules, events, users, contacts, and SMS logs (migrations managed by `caller_register`).
- **Redis (v7+) / Valkey**: Celery task queue broker on port `6379`.

### Text-to-Speech (TTS) Requirements: Local vs. Cloud
- **Offline Local Neural TTS (Kokoro-82M, Piper, Facebook MMS)**:
  - **Zero cloud accounts needed.** Runs 100% on CPU locally in air-gapped environments.
  - Requires `ffmpeg` on the host/container and pre-trained model weights in `pre_trained_models/`.
- **Cloud TTS (AWS Polly)**:
  - Requires an active AWS account with IAM credentials (`aws_access_key_id`, `aws_secret_access_key`, `aws_polly_region_name`) and `polly:SynthesizeSpeech` permissions.

### SMS Dispatch Requirements: Hardware USB Modem vs. Cloud
- **On-Premise Hardware Modem (`on_premise`)**:
  - Physical USB GSM / 3G / 4G LTE Modem (e.g. Qualcomm / Option `1e0e:9001`, Huawei, SIMCom using Linux `option` kernel driver).
  - Active SIM card with an SMS texting plan.
  - Access to serial device nodes (`/dev/ttyUSB0`..`/dev/ttyUSB3`) with permissions in the `dialout` group.
- **Cloud SMS (`twilio`)**:
  - Active Twilio account with Account SID (`twilio_account_sid`), Auth Token (`twilio_auth_token`), and sender number (`twilio_sms_from`).
  - Outbound Internet access to `api.twilio.com`. Zero physical hardware required.

---

## 3. Network Topology, Ports & Security

### Port Allocation Chart

> ⚠️ **Read this before you rely on the table below.** In the native systemd
> deployment the aiohttp services bind **`0.0.0.0`** on ports 8081-8087,
> regardless of the `*_host` values in `settings.toml` — those are the
> addresses the services use to reach *each other*, not bind addresses. The
> web UI binds whatever `py_phone_caller_ui.ui_listen_on_host` says (`0.0.0.0`
> by default).
>
> What keeps them private is therefore **the firewall, not the bind address**.
> The Ansible role opens only 80/443 (plus SSH) and leaves everything else
> filtered. If you set `py_phone_caller_manage_firewall: false` without
> another packet filter in front, all seven APIs, the UI, PostgreSQL and Redis
> are reachable from anywhere that can route to the host. On a machine with a
> public address this is not a theoretical concern.
>
> In the container deployment the services are on an internal bridge network
> and only the reverse proxy is published, so the distinction does not arise.

Only the reverse proxy (Caddy/Nginx) and Asterisk PBX are meant to be reachable, and only from your trusted LAN or VPN.

| Port | Protocol | Service | Description |
| :--- | :--- | :--- | :--- |
| **80 / 443** | TCP | Caddy Reverse Proxy | Web UI and API entrypoint |
| **5000** | TCP | `py_phone_caller_ui` | Internal Web Management UI |
| **8081** | TCP | `asterisk_caller` | Call Queue & Outbound Call REST API |
| **8082** | TCP | `generate_audio` | Neural TTS Audio Generation API |
| **8083** | TCP | `caller_register` | Call Registry & DB Migration Controller |
| **8084** | TCP | `caller_prometheus_webhook` | Prometheus Alertmanager Receiver |
| **8085** | TCP | `caller_sms` | SMS Dispatcher (Twilio / GSM Modem) |
| **8086** | TCP | `caller_scheduler` | Celery Scheduled Call Coordinator |
| **8087** | TCP | `caller_address_book` | Contact Directory & On-Call Solver API |
| **5432** | TCP | PostgreSQL 17 | Relational Database |
| **6379** | TCP | Redis 7 / Valkey | Task Queue Broker |
| **8088** | TCP / WS | Asterisk PBX | Asterisk REST Interface (ARI) & Stasis WS |
| **5060 / 5160**| UDP/TCP | Asterisk PBX | SIP Signaling (PJSIP / chan_sip) |
| **10000-20000**| UDP | Asterisk PBX | RTP Audio Stream Range |

> 🔒 **Security Notice**: Never expose py-phone-caller REST APIs directly to the public Internet without an authentication gateway (such as Caddy, Nginx with mTLS/Basic Auth, or Apache APISIX). Always deploy within a private management VLAN or VPN.

---

## 4. Method A: Automated Deployment with Ansible (On-VM / Systemd)

The Ansible automation under `assets/ansible/` takes a freshly provisioned VM
to a working platform: PostgreSQL, Redis/Valkey, Asterisk with ARI, and the
eleven Python services as systemd units behind a reverse proxy.

Budget roughly **45 minutes**, most of it waiting for `uv sync` to download
~3 GB of PyTorch and CUDA wheels. Follow 4.1 through 4.11 in order.

> `openalertd` (`src/openalert/`) is a separate Rust daemon with its own
> packaging under `src/openalert/packaging/`. It is **not** deployed by these
> playbooks.

---

> ### ℹ️ Verification status of this section
>
> Method A was executed end to end against a real host — Ubuntu 26.04,
> all-in-one, on-premise SMS, behind an existing Nginx Proxy Manager. Verified:
> §4.3-§4.10 including an idempotent `changed=0` re-run, every tag in
> isolation, PostgreSQL over the unix socket, the migrations creating all 7
> tables, ARI authentication and Stasis registration, the native SMS engine
> running with 2 modems, and every service port closed from the internet.
>
> **Not executed, so verify for yourself:** Caddy actually serving traffic (it
> was NAT-diverted on the test host by the existing proxy); RHEL/Rocky/Alma;
> Let's Encrypt; a database on another host; `py_phone_caller_git_repo` clone
> mode; Twilio as the carrier; a real outbound call or SMS (no working SIP
> trunk on the test host); and `py_phone_caller_remove_build_deps`.
>
> The step-by-step runbook with expected output at every step is
> [`assets/ansible/deploy_all/README.md`](../assets/ansible/deploy_all/README.md).

### 4.1 Choosing an Entry Point

| Directory | Deploys | Use when |
| :--- | :--- | :--- |
| `assets/ansible/deploy_all/` | Asterisk **and** the services | The PBX shares the machine (most common) |
| `assets/ansible/on-vm_py-phone-caller/` | The services only | Asterisk is a separate host or already managed |
| `assets/ansible/asterisk_py-phone-caller/` | Asterisk only | You are building the PBX first, or separately |

All three share one inventory (`on-vm_py-phone-caller/inventory`) and one set
of `group_vars`, so the steps below apply to any of them. Commands are shown
from `deploy_all`.

**Both plays read the same configuration.** The Asterisk play derives its
settings from the application configuration rather than repeating them, so the
two halves cannot drift out of sync:

| Asterisk role variable | Derived from `settings.toml` |
| :--- | :--- |
| `ari_username` | `commons.asterisk_user` |
| `ari_password` | `commons.asterisk_pass` (from `.secrets.toml`) |
| `ari_app_name` | `asterisk_ws_monitor.asterisk_stasis_app` |
| `asterisk_http_bindport` | `commons.asterisk_web_port` |
| `asterisk_context` | `asterisk_call.asterisk_context` |
| `asterisk_extension` | `asterisk_call.asterisk_extension` |
| `callback_service_url` | `call_register.call_register_http_scheme` + `_port` |

Only the SIP trunk has no counterpart in `settings.toml` (see 4.8).

---

### 4.2 Preparing the Control Node

The control node is wherever you run `ansible-playbook` — your workstation or
a CI runner. It does **not** have to be the target.

| Requirement | Why | Verify with |
| :--- | :--- | :--- |
| `ansible-core` ≥ 2.15 | `apply:` on task includes, `timeout:` task keyword | `ansible --version` |
| `rsync` | source delivery uses `ansible.posix.synchronize` | `command -v rsync` |
| Python ≥ 3.11 | `tomllib`, for the configuration converter | `python3 -V` |
| `git` + a checkout | rsync ships *this working tree*, not a git tag | `ls pyproject.toml uv.lock` |

```bash
git clone https://github.com/jcfdeb/py-phone-caller.git
cd py-phone-caller/assets/ansible/deploy_all

ansible-galaxy collection install -r requirements.yml
ansible-galaxy collection list | grep -E 'ansible.posix|community.general|community.postgresql'
```

Expected — at or above these versions:

```
ansible.posix             2.2.2
community.general         13.3.0
community.postgresql      4.2.0
```

| Collection | Needed for |
| :--- | :--- |
| `ansible.posix` | `synchronize`, `firewalld` |
| `community.general` | `ufw`, `ini_file` (Asterisk `http.conf` / `ari.conf`) |
| `community.postgresql` | role, database, grants, extensions, `pg_hba` |

> **Run `ansible-playbook` from inside the chosen directory.** Ansible reads
> `ansible.cfg` only from the current working directory, and that file sets the
> inventory, both role paths, privilege escalation and SSH multiplexing.

#### Target host requirements

| Requirement | Notes |
| :--- | :--- |
| Ubuntu 22.04+ / Debian 12+ / RHEL, Rocky, Alma 9+ | Verified on Ubuntu 26.04 with system Python 3.14.4 |
| 4 GB RAM | PyTorch and the TTS models are the constraint; 2 GB is the floor |
| **15 GB free disk** | ~7 GB venv, ~1.4 GB Cargo target, ~1 GB TTS models, plus the uv cache |
| 2+ vCPU (4 recommended) | TTS synthesis is CPU-bound |
| `rsync` and `sudo` installed | `synchronize` shells out to rsync over SSH |
| SSH as `root`, **or** passwordless sudo | Without `NOPASSWD`, rsync cannot elevate |
| Outbound HTTPS | PyPI, `astral.sh` (uv), Hugging Face (TTS models), Cloudsmith (Caddy) |

---

### 4.3 SSH Access and Inventory

The playbooks never prompt for a password, so key-based access must work
first.

```bash
ssh-copy-id root@<target-ip>
ssh -o BatchMode=yes root@<target-ip> 'echo ok; id'
```

A `~/.ssh/config` entry keeps a non-standard port out of the inventory:

```sshconfig
Host alert-node-01
    HostName 10.0.55.251
    User root
    Port 22
    IdentityFile ~/.ssh/id_ed25519
```

Connecting as a non-root user? Both of these must succeed:

```bash
ssh <user>@<target> 'sudo -n true && echo "passwordless sudo OK"'
ssh <user>@<target> 'sudo -n rsync --version | head -1'
```

Now edit `../on-vm_py-phone-caller/inventory`:

```ini
[app_servers]
alert-node-01 ansible_host=alert-node-01 ansible_user=root

[app_servers:vars]
ansible_python_interpreter=/usr/bin/python3
ansible_ssh_extra_args='-o StrictHostKeyChecking=no'
```

- The group **must** be `app_servers` — both plays target it, and the
  generated variables live in `group_vars/app_servers/`.
- Do **not** add `ansible_become` here; escalation lives in `ansible.cfg`.

Confirm connectivity and platform detection:

```bash
ansible app_servers -m ping
ansible app_servers -m setup -a 'filter=ansible_distribution*,ansible_os_family' \
  | grep -E 'distribution"|distribution_major|os_family'
```

```
alert-node-01 | SUCCESS => { "ping": "pong" }
        "ansible_distribution": "Ubuntu",
        "ansible_distribution_major_version": "26",
        "ansible_os_family": "Debian",
```

An `os_family` other than `Debian` or `RedHat` stops the role on its first
task, changing nothing.

---

### 4.4 Configuring the Application (`src/config/*.toml`)

`src/config/settings.toml` and `src/config/.secrets.toml` are the **single
source of truth** for the whole platform — the same files drive local
development, the container images and this deployment. Edit them, never the
Ansible variables directly.

#### The settings that matter first

```toml
[commons]
asterisk_user = "py-phone-caller"       # becomes the ARI user in ari.conf
asterisk_host = "pbx.lan"               # where the services reach Asterisk
asterisk_web_port = "8088"              # ARI HTTP port

[asterisk_call]
asterisk_context = "py-phone-caller"    # dialplan context created for you
asterisk_extension = "3216"             # extension entering the Stasis app
asterisk_chan_type = "PJSIP/py-phone-caller"
asterisk_caller_id = "Py-Phone-Caller"

[generate_audio]
tts_engine = "kokoro_tts"               # kokoro_tts | piper_tts | facebook_mms | google_gtts | aws_polly
num_of_cpus = 2

[caller_sms]
caller_sms_carrier = "twilio"           # "twilio" or "on_premise"
twilio_sms_from = "+15551234567"

[database]
db_host = "postgresql.lan"
db_name = "py_phone_caller"
db_user = "py_phone_caller"

[queue]
queue_host = "redis.lan"
queue_url = "redis://redis.lan:6379/7"

[py_phone_caller_ui]
ui_listen_on_host = "0.0.0.0"
ui_listen_on_port = 5000
ui_admin_user = "admin@example.com"     # the first admin account's e-mail
min_password_length = 17
```

Decisions worth understanding:

- **`asterisk_chan_type`** decides how calls leave the PBX.
  `PJSIP/py-phone-caller` dials through the trunk endpoint the Asterisk role
  creates. `Local/{phone}@py-phone-caller` routes back through the dialplan —
  what you want with local handsets or a GSM gateway.
- **`tts_engine`** — `kokoro_tts` is the best offline default. Every local
  engine needs `ffmpeg`, which the role installs.
- **`caller_sms_carrier = "on_premise"`** triggers extra work: the role
  installs the Rust toolchain, compiles the native modem engine, installs it
  into the service virtualenv, verifies it imports, and adds the service
  account to the `dialout` group. It **requires** at least one modem:

  ```toml
  [[caller_sms.modems]]
  id = "primary_carrier"
  port = "/dev/ttyUSB2"
  baud_rate = 115200
  priority = 1
  ```

  > Pin stable device names with `udev` rules (e.g. `/dev/modem_primary`).
  > `/dev/ttyUSB*` numbering changes across reboots.

- **`db_host` / `queue_host`** — leave the names your container stack uses.
  Section 4.6 redirects them per host, so one `settings.toml` serves every
  environment.

#### Credentials

```toml
# src/config/.secrets.toml
[commons]
asterisk_pass = "<ARI password>"        # ARI is HTTP Basic; make it strong
asterisk_ami_secret = "<AMI secret>"

[caller_sms]
twilio_account_sid = "AC..."
twilio_auth_token = "..."

[database]
db_password = "<PostgreSQL password>"

[py_phone_caller_ui]
ui_secret_key = "<Flask secret>"
```

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
uuidgen
```

The role **refuses to deploy** while `db_password`, `ui_secret_key` or
`asterisk_pass` still read `change_me` or `super_secure_password`.

> ⚠️ `src/config/.secrets.toml` is tracked in git with placeholder values.
> Keep your real credentials in the working tree only, and check
> `git status --porcelain src/config/` before committing.

---

### 4.5 Generating the Ansible Variables

```bash
../tools/toml_to_ansible_vars.py
```

```
Wrote .../group_vars/app_servers/config.yml
Wrote .../group_vars/app_servers/secrets.yml (0600, encrypt it with ansible-vault)
```

| File | Variable | Mode |
| :--- | :--- | :--- |
| `group_vars/app_servers/config.yml` | `py_phone_caller_config` | `0644` |
| `group_vars/app_servers/secrets.yml` | `py_phone_caller_config_secrets` | `0600` |

Both are git-ignored: they mirror your live configuration, credentials and
phone numbers included. Committed samples live in
`assets/ansible/on-vm_py-phone-caller/examples/`.

> **`group_vars/app_servers/` must remain a directory.** Ansible reads every
> file inside a `group_vars/<group>/` directory, but auto-loads a *plain* file
> only when its stem is exactly the group name. A file named
> `group_vars/app_servers.secrets.yml` is skipped **with no warning**, and the
> play then fails much later on an undefined variable. Both playbooks assert
> that the variables actually arrived, so the error is explicit.

Verify what Ansible really loaded:

```bash
ansible-inventory --host alert-node-01 | python3 -c "
import json,sys
d=json.load(sys.stdin)
for k in ('py_phone_caller_config','py_phone_caller_config_secrets','py_phone_caller_config_overrides'):
    v=d.get(k); print(f'{k}: ' + ('MISSING' if v is None else f'{len(v)} sections'))"
```

```
py_phone_caller_config: 14 sections
py_phone_caller_config_secrets: 4 sections
py_phone_caller_config_overrides: 3 sections
```

#### Encrypting the secrets

```bash
ansible-vault encrypt ../on-vm_py-phone-caller/group_vars/app_servers/secrets.yml
ansible-playbook deploy_py-phone-caller_stack.yml --ask-vault-pass
```

Re-running the converter refuses to overwrite an encrypted file — decrypt it
first, or write the fresh copy elsewhere with `--secrets-output`.

---

### 4.6 Declaring the Deployment Topology

`assets/ansible/on-vm_py-phone-caller/group_vars/all.yml` holds everything
that describes *this host* rather than the application. It is committed, and
it is merged **last**, so regenerating the files from 4.5 never clobbers it.

The four layers, later winning:

```
roles/deploy_py-phone-caller/defaults/main.yml   py_phone_caller_config_defaults
group_vars/app_servers/config.yml                py_phone_caller_config
group_vars/app_servers/secrets.yml               py_phone_caller_config_secrets
group_vars/all.yml                               py_phone_caller_config_overrides
```

#### All-in-one host

```yaml
py_phone_caller_config_overrides:
  commons:
    asterisk_host: "127.0.0.1"
  database:
    db_host: "127.0.0.1"
  queue:
    queue_host: "127.0.0.1"
    queue_url: "redis://127.0.0.1:6379/7"

py_phone_caller_hosts_entries:
  - address: "127.0.0.1"
    names:
      - "{{ caddy_domain_name }}"
      - pbx.lan
      - postgresql.lan
      - redis.lan
```

Pointing `database.db_host` at loopback is what makes provisioning painless:
the role installs PostgreSQL locally and creates the role, database, grants
and extensions over the **unix socket** as the `postgres` system user, with no
admin password.

#### Database or queue elsewhere

```yaml
py_phone_caller_config_overrides:
  database:
    db_host: "postgres.internal.example.com"

py_phone_caller_db_admin_user: "postgres"
py_phone_caller_db_admin_password: "{{ vault_pg_admin_password }}"
py_phone_caller_manage_queue: false
```

A non-local `db_host` can only be reached over TCP, so
`py_phone_caller_db_admin_password` becomes **mandatory** — the play stops
during validation and says so. Or set
`py_phone_caller_manage_database: false` and provision it yourself:

```sql
CREATE ROLE py_phone_caller LOGIN PASSWORD '...' NOSUPERUSER NOCREATEDB;
CREATE DATABASE py_phone_caller OWNER py_phone_caller ENCODING 'UTF8';
\c py_phone_caller
GRANT ALL ON SCHEMA public TO py_phone_caller;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

The `GRANT ALL ON SCHEMA public` is not optional: PostgreSQL 15 revoked
`CREATE` on `public` from `PUBLIC`, and the Piccolo migrations need it.

#### Reverse proxy

```yaml
caddy_domain_name: "alerts.example.com"
caddy_email: "ops@example.com"      # required for Let's Encrypt
```

A name ending in `.lan`, `.local`, `.internal` or `.test` automatically uses
Caddy's internal CA. Anything else goes to Let's Encrypt, which needs
`caddy_email` and ports 80/443 reachable from the internet.

**If the host already runs a reverse proxy**, disable Caddy:

```yaml
py_phone_caller_manage_caddy: false
```

The role detects this and refuses to install a second proxy, because the
failure is otherwise invisible: Caddy binds 80/443, starts cleanly and never
receives a packet, since the incumbent's NAT `REDIRECT` rules divert them
first — loopback included. The only symptom is a TLS handshake error. Section
4.11 covers wiring an existing proxy. `py_phone_caller_caddy_force: true`
overrides the check.

---

### 4.7 Preflight Checks

Three checks that change nothing.

**1. Render the configuration locally.** Merges all four layers, renders every
template, and diffs the resulting TOML against the merged configuration key by
key:

```bash
cd ../on-vm_py-phone-caller
ansible-playbook -i localhost, -c local render_check.yml
cd ../deploy_all
```

```
"toml: 14 sections, 124 keys match",
"local postgres: True",
"db host: 127.0.0.1",
"queue: redis://127.0.0.1:6379/7",
"units: 11"
```

The rendered `settings.toml`, `.secrets.toml`, `Caddyfile` and eleven unit
files are left in `/tmp/py-phone-caller-render` for inspection.

**2. Syntax check:**

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

You want ≥ 15 GB available, all four binaries present, and 200/301 from both
URLs.

---

### 4.8 Deploying Asterisk PBX

#### SIP trunk variables

These have no counterpart in `settings.toml`. Add them to
`../on-vm_py-phone-caller/group_vars/all.yml`, or to a vaulted file:

```yaml
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

Left unset they default to `CHANGE_ME`, and Asterisk installs with a trunk
that cannot register. ARI, the dialplan and the Stasis app still work — the
services come up healthy, you simply cannot place outbound calls yet.

With a **GSM gateway** on the LAN instead of a cloud trunk, point
`pbx_sip_provider_host` at the gateway and set
`caller_sms.caller_sms_carrier = "on_premise"`.

#### For a PBX on its own host

```bash
cd ../asterisk_py-phone-caller
ansible-playbook -i ../on-vm_py-phone-caller/inventory deploy_asterisk.yml
```

#### What the play does

1. Installs `asterisk`, `asterisk-dev`, `asterisk-modules`,
   `asterisk-core-sounds-en`.
2. Creates the `asterisk` user and its data, cache and sounds directories.
3. Installs the alert prompts (`greeting-message.wav`,
   `press-4-for-acknowledgement.wav`).
4. Writes four **partial** configs — `extensions_py_phone_caller.conf`,
   `pjsip_py_phone_caller.conf`, `ari_py_phone_caller.conf`,
   `iax_py_phone_caller.conf` — and `#include`s them from the stock files, so
   an existing Asterisk configuration is left intact.
5. Disables `chan_sip` to free port 5060 for PJSIP.
6. Enables ARI on `commons.asterisk_web_port` with `enabled=yes` in
   `http.conf`.
7. Starts and enables the `asterisk` service.

When the PBX shares the host with the services, do not run this separately —
use `deploy_all` (4.9), which runs both plays from one configuration.

---

### 4.9 Deploying the py-phone-caller Services

```bash
cd ../deploy_all
ansible-playbook deploy_py-phone-caller_stack.yml 2>&1 | tee /tmp/ppc-deploy.log
```

Services only, with Asterisk elsewhere:

```bash
cd ../on-vm_py-phone-caller
ansible-playbook deploy_py-phone-caller.yml
```

#### Phases, in order

| Phase | Tag | What it does |
| :--- | :--- | :--- |
| Validate | `always` | Six assertions: every config section present, database settings set, no placeholder credentials, remote DB has an admin password, on-premise SMS declares modems, `/etc/hosts` entries well formed |
| Prerequisites | `prereqs` | `/etc/hosts` block, OS packages, EPEL/CRB on RHEL, ffmpeg, Redis or Valkey, PostgreSQL server, Rust toolchain when on-premise SMS is selected |
| Service account | `user` | `py-phone-caller` system user, `nologin` shell, home `/opt/py-phone-caller`; joins `dialout` for on-premise SMS |
| Source | `source` | rsync of the repository preserving its layout; `--delete` is protected against removing the venv, TTS models, rendered config and Cargo target |
| Python env | `install` | Installs `uv`, **verifies it landed**, `uv sync --frozen --all-packages --no-dev`, builds and installs the native SMS engine, **verifies it imports** |
| Database | `database` | `pg_hba` for loopback passwords, role, database, `ALL` on schema `public`, `uuid-ossp` + `pgcrypto` |
| Configuration | `config` | Renders `settings.toml` (0640) and `.secrets.toml` (0600), each validated with `tomllib` **before** being moved into place |
| Reverse proxy | `caddy` | Conflict check, then install and configure Caddy (skipped when disabled) |
| Firewall | `firewall` | firewalld or ufw: SSH plus 80/443 |
| systemd | `systemd` | Eleven units, every one ordered after `caller-register`; units dropped from the list are stopped, disabled and removed |
| Cleanup | `cleanup` | Opt-in removal of the build toolchain |

The long step is `uv sync`: roughly 3 GB of wheels (`torch` 502 MB,
`nvidia-cublas` 403 MB, `nvidia-cudnn` 349 MB, `triton` 189 MB and ~40 more),
10-30 minutes depending on the link.

#### Expected result

```
PLAY RECAP *********************************************************************
alert-node-01 : ok=86  changed=NN  unreachable=0  failed=0  skipped=26
```

`failed=0` is the thing to look for. **A re-run reports `changed=0`** — the
role is idempotent and safe to run repeatedly.

If a task fails, the play stops there and nothing after it is applied; a
re-run converges. Section 9 lists every failure mode with its exact error
text.

---

### 4.10 Verifying the Deployment

```bash
ansible-playbook -i ../on-vm_py-phone-caller/inventory \
                 ../on-vm_py-phone-caller/verify.yml
```

Checks that every installed unit is `active`, probes all seven `/health`
endpoints with retries, and fetches the web UI:

```
"units active: 11",
"health endpoints OK: 7",
"web UI direct: HTTP 200",
"web UI via Caddy: HTTP 200"
```

#### Manual checks worth doing once

**Units and restart counts** — a non-zero `NRestarts` means a crash loop:

```bash
for u in $(systemctl list-unit-files 'py-phone-caller-*.service' --no-legend | awk '{print $1}' | sort); do
  printf '%-50s %-8s restarts=%s\n' "$u" "$(systemctl is-active $u)" "$(systemctl show -p NRestarts --value $u)"
done
```

**Database schema**, created by `caller_register` on first start:

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

JSON means ARI is up and the password matches. `401` means the two halves
disagree — re-run the whole stack playbook rather than one play.

**Stasis registration**, which proves `asterisk_ws_monitor` is connected:

```bash
asterisk -rx 'ari show apps'          # must list your asterisk_stasis_app
asterisk -rx 'dialplan show py-phone-caller'
asterisk -rx 'pjsip show registrations'
```

**On-premise SMS engine**, if selected:

```bash
/opt/py-phone-caller/venv/bin/python -c 'import rust_engine; print(rust_engine.__file__)'
journalctl -u py-phone-caller-caller-sms | grep -i rust
```

You want `Rust SMS engine started successfully` plus a line naming your modem
count and strategy.

**Confirm nothing is exposed.** From another machine:

```bash
for p in 5000 8081 8083 8085 8087 8088 5432 6379; do
  timeout 5 bash -c "</dev/tcp/<target-ip>/$p" 2>/dev/null && echo "$p OPEN <-- FIX" || echo "$p closed"
done
# Positive control: your SSH port MUST show OPEN or the test proves nothing
timeout 5 bash -c "</dev/tcp/<target-ip>/22" && echo "22 OPEN (control)"
```

Without the positive control the result is meaningless — a network that
blocks everything looks exactly like a working firewall.

#### First admin login

The UI creates its admin account on first start and writes a generated
password to the journal:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml \
  -e py_phone_caller_ui_reset_password=true --tags systemd,config

ssh alert-node-01 'journalctl -u py-phone-caller-py-phone-caller-ui -n 80 --no-pager' | grep -iA3 password
```

Log in as `py_phone_caller_ui.ui_admin_user`, change the password immediately
(`min_password_length` defaults to 17), then set
`py_phone_caller_ui_reset_password: false` and re-run — otherwise it is
regenerated on every restart.

---

### 4.11 Publishing the Web UI

#### With Caddy (the role's default)

Already done: Caddy terminates TLS on 443 and proxies to the UI. Browse to
`https://<caddy_domain_name>/`.

For a `.lan`-style name the host must resolve it — the
`py_phone_caller_hosts_entries` block from 4.6 handles the target itself, and
you want the same entry in your workstation's `/etc/hosts` or LAN DNS.

> Caddy's `tls internal` requires SNI, so `curl -k https://127.0.0.1/` with a
> `Host:` header fails with `TLSV1_UNRECOGNIZED_NAME`. Always test by name.

To trust the internal CA:

```bash
# Ask the host where Caddy keeps its CA; the path depends on XDG_DATA_HOME.
ssh alert-node-01 'find /var/lib/caddy -name root.crt -path "*authorities/local*" 2>/dev/null'
# typically: /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt

scp alert-node-01:<that-path> ppc-root.crt
sudo cp ppc-root.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates   # Debian/Ubuntu
sudo cp ppc-root.crt /etc/pki/ca-trust/source/anchors/ && sudo update-ca-trust          # RHEL/Rocky
```

#### With an existing reverse proxy

Set `py_phone_caller_manage_caddy: false` and point your proxy at
`http://<host>:5000`.

**Nginx Proxy Manager (rootless Podman)** — add a Proxy Host:

| Field | Value |
| :--- | :--- |
| Domain Names | `alerts.example.com` |
| Scheme | `http` |
| Forward Hostname / IP | `host.containers.internal` |
| Forward Port | `5000` |
| Websockets Support | **on** (the UI streams live call events) |

`host.containers.internal` resolves to `169.254.1.2` inside rootless Podman
and reaches the host with no firewall change. `127.0.0.1` does **not** work
from a container's network namespace, and the bridge or public addresses are
blocked by ufw. Verify before blaming the proxy:

```bash
podman exec <npm-container> curl -s -o /dev/null -w '%{http_code}\n' \
  http://host.containers.internal:5000/
```

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

Keep `py_phone_caller_manage_firewall: true` either way — see the warning in
section 3.

---

### 4.12 Day-2 Operations and Tags

#### Push a configuration change

```bash
vim src/config/settings.toml
assets/ansible/tools/toml_to_ansible_vars.py
cd assets/ansible/deploy_all
ansible-playbook deploy_py-phone-caller_stack.yml --tags config
```

Re-renders both TOML files and restarts the services through a handler.
Nothing else is touched.

#### Deploy new code

```bash
git pull
ansible-playbook deploy_py-phone-caller_stack.yml --tags source,install,systemd
```

#### Tags

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

Every tag is independently idempotent and reports `changed=0` on a converged
host.

#### Reclaim disk

```yaml
py_phone_caller_remove_build_deps: true
```

Removes the compilers and the uv download cache. Off by default: the next
dependency bump then needs `--tags prereqs` first, and package-manager
`autoremove` tends to take shared libraries with it.

#### Service control and backups

```bash
systemctl restart 'py-phone-caller-*'
journalctl -u 'py-phone-caller-*' -f --no-pager

sudo -u postgres pg_dump py_phone_caller | gzip > ppc-$(date +%F).sql.gz
tar -czf ppc-config-$(date +%F).tar.gz /opt/py-phone-caller/src/config /etc/asterisk
```

#### What lands where

```
/opt/py-phone-caller/
├── pyproject.toml, uv.lock         uv workspace root
├── src/                            workspace members, installed editable
│   ├── config/                     settings.toml (0640), .secrets.toml (0600)
│   └── generate_audio/             audio/ and pre_trained_models/
├── venv/                           the virtualenv uv builds
├── bin/uv
└── .uv/                            managed interpreters, cache, SMS wheels

/etc/systemd/system/py-phone-caller-*.service    11 units
/etc/asterisk/*_py_phone_caller.conf             4 partial configs, #included
/etc/caddy/Caddyfile                             when Caddy is managed
/var/log/py-phone-caller/
```

> ⚠️ The repository layout is reproduced verbatim and `src/` **must** stay a
> real directory. `uv sync` installs the workspace members as editable and
> records those absolute paths inside the virtualenv, so renaming `src/` or
> replacing it with a symlink breaks every import.

Each unit receives
`CALLER_CONFIG_DIR=/opt/py-phone-caller/src/config`, so Dynaconf reads exactly
those two TOML files — no guessing from `__file__` or the working directory.

The complete variable reference lives in
[`assets/ansible/on-vm_py-phone-caller/roles/deploy_py-phone-caller/README.md`](../assets/ansible/on-vm_py-phone-caller/roles/deploy_py-phone-caller/README.md),
and the step-by-step runbook in
[`assets/ansible/deploy_all/README.md`](../assets/ansible/deploy_all/README.md).

---

## 5. Method B: Containerized Deployment with Docker / Podman Compose

The containerized deployment packages the complete stack into 14 containers (11 microservices + PostgreSQL + Redis + Caddy) with isolated networks and healthchecks.

### 5.1 Host Prerequisites & Container Engine

Ensure either Docker with Compose v2 or Podman with Podman Compose is installed:

**On Ubuntu / Debian:**
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
```

**On Rocky Linux / AlmaLinux / RHEL:**
```bash
sudo dnf install -y podman podman-docker podman-compose
```

---

### 5.2 Building or Pulling Container Images

#### Option 1: Build Local Images from Source
From the root of the repository, execute the universal build script:

```bash
./src/build_all_images.sh
```

To customize the container engine, registry name, or image tag:
```bash
CONTAINER_ENGINE=podman IMAGE_REGISTRY=localhost IMAGE_TAG=1.0.0 ./src/build_all_images.sh
```

#### Option 2: Using Pre-Built Images from Local / Air-Gapped Registry
If images are hosted on an internal registry (e.g. `artifacts.py-phone-caller.lan:5000`), export the registry prefix:
```bash
export MY_DOCKER_REGISTRY="artifacts.py-phone-caller.lan:5000"
export VERSION="1.0.0"
```

---

### 5.3 Generating Cloud-Native Dynaconf Environment Files

`py-phone-caller` utilizes cloud-native environment variable injection. Configurations are generated from `settings.toml` and `.secrets.toml` into clean `.env` files:

```bash
# Create the environment directory
mkdir -p assets/docker-compose/env

# Convert base settings
uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --input src/config/settings.toml \
  --output assets/docker-compose/env/py-phone-caller.env

# Convert secrets (if present)
uv run python assets/scripts/config/toml_to_dynaconf_env.py \
  --ignore-missing \
  --input src/config/.secrets.toml \
  --output assets/docker-compose/env/py-phone-caller.secrets.env
```

If Asterisk is running on the host machine outside containers, ensure `settings.toml` or your environment overrides Asterisk host:
```bash
export ASTERISK_HOST="host.containers.internal" # For Docker/Podman host communication
```

---

### 5.4 Starting the Compose Stack

Navigate to `assets/docker-compose/` and start the stack in detached mode:

```bash
cd assets/docker-compose
docker compose up -d
```
*(Or `podman compose up -d`)*

Verify all containers reach healthy status:
```bash
docker compose ps
```

Expected output:
```text
NAME                                IMAGE                            STATUS
py-phone-caller-db                  postgres:17-alpine               Up (healthy)
py-phone-caller-redis               redis:7-alpine                   Up (healthy)
caller-register                     localhost/caller_register:1.0.0  Up (healthy)
asterisk-caller                     localhost/asterisk_caller:1.0.0  Up (healthy)
asterisk-ws-monitor                 localhost/asterisk_ws_monitor    Up (healthy)
asterisk-recaller                   localhost/asterisk_recaller      Up (healthy)
caller-address-book                 localhost/caller_address_book    Up (healthy)
caller-scheduler                    localhost/caller_scheduler       Up (healthy)
caller-prometheus-webhook           localhost/caller_prometheus_...  Up (healthy)
caller-sms                          localhost/caller_sms:1.0.0       Up (healthy)
generate-audio                      localhost/generate_audio:1.0.0   Up (healthy)
py-phone-caller-ui                  localhost/py_phone_caller_ui     Up (healthy)
celery-worker                       localhost/celery_worker:1.0.0    Up (healthy)
caddy                               caddy:2-alpine                   Up
```

---

### 5.5 First-Time Admin Account Bootstrap

On a fresh installation, create the default administrator user for the Web UI:

1. Launch with the admin bootstrap flag:
   ```bash
   UI_USER_RESET_PASSWORD=true docker compose up -d py_phone_caller_ui
   ```

2. Inspect the UI container log to retrieve the randomly generated temporary admin password:
   ```bash
   docker compose logs py_phone_caller_ui | grep "Admin user created"
   ```

3. Log in at `http://<server-ip>:5000` with:
   - **Username**: `admin@py-phone-caller.link`
   - **Password**: *(The generated password from logs)*

4. Change the admin password in the Web UI, then remove the environment override:
   ```bash
   UI_USER_RESET_PASSWORD=false docker compose up -d py_phone_caller_ui
   ```

---

## 6. Post-Installation Verification & Smoke Testing

### 6.1 Automated Health & Metric Verification Script

The repository includes a comprehensive verification test suite (`verify_deployment.py`) that probes all microservices for `/health` JSON responses, Prometheus `/metrics` scraping, and dynamic TTS audio generation:

From your workstation or control node:
```bash
VERIFY_HOST="10.0.55.251" uv run python verify_deployment.py
```

Expected output:
```text
======================================================================
🔎 Starting py-phone-caller deployment verification on 10.0.55.251
======================================================================

Checking asterisk_caller (port 8081)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'asterisk_caller', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2482 bytes)

Checking generate_audio (port 8082)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'generate_audio', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2410 bytes)

Checking caller_register (port 8083)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_register', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2515 bytes)

Checking caller_prometheus_webhook (port 8084)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_prometheus_webhook', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2390 bytes)

Checking caller_sms (port 8085)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_sms', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2412 bytes)

Checking caller_scheduler (port 8086)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_scheduler', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2405 bytes)

Checking caller_address_book (port 8087)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'caller_address_book', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2520 bytes)

Checking py_phone_caller_ui (port 5000)...
  ✓ /health endpoint OK (Status: 200) -> {'service': 'py_phone_caller_ui', 'status': 'healthy'}
  ✓ /metrics endpoint OK (Status: 200, 2150 bytes)

Testing Audio Generation & Polling Flow...
  ✓ Audio generation request initiated (POST /make_audio) -> Checksum: 5b9a5cfb
  ✓ Audio file generation confirmed ready (GET /is_audio_ready)

======================================================================
🎉 ALL CHECKS PASSED: py-phone-caller deployment is 100% operational!
======================================================================
```

---

### 6.2 Navigating the Web UI

Access the Web console at `http://<server-ip>:5000` (or `https://py-phone-caller.lan` if using Caddy):

- **Dashboard**: Real-time view of call queue status, total calls placed, successful DTMF acknowledgments, and pending retries.
- **Call History**: Searchable, paginated audit log of every call attempt, duration, Asterisk channel ID, heard status, and acknowledged status.
- **Address Book**: Manage on-call engineers, phone numbers, backup escalation targets, and weekly schedule matrices.
- **Managed SMS**: Filter, inspect, and export all outbound SMS logs and carrier delivery receipts.
- **WebSocket Events**: Live Asterisk Stasis event log stream.
- **Scheduled Calls**: Review and manage future scheduled automated calls.

---

### 6.3 Configuring On-Call Contacts

Before placing alerts with `phone=oncall`, you must create at least one enabled contact in the Address Book:

1. In the Web UI, click **Address Book** -> **+ Add Contact**.
2. Fill in:
   - **Name**: `Primary On-Call Engineer`
   - **Phone Number**: `+393341234567` (Use E.164 international format)
   - **Enabled**: `Checked`
   - **On-Call Availability**: Set days and hours (or check 24/7 coverage).
3. Click **Save Contact**.

Alternatively, insert a contact via the REST API:
```bash
curl -X POST "http://10.0.55.251:8087/contact" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Alex",
    "surname": "Admin",
    "phone_number": "+393341234567",
    "enabled": true,
    "on_call_availability": {
      "monday": {"start": "00:00", "end": "23:59"},
      "tuesday": {"start": "00:00", "end": "23:59"},
      "wednesday": {"start": "00:00", "end": "23:59"},
      "thursday": {"start": "00:00", "end": "23:59"},
      "friday": {"start": "00:00", "end": "23:59"},
      "saturday": {"start": "00:00", "end": "23:59"},
      "sunday": {"start": "00:00", "end": "23:59"}
    }
  }'
```

---

### 6.4 Triggering Your First Incident Call

Always enqueue calls via the resilient `/call_to_queue` endpoint:

```bash
curl -X POST "http://10.0.55.251:8081/call_to_queue" \
  --data-urlencode "phone=oncall" \
  --data-urlencode "message=Emergency alert: Production database latency spike detected on cluster 01."
```

**What happens behind the scenes:**
1. `asterisk_caller` enqueues the request.
2. The worker resolves `phone=oncall` by querying `caller_address_book`.
3. An outbound call is placed via Asterisk ARI.
4. When the on-call engineer answers, Asterisk triggers a WebSocket event to `asterisk_ws_monitor`.
5. `generate_audio` converts the message text into a 16-bit 8000 Hz Asterisk WAV file using neural TTS.
6. Asterisk plays the message to the caller.
7. If the engineer presses `4` on their dialpad, `asterisk_ws_monitor` receives the DTMF digit and marks the call as **Acknowledged** in `caller_register`.

---

### 6.5 Triggering Your First SMS Notification

To test direct SMS dispatch:

```bash
curl -X POST "http://10.0.55.251:8085/send_sms" \
  --data-urlencode "phone=+393341234567" \
  --data-urlencode "message=TEST ALERT: Critical disk space on server storage-01"
```

Check the message record:
```bash
curl "http://10.0.55.251:8085/get_sms"
```

---

## 7. Monitoring Integrations (Alertmanager, Nagios, Zabbix)

### 7.1 Prometheus Alertmanager Webhook

In your Alertmanager configuration (`alertmanager.yml`), add a webhook receiver:

```yaml
receivers:
  - name: "py-phone-caller"
    webhook_configs:
      - url: "http://10.0.55.251:8084/sms_before_call" # Sends SMS, waits 120s, then calls if unacknowledged
        send_resolved: true
```

Available webhook routes:
- `/call_only`: Immediately triggers voice calls for alerts.
- `/sms_only`: Dispatches SMS notifications only.
- `/sms_before_call`: Sends an SMS first; if the alert remains firing after `sms_before_call_wait_seconds` (default 120s), places a voice call.
- `/call_and_sms`: Simultaneously sends an SMS and places a voice call.

---

### 7.2 Nagios Event Handler Script

Deploy `assets/scripts/nagios/nagios_event_handler_call.sh` to `/usr/local/nagios/libexec/`:

```bash
sudo cp assets/scripts/nagios/nagios_event_handler_call.sh /usr/local/nagios/libexec/
sudo chmod +x /usr/local/nagios/libexec/nagios_event_handler_call.sh
```

In your Nagios `commands.cfg`:
```ini
define command {
    command_name    notify_by_py_phone_caller
    command_line    PY_PHONE_CALLER_URL="http://10.0.55.251:8081/call_to_queue" /usr/local/nagios/libexec/nagios_event_handler_call.sh "$SERVICESTATE$" "$SERVICESTATETYPE$" "$SERVICEATTEMPT$" "$HOSTNAME$" "$SERVICEDESC$" "oncall"
}
```

---

### 7.3 Zabbix Alert Script

Deploy `assets/scripts/zabbix/zabbix_alert_call.sh` to your Zabbix `AlertScriptsPath` (e.g. `/usr/lib/zabbix/alertscripts/`):

```bash
sudo cp assets/scripts/zabbix/zabbix_alert_call.sh /usr/lib/zabbix/alertscripts/
sudo chmod +x /usr/lib/zabbix/alertscripts/zabbix_alert_call.sh
```

In Zabbix Administration -> Media Types -> Create Media Type:
- **Type**: Script
- **Script name**: `zabbix_alert_call.sh`
- **Script parameters**:
  - `{ALERT.SENDTO}` (e.g. `oncall` or `+393341234567`)
  - `{ALERT.SUBJECT}`
  - `{ALERT.MESSAGE}`
  - `http://10.0.55.251:8081/call_to_queue`

---

## 8. Air-Gapped & Offline Deployments

**py-phone-caller** is designed for fully air-gapped mission-critical environments without public Internet connectivity.

### Essential Air-Gapped Infrastructure
1. **Local OCI Registry**: (e.g. `artifacts.py-phone-caller.lan:5000`)
   - Pre-push the 11 container images tagged `1.0.0`.
2. **Local PyPI Server**: (e.g. `http://artifacts.py-phone-caller.lan:8080/simple`)
   - Pre-cache Python 3.14 wheels for `uv` sync.
3. **Pre-Cached Neural TTS Models**:
   - `generate_audio` containers bake the Kokoro TTS (`kokoro-v1_0.pth`), Facebook MMS, and Piper voices directly into the container image (`/app/src/generate_audio/pre_trained_models`).
4. **Local Web UI Assets**:
   - All Bootstrap, FontAwesome, and custom stylesheets in `py_phone_caller_ui` are stored locally in `src/py_phone_caller_ui/static/` with **zero external CDN dependencies**.

---

## 9. Troubleshooting & Operational Runbook

### Ansible Deployment Failures (Method A)

Every entry below is a failure observed on a real host. The play stops at the
failing task and applies nothing after it, so a re-run always converges once
the cause is fixed.

#### The play stops during validation

| Message | Cause and fix |
| :--- | :--- |
| `py_phone_caller_config / py_phone_caller_config_secrets are empty` | The converter has not run, or its output is not in `group_vars/app_servers/` **as a directory**. Run `assets/ansible/tools/toml_to_ansible_vars.py`, then confirm with `ansible-inventory --host <host>`. |
| `Placeholder credentials are still in place` | `.secrets.toml` still contains `change_me` / `super_secure_password`. Set real values and regenerate the vars (§4.4, §4.5). |
| `db_host ... is not local, so the role cannot use peer authentication` | Supply `py_phone_caller_db_admin_password`, or set `py_phone_caller_manage_database: false` and provision by hand (§4.6). |
| `caller_sms_carrier is 'on_premise' but caller_sms.modems is empty` | Add at least one `[[caller_sms.modems]]` entry with a `port`. |
| `deploy_py-phone-caller supports Debian/Ubuntu and RHEL/Rocky only` | Unsupported `os_family`; nothing was changed. |

#### `Something else already owns the Caddy ports on this host`

Another reverse proxy is in front. The message lists the offending NAT rules
or listeners. Either set `py_phone_caller_manage_caddy: false` and point that
proxy at the UI (§4.11), or remove it. `py_phone_caller_caddy_force: true`
installs Caddy anyway — it will bind 80/443 and never receive a request.

#### `The uv installer reported success but /opt/py-phone-caller/bin/uv is missing`

The installer exited 0 without installing anything. Check outbound access to
`astral.sh`, then re-run with `--tags install -vvv`. To install by hand:

```bash
sudo -u py-phone-caller env HOME=/opt/py-phone-caller \
  UV_INSTALL_DIR=/opt/py-phone-caller/bin UV_NO_MODIFY_PATH=1 \
  sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
```

#### `uv sync` fails building a package

Read the `hint:` line at the end of uv's output — it names the dependency
chain that pulled the package in.

A known one: `curated-tokenizers` 0.0.9 ships only an sdist, and Cython 3.1
crashes compiling it on Python 3.14 (`TypeError: 'NoneType' object is
unsliceable`). It arrives via `generate-audio → kokoro → misaki[en] →
spacy-curated-transformers`. The repository's root `pyproject.toml` pins the
build compiler for exactly this reason:

```toml
[tool.uv]
build-constraint-dependencies = ["cython<3.1"]
```

For a similar sdist failure, add a constraint there and re-run `uv lock` —
build constraints do not affect the resolution, so the lock diff is one line.

Air-gapped or behind a mirror:

```yaml
py_phone_caller_uv_extra_index_url: "https://pypi.internal.example.com/simple"
py_phone_caller_uv_insecure_host: "pypi.internal.example.com"   # plain HTTP only
```

#### `uv sync` is killed, or the host runs out of disk

The wheel set is ~3 GB and the resulting venv another ~7 GB. Check `df -h /`
and `free -m`. On a slow link raise `py_phone_caller_uv_sync_timeout`
(default 3600 seconds).

#### PostgreSQL provisioning fails and the output is hidden

Those tasks pass credentials to the `postgresql_*` modules, so they run with
`no_log`. To see the real error:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml \
  --tags database -e py_phone_caller_db_no_log=false
```

Usual causes: password authentication rejected from loopback (the role writes
`md5` into `pg_hba`, which negotiates SCRAM automatically when the stored
verifier is SCRAM — set `py_phone_caller_pg_hba_method: scram-sha-256` to
require it), or a `postgres` peer login needing an explicit
`py_phone_caller_pg_unix_socket`.

#### `Rust SMS engine not found` in the caller_sms log

The compiled module is not in the service virtualenv:

```bash
/opt/py-phone-caller/venv/bin/python -c 'import rust_engine'
ansible-playbook deploy_py-phone-caller_stack.yml --tags install
```

The role builds a wheel, installs it explicitly and then asserts the import,
so this should surface as a failed play rather than a runtime log line. Note
that `uv sync` runs with `--inexact` when on-premise SMS is selected: the
engine is compiled locally and is absent from `uv.lock`, so an exact sync
would uninstall it on every run.

#### ARI returns 401, or `ari show apps` is empty

The ARI user in `ari_py_phone_caller.conf` and `commons.asterisk_pass`
disagree — typically because the group_vars were regenerated between the two
plays. Re-run the whole stack playbook rather than one half.

#### The web UI is unreachable

Work outwards from the application:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5000/    # the UI itself
systemctl status caddy                                              # the proxy
curl -skS -o /dev/null -w '%{http_code}\n' https://<domain>/         # by name, never by IP
ufw status verbose            # or: firewall-cmd --list-all
```

`TLSV1_UNRECOGNIZED_NAME` means you connected by IP address; Caddy's
`tls internal` needs SNI. Test by name.

#### A unit restarts in a loop

Check `caller-register` first — everything is ordered after it and it owns the
migrations:

```bash
journalctl -u py-phone-caller-caller-register -n 100 --no-pager
```

Then confirm the effective configuration:

```bash
sudo -u py-phone-caller /opt/py-phone-caller/venv/bin/python -c \
  'from py_phone_caller_utils.config import settings; print(settings.database.db_host, settings.queue.queue_url)'
```

#### `ffmpeg` could not be installed (RHEL)

Expected and not fatal. It only affects the TTS engines that post-process
audio with pydub. Enable RPM Fusion or install `ffmpeg` manually, then re-run
`--tags prereqs`.

---

### Common Issues and Solutions

#### 1. `ModuleNotFoundError: No module named 'piccolo_conf'`
- **Cause**: Piccolo ORM did not receive the fully qualified path to the shared DB module.
- **Solution**: Ensure the environment variable `PICCOLO_CONF=py_phone_caller_utils.py_phone_caller_db.piccolo_conf` is present in your service environment or container definition.

#### 2. `Unable to resolve 'oncall' phone: Address book returned status 404`
- **Cause**: No contact in the Address Book has `enabled: true` with valid on-call schedule hours for the current timestamp.
- **Solution**: Add an enabled on-call contact in the Web UI or via `POST /contact`.

#### 3. Asterisk Calls Fail with `Connect call failed ('127.0.0.1', 8088)`
- **Cause**: Asterisk HTTP/ARI server is not running or listening on port 8088.
- **Solution**: Check Asterisk status:
  ```bash
  sudo asterisk -rx "http show status"
  sudo asterisk -rx "ari show users"
  ```
  Ensure `http.conf` has `enabled=yes` and `bindaddr=0.0.0.0` or `127.0.0.1`.

#### 4. Audio Generation Logs `Couldn't find ffmpeg`
- **Cause**: `ffmpeg` binary missing from system `$PATH`.
- **Solution**: Install ffmpeg:
  - Ubuntu/Debian: `sudo apt install -y ffmpeg`
  - RHEL/Rocky Linux: `sudo dnf install -y ffmpeg`

#### 5. Resetting Lost Administrator Password
- **Native Systemd**:
  ```bash
  sudo systemctl stop py-phone-caller-py-phone-caller-ui
  sudo -u py-phone-caller UI_USER_RESET_PASSWORD=true /opt/py-phone-caller/venv/bin/python -m gunicorn -w 1 -b 127.0.0.1:5000 py_phone_caller_ui.app:app
  # Note the generated password in console, then press Ctrl+C and restart normal systemd service:
  sudo systemctl start py-phone-caller-py-phone-caller-ui
  ```
- **Docker Compose**:
  ```bash
  UI_USER_RESET_PASSWORD=true docker compose restart py_phone_caller_ui
  docker compose logs py_phone_caller_ui | grep "Admin user"
  UI_USER_RESET_PASSWORD=false docker compose restart py_phone_caller_ui
  ```

---

## 🎯 Summary Checklist

**Preparation**

- [ ] Target OS updated; 15 GB free disk and 4 GB RAM confirmed (§2).
- [ ] `rsync` and `sudo` present on the target; key-based SSH works
      non-interactively (§4.3).
- [ ] Control node has `ansible-core` ≥ 2.15 and the three collections from
      `requirements.yml` (§4.2).

**Configuration**

- [ ] `src/config/settings.toml` reviewed: `asterisk_chan_type`, `tts_engine`,
      `caller_sms_carrier`, UI admin e-mail (§4.4).
- [ ] `src/config/.secrets.toml` holds real credentials — no `change_me` or
      `super_secure_password` left (§4.4).
- [ ] `assets/ansible/tools/toml_to_ansible_vars.py` run; `ansible-inventory
      --host <host>` shows all three variables loaded (§4.5).
- [ ] `group_vars/all.yml` declares the topology, and the reverse-proxy
      decision is made (§4.6).
- [ ] SIP trunk variables set, or accepted as non-functional for now (§4.8).
- [ ] `render_check.yml` reports every key matching (§4.7).

**Deployment**

- [ ] Playbook finished with `failed=0`; a second run reports `changed=0`
      (§4.9).
- [ ] `verify.yml` reports **11 units active**, **7/7 health endpoints**, and
      the web UI answering HTTP 200 (§4.10).
- [ ] `\dt` in the `py_phone_caller` database lists the 7 tables created by
      the migrations (§4.10).
- [ ] `ari show apps` lists the Stasis application, and ARI returns 200 with
      the credentials from `settings.toml` (§4.10).
- [ ] On-premise SMS only: `import rust_engine` succeeds and the log says
      *Rust SMS engine started successfully* (§4.10).
- [ ] Service ports verified **closed** from another machine, with your SSH
      port as the positive control (§4.10).

**Going live**

- [ ] Web UI published through Caddy or your existing reverse proxy (§4.11).
- [ ] Admin password rotated, and `py_phone_caller_ui_reset_password` set back
      to `false` (§4.10).
- [ ] Initial on-call contact created in the Address Book (§6.3).
- [ ] Test call and test SMS both placed successfully (§6.4, §6.5).
- [ ] Monitoring webhooks connected (Prometheus / Nagios / Zabbix) (§7).
- [ ] Database backup scheduled (§4.12).

You are now ready to operate **py-phone-caller** in production! 🚀
