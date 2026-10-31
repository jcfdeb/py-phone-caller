# OpenAlert role: Phase 2 contract

Use [`../site.yml`](../site.yml) with the [explicit-inventory quickstart](../README.md).
This is a description of the current implementation, not a production-readiness
or complete security guarantee. Consult the [evidence matrix](support-matrix.md)
before treating any scenario as qualified.

## Platform and release inputs

The canonical entry point checks Debian 13 or Ubuntu 26.04, `systemd`, and
managed-host `x86_64`/`aarch64` facts. The OpenAlert role requires target Python
3.11+ and maps those CPU facts to `amd64`/`arm64`. Do not bypass `site.yml`'s
platform checks by treating direct role inclusion as a broader support promise.

| Variable | Default / requirement |
| --- | --- |
| `openalert_release` | `{}`; required mapping with `source` and `sha256`. |
| `openalert_release.source` | Absolute controller-local archive path or HTTPS URL fetched by the managed host. No default or implicit latest release. |
| `openalert_release.sha256` | Required trusted lowercase 64-hex **archive** digest, not the binary digest. |
| `openalert_instances` | `{}`; required nonempty mapping keyed by instance name. |
| `openalert_root` | `/opt/openalert`; root-owned downloads and content-addressed releases. |
| `openalert_management_dir` | `/var/lib/openalert-installer`; ownership records, candidates and listener-validation input. |
| `openalert_helper` | `/usr/local/libexec/openalert-contract.py`; managed validation helper. |
| `openalert_runtime_packages` | `dbus`, `libdbus-1-3`, `libgcc-s1`, `acl`; additional release dependencies must also be available. |
| `openalert_instance_defaults` | Shared per-instance policy/resource defaults listed below; each instance can override them. |

Keep installer/release layout defaults unless you have reviewed their ownership
and path implications. The role installs runtime packages, not a Rust toolchain.
The trusted bundle must follow the
[schema-1 release contract](../../../src/openalert/packaging/README.md), including
`release.json`, `bin/openalertd`, bundled templates/profiles and the canonical
`systemd/openalertd.service`.

Local input is checksum-checked on the controller before transfer. HTTPS input
uses certificate verification and the inventory-pinned checksum; the helper
rechecks the archive before extraction. It checks archive layout, metadata,
binary digest/ELF architecture, GNU loader, minimum glibc and required libraries
against the managed host. It does not execute the release to inspect its ELF
dependencies. A filename, successful download or CPU match alone is insufficient.

Use a separately trusted checksum, reviewed provenance and controlled artifacts:
these checks are not signatures or proof that arbitrary bundled code is safe.
The release directory is content-addressed, root-owned and treated as immutable;
cached contents are checked rather than trusted solely because a marker exists.
Do not edit extracted templates or units in place.

## Per-instance reference

Names match `[a-z][a-z0-9_-]{0,23}`. Defaults derive from the mapping key, not
from the service filename. Each instance needs a distinct account, group,
service, configuration directory and non-overlapping state directory.

| Instance key | Default | Contract |
| --- | --- | --- |
| `user` | `oa-<name>` | Dedicated non-root system account, locked password, `/usr/sbin/nologin`; home is `state_dir`. |
| `group` | `oa-<name>` | Dedicated primary group; defaults to the same name as the default user. If overriding `user`, set `group` explicitly if desired. |
| `service_name` | `openalertd-<name>.service` | Simple `.service` filename; examples explicitly use `openalertd.service` and `openalertd-public.service`. |
| `config_path` | `/etc/openalert/<name>/openalertd.toml` | Absolute `.toml` path **under `/etc/`**, with a separate protected parent directory. Arbitrary filesystem locations are not supported. |
| `state_dir` | `/var/lib/openalert/<name>` | Absolute path under `/var/lib/<base>/<instance>`; private writable state and service working directory. No overlapping instance trees or escaping data paths. |
| `config_template` | Required | Controller-side Jinja template path; rendered as protected TOML, not copied from live configuration automatically. |
| `health_url` | Required | `http://127.0.0.1:<port>/health` or IPv6 loopback equivalent; `https` when REST TLS is enabled. Must match the rendered REST listener and port. |
| `supplementary_groups` | `[]` | Explicit existing groups needed by hardware. The role sets the declared list, not an additive unmanaged list. |
| `device_paths` | `[]` | Explicit existing character-device paths under `/dev/`; configured serial devices must be declared and accessible as the service account. |
| `capabilities` | `[]` | Explicit subset of `CAP_NET_BIND_SERVICE`, `CAP_NET_ADMIN`, `CAP_NET_RAW`, `CAP_SYS_TIME`; systemd capabilities, **no file capabilities**. |
| `cpu_quota` | `50%` | Integer percentage for `CPUQuota`. |
| `memory_high` | `100M` | Integer with optional `K`, `M` or `G` suffix for `MemoryHigh`. |
| `memory_max` | `150M` | Same format for `MemoryMax`. |
| `tasks_max` | `256` | Positive integer for `TasksMax`. |
| `limit_nofile` | `65536` | Positive integer for `LimitNOFILE`. |
| `allow_unauthenticated_nonloopback` | `false` | Deliberate exposure exception, never a public-safety certification. |
| `exposure_policy` | Empty string | Nonempty operator policy/rationale required when the exception above is enabled. It does not install a firewall or enforce that policy. |

`rest_port` in the examples is an input to their Jinja template, **not** a role
default or separate listener declaration. Actual listeners are derived from
the rendered TOML. Listener checks cover REST TCP, enabled embedded Nostr relay
TCP and enabled peering UDP. They reject overlapping declarations among the
instances supplied to that run, conservatively treating IPv6 wildcard binds as
dual-stack. This is not an audit of all listening processes, omitted instances,
firewall rules or external reachability.

## Configuration, state and secret handling

Templates receive `openalert_instance` (the resolved instance mapping) and
`openalert_release_dir` (the extracted release root). Use the immutable bundled
asset path in every rendered configuration:

```toml
[templates]
template_dir = "{{ openalert_release_dir }}/templates"
default_template = "prometheus_alertmanager.json.tera"

[storage]
enabled = true
path = "{{ openalert_instance.state_dir }}/openalert.db"
recover_pending_on_startup = false
```

The helper requires that template directory to resolve to the selected release's
bundled `templates` directory; an arbitrary external template tree is not part
of this contract. It checks readable assets and supported static template
references. Writable databases/identity data must remain within instance state;
relative paths are interpreted from the state directory. External/shared state,
escaping links and database URIs are not migration mechanisms. Review all enabled
transports and recovery behavior before starting a real configuration.

Use protected controller templates plus Vault-encrypted variables, for example
through inventory's `stack_openalert_vars_files`. The example template is a
non-secret starting point, not a place to commit credentials. Sensitive render,
validation and activation tasks suppress logs/diffs. Candidates and active TOML
are root-owned, instance-group-readable `0640` files; their protected directories
are `0750`. State is owned by the instance account with mode `0750`.

Vault protects secrets at rest on the controller, not decrypted files on the
managed host. Candidate files and activation backups may retain secrets; protect
and account for them in operational backup/retention policy. Do not use debug
tasks, inventory dumps with vars, verbose secret-bearing commands or repository
commits to inspect credentials. This role's protected configuration is not a
promise of daemon-side editing of root-owned TOML.

`OPENALERT_`/`OPENALERTD_` configuration environment overrides are rejected by
the helper: the validated TOML must describe what the service runs. Do not add
out-of-band unit overrides that bypass that contract.

## Exposure and hardware exceptions

The example inventories both bind REST to loopback and disable dispatch
transports. In the two-instance example, `public` is still private. Neither the
instance name nor a passing health probe implies safe unauthenticated internet
or LAN exposure.

For non-loopback HTTP, the current helper requires REST and dashboard
authentication, and SOS authentication when SOS is enabled, unless the explicit
exposure exception is used. A non-loopback embedded Nostr relay also requires
that exception. Peering requires a valid shared key. This is configuration
validation, not verification of authentication strength, TLS deployment,
network isolation or an external proxy. A loopback health URL must still reach
the configured REST listener; a listener bound only to a non-loopback address
does not satisfy that health contract.

`allow_unauthenticated_nonloopback: true` together with a nonempty
`exposure_policy` acknowledges a reviewed exception; it does not make exposure
safe. Provision and independently verify firewall/proxy/TLS/authentication
controls before considering exposure. The role does not configure Wi-Fi APs,
reverse proxies or a safe public SOS service.

Hardware access is opt-in:

- Supply existing supplementary groups and character-device paths appropriate
  to the actual image and peripherals. Verify the device identity; stable
  `/dev/serial/by-id/` symlinks are followed for the character-device preflight.
  Declared devices must exist; serial access is checked as the instance account.
- BLE configuration requires explicit `CAP_NET_ADMIN` and `CAP_NET_RAW`.
  Clock stepping in peering time sync requires explicit `CAP_SYS_TIME`; disable
  clock stepping when it is not needed. No capability is enabled by default.
- The drop-in uses `PrivateDevices=yes` by default and relaxes it for declared
  devices or `CAP_NET_RAW`. A device declaration is **not** a device-cgroup
  allowlist or proof that only that hardware is reachable.
- Host drivers, firmware, BlueZ/D-Bus policy, serial permissions and board/image
  qualification remain operator prerequisites. Passing static checks does not
  establish radio, modem or telephony functionality.

## Staging, activation and ownership

The role does not run the standalone `install.sh`, Wi-Fi setup script or
`setcap`. It uses the release's packaged base unit and a per-instance
`instance.conf` drop-in. Systemd dependency lists cannot be removed through an
empty drop-in assignment: the packaged base's D-Bus/Bluetooth ordering remains,
and D-Bus is a runtime prerequisite even without BLE. The drop-in resets
`ExecStart`/`ExecReload`, environment, supplementary groups, directory directives,
write paths, capability sets and address families before setting instance values.
Defaults have empty capability sets, `ProtectClock=yes`, private devices and
only `AF_INET`, `AF_INET6`, `AF_UNIX`. Requested hardware capabilities explicitly
change relevant settings; other hardening remains inherited from the base unit.

The current sequence is:

1. Validate declared inputs and fresh-install conflicts; install runtime
   prerequisites and verify/extract the pinned release.
2. Create/reserve dedicated identities, private state and protected candidates.
   Run the configuration helper and the release's `openalertd check` **as each
   service account**, checking state/assets/permissions/exposure before activation.
3. Stage the packaged unit and instance drop-in, run `systemd-analyze verify`,
   and check declared listeners across all candidates. All supplied instances
   are staged before any is activated.
4. Copy validated configuration/unit assets into place, reload systemd when unit
   assets change, enable/start each instance, and restart only an instance whose
   active configuration or unit assets changed.
5. Probe only the instance's loopback health URL with `GET`, expecting HTTP 200
   and JSON `status: ok`. No redirects or proxy use; no event submission.

These are implementation boundaries, not an atomic transaction: staging can
create packages, accounts, ownership records and directories; activation can
partially complete and health can fail after startup. There is no automatic
rollback guarantee. An unchanged instance may still be started if it was stopped.
Service-account validation runs outside the final systemd sandbox and does not
prove that every runtime operation will succeed within it.
The probe does not exercise radio, calls or SMS; custom daemon configurations
can themselves initiate activity when started, so keep installation fixtures
non-dispatching and never infer authorization to test live destinations.

Ownership records under `openalert_management_dir/owners` bind the instance name
to its account, group, service, config and state paths. A fresh conflicting
account, registered unit or managed path is rejected rather than silently
adopted. Recorded identity/path changes are rejected as migration attempts.
Do not forge ownership records or delete existing data to force a fresh run.

Instances omitted from inventory are **untouched**: no pruning, disabling or
removal. Keep a complete reviewed listener inventory when planning coexistence.
Removal, adoption, state migration and lifecycle/rollback workflows are not
implemented until Phase 4. A deployment rerun is not a supported live migration.

The real role explicitly rejects `--check`; use `tests/render.yml` for offline
synthetic rendering, not as a substitute for disposable-host qualification.