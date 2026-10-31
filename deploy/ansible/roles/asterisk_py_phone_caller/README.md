# Shared PBX role

This is the single Asterisk implementation for the shared stack and the
[`legacy PBX wrapper`](../../asterisk_py-phone-caller/README.md). The role has no
dependencies on the Python application, OpenAlert, their configuration files,
or other roles. All four templates render from PBX variables alone.

## Entry points and platforms

Use the shared `deploy/ansible/site.yml` with explicit `stack_deploy_asterisk: true`,
`stack_deploy_py_phone_caller: false`, and `stack_deploy_openalert: false` for a PBX-only
deployment. The shared site's standard platform contract is Debian 13 or Ubuntu
26.04. The legacy wrapper opts into `stack_legacy_platform: true` and retains the
RedHat package path. Platform policy belongs to the shared preflight; direct role
use does not enforce the shared site's exact distribution versions.

The optional [AllStarLink provider](../../docs/asterisk-provider.md) supplies pinned
Asterisk packages for Debian 13, with AMD64 installation/API/rerun evidence and
ARM64 execution still unqualified. Set `asterisk_package_provider: allstarlink`
explicitly; there is no automatic provider fallback or replacement.

The default `distro` route uses `apt`; RedHat-family systems retain `dnf`, EPEL,
CRB/PowerTools, and the existing Enterprise Linux 10+ COPR selection. This role
does not compile Asterisk or clone build inputs. Repository package versions are
not frozen here; deployments needing exact package reproducibility must use
appropriately pinned repositories. Collection versions are pinned in
`deploy/ansible/requirements.yml`; this role uses `community.general` and
`ansible.builtin` only.

Ubuntu 26.04 LTS uses its own `resolute/universe` distro packages or an external
PBX, never the Debian AllStarLink repository. The Debian-family distro route
requires existing APT candidates for every dependency before any role mutation;
prepare repositories/indexes externally if the read-only check fails. Observed
Ubuntu package metadata and runtime limits are recorded in the provider guide.

## Public variables

Existing names are retained for inventory compatibility.

| Variable | Role default / purpose |
| --- | --- |
| `asterisk_package_provider` | `distro`; opt-in `allstarlink` for Debian 13 |
| `asterisk_allstarlink_version` | `2:22.10.1+asl3-3.10.8-1.deb13`; exact three-package pin |
| `asterisk_sip_trunk_enabled` | `true` for compatibility; set `false` to prevent trunk registration during isolated tests |
| `asterisk_http_enabled` | `"yes"` |
| `asterisk_http_bindaddr`, `asterisk_http_bindport` | `0.0.0.0`, `8088` |
| `ari_app_name`, `ari_username` | `py-phone-caller` |
| `ari_password` | `CHANGE_ME`; supply a Vault-protected value |
| `sip_provider_host`, `sip_provider_port` | `sip.messagenet.it`, `5061` |
| `sip_username`, `sip_password`, `sip_contact_user` | `CHANGE_ME`; override for the selected trunk |
| `asterisk_sip_bindaddr` | `0.0.0.0:5060` |
| `callback_service_url` | `http://127.0.0.1:8083`; used by dialplan callbacks, not probed at deployment |
| `asterisk_context`, `asterisk_extension` | `py-phone-caller`, `3216` |
| `local_sip`, `local_iax` | Both `false` in the role; legacy wrapper enables both |
| `local_sip_exten`, `local_iax_exten` | Both `2500` in the role; legacy wrapper uses IAX `2600` |
| `local_sip_pass`, `local_iax_pass` | `change_me`; supply Vault-protected values when enabled |
| `asterisk_iax_bindaddr`, `asterisk_iax_bindport` | `127.0.0.1`, `4569`; canonical loopback/RFC1918 IPv4 only, UDP port 1–65535 |
| `custom_audio_files` | `greeting-message.wav`, `press-4-for-acknowledgement.wav` |
| `asterisk_core_sounds_version` | `1.6.1`, RedHat missing-sounds fallback only |
| `asterisk_core_sounds_sha256` | Empty by default; required trusted SHA-256 for that fallback |

OS-specific paths, package lists, account and service names remain in `vars/`.
The ARI application name feeds `Stasis()` and the SIP sections. The configured
`asterisk_context` feeds the dialplan and both optional local endpoint types.
`callback_service_url` is independent of Python settings and must identify the
actual callback service. Local SIP and IAX extension numbers must not collide
when both are enabled.

Enabled local endpoints require numeric identifiers and 16–128 character
config-safe passwords (letters, digits, or `_~!@$%^&*()+,.:/?=-`); placeholders,
newlines and configuration delimiters are rejected before mutations. The legacy
wrapper's enabled endpoints therefore need real Vault-protected passwords.
IAX requires call tokens and disables peer qualification. Its module is explicitly
selected, and runtime verification only inspects its loaded peer, module and UDP
listener; it never registers a device or dispatches a call.

## Sound download contract

Before packages, users, directories, or configuration are changed, RedHat
preflight checks for `{{ asterisk_sounds_dir }}/beep.wav`. If it is absent, supply
a fixed numeric release version and a **trusted 64-hex-character SHA-256**.
No digest is fabricated, no mutable `current` URL is used, and download or
extraction failures are fatal.

The URL is
`https://downloads.asterisk.org/pub/telephony/sounds/releases/asterisk-core-sounds-en-wav-VERSION.tar.gz`.
`get_url` verifies the supplied SHA-256 in the root-owned
`/var/cache/asterisk-core-sounds` directory before extraction into the actual
sound directory. The service account cannot replace files in this download
cache. Existing core sounds are not automatically replaced; Debian uses its
packaged core sounds. Custom audio remains local under `files/sounds/` and
retains the legacy warning-and-skip behavior for missing files.

## Configuration and operational safety

The role manages `extensions_py_phone_caller.conf`, `pjsip_py_phone_caller.conf`,
`ari_py_phone_caller.conf`, and `iax_py_phone_caller.conf`, then inserts `#include`
lines into the corresponding base files without replacing unrelated content in
the `distro` route. AllStarLink fresh installations instead use role-owned base
include roots and a non-radio module allowlist; see its provider guide.
Templates and base configuration edits suppress both logs and diffs, including
pre-existing base-file secrets. Managed configuration uses mode `0640`;
INI edits do not create plaintext backups.

Notifications are change-driven. Partial configurations and ARI settings reload
Asterisk. Package, HTTP listener, and `chan_sip` disablement changes can restart
it; IAX listener/module changes also restart it, while SELinux port updates do not.
Handler errors fail the deployment rather than
being ignored. Check mode no longer forces RedHat repository/package changes;
verified archive extraction is skipped in check mode. Existing live PBX services
and other unmanaged configuration are not backed up or rolled back by this role.

The inherited HTTP bind and credential placeholders remain compatibility
defaults, not secure production recommendations. Set real credentials, restrict
the network, and review transport changes with the PBX operator. In particular,
PJSIP transport changes may require a scheduled restart beyond a normal reload.
Applying the role can cause the configured trunk to register: live validation
requires explicit operator authorization even if no call is placed.

## Offline validation

`deploy/ansible/tests/test_pbx_roles.py` covers PBX-only wrapper selectors, legacy
Vault mappings, pinned requirements, independent template rendering, configured
contexts, protected outputs, non-destructive includes, notification behavior,
and download pinning. Synthetic localhost Ansible checks cover task syntax,
Ubuntu/provider and credential preflight, missing APT candidates, legacy/inventory
variable loading, and enabled/disabled IAX rerun idempotence on temporary files.
Only temporary fixture configuration is edited; no PBX probes, downloads, calls,
messages, package installation, or service changes are performed.

`vars_plugins/pbx_legacy_vars.py` is enabled only by the legacy `ansible.cfg` to
preserve playbook-adjacent variable lookup across `import_playbook`. It delegates
Vault and group/host matching to Ansible's built-in `host_group_vars` loader;
the shared configuration must not enable it for new deployments.