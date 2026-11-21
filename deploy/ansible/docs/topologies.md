# Native topology and offline installation contract

Topology, ingress ownership, connectivity and CPU architecture are independent
choices. These profiles compose the existing shared roles, not separate installers.
**Connected `enterprise` (Debian 13, Ubuntu 26.04 LTS, and Rocky Linux 10.2 AMD64)
and fully `airgapped` `standard` (Debian 13 and Ubuntu 26.04 LTS AMD64) profiles
are runtime-qualified on disposable VMs.** ARM64 hardware tests remain paused
pending Orange Pi 5 Plus board arrival and separate authorization.

Start from the intentionally incomplete
[enterprise example](../inventories/examples/enterprise/hosts.yml) or
[standard air-gapped example](../inventories/examples/standard-airgapped/hosts.yml).
They contain documentation-only addresses, no real credentials and no dispatch
destinations. Supply reviewed artifacts and Vault variables before a separately
authorized disposable-host rehearsal. They are not production inventories.

## Profiles and compatibility

| Setting | Meaning |
| --- | --- |
| `py_phone_caller_topology: legacy` | Default: retain existing gateway/Caddy switches and application configuration. |
| `py_phone_caller_topology: standard` | Local application authentication; no managed APISIX, etcd or Keycloak. |
| `py_phone_caller_topology: enterprise` | Manage APISIX and Keycloak; configure application OIDC against the explicit public origin. |
| `py_phone_caller_ingress: caddy` | Manage the edge proxy; direct UI upstream for standard, APISIX upstream for enterprise. |
| `py_phone_caller_ingress: external` | Leave Apache or another existing edge entirely unmanaged. |
| `py_phone_caller_connectivity: online` | Normal connected installation, independently of profile. |
| `py_phone_caller_connectivity: airgapped` | Fail-closed offline installation using explicitly staged inputs; never public download fallback. |

Explicit profiles derive gateway/reverse-proxy management defaults. Existing
`py_phone_caller_manage_gateway`, `py_phone_caller_manage_reverse_proxy` and the
legacy `py_phone_caller_manage_caddy` alias remain available. Contradictions with
an explicit profile fail before component installation. In `legacy`, old flag
combinations retain their old meanings. No flag removes existing services,
certificates, firewall rules, Keycloak data or identities. Switching profile is
**not** a migration or decommissioning procedure.

The standard profile rejects inherited `auth.provider`, enabled OAuth and
`gateway.behind_gateway` settings inconsistent with local login. Clear those
explicitly rather than copying the checked-in live-site variables. UI listeners
must be loopback; new Python service units also bind their HTTP APIs to loopback.
Legacy service binding is unchanged unless `PPC_HTTP_BIND_HOST` is supplied.
Explicit enterprise disables local-login fallback; legacy gateway behavior is
unchanged. Provision and rehearse Keycloak access before any production cutover
to avoid locking out administrators.

## TLS and reverse proxies

Require `py_phone_caller_public_url` as an HTTPS origin without credentials,
paths, query or fragment. For managed Caddy, `caddy_domain_name` must match its
host and optional port. Select exactly one certificate owner:

- `py_phone_caller_tls_mode: acme`: managed Caddy obtains public certificates;
  requires `caddy_email`, suitable DNS/reachability and public connectivity.
- `internal`: Caddy's internal CA; distribute its root to client trust stores
  through an authenticated administrative channel. No public CA dependency.
- `provided`: use pre-staged `py_phone_caller_tls_certificate` and
  `py_phone_caller_tls_private_key` paths on the host. The operator owns secure
  provisioning, file permissions, chain validation and renewal.
- `external`: the unmanaged ingress owns TLS and renewal; only valid with
  `py_phone_caller_ingress: external`.

Apache → APISIX is a legitimate TLS-termination architecture. The read-only
Hetzner inspection on 2026-11-01 confirmed Apache's HTTPS vhost forwards to
`127.0.0.1:9080`, sets the HTTPS forwarding headers and uses Certbot certificates.
HTTP redirected to HTTPS and an HTTPS HEAD request returned 200. This was not
an OIDC-login, header-spoofing or renewal rehearsal, and changed no host settings.

An external edge must overwrite client-supplied forwarding headers, preserve
the reviewed public host/protocol/port, support required WebSockets, redirect
HTTP to HTTPS and restrict access to its backend. Configure only trusted proxy
addresses, not arbitrary Internet senders. Authentication redirects and secure
cookies must be tested through the complete chain. Do not assume that trusting
`X-Forwarded-*` from any source is safe.

New-profile backend/dashboard ports are not public ingress. Existing broad
firewall rules are not automatically revoked; review them during an explicitly
authorized maintenance window. Apache takeover, certificate migration and
changing production listeners are outside ordinary profile selection.

## Enterprise prerequisites

Enterprise additionally requires an already provisioned dedicated PostgreSQL
database, supplied via `gateway_keycloak_postgresql_url` (a JDBC PostgreSQL URL),
`gateway_keycloak_postgresql_username` and Vault-protected
`gateway_keycloak_postgresql_password`. It does not create or take ownership of
that database. Keycloak uses production `start`, never a development database
fallback. Preserve its database backups and validate the pinned image's schema
upgrade policy before upgrades. No public Keycloak admin route is provisioned;
use a separately protected administrative access path.

Explicit managed ingress preflight requires working `ss`, `iptables` and
`ip6tables` for ownership inspection. A foreign proxy/NAT rule or unlabelled
gateway container is a stop condition, not an invitation to replace it. For
air-gapped enterprise, rootful Podman and every reviewed digest-pinned image
must already be staged. Container startup uses `--pull=never`.

## Fully air-gapped provisioning

Air-gapped means both installer and application use local resources, **not**
"install from the Internet, disconnect later". The first supported repository
backend is a preconfigured **signed `file:` APT mirror** on Debian 13 or Ubuntu
26.04. Arbitrary HTTP mirrors and automatic mirror/OS provisioning are not part
of this implementation. Retain signature verification and reviewed keys.

Prepare the controller itself offline: its Python environment, pinned Ansible
packages and collections, this reviewed source tree and any controller-local
OpenAlert bundle must already be available. The online quickstart's `pip` and
`ansible-galaxy` downloads are preparation commands for a connected builder,
not commands to run inside the isolated environment.

Prepare matching target-native Python/toolchain/dependency caches and selected
model files on a connected, reviewed builder, then transfer through the site's
approved media process. Match OS, architecture, Python patch, `uv.lock` and
source identity; the controller's architecture must not select target artifacts.
The offline path does not manufacture missing wheels or silently reduce the
locked workspace. A lighter selected speech engine does not remove the other
declared dependencies. Manifest digests must come from a trusted review channel.

### Required offline inputs

| Input | Location / requirement |
| --- | --- |
| `py_phone_caller_local_src_path` | Controller-local prepared source release; `py_phone_caller_git_repo` must be empty. |
| `py_phone_caller_airgap_source_manifest_path` | Controller-local JSON manifest outside the source tree. |
| `py_phone_caller_airgap_source_manifest_checksum` | Independently reviewed `sha256:<hex>` of that manifest. |
| `py_phone_caller_airgap_bundle_dir` | Immutable target-local native bundle; root-owned, with no group/world-writable ancestors. |
| `py_phone_caller_airgap_manifest_path` | Target-local JSON manifest outside the bundle. |
| `py_phone_caller_airgap_manifest_checksum` | Independently reviewed `sha256:<hex>` of the target manifest. |
| `py_phone_caller_airgap_rust_toolchain` | Exact staged Rust version and GNU target triple, such as `<version>-aarch64-unknown-linux-gnu`. |
| `py_phone_caller_airgap_networks` | Optional strictly private RFC1918/ULA peer subnets; loopback is always allowed. |

Each manifest has `version: 1`, `files: {"relative/path": "<SHA256>"}` and
optionally `symlinks: {"relative/link": "relative/target"}`. The target manifest
also records `architecture` (`x86_64` or `aarch64`), `python_version` and
`uv_version`, matching the inventory pins. Inventory **every** file/link:
unlisted, missing, modified or escaping artifacts fail. Do not stage the live
working tree with credentials, local environments or unrelated build output.

Required target layout:

```text
bin/uv
python/bin/python3.14       # plus the complete matching Python runtime
uv-cache/                  # all locked wheels/sdists and build requirements
cargo/                     # offline registries, crates and any required git sources
rustup/toolchains/<exact-toolchain>/
build-constraints.txt
models/huggingface/
models/torch/
models/cache/
models/<selected-and-preloaded-assets>
```

The prepared source's `pyproject.toml` must contain reviewed exact
`tool.uv.build-constraint-dependencies` pins matching `build-constraints.txt`.
This is a build-policy prerequisite, not a reason to change or remove the
workspace dependencies. Keep workspace and Cargo lockfiles. The offline path
consumes these artifacts; see `tests/prepare_airgap_fixture.yml` and
`tests/files/prepare_airgap_fixture.py` for the disposable-builder exporter and
signed flat APT mirror helper exercised during Debian 13 and Ubuntu 26.04 LTS
AMD64 qualification. Test the full artifact set on the matching connected builder
with public egress blocked before transfer.

Set `generate_audio.pre_trained_models_folder` to `<bundle>/models`. Only local
supported TTS engines are accepted; Google TTS and cloud SMS are rejected.
The selected engine and every preloaded model need real staged assets. Kokoro
also needs `wheels/en_core_web_sm-3.8.0-py3-none-any.whl` for English; when
Japanese (`ja`) or Chinese (`zh`) Kokoro voices are used, stage the pinned
`py_phone_caller_kokoro_cjk_packages` wheels under `wheels/kokoro-cjk/` (or
enable `py_phone_caller_install_kokoro_cjk: true` in connected deployments).
Missing runtime model compatibility is an error to resolve, not permission to
silently choose a different engine.

The installer hashes inputs before invoking staged executables, disables
download fallback and executes Python/Rust builds in a network namespace.
Mutable build caches are separate from the checksum-reviewed bundle. Forced
restart handlers remain blocked until offline installation succeeds. Runtime
units receive the fixed `py_phone_caller_airgap_runtime_environment` cache paths
and offline flags; do not override them to re-enable downloads.

No public APT URI, unsafe signature bypass, APT download hook or proxy is
accepted. Source/bootstrap programs and local mirrors are trusted operator
inputs; the role does not establish their provenance merely by hashing them.

The installation path must validate its staged inputs before changes, disable
Python and Rust download fallback, and fail on incomplete caches. Optional PBX
packages and runtime libraries must also exist in the signed local APT mirror.
Debian AllStarLink retains exact package pins without adding its public
repository; Ubuntu continues using official Ubuntu packages. Optional OpenAlert
requires a controller-local checksum-pinned release.

Runtime isolation is a deployment prerequisite, not something an environment
variable alone proves. Use an isolated network with no public route; include
clients/browsers, containers, DNS and the controller in that boundary. Declare
only internal runtime peers in `py_phone_caller_airgap_networks`; Python units
deny other IP traffic. Internal DNS, time, PBX, database and queue services must
be provisioned locally where used. No network/AP/WireGuard reconfiguration is
performed by these roles.

The UI suppresses external font requests in offline mode, using bundled/system
fallback fonts. Offline API-documentation behavior is deliberately separate
from online CDN-backed documentation: interactive Swagger is unavailable, with
a local explanation and same-origin JSON links instead. Selected speech models and native SMS
build inputs must be present before service activation. No automatic model
download or public SaaS carrier is an acceptable offline fallback.

## Qualification gates and recorded status

- Synthetic preflight/rendering tests establish selector and template behavior,
  not successful installation of a complete artifact set.
- **Completed AMD64 VM qualification (2026-11-01 / 2026-11-07):**
  - Connected `enterprise` installation and unchanged reruns (`changed=0`,
    `identical_evidence=true`) passed on **Debian 13 AMD64**, **Ubuntu 26.04 LTS
    AMD64**, and **Rocky Linux 10.2 AMD64** (with Tucny Asterisk `22.9.0-1.el10`
    and SELinux `Enforcing`), including live interactive Keycloak OIDC login
    (`https://caller.internal/login` -> `/realms/py-phone-caller/protocol/openid-connect/auth`
    -> `https://caller.internal/`, HTTP `200`).
  - Fully `airgapped` `standard` installation and unchanged reruns (`changed=0`,
    `identical_evidence=true`) passed on **Debian 13 AMD64** and **Ubuntu 26.04 LTS
    AMD64** with egress blocked, including offline Piper TTS WAV synthesis,
    authentic local UI login over trusted TLS, negative-case manifest/checksum
    rejection, and selective UI change (`changed=3`, `native.sha256` untouched,
    only `py-phone-caller-ui` restarted).
- All temporary qualification VMs and networks have been deleted. Production
  changes, telephony/radio traffic and physical Orange Pi 5 Plus ARM64 hardware
  tests require separate approval upon hardware arrival. See the
  [support matrix](support-matrix.md) for full details.