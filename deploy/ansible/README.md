# Native Ansible deployment

> **Centralized Step-by-Step Guide**: See **[`deploy/docs/02-ansible-deployment.md`](../docs/02-ansible-deployment.md)** (and the **[Deployment Documentation Hub](../docs/README.md)**) for the unified step-by-step operator walkthrough across all deployment pillars.

`site.yml` is the canonical entry point for explicitly selected OpenAlert,
Python application and Asterisk components. **Component-only, combined, `standard`
`airgapped`, `enterprise`, and OpenAlert lifecycle/relocation checks are qualified
on Debian 13 AMD64, Ubuntu 26.04 LTS AMD64, Rocky Linux 10 AMD64, and AlmaLinux 10
AMD64 VMs/cloud instances; physical Orange Pi 5 Plus ARM64 hardware and live
telephony/radio dispatch remain separate validation gates.**
Start on a disposable, explicitly authorized host. This documentation does not
authorize changing or migrating a live installation.

- [OpenAlert contract and variable reference](docs/openalert.md)
- [Python inputs and compatibility/ownership mapping](docs/python-native.md)
- [Standard/enterprise topologies and fully offline installation](docs/topologies.md)
- [ARM64 appliance profile (Orange Pi 5 Plus pre-hardware contract)](docs/appliance-arm64.md)
- [Asterisk: Ubuntu, AllStarLink and Tucny (`22.9.0-1.el10`) providers, PJSIP/IAX2](docs/asterisk-provider.md)
- [Deployment consolidation and asset classification](docs/consolidation.md)
- [Support matrix and qualification evidence](docs/support-matrix.md)
- [Ansible release bundle packaging](packaging/README.md)
- [Native release packaging](../../src/openalert/packaging/README.md)

## Scope and prerequisites

The new entry point accepts Debian 13 or Ubuntu 26.04 on AMD64 (`x86_64`) or
ARM64 (`aarch64`), and Rocky 10 on AMD64 (online with `asterisk_package_provider: tucny`
pinned to `22.9.0-1.el10`), with `systemd`. OpenAlert requires managed-host Python 3.11+,
SSH access with privilege escalation, and a compatible trusted release bundle.
An accepted platform is not a qualified deployment; see the support matrix.
OpenAlert uses prebuilt releases; its Rust binary is not compiled on the managed
host. The Python stack's native SMS extension has separate build requirements.

Python and PBX implementations now live under the shared `roles/` tree.
Runtime consolidation checks pass; full lint still has recorded naming findings,
which were explicitly deferred on 2026-11-01 to allow lifecycle work to proceed.
Their additional dependencies
and configuration requirements still apply; OpenAlert-only selection does not
require their configuration or install those components.

## Canonical quickstart: private OpenAlert

### 1. Prepare the controller

Use a dedicated controller environment with Python supported by the pinned
Ansible release (Python 3.12–3.14 for `ansible-core` 2.20). With that environment
activated, run from the repository root:

```bash
cd deploy/ansible
export ANSIBLE_CONFIG="$PWD/ansible.cfg"
python -m pip install -r tests/requirements-controller.txt
ansible-galaxy collection install -r requirements.yml -p "$PWD/.collections"
```

`tests/requirements-controller.txt` pins `ansible-core==2.20.0` and
`ansible-lint==25.12.2`. `requirements.yml` pins `ansible.posix==2.1.0`,
`community.general==12.0.1` and `community.postgresql==4.2.0`; install them into
this directory's `.collections`, not an unspecified global collection path.
The disposable test host additionally uses the separate
`tests/requirements.yml`; it is not required for an SSH deployment.

### 2. Prepare an explicit, protected inventory

Copy [the one-instance example](inventories/examples/openalert-only/hosts.yml)
or [the two-instance example](inventories/examples/two-instances/hosts.yml)
into an operator-controlled inventory. Preserve the sibling `templates/`
layout when copying the examples, or change each `config_template` to its
reviewed controller-side path. Keep real inventory and secrets out of commits.

Replace `192.0.2.10`, the SSH account, release source and checksum. The example
address and `REPLACE_WITH_TRUSTED_SHA256` are deliberately non-deployable
placeholders. Set all three selectors as YAML booleans in inventory:

```yaml
stack_deploy_py_phone_caller: false
stack_deploy_asterisk: false
stack_deploy_openalert: true
```

There are no selector defaults; at least one must be `true`. The target group
defaults to `stack`; `stack_hosts` may select another explicitly reviewed
inventory group. The new `ansible.cfg` has **no implicit inventory**. Always
pass `-i`; do not reuse the legacy live inventory or run from a legacy directory
whose configuration selects it automatically.

Supply `openalert_release.source` as either an absolute **controller-local**
archive path or an HTTPS archive URL downloaded by the managed host. Pin
`openalert_release.sha256` to the trusted, lowercase 64-hex archive SHA-256.
Obtain that value through a separately controlled/reviewed channel; downloading
a checksum beside an untrusted archive does not authenticate it. Use the
[packaging contract](../../src/openalert/packaging/README.md), not a bare binary
or an arbitrary tarball. Select the bundle for the **managed host's** architecture,
not the controller's CPU or the archive filename.

Both examples use the private template: `hub` listens on `127.0.0.1:8090`, and
the second instance named `public` listens on `127.0.0.1:8092`. The name `public`
does **not** enable or endorse unauthenticated public exposure. Keep the example
dispatch transports disabled for installation validation.

Use Ansible Vault for credentials and other sensitive template inputs, protect
the controller's template/inventory files, and avoid secrets in command-line
arguments or debug output. See [configuration and exposure rules](docs/openalert.md).

### 3. Inspect the target, then deploy deliberately

From `deploy/ansible`, with the controller environment above still active:

```bash
export OPENALERT_INVENTORY=/absolute/path/to/reviewed-inventory/hosts.yml
ansible-inventory -i "$OPENALERT_INVENTORY" --graph
ansible-playbook -i "$OPENALERT_INVENTORY" site.yml --list-hosts
ansible-playbook -i "$OPENALERT_INVENTORY" site.yml --syntax-check
ansible-playbook -i "$OPENALERT_INVENTORY" site.yml --limit openalert-example --ask-become-pass
```

Replace the inventory path and limit with your reviewed disposable target.
Add `--ask-vault-pass` or your approved `--vault-id` when using encrypted vars;
omit `--ask-become-pass` only when privilege escalation is already configured.
Listing hosts and syntax checks do not validate a release or service startup.
The final command changes the host and starts the declared services.

**The real OpenAlert role explicitly rejects `--check`.** Candidate binaries,
account permissions and staged units require an actual run. For an offline,
local-only rendering exercise, use the separate synthetic playbook instead:

```bash
ansible-playbook -i localhost, -c local tests/render.yml
```

This writes fixtures to `tests/.rendered/`; it neither contacts managed hosts nor
proves runtime compatibility. Do not substitute a live inventory for this command.
Post-activation probing performs only loopback `GET /health`; it does not send
alerts, radio traffic, phone calls or SMS test messages.

## Component selection and existing entry points

Set `stack_deploy_py_phone_caller`, `stack_deploy_asterisk` and
`stack_deploy_openalert` explicitly for every run. Optional
`stack_py_phone_caller_vars_files`, `stack_asterisk_vars_files` and
`stack_openalert_vars_files` lists load reviewed vars files only for selected
components; selectors must already be defined before those files are loaded.
Python selection requires `py_phone_caller_config`. When Python and PBX are both
selected, `tasks/combined_pbx.yml` derives ARI/dialplan/callback values from the
Python configuration; standalone PBX selection uses its own variables. The
Debian AllStarLink and official Ubuntu package paths have recorded AMD64
PJSIP/IAX2 and combined-stack runtime evidence, not ARM64 qualification.

Existing commands are retained through compatibility wrappers:

- [Python VM deployment](on-vm_py-phone-caller/README.md)
- [Asterisk deployment](asterisk_py-phone-caller/README.md)
- [Legacy combined deployment](deploy_all/README.md)

Their reported results and broader platform claims do not qualify this new
entry point. Legacy inventory examples contain site-specific choices; do not
use them unchanged as a quickstart.

Explicit `standard` and `enterprise` application profiles separate gateway
selection from ingress ownership and connectivity. An externally managed
Apache TLS terminator in front of APISIX is supported as an ownership boundary,
not something the installer replaces. `legacy` remains the default for existing
inventories. Read [the topology/offline contract](docs/topologies.md) before
selecting `airgapped`: disconnected operation after an online install is not
equivalent to fully offline provisioning. These new profiles have separate
qualification requirements from the earlier VM results above.

## Operational boundary and evidence

Fresh conflicting installations fail rather than being silently adopted.
Omitted OpenAlert instances are left untouched, not disabled or removed.
Phase 4 lifecycle implementation and disposable `systemd` rehearsals on Debian 13
and Ubuntu 26.04 LTS AMD64 are complete: see the
[maintenance and recovery runbook](docs/lifecycle.md) for explicit in-place and
relocated (`relocate: true`) adoption, backup, restore and compatible asset-rollback
operations. There is no live migration authorization here.

The [support matrix](docs/support-matrix.md) separates build/static evidence from
runtime qualification: **335 automated tests and 1,247 subtests pass** across the
Ansible, OpenAlert, air-gap, and multi-pillar packaging suites. VM scenarios cover
OpenAlert isolation/safety, Python-only and combined startup, PJSIP/IAX2 (AllStarLink
on Debian 13, official `distro` on Ubuntu 26.04, and Tucny `22.9.0-1.el10` on Rocky
10 / AlmaLinux 10 — ensure `iptables-nft` is present on minimal AlmaLinux 10 images),
`standard` `airgapped` provisioning with offline Piper TTS synthesis and UI
login, connected `enterprise` provisioning with live Keycloak OIDC login, OpenAlert
in-place and relocated adoption/recovery, zero-change reruns, external-service
ownership, legacy entry points and pinned Git/local delivery. Whole-tree lint is not
clean because role-prefix naming findings remain explicitly deferred as tracked debt
(not suppressed). Physical Orange Pi 5 Plus ARM64 hardware execution and live
telephony/radio dispatch remain separate operational validation gates.

See [tests/README.md](tests/README.md) for reproduction and test runner details.