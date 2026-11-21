# Documentation Archive

This directory preserves historical, pre-release, superseded, or out-of-scope documentation for `py-phone-caller`.
These files are retained for historical traceability and are **not** maintained for current releases.

For current, verified documentation, start at **[`docs/README.md`](../README.md)** and the modular **[`deploy/docs/README.md`](../../deploy/docs/README.md)** deployment hub.

---

## Archived Documents & Canonical Replacements

| Archived File | Reason for Archiving | Current Canonical Replacement |
| :--- | :--- | :--- |
| [`OPERATOR_INSTALLATION_GUIDE.md`](OPERATOR_INSTALLATION_GUIDE.md) | Monolithic legacy installation guide pre-dating modular Ansible roles, Kubernetes/Helm, DEB/RPM, PyPI/systemd, ARM64 air-gapped appliances, and OpenAlert integration | **[`deploy/docs/README.md`](../../deploy/docs/README.md)** (Modular Guides `01`–`10`) |
| [`1.0.0-release.md`](1.0.0-release.md) | August 2026 pre-release 1.0.0 planning roadmap ("Caddy first, APISIX later") | **[`docs/ENTERPRISE_GATEWAY_AND_IAM_GUIDE.md`](../ENTERPRISE_GATEWAY_AND_IAM_GUIDE.md)** & **[`docs/1.0.1-release.md`](../1.0.1-release.md)** |
| [`release-1.0.0-audit-report.md`](release-1.0.0-audit-report.md) | Point-in-time pre-1.0.0 codebase snapshot (55 tests, pre-Silero, pre-Option C dual-contact SMS/SIP, pre-OpenAlert) | **[`docs/architecture-and-call-flows.md`](../architecture-and-call-flows.md)** & **[`docs/services-and-endpoints.md`](../services-and-endpoints.md)** |
| [`deployment-validation-report.md`](deployment-validation-report.md) | Point-in-time 1.0.0 pre-release VM validation log using legacy Ansible playbook paths | **[`deploy/docs/10-end-to-end-installation-validation.md`](../../deploy/docs/10-end-to-end-installation-validation.md)** & **[`deploy/ansible/docs/support-matrix.md`](../../deploy/ansible/docs/support-matrix.md)** |
| [`pre-release-2026.md`](pre-release-2026.md) | Obsolete August 2026 pre-1.0.0 gap assessment | **[`docs/README.md`](../README.md)** |
| [`RELEASE_CANDIDATE_GUIDE.md`](RELEASE_CANDIDATE_GUIDE.md) | Pre-1.0.0 release candidate checklist | **[`deploy/docs/08-release-packaging.md`](../../deploy/docs/08-release-packaging.md)** |
| [`how_to_install_this_stuff.md`](how_to_install_this_stuff.md) | Legacy informal installation notes with obsolete container/package references | **[`deploy/docs/README.md`](../../deploy/docs/README.md)** |
| [`py-phone-caller_2025.05.md`](py-phone-caller_2025.05.md) | Legacy May 2025 architecture archive (pre-UV workspace, pre-Python 3.14) | **[`docs/architecture-and-call-flows.md`](../architecture-and-call-flows.md)** |
| [`virtualbox-setup.md`](virtualbox-setup.md) | Out-of-scope legacy two-VM VirtualBox + FreePBX desktop lab guide | **[`deploy/docs/03-docker-compose-deployment.md`](../../deploy/docs/03-docker-compose-deployment.md)** & **[`docs/freepbx-asterisk-setup-guide.md`](../freepbx-asterisk-setup-guide.md)** |
