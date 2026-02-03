# 📘 Ansible Role: Asterisk for py-phone-caller

This role installs and configures **Asterisk PBX** (v18/20+) specifically for the **py-phone-caller** emergency alert system.

It is designed to be **OS-Agnostic** (supporting Ubuntu/Debian and RHEL/Rocky Linux) and **Non-Destructive** (it uses `#include` statements to inject configurations without overwriting system defaults).

## 📋 Requirements

* **Ansible:** 2.12 or higher.
* **Ansible Collections:** `community.general` (Required for `.ini` configuration).
* **Target OS:**
    * Ubuntu 22.04 LTS / 24.04 LTS (**Recommended** / Fully Supported)
    * Red Hat Enterprise Linux (RHEL) 9 / Rocky Linux 9 (**Recommended** / Fully Supported)
    * RHEL/Rocky 8 (Legacy / Supported)
    * RHEL/Rocky 10 (**Experimental**: Requires manual addition of Asterisk repositories as they are not yet available in EPEL 10)

> [!TIP]
> **Why Rocky 9?** As of early 2026, Asterisk packages are readily available in the official EPEL 9 repositories. EPEL 10 is still being populated, and automated installation on Rocky 10 will fail until the packages are added by the community.
* **Access:** SSH with `sudo` privileges on the target machine.

---

## 🚀 Installation

There are two ways to install this role into your project.

### Option A: Local Directory (Recommended for Dev)
Simply copy the entire folder `asterisk_py_phone_caller` into your project's `roles/` directory.

Project structure:
```text
my-project/
├── inventory.ini
├── deploy_asterisk.yml
└── roles/
    └── asterisk_py_phone_caller/
        ├── defaults/
        ├── tasks/
        ├── templates/
        └── ...
```

### Option B: Via `requirements.yml` (Best for Git Ops)
If you host this role in a separate Git repository, add it to your `requirements.yml`:

```yaml
# requirements.yml
roles:
  - src: https://github.com/your-org/asterisk_py_phone_caller.git
    scm: git
    version: main
    name: asterisk_py_phone_caller
```

Then install it:
```bash
ansible-galaxy install -r requirements.yml -p ./roles
```

---

## ⚙️ Configuration

### 1. Required Audio Files
Before running the role, you **must** place your custom `.wav` (or `.gsm`) audio files in the `files/sounds/` directory of the role.

```text
roles/asterisk_py_phone_caller/files/sounds/
├── greeting-message.wav
└── press-4-for-acknowledgement.wav
```
*The role will skip deployment of these files if they are missing (a warning will be displayed).*

### 2. Role Variables
These variables can be overridden in your `playbook`, `inventory`, or `group_vars`.

| Variable | Default | Description |
| :--- | :--- | :--- |
| **HTTP / ARI** | | |
| `asterisk_http_enabled` | `"yes"` | Enables the internal HTTP server for ARI. |
| `asterisk_http_bindaddr` | `"0.0.0.0"` | IP address to bind HTTP server (0.0.0.0 for all). |
| `asterisk_http_bindport` | `8088` | Port for ARI (HTTP). |
| `ari_app_name` | `"py-phone-caller"` | Stasis application name used in Python/Rust. |
| `ari_username` | `"py-phone-caller"` | ARI API Username. |
| `ari_password` | `"CHANGE_ME"` | **SECURE:** ARI API Password. |
| **SIP Trunking** | | |
| `sip_provider_host` | `"sip.messagenet.it"` | Hostname or IP of the SIP Provider or Gateway. |
| `sip_provider_port` | `5061` | Port of the SIP Provider or Gateway. |
| `sip_username` | `"5318393"` | SIP Username (Authentication ID). |
| `sip_password` | `"CHANGE_ME"` | **SECURE:** SIP Password. |
| `sip_contact_user` | `"0719256355"` | The number/user presented in the Contact header. |
| `asterisk_sip_bindaddr` | `"0.0.0.0:5060"` | Local address and port for PJSIP to listen on. |
| **Integration** | | |
| `callback_service_url` | `"http://127.0.0.1:8083"` | URL of the Rust/Python service to receive CURL events. |
| `asterisk_extension` | `"3216"` | The extension number to trigger the py-phone-caller logic. |

---

## 📖 Usage Examples

### Scenario A: Cloud Provider (Development/Online)
Use this configuration when connecting to a VoIP provider like Messagenet over the Internet.

```yaml
# deploy_asterisk.yml
- name: Deploy Asterisk (Cloud Trunk)
  hosts: pbx_servers
  become: yes
  roles:
    - asterisk_py_phone_caller
  vars:
    sip_provider_host: "sip.messagenet.it"
    sip_username: "5318393"
    sip_password: "{{ vault_messagenet_password }}" # Encrypted via Ansible Vault
    ari_password: "{{ vault_ari_password }}"
```

### Scenario B: Air-Gapped (Production/Emergency)
Use this configuration when the PBX is offline and connected via LAN to a physical GSM Gateway (e.g., Yeastar/Dinstar).

```yaml
# deploy_asterisk.yml
- name: Deploy Asterisk (Air-Gapped GSM Gateway)
  hosts: pbx_servers
  become: yes
  roles:
    - asterisk_py_phone_caller
  vars:
    # IP Address of the physical GSM Gateway on the LAN
    sip_provider_host: "192.168.1.200"
    
    # Credentials configured INSIDE the GSM Gateway for this trunk
    sip_username: "asterisk_trunk"
    sip_password: "{{ vault_gateway_password }}"
    
    # How Asterisk identifies itself to the Gateway
    sip_contact_user: "asterisk"
```

---

## 🏃 How to Run

### 1. Dry Run (Test)
Check what changes will be made without applying them:
```bash
ansible-playbook -i inventory.ini deploy_asterisk.yml --check
```

### 2. Deploy
Apply configuration and restart Asterisk:
```bash
ansible-playbook -i inventory.ini deploy_asterisk.yml
```

## ✅ Testing & Verification

After the playbook finishes, verify the status on the target server using the following steps.

### 1. Check SIP Registration
Verify that Asterisk has successfully registered with your SIP provider (e.g., Messagenet):
```bash
asterisk -x "pjsip show registrations"
```
*Expected status: **Registered***

### 2. Verify PJSIP Endpoints
Ensure the `py-phone-caller` endpoint is active and bound to the correct transport:
```bash
asterisk -x "pjsip show endpoints"
```

### 3. Check ARI User & Connectivity
Verify that the ARI user is correctly configured and the HTTP interface is reachable:
```bash
# Check ARI user in Asterisk
asterisk -x "ari show users"

# Test ARI connectivity via CURL (Run from the server)
# Replace 'CHANGE_ME' with your actual ari_password
curl -v -u py-phone-caller:CHANGE_ME http://localhost:8088/ari/asterisk/info
```

### 4. Validate Dialplan
Ensure the custom dialplan context and extension are properly loaded:
```bash
asterisk -x "dialplan show py-phone-caller"
```
*You should see extension `3216` (or your custom `asterisk_extension`) with its associated priorities.*

### 5. Confirm Audio Deployment
Check that the custom alert messages are present and have the correct ownership:
```bash
ls -l /var/lib/asterisk/sounds/en/greeting-message.wav
ls -l /var/lib/asterisk/sounds/en/press-4-for-acknowledgement.wav
```

---

## 🧩 Architecture Notes
* **Non-Destructive:** This role injects configuration via `#include` in `pjsip.conf`, `extensions.conf`, and `ari.conf`. It does not delete existing configurations.
* **Module Management:** The role explicitly disables the deprecated `chan_sip.so` in `modules.conf` to avoid port conflicts with PJSIP (standard port 5060).
* **Security:** This role configures Asterisk with `dialout` permissions (on RHEL) only if strictly necessary. For Air-Gapped GSM setups using SIP Gateways, no special hardware privileges are required.
* **Logs:** Asterisk logs are located at `/var/log/asterisk/full` (or `messages.log` on some Debian systems).

---
### 🛠 Troubleshooting: 403 Forbidden Errors
If you see a `403 Forbidden` error during SIP registration:
1. **Check Credentials:** Ensure `sip_username` and `sip_password` are correct in `deploy_asterisk.yml`.
2. **Account Status:** Verify with your provider (e.g., Messagenet) that the account is active and not locked due to too many failed attempts.
3. **Wait it Out:** The role now configures `forbidden_retry_interval=600`, which means Asterisk will wait 10 minutes before retrying after a 403 error. This prevents your IP from being blacklisted by the provider. You can trigger a manual retry by reloading PJSIP: `asterisk -x "pjsip reload"`.

---
**Maintained by:** py-phone-caller team