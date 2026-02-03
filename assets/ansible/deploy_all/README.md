# 🚀 All-in-One Deployment: Complete py-phone-caller Stack

This is the **one-command deployment** for the entire **py-phone-caller** emergency alert system stack. It orchestrates the installation of both **Asterisk PBX** and the **py-phone-caller microservices** on your target infrastructure.

Perfect for rapid deployment, testing, or production rollout where you want everything configured and running with minimal manual intervention.

---

## 📦 What Gets Deployed

This playbook deploys the complete stack in two phases:

### Phase 1: Asterisk PBX Infrastructure
* **Asterisk PBX** (v18/20+) with PJSIP configuration
* **ARI (Asterisk REST Interface)** for application control
* **SIP Trunk** configuration (Cloud provider or GSM Gateway)
* **Custom dialplan** and audio files for emergency alerts
* **WebSocket support** for real-time call monitoring

### Phase 2: py-phone-caller Microservices
* **11 Microservices** including call management, SMS, TTS, scheduling, and web UI
* **PostgreSQL database** schema initialization
* **Redis queue** configuration
* **Caddy reverse proxy** for HTTPS termination
* **Systemd service** management for all components
* **Firewall rules** and security hardening

**Result:** A fully functional emergency alert platform ready to make calls and send SMS messages.

---

## 📋 Requirements

### System Requirements
* **Target OS:**
    * Ubuntu 22.04 LTS / 24.04 LTS (**Recommended**)
    * RHEL/Rocky Linux 9 (**Recommended**)
* **System Resources:**
    * **RAM:** 4GB+ (2GB for services + 2GB for TTS models)
    * **Storage:** 10GB+ free space
    * **CPU:** 4+ cores recommended
* **Network:** Internet access for initial setup (can run air-gapped after deployment)

### Infrastructure Requirements
* **PostgreSQL:** 12+ (can be on same host or remote)
* **Redis:** 6+ (can be on same host or remote)
* **SSH Access:** User with `sudo` privileges on target host(s)

### Ansible Requirements
* **Ansible:** 2.12 or higher
* **Collections:** `community.general`

Install the required collection:
```bash
ansible-galaxy collection install community.general
```

---

## 🎯 Quick Start

### 1. Configure Your Inventory
Edit the inventory file to specify your target host(s):

```bash
# Edit the inventory file
vim ../on-vm_py-phone-caller/inventory
```

Example inventory:
```ini
[app_servers]
alert-server-01 ansible_host=192.168.1.100 ansible_user=admin

[app_servers:vars]
ansible_become=yes
ansible_python_interpreter=/usr/bin/python3
```

### 2. Configure Credentials
Edit the playbook and set your credentials:

```bash
vim deploy_py-phone-caller_stack.yml
```

**Important variables to customize:**
```yaml
# Asterisk credentials
ari_password: "YOUR_SECURE_PASSWORD"
sip_username: "YOUR_SIP_USERNAME"
sip_password: "YOUR_SIP_PASSWORD"

# py-phone-caller configuration
py_phone_caller_config:
  database:
    db_password: "YOUR_DB_PASSWORD"
```

> [!WARNING]
> **Security:** Never commit real passwords to Git! Use Ansible Vault for production:
> ```bash
> ansible-vault encrypt_string 'YourPassword' --name 'ari_password'
> ```

### 3. Deploy Everything
Run the all-in-one deployment:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml
```

That's it! The playbook will:
1. Install and configure Asterisk PBX (5-10 minutes)
2. Deploy all py-phone-caller services (10-20 minutes)
3. Configure networking, firewall, and systemd services
4. Start all services and verify deployment

---

## ⚙️ Configuration

### Architecture Configuration

The playbook uses a **pre-configured ansible.cfg** that automatically:
* Points to the correct inventory file
* Sets up role paths for both Asterisk and py-phone-caller roles
* Disables host key checking for easier deployment
* Configures Python interpreter detection

**ansible.cfg contents:**
```ini
[defaults]
inventory = ../on-vm_py-phone-caller/inventory
roles_path = ../asterisk_py-phone-caller/roles:../on-vm_py-phone-caller/roles
host_key_checking = False
interpreter_python = auto_silent
```

### Common Configuration Scenarios

#### Scenario A: Single-Host Deployment (All-in-One)
Deploy everything on a single server:

```yaml
# deploy_py-phone-caller_stack.yml
- name: Deploy Asterisk PBX
  hosts: all
  become: yes
  vars:
    ari_password: "{{ vault_ari_password }}"
    sip_provider_host: "sip.messagenet.it"
    sip_username: "{{ vault_sip_username }}"
    sip_password: "{{ vault_sip_password }}"
  roles:
    - asterisk_py_phone_caller

- name: Deploy py-phone-caller Stack
  hosts: all
  become: yes
  vars:
    py_phone_caller_local_src_path: "{{ playbook_dir }}/../../../src"
    py_phone_caller_config:
      commons:
        asterisk_host: "localhost"  # Same host
      database:
        db_host: "localhost"
        db_password: "{{ vault_db_password }}"
      queue:
        queue_host: "localhost"
  roles:
    - deploy_py-phone-caller
```

#### Scenario B: Distributed Deployment
Deploy across multiple servers:

```yaml
# Inventory
[pbx_servers]
pbx-01 ansible_host=192.168.1.10

[app_servers]
app-01 ansible_host=192.168.1.20

[db_servers]
db-01 ansible_host=192.168.1.30

# Playbook
- name: Deploy Asterisk PBX
  hosts: pbx_servers
  become: yes
  vars:
    ari_password: "{{ vault_ari_password }}"
  roles:
    - asterisk_py_phone_caller

- name: Deploy py-phone-caller Stack
  hosts: app_servers
  become: yes
  vars:
    py_phone_caller_config:
      commons:
        asterisk_host: "192.168.1.10"  # PBX server
      database:
        db_host: "192.168.1.30"  # DB server
        db_password: "{{ vault_db_password }}"
  roles:
    - deploy_py-phone-caller
```

#### Scenario C: Air-Gapped with GSM Gateway
Deploy without internet access using local GSM gateway:

```yaml
- name: Deploy Asterisk PBX
  hosts: all
  become: yes
  vars:
    # Local GSM Gateway on LAN
    sip_provider_host: "192.168.1.200"
    sip_provider_port: 5060
    sip_username: "asterisk_trunk"
    sip_password: "{{ vault_gateway_password }}"
    sip_contact_user: "asterisk"
  roles:
    - asterisk_py_phone_caller

- name: Deploy py-phone-caller Stack
  hosts: all
  become: yes
  vars:
    py_phone_caller_local_src_path: "/mnt/usb/py-phone-caller/src"
    py_phone_caller_config:
      commons:
        asterisk_host: "localhost"
      caller_sms:
        caller_sms_carrier: "on_premise"
        modems:
          - id: "primary_gsm"
            port: "/dev/ttyUSB0"
            baud_rate: 115200
            priority: 1
  roles:
    - deploy_py-phone-caller
```

---

## 🎮 Advanced Usage

### Deployment with Tags
Run only specific parts of the deployment:

```bash
# Deploy only Asterisk PBX
ansible-playbook deploy_py-phone-caller_stack.yml --tags asterisk

# Deploy only configuration updates
ansible-playbook deploy_py-phone-caller_stack.yml --tags config

# Deploy only systemd services
ansible-playbook deploy_py-phone-caller_stack.yml --tags systemd
```

### Dry Run (Check Mode)
See what would change without making changes:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml --check --diff
```

### Limit to Specific Hosts
Deploy to only certain hosts from inventory:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml --limit app-01
```

### Verbose Output
Get detailed execution information:

```bash
ansible-playbook deploy_py-phone-caller_stack.yml -vvv
```

---

## ✅ Post-Deployment Verification

After deployment completes, verify the entire stack:

### 1. Check Asterisk PBX
```bash
# SSH to the target server
ssh admin@192.168.1.100

# Verify Asterisk is running
sudo systemctl status asterisk

# Check SIP registration
sudo asterisk -x "pjsip show registrations"

# Verify ARI user
sudo asterisk -x "ari show users"

# Test ARI connectivity
curl -u py-phone-caller:SuperSecret http://localhost:8088/ari/asterisk/info
```

### 2. Check py-phone-caller Services
```bash
# Check all services are running
systemctl status 'py-phone-caller-*'

# View service logs
journalctl -u 'py-phone-caller-*' -n 50

# Test web interface
curl -I http://localhost:5000
```

### 3. End-to-End Test
```bash
# Test a call via API
curl -X POST http://localhost:8081/place_call \
  -H "Content-Type: application/json" \
  -d '{"phone": "+1234567890", "message": "Test emergency alert"}'

# Check call was logged
curl http://localhost:8083/calls | jq
```

### 4. Access Web UI
Open your browser and navigate to:
* **Local:** http://localhost:5000
* **Remote:** https://py-phone-caller.lan (or your configured domain)

**Default login:** Check configuration for `ui_admin_user`

---

## 📊 Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Target Server(s)                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌──────────────────┐         ┌──────────────────────┐      │
│  │  Asterisk PBX    │◄────────┤  py-phone-caller     │      │
│  │                  │  ARI    │  Services (11x)      │      │
│  │  • PJSIP         │         │                      │      │
│  │  • ARI           │         │  • Call Management   │      │
│  │  • Dialplan      │         │  • SMS Service       │      │
│  │  • WebSocket     │         │  • TTS Engine        │      │
│  └────────┬─────────┘         │  • Web UI            │      │
│           │                   │  • Scheduler         │      │
│           │ SIP               │  • Address Book      │      │
│           ▼                   └──────────┬───────────┘      │
│  ┌──────────────────┐                   │                   │
│  │  SIP Provider    │                   │                   │
│  │  or GSM Gateway  │                   ▼                   │
│  └──────────────────┘         ┌──────────────────────┐      │
│                                │  PostgreSQL + Redis  │      │
│                                └──────────────────────┘      │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🛠 Troubleshooting

### Playbook Fails on Asterisk Phase
**Symptoms:** Deployment stops during Asterisk installation

**Solutions:**
1. Check OS compatibility (Ubuntu 22.04/24.04 or Rocky 9)
2. Verify internet connectivity for package downloads
3. Check for port conflicts (5060, 8088)
4. Review Asterisk logs: `sudo tail -f /var/log/asterisk/messages`

### Playbook Fails on py-phone-caller Phase
**Symptoms:** Deployment stops during microservices setup

**Solutions:**
1. Verify Python 3.9+ is available
2. Check disk space (need 5GB+ for models)
3. Verify PostgreSQL and Redis are accessible
4. Check source path is correct: `{{ playbook_dir }}/../../../src`

### Services Won't Start
**Symptoms:** Systemd services fail to start

**Solutions:**
```bash
# Check which service failed
systemctl status 'py-phone-caller-*' | grep failed

# View detailed logs for failed service
journalctl -u py-phone-caller-SERVICE_NAME -n 100

# Check configuration
cat /opt/py-phone-caller/src/config/settings.toml

# Verify file permissions
ls -la /opt/py-phone-caller/
```

### Connection Between Components Fails
**Symptoms:** Services can't communicate with Asterisk or database

**Solutions:**
1. Check firewall rules: `sudo firewall-cmd --list-all` or `sudo ufw status`
2. Test connectivity: `telnet localhost 8088` (Asterisk ARI)
3. Verify DNS/hostname resolution: `ping pbx.lan`
4. Check credentials in `/opt/py-phone-caller/src/config/settings.toml`

---

## 🔐 Security Best Practices

### 1. Use Ansible Vault
Never store passwords in plaintext:

```bash
# Create a vault file
ansible-vault create secrets.yml

# Add your secrets
ari_password: "YourSecurePassword"
sip_password: "YourSIPPassword"
db_password: "YourDBPassword"

# Run playbook with vault
ansible-playbook deploy_py-phone-caller_stack.yml --ask-vault-pass
```

### 2. Configure Firewall
Ensure only necessary ports are exposed:

```bash
# On the target server
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --permanent --add-port=5060/udp  # SIP (only if needed externally)
sudo firewall-cmd --reload
```

### 3. Enable HTTPS
For production, configure proper SSL certificates:

```yaml
py_phone_caller_config:
  caddy_email: "admin@yourcompany.com"  # For Let's Encrypt
  caddy_domain_name: "alerts.yourcompany.com"
```

### 4. Restrict Database Access
Configure PostgreSQL to only accept connections from the app server:

```bash
# On database server: /etc/postgresql/*/main/pg_hba.conf
host    py_phone_caller    py_phone_caller    192.168.1.20/32    scram-sha-256
```

---

## 📚 Additional Resources

* **Asterisk Role Documentation:** `../asterisk_py-phone-caller/README.md`
* **py-phone-caller Role Documentation:** `../on-vm_py-phone-caller/roles/deploy_py-phone-caller/README.md`
* **Main Project README:** `../../../README.md`

---

## 🆘 Support & Maintenance

### Updating the Stack
To update an existing deployment:

```bash
# Pull latest changes
git pull origin main

# Re-run deployment (only changed items will update)
ansible-playbook deploy_py-phone-caller_stack.yml
```

### Backup Important Data
Before major updates, back up:

```bash
# PostgreSQL database
pg_dump -h localhost -U py_phone_caller py_phone_caller > backup.sql

# Configuration
tar -czf config-backup.tar.gz /opt/py-phone-caller/src/config/

# Asterisk configuration
tar -czf asterisk-backup.tar.gz /etc/asterisk/
```

### Health Monitoring
Set up monitoring for production:

```bash
# Check all services are healthy
systemctl is-active asterisk py-phone-caller-*

# Monitor logs continuously
journalctl -u 'py-phone-caller-*' -f
```

---

**Maintained by:** py-phone-caller team
**License:** Check main project repository
**Contributions:** Welcome! Submit issues or PRs to the main repository
