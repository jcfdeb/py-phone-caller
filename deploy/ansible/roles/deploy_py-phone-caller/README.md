## Shared role and migration contract

The role remains named `deploy_py-phone-caller`; existing `py_phone_caller_*`
variables are retained. It explicitly includes `postgresql`, `queue`, `gateway`,
`reverse_proxy`, and `firewall`, which consume the same variable namespace and
effective configuration. Entrypoints own inventory loading and platform preflight:
the new native path targets Debian 13 / Ubuntu 26.04; legacy RedHat package,
PostgreSQL initialization, Valkey, COPR, and firewalld branches remain available.

`py_phone_caller_topology` defaults to `legacy`, preserving the switches below.
Explicit `standard`/`enterprise` profiles add consistent authentication, ingress
and TLS policy; `py_phone_caller_connectivity: airgapped` requires a complete
offline artifact set. See [the topology contract](../../docs/topologies.md).
New profiles are not yet runtime-qualified; no existing ingress is adopted or
disabled automatically.

| Management selector | Default / compatibility |
| --- | --- |
| `py_phone_caller_manage_postgresql` | Legacy `manage_database` AND `manage_local_postgres`; true for local defaults |
| `py_phone_caller_manage_queue` | True when effective `queue.queue_host` is loopback |
| `py_phone_caller_manage_gateway` | Existing opt-in flag, false |
| `py_phone_caller_manage_reverse_proxy` | Existing `manage_caddy` flag, true |
| `py_phone_caller_manage_firewall` | Existing flag, true |

Selectors are booleans. `false` means **leave installed resources untouched**, not
uninstall or stop. External database/queue hosts never trigger local packages or
service management, even if their selector is true. Remote databases, including
the optional Keycloak database, must be provisioned outside this role. A local
but externally managed service also uses `false`. No wildcard unit discovery or
automatic stale-unit deletion remains; retire old units explicitly after review.

### Source and reproducibility inputs

Both Git and local-copy deployments use `<install_dir>/app/<workspace member>`.
Git requires a full commit SHA and stages in `<install_dir>/.source`; local delivery
requires `py_phone_caller_local_src_path` to be the repository root. Root
`pyproject.toml` AND `uv.lock` paths are translated from `src/` to `app/`; member
relative dependency paths are preserved. Only root README/LICENSE/babel metadata
is copied, not controller inventories or credentials. Existing `src/`, `data/`,
models, rendered config, and generated audio survive migration. Inspect/copy any
legacy state to its configured runtime path yourself; the role does not delete it.

Native installation retains `uv sync --frozen --all-packages --no-dev`. Full ARM
lock qualification is a later gate. AMD64 startup/rerun checks passed on Debian 13
and Ubuntu 26.04 LTS with uv **0.11.15** / Python **3.14.5**; the uv catalogue does
not offer 3.14.6. See [tested inputs and mappings](../../docs/python-native.md).
`--inexact` preserves the explicitly installed native SMS/spaCy extras only when
selected. Supply reviewed `sha256:<64 lowercase hex>` values for
`py_phone_caller_uv_installer_checksum`, `py_phone_caller_spacy_model_checksum`
(Kokoro only), and `py_phone_caller_caddy_signing_key_checksum` (managed Debian
upstream Caddy repository). uv/Python/maturin versions must be exact; existing uv
must match the selected version. Git branches and unverified downloads fail closed.

Gateway images (`py_phone_caller_{etcd,apisix,apisix_dashboard,keycloak}_image`)
must be inventory-reviewed `registry/name@sha256:<digest>` references. Empty
defaults deliberately fail rather than select `latest`. Review image compatibility,
architecture and `py_phone_caller_keycloak_uid` (default 1000) before enabling.
Container supplementary group 0 permits reading root-group 0640 TLS/config mounts;
Keycloak passwords are in a root-only 0600 environment file, never in the unit.
Set a private APISIX admin token; the upstream example token is rejected.

Shared configuration/dependency changes restart declared Python consumers;
service-source/unit changes restart only affected declared services. Gateway units
have their own change tracking. `manage_services=false` suppresses Python handlers.
All secret templates disable output and diff; `db_no_log=false` no longer exposes
credentials. Gateway provisioning no longer resets the Web UI fallback password
on every run; use the application's explicit account-recovery procedure instead.

Optional `py_phone_caller_service_ip_address_deny` and
`py_phone_caller_service_ip_address_allow` lists emit systemd network restrictions.
The disposable profile denies `any` except `localhost`; this intentionally blocks
real trunks/providers and model downloads at runtime. Production policies must
match the required dependency endpoints rather than copy the test restriction.

## Notes

* No `PYTHONPATH` is set. `uv sync` installs every workspace member into the
  virtualenv as an editable install pointing at `<install_dir>/app`, which is
  why that path must not move.
* `PrivateTmp` is deliberately off: `caller_sms` and `celery_worker` share the
  on-premise SMS SQLite database under `/tmp`.
* Migrations are not run from Ansible. `caller_register` applies them at
  startup, exactly as in the container and Kubernetes stacks, so there is one
  implementation rather than two.

### API Gateway & Keycloak IAM Integration (Opt-In)

| Variable | Default | Description |
| --- | --- | --- |
| `py_phone_caller_manage_gateway` | `false` | Enable Apache APISIX gateway and Keycloak IAM |
| `py_phone_caller_gateway_http_port` | `9080` | APISIX plaintext ingress port |
| `py_phone_caller_gateway_https_port` | `9443` | APISIX TLS reverse proxy port |
| `py_phone_caller_gateway_dashboard_port` | `9001` | APISIX Manager Dashboard port |
| `py_phone_caller_keycloak_http_port` | `8180` | Keycloak plaintext HTTP port |
| `py_phone_caller_keycloak_https_port` | `8443` | Keycloak TLS HTTPS port |
| `py_phone_caller_keycloak_realm` | `"py-phone-caller"` | Keycloak security realm |
| `py_phone_caller_keycloak_admin_user` | `"admin"` | Keycloak administrative account |
| `py_phone_caller_credentials_dir` | `"{{ inventory_dir }}/credentials"` | Control node secret storage |
| `py_phone_caller_server_credentials_path` | `"/etc/py-phone-caller/credentials.env"` | Target emergency credential export (0600) |

#### Credential storage

With the gateway enabled, explicit inventory secrets take precedence; otherwise
the role reuses the private target credential file or generates control-node
secrets under `py_phone_caller_credentials_dir`. Retain and protect that directory
across runs. Prefer Vault-encrypted **inventory variables** for reviewed secrets;
do not encrypt the raw files consumed by `lookup('password')` in place.

The target recovery file is root-only (`0600`) and is never printed. The legacy
Web UI fallback password variable is not used to reset application accounts.
Inventory loading, Vault invocation, and recovery wrappers belong to the calling
entrypoint, not this role.
