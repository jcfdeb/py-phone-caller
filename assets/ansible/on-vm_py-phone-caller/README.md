# 📱 Ansible Role: Deploy py-phone-caller

This role deploys the complete **py-phone-caller** microservices stack on Linux systems, providing an emergency alert and notification platform with SMS, voice calls, and web interface capabilities.

It handles the full deployment lifecycle from system dependencies to service configuration and is designed to be **OS-Agnostic** (supporting Ubuntu/Debian and RHEL/Rocky Linux) and **Production-Ready** with proper security, firewall, and service management.

## 📋 Requirements

* **Ansible:** 2.9 or higher.
* **Target OS:**
    * Ubuntu 22.04 LTS / 24.04 LTS (**Recommended** / Fully Supported)
    * Red Hat Enterprise Linux (RHEL) 9 / Rocky Linux 9 (**Recommended** / Fully Supported)
    * RHEL/Rocky 8 (Legacy / Supported)
* **System Resources:**
    * **RAM:** 2GB+ (Required for PyTorch and TTS model compilation)
    * **Storage:** 5GB+ free space for dependencies and models
    * **CPU:** 2+ cores recommended for audio processing
* **Network:** Internet access required for PyPI packages and HuggingFace model downloads
* **Access:** SSH with `sudo` privileges on the target machine

> [!TIP]
> **Performance Note:** The initial deployment downloads large machine learning models (~500MB+) and compiles PyTorch. This process can take 10-15 minutes depending on your server specs and internet connection.

---

## 🚀 Installation

There are two ways to install this role into your project.

### Option A: Local Directory (Recommended for Dev)
Simply copy the entire folder `deploy_py-phone-caller` into your project's `roles/` directory.

Project structure:
```text
my-project/
├── inventory
├── py-phone-caller_deploy.yml
└── roles/
    └── deploy_py-phone-caller/
        ├── defaults/
        ├── tasks/
        ├── templates/
        ├── handlers/
        └── ...
```

### Option B: Via `requirements.yml` (Best for Git Ops)
If you host this role in a separate Git repository, add it to your `requirements.yml`:

```yaml
# requirements.yml
roles:
  - src: https://github.com/your-org/deploy_py-phone-caller.git
    scm: git
    version: main
    name: deploy_py-phone-caller
```

Then install it:
```bash
ansible-galaxy install -r requirements.yml -p ./roles
```

---

## ⚙️ Configuration

### 1. Core Variables
These variables control the basic installation and runtime behavior. Override them in your `playbook`, `inventory`, or `group_vars`.

| Variable | Default | Description |
| :--- | :--- | :--- |
| **Installation Paths** | | |
| `py_phone_caller_user` | `"py-phone-caller"` | System user for running services. |
| `py_phone_caller_group` | `"py-phone-caller"` | System group for running services. |
| `py_phone_caller_install_dir` | `"/opt/py-phone-caller"` | Installation directory for the application. |
| `py_phone_caller_log_dir` | `"/var/log/py-phone-caller"` | Log directory for all services. |
| **Source Control** | | |
| `py_phone_caller_git_repo` | `""` | Git repository URL (leave empty if deploying from local source). |
| `py_phone_caller_git_version` | `"main"` | Git branch/tag to deploy. |
| `py_phone_caller_local_src_path` | `""` | Local source path (for offline/development deployment). |
| **Web Interface** | | |
| `caddy_domain_name` | `"py-phone-caller.lan"` | Domain name for the web UI and API services. |
| `caddy_email` | `""` | Email for Let's Encrypt (leave empty for local/self-signed). |

### 2. Service Configuration
The role configures multiple microservices. Key configuration options:

| Section | Key Variables | Description |
| :--- | :--- | :--- |
| **Asterisk Integration** | `asterisk_host`, `asterisk_web_port`, `asterisk_user` | Connection settings for Asterisk PBX. |
| **Database** | `db_host`, `db_port`, `db_name`, `db_user`, `db_password` | PostgreSQL connection settings. |
| **Queue** | `queue_host`, `queue_port`, `queue_url` | Redis queue configuration. |
| **SMS Service** | `caller_sms_carrier`, `modems`, `sms_strategy` | SMS carrier settings (on-premise or Twilio). |
| **TTS Engine** | `tts_engine`, `kokoro_lang`, `piper_language_code` | Text-to-speech engine selection (kokoro_tts, piper, etc.). |
| **Web UI** | `ui_listen_on_host`, `ui_listen_on_port`, `ui_admin_user` | Web interface configuration. |

> [!NOTE]
> All configuration options have sensible defaults defined in `defaults/main.yml`. For production deployments, you should override at minimum: database credentials, SMS settings, and domain names.

### 3. Deployed Services
The role deploys the following systemd services:

* `py-phone-caller-asterisk_caller.service` - Handles outbound call placement
* `py-phone-caller-asterisk_recaller.service` - Manages call retries and backup callees
* `py-phone-caller-asterisk_ws_monitor.service` - Monitors Asterisk WebSocket events
* `py-phone-caller-caller_address_book.service` - Contact management API
* `py-phone-caller-caller_prometheus_webhook.service` - Prometheus AlertManager integration
* `py-phone-caller-caller_register.service` - Call event registration and tracking
* `py-phone-caller-caller_scheduler.service` - Scheduled call management
* `py-phone-caller-caller_sms.service` - SMS sending service
* `py-phone-caller-generate_audio.service` - Text-to-speech audio generation
* `py-phone-caller-py_phone_caller_ui.service` - Web interface (Gunicorn)
* `py-phone-caller-celery_worker.service` - Celery background task worker

---

## 📖 Usage Examples

### Scenario A: Development/Testing Deployment
Use this configuration for local development or testing on a single machine.

```yaml
# py-phone-caller_deploy.yml
- name: Deploy py-phone-caller (Development)
  hosts: dev_servers
  become: yes
  roles:
    - deploy_py-phone-caller
  vars:
    caddy_domain_name: "localhost"
    py_phone_caller_config:
      commons:
        asterisk_host: "localhost"
      database:
        db_host: "localhost"
        db_password: "{{ vault_dev_db_password }}"
      queue:
        queue_host: "localhost"
```

### Scenario B: Production Deployment (Distributed)
Use this configuration for production with separate database and queue servers.

```yaml
# py-phone-caller_deploy.yml
- name: Deploy py-phone-caller (Production)
  hosts: app_servers
  become: yes
  roles:
    - deploy_py-phone-caller
  vars:
    caddy_domain_name: "alerts.company.com"
    caddy_email: "admin@company.com"
    py_phone_caller_config:
      commons:
        asterisk_host: "pbx.internal.lan"
        asterisk_ami_user: "{{ vault_ami_user }}"
      database:
        db_host: "postgres.internal.lan"
        db_name: "py_phone_caller_prod"
        db_user: "py_phone_caller"
        db_password: "{{ vault_prod_db_password }}"
      queue:
        queue_host: "redis.internal.lan"
        queue_url: "redis://redis.internal.lan:6379/7"
      caller_sms:
        caller_sms_carrier: "on_premise"
        modems:
          - id: "primary_gsm"
            port: "/dev/ttyUSB0"
            baud_rate: 115200
            priority: 1
          - id: "backup_gsm"
            port: "/dev/ttyUSB1"
            baud_rate: 115200
            priority: 2
      py_phone_caller_ui:
        ui_admin_user: "{{ vault_admin_email }}"
```

### Scenario C: Air-Gapped/Offline Deployment
Use this configuration for systems without internet access.

```yaml
# py-phone-caller_deploy.yml
- name: Deploy py-phone-caller (Air-Gapped)
  hosts: isolated_servers
  become: yes
  roles:
    - deploy_py-phone-caller
  vars:
    # Deploy from local source (pre-downloaded)
    py_phone_caller_local_src_path: "/mnt/usb/py-phone-caller"
    caddy_domain_name: "py-phone-caller.local"

    py_phone_caller_config:
      commons:
        asterisk_host: "192.168.1.10"
      database:
        db_host: "192.168.1.20"
        db_password: "{{ vault_offline_db_password }}"
      queue:
        queue_host: "192.168.1.20"
        queue_url: "redis://192.168.1.20:6379/7"
      generate_audio:
        tts_engine: "kokoro_tts"  # Lightweight offline TTS
```

---

## 🏃 How to Run

### 1. Dry Run (Test)
Check what changes will be made without applying them:
```bash
ansible-playbook -i inventory py-phone-caller_deploy.yml --check
```

### 2. Deploy
Apply configuration and start all services:
```bash
ansible-playbook -i inventory py-phone-caller_deploy.yml
```

### 3. Deploy Specific Components
Use tags to deploy only specific parts:
```bash
# Update configuration only
ansible-playbook -i inventory py-phone-caller_deploy.yml --tags config

# Update systemd services only
ansible-playbook -i inventory py-phone-caller_deploy.yml --tags systemd

# Update database schema
ansible-playbook -i inventory py-phone-caller_deploy.yml --tags database
```

---

## ✅ Testing & Verification

After the playbook finishes, verify the deployment on the target server using the following steps.

### 1. Check Service Status
Verify that all services are running:
```bash
systemctl status 'py-phone-caller-*'
```
*All services should show **active (running)** status.*

### 2. Check Logs
View logs for any service:
```bash
# View all service logs
journalctl -u 'py-phone-caller-*' -f

# View specific service logs
journalctl -u py-phone-caller-asterisk_caller -n 50

# Check log directory
ls -lh /var/log/py-phone-caller/
```

### 3. Verify Web Interface
Access the web UI and verify it's accessible:
```bash
# Test from the server
curl -I http://localhost:5000

# Or access from your browser
# https://py-phone-caller.lan (or your configured domain)
```

### 4. Test Database Connectivity
Verify database connection:
```bash
# Run as the py-phone-caller user
sudo -u py-phone-caller /opt/py-phone-caller/venv/bin/python -c "
from sqlalchemy import create_engine
engine = create_engine('postgresql://py_phone_caller:password@localhost/py_phone_caller')
with engine.connect() as conn:
    print('Database connection successful!')
"
```

### 5. Test API Endpoints
Check that microservices are responding:
```bash
# Test Caller Register Service (port 8083)
curl http://localhost:8083/health

# Test Generate Audio Service (port 8082)
curl http://localhost:8082/health

# Test SMS Service (port 8085)
curl http://localhost:8085/health

# Test Address Book Service (port 8087)
curl http://localhost:8087/health
```

### 6. Verify Configuration
Check the deployed configuration:
```bash
cat /opt/py-phone-caller/src/config/settings.toml
```

---

## 🧩 Architecture Notes

* **Modular Design:** The role is split into logical task files (prereqs, user, source, install, database, config, caddy, firewall, systemd, cleanup) for maintainability.
* **Python Virtual Environment:** All Python dependencies are installed in an isolated virtualenv at `/opt/py-phone-caller/venv`.
* **Service Management:** Each microservice runs as a separate systemd unit under the dedicated `py-phone-caller` user.
* **Reverse Proxy:** Caddy is configured to provide HTTPS termination and reverse proxy functionality for the web UI.
* **Security:** The role configures firewall rules (firewalld/ufw), creates a dedicated system user, and sets proper file permissions.
* **Idempotent:** The role can be run multiple times safely without causing issues.

---

## 🛠 Troubleshooting

### Service Won't Start
If a service fails to start:
```bash
# Check service status and logs
systemctl status py-phone-caller-asterisk_caller
journalctl -u py-phone-caller-asterisk_caller -n 100

# Verify configuration
cat /opt/py-phone-caller/src/config/settings.toml

# Check file permissions
ls -la /opt/py-phone-caller/
```

### Database Connection Errors
If services can't connect to the database:
1. **Verify Credentials:** Check `settings.toml` for correct database credentials
2. **Test Connection:** Use `psql` to manually test the connection:
   ```bash
   psql -h localhost -U py_phone_caller -d py_phone_caller
   ```
3. **Check Firewall:** Ensure PostgreSQL port (5432) is accessible
4. **Check PostgreSQL:** Verify PostgreSQL is running and accepting connections

### TTS Audio Generation Fails
If audio generation is failing:
1. **Check Models:** Verify TTS models are downloaded in `/opt/py-phone-caller/pre_trained_models/`
2. **Check Disk Space:** TTS models require significant disk space
3. **Check Logs:** Review `generate_audio` service logs for specific errors
4. **Verify Engine:** Ensure the configured `tts_engine` is supported and properly installed

### Port Conflicts
If services fail due to port conflicts:
1. **Check Ports:** Verify no other services are using the required ports (5000, 8081-8087)
   ```bash
   netstat -tlnp | grep -E ':(5000|808[1-7])'
   ```
2. **Modify Config:** Override port numbers in your playbook variables if needed

---

## 🔒 Security Considerations

* **Credentials:** Always use Ansible Vault for sensitive data (database passwords, API keys):
  ```bash
  ansible-vault encrypt_string 'my_secret_password' --name 'vault_db_password'
  ```
* **Firewall:** The role configures firewall rules, but review them for your environment
* **HTTPS:** Configure proper SSL certificates for production (set `caddy_email` for Let's Encrypt)
* **User Permissions:** The role creates a dedicated unprivileged user; services do not run as root
* **Database Access:** Restrict database access to only the application server IPs

---

**Maintained by:** py-phone-caller team