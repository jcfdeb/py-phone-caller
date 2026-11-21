# Deployment Consolidation & Asset Classification

This document inventories the deployment assets across `deploy/ansible/`, `deploy/systemd/`, and `deploy/gateway/`, classifying canonical entry points, supported compatibility wrappers, experimental/unqualified paths, and removed obsolete duplicates (Step 5 of the Ansible production role consolidation).

## 1. Canonical Entry Points & Shared Roles

| Path | Classification | Responsibility |
| --- | --- | --- |
| [`deploy/ansible/site.yml`](../site.yml) | **Canonical** | Primary inventory-driven entry point for `OpenAlert`, `py-phone-caller`, and `Asterisk` on `AMD64` and `ARM64`. |
| [`deploy/ansible/playbooks/adopt.yml`](../playbooks/adopt.yml) | **Canonical** | Explicit OpenAlert adoption playbook (`adopt-openalert-in-place` and `relocate: true` / `adopt-openalert-relocate`). |
| [`deploy/ansible/playbooks/backup.yml`](../playbooks/backup.yml), [`restore.yml`](../playbooks/restore.yml), [`rollback.yml`](../playbooks/rollback.yml) | **Canonical** | Explicit maintenance-window backup, restore, and asset-only rollback playbooks via `roles/stack_lifecycle`. |
| [`deploy/ansible/verify.yml`](../verify.yml) | **Canonical** | Non-dispatching post-deployment health and service verification. |
| [`deploy/ansible/roles/`](../roles/) | **Canonical** | Shared modular role tree (`stack_preflight`, `stack_airgap`, `stack_lifecycle`, `openalert`, `deploy_py-phone-caller`, `asterisk_py_phone_caller`, `postgresql`, `queue`, `gateway`, `reverse_proxy`, `firewall`). |
| [`deploy/ansible/tools/toml_to_ansible_vars.py`](../tools/toml_to_ansible_vars.py) | **Canonical** | Converts `src/config/settings.toml` and `.secrets.toml` into Ansible variables. |
| [`src/openalert/packaging/systemd/openalertd.service`](../../../src/openalert/packaging/systemd/openalertd.service) | **Canonical** | Hardened base `systemd` unit packaged into OpenAlert release bundles and consumed by `roles/openalert`. |

## 2. Retained Compatibility Wrappers

| Path | Classification | Target / Behavior |
| --- | --- | --- |
| [`deploy/ansible/on-vm_py-phone-caller/deploy_py-phone-caller.yml`](../on-vm_py-phone-caller/deploy_py-phone-caller.yml) | **Compatibility Wrapper** | Imports `../site.yml` with `app_servers` group and Python-only selection (`stack_deploy_py_phone_caller: true`). |
| [`deploy/ansible/on-vm_py-phone-caller/test_deploy.yml`](../on-vm_py-phone-caller/test_deploy.yml) | **Compatibility Wrapper** | Imports `deploy_py-phone-caller.yml` for backwards compatibility with earlier CLI invocations. |
| [`deploy/ansible/on-vm_py-phone-caller/verify.yml`](../on-vm_py-phone-caller/verify.yml) | **Compatibility Wrapper** | Imports `../verify.yml` for `app_servers`. |
| [`deploy/ansible/on-vm_py-phone-caller/render_check.yml`](../on-vm_py-phone-caller/render_check.yml) | **Offline Render Check** | Offline template and TOML parity validator using synthetic fixtures by default. |
| [`deploy/ansible/asterisk_py-phone-caller/deploy_asterisk.yml`](../asterisk_py-phone-caller/deploy_asterisk.yml) | **Compatibility Wrapper** | Imports `../site.yml` with `pbx_servers:all` and PBX-only selection (`stack_deploy_asterisk: true`). |
| [`deploy/ansible/deploy_all/deploy_py-phone-caller_stack.yml`](../deploy_all/deploy_py-phone-caller_stack.yml) | **Compatibility Wrapper** | Imports `../site.yml` for combined Asterisk + Python deployment on `app_servers`. |
| [`deploy/gateway/keycloak/setup_keycloak.py`](../../gateway/keycloak/setup_keycloak.py) & [`deploy/gateway/apisix/setup_apisix_routes.py`](../../gateway/apisix/setup_apisix_routes.py) | **Synchronized Reference Copies** | Kept byte-identical to `deploy/ansible/roles/gateway/files/setup_*.py` (hardened, no default passwords or credential printing) for standalone operator reference in `docs/ENTERPRISE_GATEWAY_AND_IAM_GUIDE.md`. |
| [`deploy/systemd/on-system/`](../../systemd/on-system/) | **Standalone Reference Units** | Reference `systemd` unit files for manual non-Ansible reference; `openalertd.service` is kept identical to `src/openalert/packaging/systemd/openalertd.service`. |

## 3. Experimental / Unqualified Paths

| Path | Classification | Notes |
| --- | --- | --- |
| [`deploy/ansible/rh/`](../rh/README.md) | **Experimental / Legacy Podman** | Standalone Red Hat / Fedora Podman playbook retained for historical reference; not part of `site.yml` qualification. |
| [`deploy/systemd/as-non-root-container/`](../../systemd/as-non-root-container/Readme.txt) | **Experimental / Legacy Podman Units** | Static rootless Podman user unit examples; not managed by `site.yml`. |
| Tucny EL10 Asterisk provider (`roles/asterisk_py_phone_caller/tasks/*tucny*.yml`) | **Qualified Opt-In Provider (`22.9.0-1.el10`)** | Opt-in Rocky 10 DNF provider pinned to `22.9.0-1.el10` (complete symbol closure across `res_ari_events.so` and `res_stasis.so`; upstream `22.10.1-1.el10` through `22.12.0-1.el10` remain excluded due to missing `stasis_app_claim_channel` symbol). |

## 4. Removed Obsolete Duplicates (Completed Post-Step 4 Qualification)

Following completion of Step 4 runtime qualification across Debian 13 `AMD64`, Ubuntu 26.04 LTS `AMD64`, and Rocky Linux 10.2 `AMD64`, the following pre-`uv`-workspace `systemd` unit files in `deploy/systemd/on-system/` were removed as obsolete duplicates of the canonical hyphenated module-based units in the same directory:
- `deploy/systemd/on-system/asterisk-call.service` (superseded by `asterisk-caller.service`)
- `deploy/systemd/on-system/call-register.service` (superseded by `caller-register.service`)
- `deploy/systemd/on-system/caller_prometheus_webhook.service` (superseded by `caller-prometheus-webhook.service`)
- `deploy/systemd/on-system/caller_sms.service` (superseded by `caller-sms.service`)
