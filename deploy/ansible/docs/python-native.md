# Native Python deployment and compatibility mapping

The shared entry point supports independently selected Python, Asterisk and
OpenAlert on Debian 13, Ubuntu 26.04 LTS, Rocky Linux 10, and AlmaLinux 10. AMD64
startup/rerun evidence is in the [support matrix](support-matrix.md); physical ARM64
appliance execution remains a separate maintenance gate.
Neither a working VM installation nor this document authorizes live adoption.

## Inventory and source inputs

Generate application variables from **reviewed, private** TOML files with the
[converter](../tools/README.md), using its explicit `--output` and
`--secrets-output` paths in your new inventory. Encrypt secrets with Vault. Do not
reuse the checked-in legacy site inventory or copy the runtime test passwords.

```yaml
stack_deploy_py_phone_caller: true
stack_deploy_asterisk: true
stack_deploy_openalert: false

# Ubuntu 26.04: official distribution packages. On Debian 13 explicitly choose
# allstarlink, or leave stack_deploy_asterisk false for an externally managed PBX.
asterisk_package_provider: distro
asterisk_http_bindaddr: 127.0.0.1
asterisk_sip_bindaddr: 127.0.0.1:5060
asterisk_sip_trunk_enabled: false
local_sip: false
local_iax: false

py_phone_caller_local_src_path: /absolute/path/to/reviewed/repository
py_phone_caller_uv_installer_checksum: "sha256:REPLACE_WITH_REVIEWED_SHA256"
py_phone_caller_manage_postgresql: true
py_phone_caller_manage_queue: true
py_phone_caller_manage_gateway: false
py_phone_caller_manage_reverse_proxy: false
py_phone_caller_manage_firewall: false
```

The application still needs complete `py_phone_caller_config` and
`py_phone_caller_config_secrets` variables; this snippet is not a complete
inventory. Declare private application listeners and reviewed database/queue
endpoints there. Disabled firewall management is not an exposure policy: apply
your independently managed firewall before enabling non-loopback services.
See the [PJSIP/IAX2 reference](asterisk-provider.md#explicit-local-pjsip--iax2)
to opt in to local endpoints with protected credentials.

For Git delivery set `py_phone_caller_git_repo` and a full immutable
`py_phone_caller_git_version` commit instead of a local path. Git stages in
`/opt/py-phone-caller/.source`; both delivery methods install the workspace under
`/opt/py-phone-caller/app`. Configuration, generated audio, models and state are
excluded from source deletion. This is not a migration procedure for legacy data.

The validated default toolchain pair is **uv 0.11.15 / Python 3.14.5**. Its uv
catalogue does not offer Python 3.14.6: changing Python alone is insufficient.
Review updated toolchain pins together, on disposable hosts. The reviewed
`https://astral.sh/uv/0.11.15/install.sh` SHA-256 for these tests was
`1f2aa4d24003ae99e4979f87f5e3122d240ec6b1ef0bc06c4bee3e33bb9151f2`.
This records a publisher-HTTPS review, not an independent signature authority;
production inventories must supply their own approved checksum.

The role retains `uv sync --frozen --all-packages --no-dev`. Selecting another
TTS engine does not omit the other locked dependencies. CPU/model inference,
modem hardware and capacity tests are separate from service startup. For single-board
and resource-bounded hosts, `py_phone_caller_ui_workers`,
`py_phone_caller_ui_threads`, `py_phone_caller_celery_concurrency`,
`py_phone_caller_service_{cpu_quota,memory_high,memory_max,tasks_max}` and
`py_phone_caller_service_resource_overrides` tune Gunicorn, Celery and per-unit
`systemd` cgroup limits without modifying role templates; see the
[ARM64 appliance profile](appliance-arm64.md).

## Ownership and compatibility

| Existing setting/command | Shared behavior |
| --- | --- |
| `py_phone_caller_manage_database` + `py_phone_caller_manage_local_postgres` | Compatibility inputs to `py_phone_caller_manage_postgresql`; remote endpoints never provision a local database. |
| `py_phone_caller_manage_queue` | Local Redis/Valkey management only; false leaves existing service/configuration untouched. |
| `py_phone_caller_manage_caddy` | Compatibility input to `py_phone_caller_manage_reverse_proxy`. |
| `py_phone_caller_manage_gateway`, `py_phone_caller_manage_firewall` | Explicit ownership; disabling does not remove existing resources. |
| `py_phone_caller_*`, `ari_*`, `local_sip*`, `local_iax*`, `pbx_*` | Existing public namespaces/legacy aliases retained. |
| `on-vm_py-phone-caller/deploy_py-phone-caller.yml` | Python-only compatibility wrapper, `app_servers`. |
| `deploy_all/deploy_py-phone-caller_stack.yml` | Python + PBX wrapper, `app_servers`, shared ARI/dialplan values. |
| `asterisk_py-phone-caller/deploy_asterisk.yml` | PBX-only wrapper; historical `pbx_servers:all` selection includes all inventory hosts. Review `--list-hosts` and use `--limit`. |
| `on-vm_py-phone-caller/verify.yml` | Compatibility wrapper for shared `verify.yml`; status/health GETs only. |

Optional gateway containers require digest-pinned images and protected secrets;
optional managed Caddy/model downloads require their own reviewed checksums.
Empty pins fail rather than silently downloading floating releases. Gateway
provisioning fingerprints prevent repeated API writes on unchanged inputs; API
failures do not write a successful-completion marker.

Use shared `verify.yml` with the same protected inventory/configuration used for
deployment. It verifies declared units, health endpoints and UI reachability; it
does not originate calls, SMS or alerts. Reboot, upgrades, adoption and database
restore qualification remain outside this phase.
