# Native installer checks

Run from `deploy/ansible` in the pinned controller environment described in the
parent README, with `ANSIBLE_CONFIG="$PWD/ansible.cfg"`. Never use the checked-in
live inventory for these checks.

## Topology and offline contracts

```bash
python -m pytest tests/test_topology.py tests/test_topology_ingress.py tests/test_airgap.py tests/test_runtime_isolation.py -q
```

These use synthetic inventories, files and rendered configuration only. They do
not install a full offline Python/TTS artifact set or start production gateway
containers. See [topology prerequisites and runtime gates](../docs/topologies.md)
for egress-blocked installation/rerun, local login, certificate trust and OIDC
rehearsals requiring a newly authorized disposable host. `--offline` on a linter
is unrelated to qualifying an air-gapped installation. ARM64 hardware remains
paused until device arrival.

## Offline checks

```bash
python -m unittest discover -s tests -p test_openalert_contract.py -v
python -m pytest tests tools/test_toml_to_ansible_vars.py -q
ansible-playbook -i localhost, site.yml --syntax-check
ansible-playbook -i localhost, tests/render.yml
ansible-playbook -i localhost, tests/preflight.yml
ansible-lint --offline -c .ansible-lint roles/openalert roles/stack_preflight tests/render.yml tests/preflight.yml
```

The 48 helper/runner tests use synthetic ELF/runtime fixtures, including ARM64, not
emulation or real hardware execution. Preflight tests use synthetic host facts
and never deploy component roles; expected invalid-selector failures are caught
and asserted. Rendered examples are written under the ignored `.rendered/` path.
The scoped lint command covers OpenAlert/preflight. Full native-tree lint also
checks consolidated roles and still reports role-prefix naming findings; see the
support matrix. Those findings are not suppressed or claimed as a pass.
The final regression run passed **110 tests / 709 subtests** without warnings;
the final standalone full lint run reported **77 naming findings only**. Run lint
after the tests, not concurrently: synthetic role tests create and remove temporary
playbooks inside role directories that lint would otherwise discover mid-run.

## Disposable systemd integration

**Rootless-container limitation:** on the available rootless Podman host, systemd fails at
`226/NAMESPACE` setting up the packaged sandbox (`/proc/irq`: permission denied).
Archive/config/unit staging passed, but service startup, health and subsequent
idempotence cases did not. Do not disable production hardening to make tests pass.
All eleven scenarios subsequently passed on Debian 13 and Ubuntu 26.04.1 AMD64 VMs.
Use a disposable Debian 13 or Ubuntu 26.04 VM with working namespace isolation
for qualification. No existing live server or field node is an authorized target.

Copy `disposable-vm.example.yml` outside the repository (or into ignored
`.runtime/`), enter your authorized test host's connection settings, and run:

```bash
python tests/run_disposable.py --bundle /absolute/path/to/openalertd.tar.gz \
  --sha256 TRUSTED_SHA256 --inventory /absolute/path/to/disposable-vm.yml \
  --host disposable-openalert --allow-disposable-changes
```

The runner requires both the command-line acknowledgement and the inventory's
`stack_disposable_test_acknowledged: true`. It limits installation and inspection
to the single named host. `inspect.yml` records nonsecret service start timestamps
and package/workspace state without reading application logs or sending events.

The container harness is retained for compatible isolated runtimes. It creates
no published ports or host device mounts. Its outer `SYS_ADMIN`/unmask settings
apply only to a **rootless container**, not to the OpenAlert account; do not run
these commands as root or add privileged host mounts.

```bash
ansible-galaxy collection install -r tests/requirements.yml -p "$PWD/.collections"
podman build --pull=never -t localhost/openalert-ansible-test:phase2 -f tests/Containerfile tests
# In a separate terminal, keep the disposable container running:
podman run --rm --name openalert-ansible-phase2 \
  --label openalert.ansible-test=true --cap-add SYS_ADMIN --security-opt unmask=ALL \
  --systemd=always --hostname openalert-test localhost/openalert-ansible-test:phase2
```

Supply an actual locally built AMD64 release and its independently verified
checksum. The base image is pinned by digest; provision that image first if
`--pull=never` reports it missing. The harness uses only the labelled test
container and refuses an unlabelled target:

```bash
python tests/run_disposable.py --bundle /absolute/path/to/openalertd.tar.gz \
  --sha256 TRUSTED_SHA256 --allow-disposable-changes
podman stop --time 10 openalert-ansible-phase2
```

The runner defines two-instance installation, unchanged rerun (`changed=0` and
unchanged start timestamps), one-instance configuration change, missing-template
rejection, duplicate-listener rejection, wrong-checksum rejection and omitted
instance preservation. It verifies that PBX/database/queue packages and the
Python workspace were not installed. The examples disable dispatch transports;
only health GETs are used. Logs go to ignored `.runtime/` with restricted parent
permissions. Test definitions are not passing execution evidence.

All eleven runtime cases passed on both authorized AMD64 VMs, including unsafe
exposure, unmanaged-unit conflicts, duplicate units and synthetic-secret diff
assertions. End-to-end HTTPS delivery remains untested. Use repeated `--scenario`
options to select additional cases; the default runs the complete suite, and
each invocation first establishes a safe two-instance baseline.
Exact artifact/image/results are recorded in `docs/support-matrix.md`.
Python/PBX combined and external-dependency checks use the separate runner below.

## PBX checks: official Ubuntu packages or Debian AllStarLink

```bash
python tests/test_pbx_roles.py
python tests/run_pbx_disposable.py --inventory /absolute/path/to/disposable-vm.yml \
  --host disposable-pbx --provider distro --allow-disposable-changes
```

The second command **installs and starts Asterisk on an authorized Ubuntu 26.04 VM**.
Use `--provider allstarlink` for the reviewed Debian 13 third-party package set.
The target must also declare `stack_disposable_test_acknowledged: true`. It uses
the shared entry point with Python and OpenAlert unselected, loopback ARI/SIP,
local PJSIP/IAX2 endpoints, no trunk registration and no radio modules. Random ARI,
PJSIP and IAX credentials are retained under ignored `.runtime/pbx/` with restricted permissions;
never commit these inputs. Requests are status GETs only, not calls or alerts.

Both AMD64 VMs passed authenticated/unauthenticated API checks, PJSIP/IAX2
module/endpoint/listener checks, zero-change reruns with matching service timestamps,
provider-conflict rejection and output/diff secret checks.
Logs and nonsecret runtime evidence are under `.runtime/pbx/`. This runner does
not test real calls, ARM64, package-version upgrades, reboot or recovery.

## Full Python and combined startup checks

First run the PBX checks above, retaining their private generated inputs. The
Python runner reuses those credentials, never a live site's variables. It uses
the complete synthetic `fixtures/python-runtime.yml`, a fresh test database and
queue index, empty receiver/modem lists, private application listeners, and
systemd `IPAddressDeny=any` / `IPAddressAllow=localhost` restrictions. The full
frozen Python workspace is installed; no dependency profiles are removed.

```bash
python tests/run_python_disposable.py \
  --inventory /absolute/path/to/disposable-vm.yml --host disposable-pbx \
  --provider distro --uv-installer-sha256 REVIEWED_UV_INSTALLER_SHA256 \
  --scenario python --allow-disposable-changes
```

Use `allstarlink` on Debian. Require the same inventory acknowledgement and an
explicit single-host limit. The installer changes services on that host;
ordinary checks perform health/status GETs, not calls, SMS or alert submission.
The root `verify.yml` is shared; the legacy location is a compatibility wrapper.

Available scenarios:

| `--scenario` | Additional inputs and checks |
| --- | --- |
| `python` | Python-only selection with managed local database/queue; service startup/health and zero-change rerun. |
| `combined` | Add `--bundle /absolute/openalertd.tar.gz --sha256 TRUSTED_SHA256`; deploy Python, PBX and two OpenAlert instances together. |
| `external` | After a managed baseline, turn database/queue management off; require unchanged dependency configuration hashes and unmanaged service timestamps. This uses local endpoints, not a second database machine. |
| `legacy-python` | Invoke the old Python wrapper, retaining `app_servers` selection. |
| `legacy-combined` | Invoke the old combined wrapper, with Python-derived ARI/dialplan values. |
| `git` | Add `--git-repo HTTPS_REPOSITORY --git-commit FULL_COMMIT_SHA`; use an available immutable revision, never a moving branch. |

Every scenario compares service start timestamps and checks `changed=0` on the
second run. `--resume-rerun` resumes only that second check after a completed
installation report, for a timeout—not to ignore failures. Legacy scenarios use
synthetic top-level playbooks with `ANSIBLE_PLAYBOOK_VARS_ROOT=top` so adjacent
checked-in live-site variables are never loaded. Controller logs/reports stay
under ignored `.runtime/python/<host>/<scenario>/`; they are scanned for the
synthetic credentials. Do not publish private input files.

Recorded results: Python-only, combined and externally managed dependency modes
passed on both AMD64 distributions. Legacy Python and Git delivery passed on
Ubuntu; legacy combined passed on Debian. The disposable Ubuntu VM/disk were
deleted afterwards. Gateway provisioning uses isolated API fixtures; actual
gateway containers, remote dependency transport, model inference and hardware
are not qualified by these checks.

## Lifecycle fixtures

```bash
python -m pytest tests/test_stack_snapshot.py tests/test_stack_lifecycle.py tests/test_openalert_lifecycle.py -q
python tests/run_postgresql_snapshot_fixture.py -v
ansible-lint --offline -c .ansible-lint roles/stack_lifecycle roles/openalert playbooks/adopt.yml playbooks/backup.yml playbooks/restore.yml playbooks/rollback.yml
```

The PostgreSQL fixture requires local server/client binaries, runs as the current
non-root user, uses only a private Unix socket (no TCP listener), and shuts down
its temporary server in `finally`. All data lives under ignored `tests/.runtime`.
It exercises an actual custom dump and database restore, not a mocked database.
It does not run the privileged role or qualify systemd recovery on Debian/Ubuntu.
The snapshot tests cover committed SQLite WAL content, corrupt/unsafe snapshots,
mapping and retained pre-restore files. Guards invoke read-only Ansible with
synthetic facts; they never load a live inventory.

Both earlier cloud VMs were deleted. See [the lifecycle runbook](../docs/lifecycle.md)
for the separately authorized disposable-host rehearsals still required before
production adoption or recovery claims.
