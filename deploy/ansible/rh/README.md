# Legacy Red Hat / Fedora Podman Playbook (`deploy/ansible/rh/`)

> **Status: Experimental / Unqualified Legacy Container Path**

This directory (`deploy/ansible/rh/`) contains an older standalone Podman container playbook (`py-phone-caller-podman.yml`) and variable/template examples (`py_phone_caller_vars_file.yml`, `caller_config.toml.jinja2`) originally created for single-host rootful/rootless Podman container experimentation on Red Hat / Fedora.

## Important Boundaries

1. **Not the Canonical Ansible Entry Point**:
   - For native `systemd` deployments of `OpenAlert`, `py-phone-caller`, and `Asterisk`, use [`deploy/ansible/site.yml`](../site.yml) and follow the [Canonical Ansible Deployment Guide](../README.md).
   - For container deployments, use the canonical root [`docker-compose.yml`](../../../docker-compose.yml) or Kubernetes/Helm manifests under [`deploy/k8s/`](../../k8s/) and [`deploy/helm/py-phone-caller/`](../../helm/py-phone-caller/).
2. **Rocky Linux 10 Qualification Status**:
   - Native Rocky Linux 10 AMD64 support is tracked under `deploy/ansible/site.yml` and [`docs/asterisk-provider.md`](../docs/asterisk-provider.md). As documented in [`docs/support-matrix.md`](../docs/support-matrix.md), the evaluated Tucny EL10 Asterisk `22.11.0-1.el10` build is currently blocked at the required `res_ari_events.so` symbol check (`stasis_app_claim_channel`).
   - Do not use this legacy `rh/` Podman playbook as a substitute for native `systemd` qualification or enterprise profile validation.
