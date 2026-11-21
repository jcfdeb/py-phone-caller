# 02. Native Ansible Deployment Guide (`deploy/ansible`)

The **Modular Native Ansible Installer** (`deploy/ansible/site.yml`) is the flagship bare-metal and virtual-machine installer for `py-phone-caller`, `openalertd`, and `Asterisk PBX`.

It allows you to independently select any combination of the three core components (`stack_deploy_py_phone_caller`, `stack_deploy_asterisk`, `stack_deploy_openalert`), choose between `standard` and `enterprise` (APISIX + Keycloak OIDC) topologies, run either `online` or 100% `airgapped`, and manage full operational lifecycles (`adopt.yml`, `backup.yml`, `restore.yml`, `rollback.yml`).

> [!NOTE]
> **Verified OS Matrix (`2026-11-19`)**
> - **Debian 13 (`trixie`) AMD64**: Qualified for `standard` (`online` & `airgapped`), `enterprise`, AllStarLink Asterisk 22 (`2:22.10.1+asl3-3.10.8-1.deb13`), and OpenAlert systemd lifecycle/adoption.
> - **Ubuntu 26.04.1 LTS (`resolute`) AMD64**: Qualified for `standard` (`online` & `airgapped`), `enterprise`, official Ubuntu Asterisk 22 (`1:22.5.2~dfsg`), and OpenAlert systemd lifecycle/adoption.
> - **Rocky Linux 10.2 AMD64 (`SELinux Enforcing`)**: Qualified for `online` `standard` and `enterprise` with Tucny Asterisk 22 (`22.9.0-1.el10`), OpenAlert systemd lifecycle (`openalertd.service`), Valkey, and live Keycloak OIDC login.
> - **ARM64 (`aarch64` / Orange Pi 5 Plus RK3588, Armbian 26.11.3 / Ubuntu 26.04 LTS)**: Qualified for all-in-one `standard` (`online` & `airgapped`) with Asterisk 22 (`distro`), PostgreSQL 18, Redis 8, Caddy internal TLS, `openalertd v1.0.0` (`arm64`), offline Piper TTS, authentic UI login, `changed=0` reruns, and cold-reboot recovery. See **[09. ARM64 Appliance & Air-Gapped Deployment](09-arm64-appliance-and-airgapped-deployment.md)** and **[10. End-to-End Installation Validation](10-end-to-end-installation-validation.md)**.

---

## Step 1: Set Up the Ansible Controller Environment

Run these commands on your workstation or deployment controller (requires **Python 3.12–3.14**):

```bash
cd deploy/ansible

# 1. Create and activate an isolated controller virtual environment (or use your project .venv)
python3 -m venv .venv-ansible
source .venv-ansible/bin/activate

# 2. Point Ansible to the repository's pinned ansible.cfg (no implicit inventory)
export ANSIBLE_CONFIG="$PWD/ansible.cfg"

# 3. Install pinned ansible-core (2.20.0) and ansible-lint (25.12.2)
python -m pip install --upgrade pip
python -m pip install -r tests/requirements-controller.txt

# 4. Install pinned Ansible Galaxy collections into deploy/ansible/.collections
ansible-galaxy collection install -r requirements.yml -p "$PWD/.collections"
```

> [!TIP]
> **Using the Pre-Built Offline Ansible Bundle (`dist/ansible/`)**
> If you extracted `dist/ansible/py-phone-caller-ansible-v1.0.0-offline.tar.gz`, the `.collections/` directory is already bundled and verified inside the archive—you can skip step 4!

---

## Step 2: Convert Existing `settings.toml` & `.secrets.toml` (Optional Helper)

If you already configured `src/config/settings.toml` and `src/config/.secrets.toml`, you can automatically convert them into Ansible inventory variables (`config.yml` and `secrets.yml`) using the included converter tool:

```bash
python3 tools/toml_to_ansible_vars.py \
  --input ../../src/config/settings.toml \
  --input ../../src/config/.secrets.toml \
  --output /tmp/my-ppc-inventory-vars/config.yml \
  --secrets-output /tmp/my-ppc-inventory-vars/secrets.yml
```

*(Or simply run `python3 tools/toml_to_ansible_vars.py --output /tmp/my-ppc-inventory-vars/config.yml --secrets-output /tmp/my-ppc-inventory-vars/secrets.yml`, since it reads `src/config/settings.toml` and `src/config/.secrets.toml` by default!)*

Encrypt the generated `secrets.yml` immediately with Ansible Vault:

```bash
ansible-vault encrypt /tmp/my-ppc-inventory-vars/secrets.yml
```

> **Important Security Gate (`validate.yml`)**: The `deploy_py-phone-caller` Ansible role enforces a strict pre-flight secret check and will refuse to deploy if `asterisk_pass`, `db_password`, or `ui_secret_key` still contain default template placeholders (`"change_me"` or `"super_secure_password"`). Ensure you set real credentials in `.secrets.toml` (or `secrets.yml`) before running `site.yml`.

---

## Step 3: Create Your Explicit Inventory (`hosts.yml`)

`deploy/ansible/ansible.cfg` intentionally defines **no default inventory** so you can never accidentally overwrite a production host. You must always pass `-i /path/to/hosts.yml` and explicitly set all three component selectors (`true` or `false`):

```yaml
stack_deploy_py_phone_caller: true   # 11 Python services + PostgreSQL + Redis + Caddy
stack_deploy_asterisk: true          # Local Asterisk 22 PBX (PJSIP / IAX2 / ARI)
stack_deploy_openalert: true         # openalertd daemon(s)
```

### Choose a Starting Example Inventory

Copy one of the ready-made templates from `deploy/ansible/inventories/examples/` to a private directory outside Git:

| Example Inventory Path | Topology & Purpose |
| :--- | :--- |
| [`inventories/examples/openalert-only/hosts.yml`](../ansible/inventories/examples/openalert-only/hosts.yml) | Single `openalertd` instance (`hub` on `127.0.0.1:8090`) |
| [`inventories/examples/two-instances/hosts.yml`](../ansible/inventories/examples/two-instances/hosts.yml) | Two isolated `openalertd` instances (`hub` `:8090` + `public` `:8092`) on one host |
| [`inventories/examples/pbx-allstarlink/hosts.yml`](../ansible/inventories/examples/pbx-allstarlink/hosts.yml) | Standalone Asterisk 22 PBX on Debian 13 via AllStarLink |
| [`inventories/examples/pbx-ubuntu/hosts.yml`](../ansible/inventories/examples/pbx-ubuntu/hosts.yml) | Standalone Asterisk 22 PBX on Ubuntu 26.04 LTS via official Ubuntu packages |
| [`inventories/examples/enterprise/hosts.yml`](../ansible/inventories/examples/enterprise/hosts.yml) | **Enterprise Stack**: Python suite + Asterisk + OpenAlert + Apache APISIX Gateway + Keycloak OIDC SSO |
| [`inventories/examples/standard-airgapped/hosts.yml`](../ansible/inventories/examples/standard-airgapped/hosts.yml) | **Standard / Air-Gapped Stack**: Python suite + Asterisk + OpenAlert with local UI login (can be switched to `online` by setting `py_phone_caller_connectivity: online`) |
| [`inventories/examples/appliance-orangepi5plus/hosts.yml`](../ansible/inventories/examples/appliance-orangepi5plus/hosts.yml) | **ARM64 Appliance Profile (Qualified on Orange Pi 5 Plus RK3588)**: All-in-one ARM64 stack with tuned worker counts and systemd cgroup v2 memory/CPU quotas (see [Guide 09](09-arm64-appliance-and-airgapped-deployment.md)) |

### Complete Example: Combined Standard Stack (`hosts.yml`)

Below is a complete, step-by-step `hosts.yml` for deploying **Python + Asterisk + OpenAlert** on a fresh Debian 13 or Ubuntu 26.04 server:

```yaml
---
all:
  children:
    stack:
      hosts:
        alert-server-01:
          ansible_host: 192.0.2.50
          ansible_user: debian
          ansible_become: true

          # 1. Explicit Component Selectors (all 3 required)
          stack_deploy_py_phone_caller: true
          stack_deploy_asterisk: true
          stack_deploy_openalert: true

          # 2. Topology & Ingress Profile
          py_phone_caller_topology: standard       # 'standard' (local UI login) or 'enterprise' (APISIX + Keycloak OIDC)
          py_phone_caller_connectivity: online     # 'online' or 'airgapped'
          py_phone_caller_ingress: caddy           # 'caddy' or 'external'
          py_phone_caller_tls_mode: internal       # 'acme', 'internal', 'provided', or 'external'
          py_phone_caller_public_url: "https://alerts.example.internal"
          caddy_domain_name: "alerts.example.internal"

          # 3. Source Delivery & Pinned Installer Checksums
          py_phone_caller_local_src_path: /abs/path/to/py-phone-caller
          py_phone_caller_uv_installer_checksum: "sha256:1f2aa4d24003ae99e4979f87f5e3122d240ec6b1ef0bc06c4bee3e33bb9151f2"
          py_phone_caller_spacy_model_checksum: "sha256:1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85"
          py_phone_caller_caddy_signing_key_checksum: "sha256:783dfee04b19e851a928cd87b34710213ebbe7628f98d9f34595ab83be578c00"

          # 4. Asterisk Package Provider
          #    - Debian 13: 'allstarlink' (requires asterisk_http_bindaddr: "127.0.0.1")
          #    - Ubuntu 26.04: 'distro'
          #    - Rocky Linux 10: 'tucny' (requires asterisk_http_bindaddr: "127.0.0.1")
          asterisk_package_provider: allstarlink
          asterisk_http_bindaddr: "127.0.0.1"
          asterisk_sip_bindaddr: "127.0.0.1:5060"
          asterisk_sip_trunk_enabled: false
          local_sip: false
          local_iax: false
          # Set true (with asterisk_sip_bindaddr: "0.0.0.0:5060") to auto-provision
          # ready-to-use local SIP extension 1000 with a random password logged on run:
          asterisk_sip_exten_1000_enabled: false

          # 5. Load reviewed Python config & encrypted secrets vars files
          stack_py_phone_caller_vars_files:
            - /tmp/my-ppc-inventory-vars/config.yml
            - /tmp/my-ppc-inventory-vars/secrets.yml

          # 6. Single-node & Standard-profile overrides
          #    Setting db_host and queue_host to "127.0.0.1" instructs the role to automatically
          #    install and configure local PostgreSQL and Redis/Valkey on this server.
          py_phone_caller_config_overrides:
            commons:
              asterisk_host: "127.0.0.1"
            database:
              db_host: "127.0.0.1"
            queue:
              queue_host: "127.0.0.1"
            auth:
              provider: local
              oauth2:
                enabled: false
            gateway:
              behind_gateway: false
            py_phone_caller_ui:
              ui_listen_on_host: "127.0.0.1"
            caller_sms:
              caller_sms_carrier: twilio

          # 7. OpenAlert Release Bundle & Instance Definition (mapping keyed by instance name)
          openalert_release:
            source: /abs/path/to/src/openalert/dist/openalertd-v0.2.0-linux-x86_64.tar.gz
            sha256: "86f444506182b2e2ada4fc7efea1ea77a61752ec8f63daefef99de5d1ead5b40"
          openalert_instances:
            hub:
              service_name: openalertd.service
              config_template: "{{ playbook_dir }}/inventories/examples/templates/private.toml.j2"
              health_url: "http://127.0.0.1:8090/health"
              rest_port: 8090
              openalert_schema:
                current: "1"
                target: "1"
```

> [!IMPORTANT]
> **Using or Building the OpenAlert Release Archive (`openalert_release.source`)**
> The verified `v0.2.0` release bundle (containing `release.json` contract metadata) is included at `src/openalert/dist/openalertd-v0.2.0-linux-x86_64.tar.gz` (and `src/openalert/dist/phase1-validation-20261030/openalertd-v0.2.0-linux-x86_64.tar.gz`). If you rebuild `openalertd` from source, run:
> ```bash
> cargo build --release --manifest-path src/openalert/Cargo.toml
> ./src/openalert/packaging/build_release_bundle.sh \
>   --target x86_64-unknown-linux-gnu \
>   --binary src/openalert/target/release/openalertd \
>   --source-revision "$(git rev-parse HEAD)" \
>   --build-baseline "debian-13-amd64" \
>   --rustc-version "rustc 1.99.1" \
>   --output-dir src/openalert/dist
> ```
> Copy the printed `Archive:` path and `SHA-256:` digest into `openalert_release.source` and `openalert_release.sha256`.

---

## Step 4: Pre-Flight Validation & Deployment

Always run the inventory graph and syntax checks first, then execute `site.yml`:

```bash
cd deploy/ansible
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
export MY_INVENTORY="/abs/path/to/my-inventory/hosts.yml"

# 1. Verify inventory structure and host targeting
ansible-inventory -i "$MY_INVENTORY" --graph
ansible-playbook -i "$MY_INVENTORY" site.yml --list-hosts
ansible-playbook -i "$MY_INVENTORY" site.yml --syntax-check

# 2. Run the deployment (add --ask-vault-pass if using encrypted secrets.yml)
ansible-playbook -i "$MY_INVENTORY" site.yml --limit alert-server-01 --ask-become-pass --ask-vault-pass
```

> [!WARNING]
> **Do not pass `--check` to `site.yml` when `stack_deploy_openalert: true`.**
> The `openalert` role validates candidate binaries, system users, and staged configuration files on disk before switching services and intentionally fails closed if invoked in `--check` dry-run mode. To test template rendering locally without touching any host, run:
> ```bash
> ansible-playbook -i localhost, -c local tests/render.yml
> ```

---

## Step 5: Post-Deployment Verification (`verify.yml`)

After `site.yml` finishes with `failed=0`, run the read-only verification playbook to confirm all systemd services, private listeners, and HTTP `/health` endpoints are healthy:

```bash
ansible-playbook -i "$MY_INVENTORY" verify.yml --limit alert-server-01 --ask-become-pass --ask-vault-pass
```

You can also run `site.yml` a second time to confirm **idempotency** (`changed=0` across all tasks).

---

## Step 6: Day-2 Lifecycle Operations (Backup, Restore, Rollback & Adoption)

The Ansible suite includes dedicated Day-2 operational playbooks under `deploy/ansible/playbooks/`. All lifecycle operations acquire a host lock (`/run/lock/py-phone-caller-lifecycle`) and require explicit maintenance confirmation:

| Playbook | Purpose | Command Example |
| :--- | :--- | :--- |
| **`playbooks/backup.yml`** | Creates a verified, hash-manifested snapshot of OpenAlert SQLite databases (via online SQLite backup API), configs, and local PostgreSQL (`pg_dump --format=custom`) | `ansible-playbook -i "$MY_INVENTORY" playbooks/backup.yml --limit alert-server-01` |
| **`playbooks/restore.yml`** | Restores a verified snapshot (keeps services stopped by default until operator review) | `ansible-playbook -i "$MY_INVENTORY" playbooks/restore.yml --limit alert-server-01` |
| **`playbooks/rollback.yml`** | Rolls back binaries, units, and configs when `schema_compat_id` matches (refuses automatic rollback across incompatible DB migrations) | `ansible-playbook -i "$MY_INVENTORY" playbooks/rollback.yml --limit alert-server-01` |
| **`playbooks/adopt.yml`** | Safely adopts an existing unmanaged `openalertd` systemd unit (in-place or with `relocate: true` from `/root` or `/home/<user>` into `/var/lib/openalert/...`) | `ansible-playbook -i "$MY_INVENTORY" playbooks/adopt.yml --limit alert-server-01` |

---

## Deep-Dive Ansible Reference Documents

For specialized topics, see the detailed topical references inside `deploy/ansible/docs/`:
- **[OpenAlert Role Contract & Variables](../ansible/docs/openalert.md)**
- **[Python Native Role & Variable Mapping](../ansible/docs/python-native.md)**
- **[Asterisk Providers (AllStarLink, Ubuntu Official, Tucny EL10) & PJSIP/IAX2](../ansible/docs/asterisk-provider.md)**
- **[Standard, Enterprise & Air-Gapped Topologies](../ansible/docs/topologies.md)**
- **[Backup, Restore, Rollback & Legacy Adoption Runbook](../ansible/docs/lifecycle.md)**
- **[Orange Pi 5 Plus ARM64 Appliance Contract](../ansible/docs/appliance-arm64.md)**
- **[Support Matrix & Cloud VM Qualification Ledger](../ansible/docs/support-matrix.md)**
