# Asterisk package providers

The shared PBX role supports an **explicitly selected AllStarLink provider** for
Debian 13 (`trixie`) on AMD64 and ARM64. It is not an architecture-based fallback.
AllStarLink packages are third-party Asterisk builds with radio extensions, not
official Debian packages. Only the AMD64 installation/API/rerun scenario below
has been exercised; this is not full telephony or ARM64 qualification.

## Selection

| Setting | Behavior |
| --- | --- |
| `stack_deploy_asterisk: false` | Leave the PBX entirely unmanaged. Configure Python's ARI endpoint for the externally managed PBX. No PBX packages, repository or configuration changes. |
| `stack_deploy_asterisk: true`, `asterisk_package_provider: distro` | Existing distribution-package route, where packages are available; compatibility default. Debian 13's official repositories currently lack the server package. |
| `stack_deploy_asterisk: true`, `asterisk_package_provider: allstarlink` | Signed `trixie/main` packages with exact version selection. Debian 13 only; no Ubuntu or RedHat repository mixing. |

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

## Pins and trust boundary

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

## Configuration and safety

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

Both providers retain the public `local_sip` / `local_iax` selectors and the four
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
Select `--provider distro` for Ubuntu or `--provider allstarlink` for Debian 13;
the isolated inventory must acknowledge `stack_disposable_test_acknowledged`.
These checks inspect configuration/status only; they do not register phones or
originate calls.

## Evidence and remaining work

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
