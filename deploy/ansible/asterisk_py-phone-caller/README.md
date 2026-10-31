# Asterisk compatibility entry point

The PBX implementation now lives in [`../roles/asterisk_py_phone_caller`](../roles/asterisk_py_phone_caller/README.md).
`deploy_asterisk.yml` imports `../site.yml`; it no longer maintains a separate role copy.
This wrapper sets `stack_deploy_asterisk: true`, `stack_deploy_python: false`,
`stack_deploy_openalert: false`, and `stack_legacy_platform: true`. It does not load
Python application configuration or install the Python/OpenAlert services.

**Compatibility warning:** the original host pattern is **`pbx_servers:all`**, not
`asterisk`. This union includes every inventory host. It is preserved deliberately;
always choose the intended inventory and use `--limit` when needed.

Run from this directory, or explicitly select this directory's `ansible.cfg`.
No inventory is selected implicitly. Existing `-i inventory.ini` usage is retained.
The configuration points at shared roles and collections. Its compatibility-only
`pbx_legacy_vars` plugin preserves adjacent `group_vars`/`host_vars` after the site
import, using Ansible's built-in loader (including Vault and group matching).
Inventory-adjacent variables continue to load normally. The shared entry point
does not enable this legacy loader by default.

The shared site's new deployment targets are Debian 13 and Ubuntu 26.04. This
wrapper explicitly opts into legacy platform compatibility, retaining the old
Debian-family and RedHat-family package paths; that is not a claim of fresh
validation on every legacy distribution.

## Preserved wrapper variables

| Variable | Compatibility value |
| --- | --- |
| `ari_password` | `vault_ari_password`, falling back to `change_me` |
| `sip_username` | `vault_sip_username`, falling back to `py-phone-caller` |
| `sip_password` | `vault_sip_password`, falling back to `py-phone-caller` |
| `local_sip` / `local_sip_exten` | `true` / `2500` |
| `local_iax` / `local_iax_exten` | `true` / `2600` |
| `local_sip_pass` / `local_iax_pass` | Corresponding `vault_*` variable, falling back to `change_me` |

These mappings retain their original play-variable precedence; direct overrides
can still be supplied with extra variables. **Replace all placeholder passwords
with Vault-protected values before deployment.** The role's public PBX variable
names are unchanged. See the shared role README for defaults and safety limits.

## Install dependencies and use the wrapper

From this directory:

```bash
ansible-galaxy collection install -r requirements.yml -p ../.collections
ansible-playbook -i inventory.ini deploy_asterisk.yml --limit YOUR_PBX_HOST --syntax-check
ansible-playbook -i inventory.ini deploy_asterisk.yml --limit YOUR_PBX_HOST --check
```

Remove `--check` only for an authorized deployment. The compatibility requirements
mirror the exact pins in `../requirements.yml`; an offline regression checks that
they remain equal. The PBX role itself needs only `community.general` in addition
to `ansible.builtin`.

On RedHat, missing core sounds now require `asterisk_core_sounds_version` and a
trusted `asterisk_core_sounds_sha256` **before any role mutation**. The default
version is `1.6.1`; no checksum is invented or fetched from the same untrusted
artifact. Already installed core sounds and Debian's packaged sounds do not
require this fallback. See the shared role README for the download contract.

## Operational limits

Debian 13 can opt into [AllStarLink packages](../docs/asterisk-provider.md) using
`asterisk_package_provider: allstarlink`. This requires loopback ARI and a real
Vault-managed credential. It refuses automatic takeover/provider changes and
uses owned non-radio base files; the preservation description below applies to
the default distribution-package route. Review the wrapper's enabled local
extensions and set `asterisk_sip_trunk_enabled: false` for isolated tests.

Ubuntu 26.04 LTS must use `asterisk_package_provider: distro` with Ubuntu's
`universe` packages available in prepared APT indexes, or an externally managed
PBX. Missing package candidates fail before role mutations; the role never adds
Debian AllStarLink sources to Ubuntu. See the provider guide for observed package
metadata; Ubuntu and enabled-IAX runtime qualification remain separate checks.

The wrapper still enables both local PJSIP and IAX2. Both need numeric, distinct
extension numbers and Vault-managed 16–128 character config-safe passwords;
the historical `change_me` fallback now fails preflight when an endpoint is enabled.
IAX defaults to `asterisk_iax_bindaddr: 127.0.0.1` and
`asterisk_iax_bindport: 4569`; only private/loopback IPv4 listeners are accepted.
IAX call tokens are required. Module/listener changes restart Asterisk, while
unchanged runs do not. Enabled-IAX verification inspects modules, peer configuration
and sockets without calls, registration or peer qualification.

The role preserves existing Asterisk configuration and adds four managed partial
includes. Changed configuration can reload Asterisk; package, HTTP listener, or
module-disable changes can restart it. There is no unconditional role-level
restart, and handler failures are not swallowed. Check mode no longer forces
RedHat package/repository mutations.

Credential-bearing templates and base configuration edits use `no_log: true`
and `diff: false`. Avoid verbose ad-hoc credential printing, external debugging
callbacks, or passing plaintext secrets on a command line. Existing HTTP exposure
defaults are unchanged; secure the PBX network and authentication before use.

Offline tests use synthetic variables and temporary configuration fixtures only,
and perform no calls, messages, PBX probes, package installation, or service changes.
Live-host validation of this
consolidation must be performed separately after integration review.