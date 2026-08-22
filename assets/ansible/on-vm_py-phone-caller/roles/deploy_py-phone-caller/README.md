# Ansible Role: deploy_py-phone-caller

This role deploys the `py-phone-caller` microservices stack on Linux systems. It handles the full lifecycle of the deployment, from installing system dependencies to configuring the application and starting systemd services.

Supported OS Families:
- Debian/Ubuntu (tested on Ubuntu 22.04)
- RedHat/Rocky Linux (tested on Rocky Linux 9)

## Features

- **System Setup**: Installs required packages (Python 3.14 via `uv`, Redis, PostgreSQL, FFmpeg).
- **Environment**: Sets up a Python virtual environment using `uv` for fast dependency management.
- **Application**: Installs the `py-phone-caller` stack, including complex audio dependencies (Torch, Kokoro TTS).
- **Database**: Configures PostgreSQL user and database, and adjusts `pg_hba.conf` for password authentication on RHEL-based systems.
- **Security**: Configures system firewalls (UFW or firewalld) to allow traffic to application ports.
- **Service Management**: Creates and manages Systemd units for all microservices and Celery workers.
- **Cleanup**: Removes development artifacts from the production environment to keep the deployment clean.

## Requirements

- **Target System**:
  - `uv` can install Python 3.14 for the workspace.
  - Internet access (required to download PyPI packages and HuggingFace models).
  - Sufficient RAM (~2GB+) for installing audio dependencies like `torch`.
- **Control Node**:
  - Ansible 2.9 or higher.

## Role Variables

The role is highly configurable. Below are the main variables and their default values (see `defaults/main.yml` for the full list).

### General Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `py_phone_caller_user` | `py-phone-caller` | The system user created to run the services. |
| `py_phone_caller_group` | `py-phone-caller` | The system group. |
| `py_phone_caller_install_dir` | `/opt/py-phone-caller` | Installation root directory. |
| `py_phone_caller_log_dir` | `/var/log/py-phone-caller` | Directory for application logs. |
| `py_phone_caller_venv_dir` | `{{ install_dir }}/venv` | Path to the virtual environment. |
| `py_phone_caller_ui_reset_password` | `false` | Set to `true` only for intentional first-time admin bootstrap or password reset. |
| `py_phone_caller_service_host` | `{{ caddy_domain_name }}` | Default host used by py-phone-caller services to call each other. |
| `py_phone_caller_pbx_host` | `pbx.lan` | Default Asterisk PBX hostname used in generated configuration. |
| `py_phone_caller_database_host` | `postgresql.lan` | Default PostgreSQL hostname used in generated configuration. |
| `py_phone_caller_queue_host` | `redis.lan` | Default Redis hostname used in generated configuration. |
| `py_phone_caller_hosts_entries` | `[]` | Optional `/etc/hosts` aliases; empty means DNS or the existing host resolver is used. |
| `py_phone_caller_manage_database` | `true` | When true, automatically provisions the database, user, permissions, and extensions. |
| `py_phone_caller_manage_local_postgres` | `auto` | When true (auto-detected if host is localhost), installs and starts local PostgreSQL daemon. |
| `py_phone_caller_db_admin_user` | `postgres` | Administrative username used to provision the database and application role. |
| `py_phone_caller_db_admin_password` | `""` | Administrative password for PostgreSQL. If provided, connects over TCP with admin credentials. |

### Source Code Management

You can choose to clone the source code from a Git repository or copy it from a local path (useful for development or air-gapped deployments with pre-downloaded source).

| Variable | Default | Description |
|----------|---------|-------------|
| `py_phone_caller_git_repo` | `""` | Git repository URL. If set, `git clone` is used. |
| `py_phone_caller_git_version` | `main` | Branch, tag, or commit to checkout. |
| `py_phone_caller_local_src_path` | `""` | Local path to the `src/` directory (e.g. `../../src`). Used if `git_repo` is empty. |

### Configuration (`settings.toml`)

The application configuration (`settings.toml`) is generated dynamically. You can override any default setting by defining the `py_phone_caller_config` dictionary. This dictionary is deep-merged with the defaults.

**Key Configuration Sections:**

```yaml
py_phone_caller_pbx_host: "pbx.lan"
py_phone_caller_database_host: "postgresql.lan"
py_phone_caller_config:
  database:
    db_password: "your_secure_password"
  caller_sms:
    twilio_account_sid: "..."
    twilio_auth_token: "..."
  py_phone_caller_ui:
    ui_admin_user: "admin@example.com"
```

Set `py_phone_caller_ui_reset_password: true` for one deployment run when you need to create the first admin account or reset its password. Set it back to `false` immediately afterwards so normal service restarts do not rotate the admin password again.

### Optional host aliases

The role does not hardcode lab or localhost mappings in `/etc/hosts`. Prefer DNS where possible. For air-gapped or lab networks without DNS, provide explicit aliases:

```yaml
py_phone_caller_hosts_entries:
  - address: "<INFRA_SERVICES_IP>"
    names:
      - postgresql.lan
      - pbx.lan
      - redis.lan
  - address: "<REVERSE_PROXY_IP>"
    names:
      - nginx.lab.local
```

If `py_phone_caller_hosts_entries` is empty, the role removes old py-phone-caller-managed host aliases and leaves normal system DNS resolution untouched.

### Services and Ports

The role automatically configures the firewall to open the following ports for the microservices:

| Service | Port | Description |
|---------|------|-------------|
| **py_phone_caller_ui** | 5000 | Web Dashboard (UI) |
| **asterisk_caller** | 8081 | Call Initiator Service |
| **generate_audio** | 8082 | TTS Engine (Kokoro, etc.) |
| **caller_register** | 8083 | Call Registry Service |
| **caller_prometheus_webhook** | 8084 | Monitoring/Alerting Webhook |
| **caller_sms** | 8085 | SMS Gateway Service |
| **scheduled_calls** | 8086 | Call Scheduler Service |
| **caller_address_book** | 8087 | Contact Management Service |

## Dependencies

This role has no external Ansible role dependencies. It manages all necessary system components internally.

## Example Playbooks

### 1. Deploy from Git (Production)

```yaml
- hosts: phone_servers
  become: yes
  roles:
    - role: deploy_py-phone-caller
      vars:
        py_phone_caller_git_repo: "https://github.com/your-org/py-phone-caller.git"
        py_phone_caller_pbx_host: "{{ vault_pbx_host }}"
        py_phone_caller_config:
          database:
            db_password: "{{ vault_db_password }}"
```

### 2. Deploy from Local Source (Development/Testing)

```yaml
- hosts: dev_servers
  become: yes
  roles:
    - role: deploy_py-phone-caller
      vars:
        # Assumes the playbook is run from assets/ansible/...
        py_phone_caller_local_src_path: "../../../src"
        py_phone_caller_config:
          database:
            db_password: "{{ lookup('env', 'PY_PHONE_CALLER_DB_PASSWORD') | default('change_me', true) }}"
```

## Troubleshooting

- **Audio Generation**: The `generate_audio` service compiles `torch` and downloads large TTS models. This process can take several minutes on the first run. Check the service logs if startup seems slow:
  ```bash
  journalctl -fu py-phone-caller-generate-audio
  ```
- **Firewall**: If you cannot access the UI on port 5000, verify the firewall status:
  - Ubuntu: `ufw status`
  - Rocky: `firewall-cmd --list-ports`
- **Database Authentication**: On Rocky Linux, this role modifies `pg_hba.conf` to allow `md5` authentication for localhost. If you change the database host or user, ensure `py_phone_caller_config.database` settings match your PostgreSQL configuration.

## License

MIT

## Author Information

_py-phone-caller team_
