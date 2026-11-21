# Native lifecycle and recovery

**Phase 4 implementation and disposable `systemd` rehearsals on Debian 13 and
Ubuntu 26.04 LTS AMD64 are complete; this is not live-migration authorization.**
Always rehearse on an isolated target before using these operations on an existing
site. All temporary qualification VMs have been deleted. Production maintenance
and dispatch/ARM64 hardware tests require separate authorization. Phase 3's
role-prefix naming findings remain explicitly deferred as tracked debt (not
suppressed).

## Explicit scope, not automatic discovery

`playbooks/backup.yml`, `restore.yml` and `rollback.yml` invoke the shared
`stack_lifecycle` role. They do not select a live inventory, install a database,
adopt external services or discover units by prefix. Run from `deploy/ansible`
with its `ansible.cfg` and a reviewed inventory; always limit maintenance to the
intended host. Check mode is rejected, because it cannot prove snapshot validity.

Before maintenance:

1. Obtain a maintenance window and separate authorization for the target. Block
   incoming alerts/calls, suspend schedulers and drain or deliberately quarantine
   queues. Stop **all writers**, including external clients, not just HTTP units.
2. Review exact configuration, identities/keys, custom templates, state paths,
   unit files/drop-ins and immutable release assets. Include every dependency
   needed to recover; a list of paths is not automatic backup completeness.
3. Record artifact hashes, source/lockfile revision, package versions and the
   reviewed database schema compatibility identifier. Schema identifiers are
   operator assertions based on migration review, not automatic schema detection.
4. Check space for snapshots **and** retained pre-restore files, and save an
   encrypted off-host copy with a separately trusted manifest digest. Local
   snapshots alone do not survive loss of the host/disk.

Example maintenance variables (synthetic paths; adapt to the target):

```yaml
stack_lifecycle_acknowledged: true
stack_lifecycle_maintenance_window: "Approved isolated rehearsal"
stack_lifecycle_snapshot_id: rehearsal-001
stack_lifecycle_kind: full
stack_lifecycle_schema_id: reviewed-schema-v1
stack_lifecycle_release_id: reviewed-artifact-sha256-or-deployment-revision
stack_lifecycle_paths:
  - /etc/openalert/hub
  - /etc/systemd/system/openalertd-hub.service
  - /etc/systemd/system/openalertd-hub.service.d
  - /var/lib/openalert/hub
stack_lifecycle_units:
  - openalertd-hub.service
stack_lifecycle_postgresql_databases: []
```

```bash
ansible-playbook -i /absolute/reviewed-inventory.yml playbooks/backup.yml \
  --limit rehearsal-host -e @/absolute/maintenance.yml
```

Each backup requires a new snapshot ID; existing backups are never overwritten.
Omitted units/paths/instances are untouched. Empty unit lists require the explicit
`stack_lifecycle_quiesced: true` assertion for an already-offline dataset.
`/run/lock/py-phone-caller-lifecycle` serializes lifecycle runs on a host. An
interrupted run may leave a stale lock: investigate the interrupted operation
before manually removing it. Never steal a lock or run independent installers
concurrently. The lock cannot prevent an administrator or another deployment
system from modifying files outside this protocol.

## Snapshot contract

Default storage is `/var/backups/py-phone-caller`, root-owned mode `0700`.
Snapshots contain a versioned manifest, content hashes, original paths/modes/
numeric ownership and metadata. Secret contents and recovery command output are
suppressed in Ansible logs and diffs. This is access protection, **not encryption**
or an independently signed authenticity guarantee.

The helper rejects symlinks, special files, traversal, overlapping roots and
malformed manifests. SQLite databases are recognized by their header and copied
using SQLite's consistent backup API, including committed WAL contents; WAL/SHM
files are not copied as ordinary data. Do not snapshot entire homes or virtual
environments containing links. Select concrete application roots, and reproduce
the Python environment from its recorded locked inputs instead.

Restoration verifies all artifacts against the independently supplied plan before
writing active paths. Replaced roots are retained in private sibling directories
for manual recovery; no automatic pruning is performed. Directory replacement
is not a globally atomic multi-filesystem transaction, and a power failure still
requires inspection. Filesystem ACLs, extended attributes, SELinux labels, file
capabilities and changed UID/GID mappings need explicit recovery review; ordinary
mode/ownership preservation alone is not sufficient for those installations.

### PostgreSQL

Add exact local database names to `stack_lifecycle_postgresql_databases` for a
full snapshot. The role uses `pg_dump --format=custom`, with peer authentication
as `postgres` on `/var/run/postgresql`, port `5432`; clients must already be
installed and compatible with the server. It never reads or prints a database
password. PostgreSQL itself remains running while application writers are stopped.
Raw `/var/lib/postgresql` backups are rejected.

This initial workflow does **not** take over external databases, alternate ports,
cluster-wide roles/tablespaces or replication configuration. Protect those with
their own database-aware procedure. Dumps of several databases are individually
consistent, not one cross-database transaction. Target roles, extensions and
databases must already exist. No Redis/Valkey queue replay policy is inferred.

## Full restore

Use the same paths, unit list, release identity, snapshot ID and database names
as the backup. `stack_lifecycle_snapshot_schema_id` identifies the **snapshot's**
schema; `stack_lifecycle_schema_id` identifies the current state. Unlike binary
rollback, explicit full recovery may restore an older schema and lose data
created after the backup. Obtain the separate data-loss approval first.

```yaml
stack_lifecycle_snapshot_schema_id: reviewed-schema-v1
stack_lifecycle_database_restore_acknowledged: true  # Required if PostgreSQL is selected
stack_lifecycle_start_after_restore: false           # Safe default
```

```bash
ansible-playbook -i /absolute/reviewed-inventory.yml playbooks/restore.yml \
  --limit rehearsal-host -e @/absolute/maintenance.yml
```

The role stops declared services, restores verified files, then performs
`pg_restore --clean --if-exists --exit-on-error --single-transaction` for each
declared database. Failures leave application services stopped. Database restore
is transactional per database, not across databases or filesystem roots. Inspect
the recovery result before enabling any traffic.

Services remain stopped by default. Validate configuration as the service
account, immutable release compatibility, permissions, database contents and
identity/routing preservation first. Review pending work to avoid replaying old
calls or alerts. Only then explicitly set `stack_lifecycle_start_after_restore`
to `true` for a rehearsed procedure. Optional `stack_lifecycle_health_urls` accepts
only loopback `/health` endpoints and uses GET without redirects or proxies.
Starting a daemon can resume its own background dispatch even if the verifier
only sends GETs; isolate egress and hardware for rehearsals.

## Asset-only rollback

Create a **separate** backup with `stack_lifecycle_kind: assets`, containing both
the matching configuration/unit definitions and the previous immutable release.
Only `/etc/...` and `/opt/<application>/releases/...` paths are accepted; writable
state and PostgreSQL dumps are forbidden. Do not label a state directory as an
asset to bypass the contract.

```bash
ansible-playbook -i /absolute/reviewed-inventory.yml playbooks/rollback.yml \
  --limit rehearsal-host -e @/absolute/asset-snapshot.yml
```

Rollback requires identical current/snapshot schema compatibility identifiers.
**Binary rollback is not database rollback.** If the candidate performed an
incompatible migration, stop; use the reviewed full recovery procedure instead.
Generic asset snapshots do not downgrade APT packages or reconstruct a Python
virtual environment, and are not a claim of automatic Python/PBX version rollback.

## OpenAlert candidate activation and in-place adoption

Normal deployment now retains a full state checkpoint and a separate matched-assets
checkpoint **only for changed existing instances**, after all candidates pass
validation. Declare reviewed schema compatibility per instance:

```yaml
openalert_instances:
  hub:
    config_template: /absolute/protected/hub.toml.j2
    health_url: http://127.0.0.1:8090/health
    openalert_schema:
      current: reviewed-schema-v1
      target: reviewed-schema-v1
```

Schema values are not release versions. After an upgrade, update `current` to the
recorded active schema before the next changed deployment. Previously managed
instances without an active schema record require an explicit reviewed assertion
on their first changed deployment. Fresh installs can omit schema metadata;
existing installations cannot omit it on a changed activation.

Changed instances stop before consistent checkpointing; new assets activate only
after checkpoint verification. Failed activation attempts matched configuration,
unit/drop-in and management-record recovery **only when schemas match**, without
replacing current database contents. A schema mismatch, incomplete checkpoint or
failed recovered health leaves the instance stopped and reports the retained
checkpoint location. A recovered candidate failure still fails the playbook.
Unchanged instances receive health verification without stop/restart/checkpoint;
an already-stopped unchanged service fails health rather than being started
implicitly.

Transactions live under
`/var/lib/openalert-installer/checkpoints/<instance>/<transaction>/`, with private
`full.json`, `assets.json`, `recovery.json`, `full/` and `assets/` snapshots.
Immutable release directories are retained rather than pruned. These checkpoints
use the snapshot helper directly and are **not** interchangeable with generic
`stack_lifecycle_snapshot_id` backups. Before manual data recovery, review their
plans, verify the snapshot with the helper, quiesce the instance, and restore the
full snapshot only with separate data-loss approval. Do not edit transaction
metadata to force an incompatible automatic recovery.

`playbooks/adopt.yml` is the explicit OpenAlert adoption entry point, supporting
both **in-place** adoption (`adopt-openalert-in-place`) and **account/path
relocation** (`relocate: true` with `adopt-openalert-relocate`), using the same
`stack_hosts`/`stack` host selection as other lifecycle playbooks.

For in-place adoption (where service name, non-root user/group, `/etc/openalert/...`
config path and `/var/lib/openalert/...` state directory already match):

```yaml
openalert_adopt: true
openalert_maintenance_window: true
openalert_adoption_acknowledgement: adopt-openalert-in-place
openalert_legacy_instances:
  hub:
    service_name: openalertd-hub.service
    user: oa-hub
    group: oa-hub
    config_path: /etc/openalert/hub/openalertd.toml
    state_dir: /var/lib/openalert/hub
    unit_path: /etc/systemd/system/openalertd-hub.service
    binary_path: /usr/local/bin/openalertd
    templates_dir: /etc/openalert/hub-templates
```

The first five legacy fields must match the target instance exactly. Add
`openalert_templates_dir: /etc/openalert/hub-templates` to that instance and
declare equal current/target schema IDs.

For account/path relocation from a root-run VPS layout (`/root/...` or `User=root`)
or a home-directory field-node layout (`/home/<user>/...` with a non-root user)
into dedicated `oa-<instance>` system accounts, `/etc/openalert/<instance>/openalertd.toml`,
and `/var/lib/openalert/<instance>`:

```yaml
openalert_adopt: true
openalert_maintenance_window: true
openalert_adoption_acknowledgement: adopt-openalert-relocate
openalert_legacy_instances:
  hub:
    relocate: true
    service_name: openalertd.service
    user: root
    group: root
    config_path: /etc/openalert/openalertd.toml
    state_dir: /root/openalert-hub
    unit_path: /etc/systemd/system/openalertd.service
    binary_path: /usr/local/bin/openalertd
    templates_dir: /usr/share/openalert/templates
  public:
    relocate: true
    service_name: openalertd-public.service
    user: root
    group: root
    config_path: /etc/openalert-public/openalertd.toml
    state_dir: /var/lib/openalert-public
    unit_path: /etc/systemd/system/openalertd-public.service
    binary_path: /usr/local/bin/openalertd
    templates_dir: /usr/share/openalert/templates
```

When `relocate: true` is set:
- `service_name` must match the target instance's `service_name`, while the target
  instance defines a dedicated non-root `user`/`group` and disjoint `/etc/...` and
  `/var/lib/...` target paths.
- Candidate staging creates only the disjoint target account, target directories
  and staged custom templates (if templates are relocated out of `/root`, `/home`,
  or the legacy `state_dir`), without mutating legacy unit, configuration or state
  files prior to validation.
- Equivalence verification requires 100% identical parsed TOML settings (keys,
  ports, listeners, auth tokens, routing, transports), allowing only
  `[templates].template_dir` to map from `legacy.templates_dir` to
  `openalert_instance.openalert_templates_dir` and `[storage].path` to preserve the
  exact relative database filename inside the relocated `state_dir`.
- During activation, after stopping the legacy unit and verifying both `full` and
  `assets` checkpoints of the legacy paths (including WAL-folded, integrity-checked
  SQLite databases and key files), the checkpoint step materializes the verified
  state snapshot into the target `state_dir` with target account ownership and
  non-world permissions (`0750` directories, `0600`/`0640` files).
- If candidate activation or health verification fails, `openalert_recover` restores
  the legacy unit and configuration from `assets` and quarantines the newly created
  target paths (`*.openalert-failed-<uuid>`), leaving the legacy `state_dir` and
  configuration intact.

Render the **complete existing TOML**: parsed equality is required, protecting
keys, ports and routing, not just a selected subset of settings. Back up any
additional secret or identity file paths not represented by the declared state
before maintenance.

Adoption rejects unsupported service hooks/environment files/drop-ins, alternate
roots, indirect launch commands and unapproved working-directory changes. Remove
the adoption flags/mapping after successful takeover and use ordinary `site.yml`
for subsequent runs. Legacy state directories are retained untouched after
relocation for operator inspection; there is no automatic instance removal or
pruning. Python/PBX adoption and package rollback remain manual, separately
reviewed procedures.

## Qualification status and pre-migration checklist

Disposable `systemd` rehearsals on **both Debian 13 AMD64 and Ubuntu 26.04 LTS AMD64**
were completed on 2026-11-07 (`ppc-qual-debian-standard-20261107` and
`ppc-qual-ubuntu-standard-20261107`), covering:
- In-place adoption (`adopt-openalert-in-place`) and account/path relocation
  (`relocate: true` / `adopt-openalert-relocate`) for root-run VPS (`User=root`,
  `/root/...`) and home-directory field layouts (`User=fieldops`, `/home/fieldops/...`).
- Candidate-health failure recovery and failed-path quarantine (`*.openalert-failed-<uuid>`)
  leaving the legacy service active and uncorrupted.
- Ordinary `site.yml` unchanged reruns (`changed=0`) after adoption.
- Full `backup.yml` -> `restore.yml` (SQLite + PostgreSQL 17/18 `py_phone_caller_runtime`),
  assets-only `rollback.yml`, and incompatible-schema rollback refusal.

See the [support matrix](support-matrix.md) for recorded image and artifact identities.
Before any live-host migration, rehearse the exact site inventory/templates on an
isolated target; physical Orange Pi 5 Plus ARM64 hardware and actual dispatch remain
separate gates pending board arrival and authorization.
