# Asterisk package providers

The shared PBX role supports an **explicitly selected AllStarLink provider** for
Debian 13 (`trixie`) on AMD64 and ARM64. It is not an architecture-based fallback.
AllStarLink packages are third-party Asterisk builds with radio extensions, not
official Debian packages. Only the AMD64 installation/API/rerun scenario below
has been exercised; this is not full telephony or ARM64 qualification.

An explicit **Tucny Asterisk 22** provider is also implemented for **online Rocky
Linux 10 AMD64 only**. Its package/trust review and offline tests are described
below; **this is not runtime qualification**. There is no automatic fallback,
cross-distribution repository mixing, or platform override for this provider.

## Selection

| Setting | Behavior |
| --- | --- |
| `stack_deploy_asterisk: false` | Leave the PBX entirely unmanaged. Configure Python's ARI endpoint for the externally managed PBX. No PBX packages, repository or configuration changes. |
| `stack_deploy_asterisk: true`, `asterisk_package_provider: distro` | Existing distribution-package route, where packages are available; compatibility default. Debian 13's official repositories currently lack the server package. |
| `stack_deploy_asterisk: true`, `asterisk_package_provider: allstarlink` | Signed `trixie/main` packages with exact version selection. Debian 13 only; no Ubuntu or RedHat repository mixing. |
| `stack_deploy_asterisk: true`, `asterisk_package_provider: tucny` | Explicit reviewed Tucny EL10 Asterisk 22 RPMs, exact managed installation versions, online Rocky 10 AMD64 only. Bypasses the legacy COPR and sound-tarball routes. |

### Ubuntu 26.04 LTS

Use `asterisk_package_provider: distro`, with Ubuntu's **universe** component
enabled and current package indexes prepared by the host administrator. Public
Launchpad metadata inspected on 2026-10-30 reports published source and AMD64
binary `asterisk` **`1:22.5.2~dfsg+~cs6.15.60671435-1`** in
`resolute/universe`, Release pocket:
[source publication](https://api.launchpad.net/1.0/ubuntu/+archive/primary/+sourcepub/17710662),
[AMD64 publication](https://api.launchpad.net/1.0/ubuntu/+archive/primary/+binarypub/232380678).
That exact version also passed the disposable Ubuntu runtime checks below. It
is not a fixed role pin: the distro provider follows the configured authenticated
APT candidate. The [Ubuntu example](../inventories/examples/pbx-ubuntu/hosts.yml)
uses this official provider with private PJSIP/IAX2 endpoints.

Before any package/configuration mutation, the Debian-family distro route checks
`apt-cache policy` for every required package, including in check mode. A missing
candidate or empty/stale index fails with preparation instructions; it does not
add repositories or refresh indexes to conceal that failure. Prepare Ubuntu
repositories externally, or set `stack_deploy_asterisk: false` and use an external
PBX. **Never install Debian AllStarLink packages on Ubuntu.** Package-triggered
startup is suppressed until the role has configured the service. ARM hardware
validation remains deferred.

### Debian AllStarLink selection

Copy [the sanitized PBX-only inventory](../inventories/examples/pbx-allstarlink/hosts.yml)
into a private inventory directory. Replace its documentation-only address and
provide `vault_ari_password` through encrypted inventory variables. From
`deploy/ansible`, using the controller environment in the main README:

```bash
ansible-playbook -i /path/to/private/hosts.yml site.yml --limit pbx-example --ask-vault-pass
```

Run only on an authorized fresh/disposable host. New inventories must supply all
three component selectors. Legacy wrappers can also select the provider, but
retain their historical local-extension and credential mappings; review them
rather than copying live-site inventory. For combined Python/PBX deployments,
shared orchestration derives ARI credentials and dialplan values from the Python
configuration, which must satisfy the same provider checks.

## AllStarLink pins and trust boundary

- `asterisk_allstarlink_version` defaults to
  `2:22.10.1+asl3-3.10.8-1.deb13`, including the Debian epoch. All three packages
  (`asl3-asterisk`, `asl3-asterisk-modules`, `asl3-asterisk-config`) use that exact
  version. The config package is a required dependency; the full AllStarLink
  node setup, repository-switch helper and optional recommendations are not installed.
- The source is `https://repo.allstarlink.org/public`, suite `trixie`, component
  **`main` only**. APT architecture comes from managed-host facts, not the controller.
  A dedicated `Signed-By` keyring confines this key to that source. Preferences
  reject unrelated packages from the repository and select only the pinned PBX set.
- The armored key at `https://repo.allstarlink.org/public/allstarlink.asc` is
  SHA-256 pinned to
  `88bd5cb1f27cd1ccc3fc60e85f636bb072b2351c33437822f9b0a9edc737d7e7`.
  Its primary fingerprint is
  **`F2AF416869932ABB39E165E5409D50181BD84509`** (`AllStarLink Repository`).
  This was checked against the publisher's key files and repository-bootstrap
  package on 2026-10-30. **No independent fingerprint attestation was found**:
  initial trust is the reviewed publisher HTTPS source, not a separate trust
  authority. Future key rotation requires deliberate code/pin review.
- APT verifies signed repository metadata and package hashes; authentication is
  never bypassed. Ordinary Debian library dependencies remain distribution-managed,
  not a fully frozen OS snapshot. Archive selected packages if long-term reproduction
  is required: the upstream repository can prune old versions.

The role does not install `asl-apt-repos`, execute an upstream bootstrap script,
add testing/unstable repositories, compile Asterisk or silently downgrade it.

## AllStarLink configuration and safety

Installation suppresses package-triggered startup with `policy_rc_d: 101`.
Before the first managed start, the role replaces the newly installed vendor
radio bootstrap with owned PBX include roots and a module allowlist:

- `autoload=no`; explicit PJSIP, Stasis, HTTP/WebSocket and ARI modules. Radio
  drivers, `app_rpt`, EchoLink and AllStarLink registration modules are not loaded.
- The application retains its four `*_py_phone_caller.conf` partial files.
  **For this provider**, `modules.conf`, `extensions.conf`, `pjsip.conf`,
  `iax.conf` and `manager.conf` are role-owned. Put application customization in
  the partial templates; arbitrary edits to these base files are not preserved.
  The distribution provider retains the historical non-destructive include pattern.
- AMI is disabled; package-added hardware groups are removed from the dedicated
  account. No hardware access is needed for the tested PBX-only profile.
- Initial provider support requires ARI on `127.0.0.1` or `::1`, with a
  non-placeholder Vault-managed password of at least 16 characters. Use an
  explicitly secured tunnel/proxy if access from another host is required;
  the role does not provision that networking.
- `asterisk_sip_trunk_enabled: false` omits the outbound trunk and its registration
  module. Set this for isolated installation tests. Its compatibility default is
  `true`, so selecting a real trunk can initiate SIP registration even without calls.
- The example also binds SIP to loopback and disables local SIP/IAX endpoints.
  Explicit `local_iax: true` requires `chan_iax2`, with a separately configurable
  private listener (see below). LAN SIP, RTP and device policies need separate network review.
  Private ARI/SIP bindings do not mean every library UDP socket is loopback-bound.

The role rejects unmanaged PBX paths/packages and provider changes before adding
the repository. `/var/lib/py-phone-caller-pbx/provider` records ownership after
fresh-install checks, allowing interrupted installations to resume. Do not fabricate
that record to adopt a live PBX. Disabling management leaves resources installed.

Changed packages, modules or HTTP settings restart Asterisk; other partial
configuration changes reload it. PJSIP transport changes can still require a
scheduled restart. Unchanged runs do neither. After pending handlers, the role
requires authenticated `GET /ari/asterisk/info` and operational application
modules, with no radio modules loaded. Configuration and API credentials are
suppressed in output and diffs. These checks never originate calls or submit alerts.

### Explicit local PJSIP + IAX2

All providers retain the public `local_sip` / `local_iax` selectors and the four
partial includes. For a private, non-dispatch verification profile:

```yaml
asterisk_sip_trunk_enabled: false
asterisk_http_bindaddr: 127.0.0.1
asterisk_sip_bindaddr: 127.0.0.1:5060
local_sip: true
local_sip_exten: 2500
local_sip_pass: "{{ vault_local_sip_pass }}"
local_iax: true
local_iax_exten: 2600
local_iax_pass: "{{ vault_local_iax_pass }}"
asterisk_iax_bindaddr: 127.0.0.1
asterisk_iax_bindport: 4569
```

Enabled local endpoint identifiers must be numeric and distinct. Their passwords
must be 16–128 characters from letters, digits, or `_~!@$%^&*()+,.:/?=-` (URL-safe
random credentials are suitable); whitespace, configuration delimiters and
placeholder values fail preflight. Use encrypted inventory variables, never CLI
plaintext. Managed credential partials stay `0640`, with logs/diffs suppressed.

IAX accepts canonical IPv4 loopback or RFC1918 addresses only; wildcard/public
addresses and invalid ports fail before changes. LAN bindings still require
operator-managed firewall/access policy. IAX call tokens are required and peer
qualification is disabled, so inspection sends no peer traffic. There is no IAX
trunk registration. Changing its listener or module selection schedules a restart;
an unchanged rerun does not. The distro route preserves unrelated base content,
but explicitly manages the IAX module load/noload directive and enabled listener.

When IAX is enabled, role checks require a running `chan_iax2`, the loaded peer's
context and set secret, and the private UDP listener, using CLI/socket inspection
only. The opt-in `tests/run_pbx_disposable.py` now enables PJSIP and IAX2, checks
PJSIP endpoint configuration and IAX file permissions, scans all three credentials
for leaks, and requires `changed=0` plus identical runtime evidence on rerun.
Select `--provider distro` for Ubuntu, `--provider allstarlink` for Debian 13,
or `--provider tucny` for authorized Rocky 10 AMD64 qualification;
the isolated inventory must acknowledge `stack_disposable_test_acknowledged`.
These checks inspect configuration/status only; they do not register phones or
originate calls.

## Tucny EL10 Asterisk 22: reviewed DNF provider

**Runtime status (2026-11-07): `22.9.0-1.el10` is qualified on Rocky Linux 10.2 AMD64; do not use `22.10.1-1.el10`, `22.11.0-1.el10`, or `22.12.0-1.el10`.**
On 2026-11-01, testing `22.11.0-1.el10` exposed an upstream packaging symbol mismatch in `res_ari_events.so` (`undefined symbol: stasis_app_claim_channel`). Symbol inspection across all published `https://ast.tucny.com/repo/asterisk-22/el10/x86_64/` RPMs on 2026-11-07 confirmed that `22.10.1-1.el10`, `22.11.0-1.el10`, and `22.12.0-1.el10` carry that undefined reference in `res_ari_events.so`, whereas **`22.9.0-1.el10`** has complete symbol closure across `/usr/sbin/asterisk`, `res_stasis.so`, and `res_ari_events.so`. Pinning `asterisk_tucny_version: "22.9.0-1.el10"` passed full disposable PBX qualification (`run_pbx_disposable.py --provider tucny`), connected `enterprise` stack qualification (`run_topology_disposable.py`), and interactive OIDC login on Rocky 10.2 AMD64 with SELinux enforcing. See [runtime evidence](support-matrix.md).

### Explicit inventory selection

Use the shared entry point only after its strict platform checks permit the
target; do not use a legacy-platform or distribution override to bypass them.
The role itself additionally requires online Rocky 10 `x86_64`. A private
PBX-only inventory can select:

```yaml
stack_deploy_py_phone_caller: false
stack_deploy_openalert: false
stack_deploy_asterisk: true
asterisk_package_provider: tucny
py_phone_caller_connectivity: online
asterisk_tucny_version: "22.9.0-1.el10"
asterisk_tucny_sounds_version: "1.6.1-1.el10"
asterisk_http_bindaddr: "127.0.0.1"
asterisk_sip_bindaddr: "127.0.0.1:5060"
asterisk_sip_trunk_enabled: false
ari_password: "{{ vault_ari_password }}"
```

ARI must bind to `127.0.0.1` or `::1`. ARI, enabled local endpoints and enabled
trunks require non-placeholder, configuration-safe 16–128 character passwords
from encrypted inventory. The local PJSIP/IAX settings above also apply. A
real trunk can register; keep it disabled for non-dispatch qualification.

### Repositories, packages and updates

The role renders `/etc/yum.repos.d/py-phone-caller-tucny.repo` rather than using
the publisher's stale `el10.repo` (which does not list Asterisk 22):

| Repository ID | Base URL | Exact `includepkgs` names |
| --- | --- | --- |
| `py-phone-caller-tucny-22` | `https://ast.tucny.com/repo/asterisk-22/el10/x86_64/` | `asterisk`, `asterisk-pjsip`, `asterisk-curl`, `asterisk-iax2` |
| `py-phone-caller-tucny-common` | `https://ast.tucny.com/repo/asterisk-common/el10/x86_64/` | `asterisk-sounds-core-en`, `asterisk-sounds-core-en-wav` |

Both repositories remain **enabled** for normal DNF maintenance. The managed
transaction selects full version-release and architecture, not `latest` or a
wildcard: `22.9.0-1.el10.x86_64` for the core, PJSIP and CURL packages, plus IAX2
when `local_iax` is enabled. A previously managed IAX2 package remains installed
and follows the exact version pin when IAX is subsequently disabled; its module
and credential partial are disabled instead of automatically removing packages.
CURL is an optional upstream subpackage but required by this role's callback
dialplan. ARI is in the **core `asterisk` RPM**, not a separate ARI package.

Both English sounds RPMs are pinned to `1.6.1-1.el10.noarch`. File-list review
found that `asterisk-sounds-core-en` contains directories/documentation only;
the **`-wav` subpackage** supplies `/usr/share/asterisk/sounds/beep.wav` and the
other WAV prompts. Tucny custom WAV files use `/usr/share/asterisk/sounds`, not
the legacy RedHat `/sounds/en` path. The role verifies a nonempty packaged beep
and never downloads or unpacks a sound archive for Tucny.

EPEL is bootstrapped with the `epel-release` package from standard Rocky
`extras` (only `baseos`, `appstream`, `extras` enabled for that bootstrap).
`dnf-plugins-core` enables standard Rocky `crb` persistently; `gnupg2` supplies
the fingerprint inspection required by Ansible's `rpm_key`. Remaining runtime
libraries, such as codec2/GSM/SRTP dependencies, are resolved by DNF from those
standard repositories and EPEL. Only required SELinux administration packages
are added; no Development Tools, Asterisk development packages, compilation,
COPR, remote installer script, or SELinux disablement is used. The PBX transaction
temporarily disables unrelated repositories and permits only these standard
dependency repositories plus the two narrow Tucny sources. Weak dependencies,
unauthenticated packages, automatic downgrades and dependency erasure are disabled.

For a managed upgrade, review the new EL10 Asterisk 22 release, its subpackages
and signatures, set **`asterisk_tucny_version` to that exact version-release**
in inventory (and independently review `asterisk_tucny_sounds_version` when
needed), then rehearse a role rerun on a disposable host before production.
The role refuses an inventory pin older than any installed reviewed package
**before repository or package changes**. Missing pinned releases fail rather
than falling back. Keep an authenticated package archive if upstream retention
is insufficient.

This is an installation/reconciliation pin, **not a DNF versionlock**. An
operator's ordinary `dnf upgrade` can advance these enabled repositories' PBX
packages; update the reviewed inventory pins to match before the next role run.
The role will not silently downgrade such an update. OS dependencies remain
distribution-managed rather than frozen to an OS snapshot. Standard DNF package
updates may restart the service through RPM scriptlets; schedule maintenance.

### Trust boundary and known limitations

- The public key is vendored as `files/RPM-GPG-KEY-tucnyastrepo` from
  `https://ast.tucny.com/repo/RPM-GPG-KEY-tucnyastrepo`.
  SHA-256: `f7864d4fefd63ebe56c997dfe8d6c716c8d524e7391de0aece1caee4b88ac011`.
  Primary fingerprint: **`F323210FB8EAC82E8F2C5262EFE47D937C0C1849`**,
  created 2023-02-25, identity `Tucny Asterisk Repo <ast@tucny.com>`.
  GnuPG verifies this full fingerprint before `rpmkeys --import` and again against
  the installed target key. Queries inspect only that key, not unrelated Rocky
  version-6 keys that the pinned Ansible `rpm_key` module cannot parse. A short-key-ID
  collision or multiple keys fails closed. Rotation requires a deliberate
  vendored-key and fingerprint/hash review, not a fresh unpinned fetch.
- The prior package review verified RSA4096/SHA256 signatures on the core,
  PJSIP and IAX2 RPMs. DNF requires signature verification for **every** installed
  package, including CURL and sounds. Repositories use `gpgcheck: true` and
  `sslverify: true`; authentication is never disabled.
- **Metadata is unsigned:** the publisher's `repomd.xml.asc` is absent (404).
  `repo_gpgcheck: false` is intentional, not a claim of authenticated metadata.
  HTTPS and RPM signatures do not provide signed metadata freshness, availability,
  or protection from repository withholding/replay. Exact managed pins and
  downgrade rejection reduce, but do not eliminate, these risks.
- **TOFU identity caveat:** only the publisher's same-host HTTPS key was found;
  there is **no independently published/attested fingerprint**. Signature success
  authenticates packages to that reviewed key, not an independently established
  publisher identity. RPM imports the key into its system trust database; this
  is not APT's per-source `Signed-By` isolation. `includepkgs` limits package names,
  not the global trust of imported RPM keys.
- There is **no security-update SLA** or production certification. Monitor both
  Asterisk and the third-party publisher, review updates deliberately, and accept
  this trust boundary explicitly before deployment.

### Ownership, configuration and service

Before changes, RPM facts and existing paths reject unmanaged PBX packages,
configuration, data, binaries and service units. The ownership record is
`/var/lib/py-phone-caller-pbx/provider`, containing `tucny`. Conflicting records
fail even when switching back to `distro`; neither adoption, provider replacement,
automatic removal nor rollback is implemented. Do not manufacture the marker to
take over an existing PBX. Disabling management leaves existing resources alone.

The four application partial files and their credential protections remain.
Tucny owns `extensions.conf`, `pjsip.conf`, `iax.conf`, `ari.conf`, `http.conf`,
`manager.conf` and `modules.conf`; unrelated edits to these roots are not retained.
ARI has no inherited vendor accounts, AMI is disabled, and the non-radio module
allowlist is reused **without AllStarLink account/group tasks**. PJSIP, Stasis,
ARI, WebSocket and optional IAX2 are explicitly selected with `autoload=no`.
Tucny additionally loads its separately built speech, geolocation, AGI, statistics
and crypto dependencies; with `22.9.0-1.el10`, `res_ari_events.so`, `res_stasis.so`,
PJSIP, and IAX2 all load cleanly and report `Running`.

RPM inspection found `/usr/lib/systemd/system/asterisk.service` using
`User=asterisk`, `Group=asterisk`, `Type=simple`, and
`ExecStart=/usr/sbin/asterisk -f -C /etc/asterisk/asterisk.conf`, with native
stop/reload commands and `PrivateTmp=true`. The role retains that packaged unit.
The reviewed initial-install scriptlet reloads systemd but does **not** start
Asterisk, so private configuration precedes the first managed start. Upgrade
scriptlets can `try-restart` an existing service. The role creates `/run/asterisk`
before first start, matching the package's `/usr/lib/tmpfiles.d/asterisk.conf`.
The package selects `/usr/share/asterisk` as its data/sound root and
`/usr/lib64/asterisk/modules` for modules. Both PBX-only and full `enterprise`
qualification passed on Rocky 10.2 AMD64 with SELinux **Enforcing**.

### Validation status

`tests/test_tucny_provider.py` runs real local Ansible against synthetic facts
and temporary configuration only: platform/secret/version preflight, unmanaged
ownership/provider rejection, upgrade/downgrade guards, key/hash and repository
contracts, exact package selection, and secret-safe idempotent rendering.
The existing PBX regression tests also pass. No downloads or RPM transactions
occur in these tests.

The disposable runner accepts `--provider tucny`, queries RPM versions rather
than dpkg, requires the exact selected core/module/sound versions and architectures,
and retains ARI authentication, PJSIP/IAX2, module exclusion, credential leakage,
zero-change rerun and conflicting-provider assertions. On 2026-11-07, on a fresh
Rocky Linux 10.2 AMD64 VM (`ppc-qual-rocky-pbx-20261107`) with `22.9.0-1.el10`,
`run_pbx_disposable.py --provider tucny`, connected `enterprise` stack qualification
(`run_topology_disposable.py`), and interactive Keycloak OIDC authentication all
passed with `changed=0` on unchanged rerun and SELinux `Enforcing`. The VM, disk,
and temporary networking were removed after testing.

## Debian/Ubuntu runtime evidence and remaining work

On 2026-10-30 the authorized **Debian 13 AMD64 VM** installed the pinned set using
authenticated APT metadata. Authenticated ARI returned 200; unauthenticated ARI
returned 401. PJSIP, Stasis, WebSocket and ARI channel/event modules were running;
radio modules were absent, AMI disabled, and the account had no hardware groups.
An unchanged rerun reported **`changed=0`**, with identical PBX/OpenAlert service
timestamps. Attempting to select `distro` afterwards failed with zero changes.
The random test credential was absent from captured output, logs and diff output.

The earlier result used `local_iax: false`. Subsequent runs on **both Debian 13
and Ubuntu 26.04.1 AMD64** enabled local PJSIP and IAX2 and passed module,
endpoint/context, IAX secret-file permission and loopback UDP listener checks.
ARI returned 200 with credentials and 401 without them. Unchanged reruns made
zero changes and preserved service timestamps; provider-switch rejection and
all three credential-output checks passed. Ubuntu installed only official
`asterisk`/`asterisk-modules` version `1:22.5.2~dfsg+~cs6.15.60671435-1`.
Combined Python/PBX/OpenAlert installation and unchanged reruns passed on both
VMs as well. No calls or peer registration were generated.

The first run exposed a missing `res_websocket_client` dependency; a later rerun
exposed two writers normalizing `modules.conf` differently. Both were corrected
before recording the passing results. No calls were processed. Existing OpenAlert
test services were not restarted. See [tests](../tests/README.md) and the
[support matrix](support-matrix.md).

**Still unqualified:** ARM64 execution, local-extension/trunk calls, media/audio
delivery, package-version upgrades, reboot recovery and adoption/rollback. The
broader consolidation remains in progress. Pinning also means security updates
need active review: monitor upstream Asterisk and AllStarLink advisories, select
a fixed updated version, and rehearse it on an isolated host before production.
No security-update SLA or production-readiness certification is asserted here.

Publisher references: [repository policy](https://allstarlink.github.io/developers/aptly/),
[package sources](https://github.com/AllStarLink/asl3-asterisk),
[AMD64 index](https://repo.allstarlink.org/public/dists/trixie/main/binary-amd64/Packages),
[ARM64 index](https://repo.allstarlink.org/public/dists/trixie/main/binary-arm64/Packages).
