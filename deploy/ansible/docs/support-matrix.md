# Native deployment support and evidence matrix

**No production-ready claim or live migration
authorization is made.** Platform acceptance in `site.yml`, synthetic fixtures,
a built archive and a prepared test host are different kinds of evidence.

This snapshot records checks executed on **2026-10-30** and the explicitly dated
Phase 4 additions from **2026-11-01**. Phases 1–2 are complete
for the recorded milestone. The rootless-container limitation was resolved by
using separately authorized Debian 13 and Ubuntu 26.04 Google Cloud VMs.
Phase 3 runtime checks below are complete. On **2026-11-01**, the user approved
closing that implementation milestone with its 77 naming findings explicitly
deferred, not fixed or suppressed, so Phase 4 implementation can proceed.
Do not infer broader platform qualification from these scenario-specific results.

## Evidence versus qualification

| Scenario | Recorded result | What this establishes / does not establish |
| --- | --- | --- |
| Phase 1 release packaging tests | **27 tests passed** in the recorded Phase 1 evidence. | Packaging/fixture evidence, not managed-host runtime or board qualification. |
| Real native AMD64 release build | **Completed:** locked Rust **1.99.1** build on **openSUSE Leap 16.0**; archive checksum verified; artifact minimum glibc **2.38**. | Real build evidence. openSUSE was the builder, not an accepted `site.yml` deployment target. This does not prove Debian/Ubuntu runtime compatibility. |
| Phase 2 contract helper/runner tests | **48 tests passed**, including synthetic AMD64/ARM64 architecture fixtures and runner failure-parser regressions. | Archive/metadata/runtime-check, config, path and listener logic under test fixtures. Synthetic ELF/runtime fixtures are not real ARM64 execution or a full host security audit. |
| New entry-point syntax and offline rendering | **Passed** in the supplied snapshot. | Playbook syntax and synthetic private template/drop-in rendering. No service startup or hardware validation. |
| Component-isolation preflight | **Passed:** PBX-only selection with deliberately undefined Python/OpenAlert inputs; invalid selector values rejected. | Read-only orchestration checks with synthetic facts, not PBX installation. |
| Earlier rootless Ubuntu 26.04 container attempt | **Historical blocker:** service startup failed at `226/NAMESPACE` before daemon execution. | Rootless Podman could not create the protected mount namespace. The sandbox was not weakened; the container was removed. Later VM results below supersede this blocker for VM qualification, not container support. |
| Phase 2 lint | **Passed for new OpenAlert/preflight roles and offline test playbooks.** | Whole-entry-point lint also traverses legacy PBX code and reports existing namespace/style findings; legacy cleanup remains in Phase 3. |
| Debian 13 AMD64 VM runtime | **Passed:** fresh two-instance installation; healthy services; unchanged rerun with `changed=0` and identical start timestamps; hub-only change restarts only hub; missing-template, duplicate-listener and wrong-checksum rejection; omitted-instance preservation. | Real execution using the artifact below on kernel `6.12.113+deb13-cloud-amd64`. OpenAlert-only isolation verified: no Python workspace, Asterisk, PostgreSQL or queue packages. Not ARM64, peripheral or load qualification. |
| Debian VM safety and secret-output scenarios | **Passed:** unsafe exposure, unmanaged `ssh.service` conflict and duplicate-unit rejection; synthetic secrets present in staged/live TOML but absent from logs/stdout/stderr/diffs. | All negative cases preserved both OpenAlert start timestamps. Eleven runtime scenarios passed in total. The existing SSH service was not modified. |
| Ubuntu 26.04.1 LTS AMD64 OpenAlert | **Passed:** all eleven disposable-runtime cases, including two-instance startup, selective restart, rejection cases, output/diff redaction and zero-change rerun. | Tested before installing Python/PBX/data services, preserving OpenAlert-only isolation. Same trusted AMD64 artifact as Debian. |
| AllStarLink PBX-only, Debian 13 AMD64 | **Passed:** signed APT installation of `2:22.10.1+asl3-3.10.8-1.deb13`; authenticated ARI 200, unauthenticated 401; required modules running and radio modules absent; unchanged rerun `changed=0` with identical service timestamps; provider-change rejection with zero changes; credential absent from diff/logs. | 22 focused offline PBX tests also passed, including 11 AllStarLink preflight cases. Private ARI/SIP, AMI disabled, no calls processed. OpenAlert test services remained untouched. Not ARM64, call/media, upgrade, reboot or migration qualification. See [provider contract](asterisk-provider.md). |
| HTTPS artifact delivery | **Implemented with certificate verification and inventory-pinned SHA-256; end-to-end HTTPS delivery untested.** | Current VM runs used controller-local artifacts. |
| Ubuntu 26.04 ARM64 (Armbian 26.11.3) physical Orange Pi 5 Plus (RK3588) appliance (`online` & `airgapped`) | **Passed (2026-11-19 / 2026-11-20):** native ARM64 `openalertd v1.0.0` build (`1m 19s`), full frozen Python `3.14.5` workspace (`uv 0.11.15`, 217 wheels) + native `rust_engine` SMS extension (`aarch64`) built online and from scratch inside `unshare --net`; unchanged `site.yml` reruns `changed=0` (`ok=225` online, `ok=259` air-gapped) with identical timestamps across all 16 services; offline Piper TTS WAV synthesis (`7,642 ms` / `6,372 ms`, `45.3°C` peak); authentic Caddy strict-TLS Web UI login (`302 -> /`, `200`, `80,859 B`); cold-reboot recovery (`16/16 active`, `NRestarts=0`, `verify.yml` `ok=11`); **live on-premise GSM SMS delivery** over physical `SIMCOM_SIM7600E-H` (`14s`, Attempt 1, handset receipt confirmed); and **live Asterisk 22 VoIP/SIP voice call** to a LAN SIP softphone with on-the-fly offline Piper TTS synthesis, RTP audio playback, and PostgreSQL `heard_at` callback while air-gapped (`IPAddressDeny=any`). | Real physical RK3588 board + SIM7600E-H USB GSM + LAN SIP softphone execution (8 GB RAM, 512 GB NVMe, kernel `6.1.115-vendor-rk35xx`, `systemd 259`, `cgroup2fs`). Details below. Does not establish Debian 13 ARM64, PSTN SIP trunk peering, or physical BLE/LoRa RF transmission qualification. |
| Python-only and same-host Python/PBX/two-instance OpenAlert, Debian 13 and Ubuntu 26.04.1 AMD64 | **Passed:** full frozen workspace installation with uv 0.11.15 / Python 3.14.5, eleven application units, seven API health endpoints and UI; unchanged reruns `changed=0`, identical service timestamps. | Synthetic configuration, private listeners, empty test database/queue, loopback-only application egress. No TTS generation, calls, SMS or alert dispatch. Python-only leaves the existing test PBX/OpenAlert unmanaged. |
| PJSIP + IAX2 on both AMD64 VMs | **Passed:** required modules, local PJSIP endpoint/context, IAX peer/context/private UDP listener and protected credential file; ARI 200/401; zero-change reruns, secret redaction and provider-conflict rejection. | Debian uses the pinned AllStarLink set; Ubuntu uses official `resolute/universe` `asterisk`/`asterisk-modules` **`1:22.5.2~dfsg+~cs6.15.60671435-1`**. No third-party Ubuntu repository. No endpoint registration or calls were generated. |
| Externally managed database/queue mode, both AMD64 VMs | **Passed:** database/queue management disabled, configuration checksums unchanged, PostgreSQL/Redis/PBX/OpenAlert start timestamps unchanged; zero-change application rerun. | Existing loopback services treated as externally managed. This does not test a database/queue on another machine or remote TLS/firewall policy. |
| Legacy commands | **Passed:** Python wrapper on Ubuntu and combined wrapper on Debian, including zero-change reruns and unchanged timestamps. | Synthetic top-level test playbooks isolate checked-in live-site variables. Offline tests also cover legacy PBX host selection and variable loading. |
| Git/local source delivery | **Passed:** local-copy deployment on both VMs; pinned Git deployment/rerun on Ubuntu at `4484f140326f444791c691e795973ee41f469ccb`. | Public commit's `uv.lock` matches local SHA-256 `47374806a893485e66e5c3a3f8d44a9fda0154b5f2f717a2a8e4e35a1d365893`. An unpublished local commit was correctly rejected before retrying the available pin. Offline parity/state-preservation tests also pass. |
| Phase 3 automated regressions | **Passed: 110 tests, 709 subtests**, including six TOML-converter tests; no test warnings. | Real Ansible syntax/preflight/rendering, source and restart selection, gateway API idempotence/failure stamps, protected output, PBX/IAX/provider checks and release-contract tests. Gateway fixtures are not production-container qualification. |
| Whole native-tree lint | **Not clean: 77 `var-naming[no-role-prefix]` findings**, no other violations in the Phase 3 standalone run. No rule was disabled to hide them. | Public legacy namespaces must remain compatible; internal renames require the mandatory rename facility. User-approved deferred debt, no longer a gate on later implementation. |
| BLE, LoRa, serial modems, clock stepping, Wi-Fi AP/SOS exposure | **Hardware and exposure scenarios untested/unqualified here.** | Group/device/capability checks are not physical functional tests; the role does not provision Wi-Fi APs. |
| Radio transmission, calls or SMS dispatch | **Not tested by the installation probe.** | The role probes only loopback health with GET, never a dispatch endpoint. No functional delivery claim. |
| Phase 4 snapshot safety helper (2026-11-01) | **27 tests passed**, including committed SQLite WAL data, mapped restoration, corrupted snapshots, symlinks, private modes and replacement failure recovery. | Filesystem fixtures, not root-owned or systemd runtime qualification. Hashes establish integrity, not snapshot authenticity. |
| Phase 4 lifecycle guards (2026-11-01) | **8 tests / 25 subtests passed**, including real read-only Ansible preflight, authorization, scope, schema and data-loss guards. | No deployment inventory loaded and no system services changed. |
| Phase 4 integrated offline regressions and scoped lint (2026-11-01) | **156 tests / 785 subtests passed** across `deploy/ansible/tests`; scoped OpenAlert/lifecycle lint **passed with zero findings** across 29 files. | Includes 17 OpenAlert lifecycle tests and existing Python/PBX/entry-point regressions. Does not erase the deferred 77 findings elsewhere or qualify service recovery. |
| Phase 4 PostgreSQL recovery fixture (2026-11-01) | **Passed:** real local PostgreSQL custom dump, verified snapshot, changed data/configuration and matched restoration. | Isolated user-owned cluster with no TCP listener; child server stopped and fixture removed. Not a Debian/Ubuntu systemd-host or external database recovery qualification. |
| Existing installation adoption and lifecycle operations | **Passed (2026-11-07):** Guarded in-place adoption (`adopt-openalert-in-place`), account/path relocation (`relocate: true` / `adopt-openalert-relocate`) for root-run VPS (`User=root`, `/root/...`) and home-directory field layouts (`User=fieldops`, `/home/fieldops/...`), candidate-health failure recovery/quarantine, full `backup.yml` -> `restore.yml` (SQLite + PostgreSQL 18), and assets-only `rollback.yml` rehearsed on **both Debian 13 AMD64 and Ubuntu 26.04 LTS AMD64 systemd hosts**. | See [lifecycle runbook](lifecycle.md). Omission leaves instances untouched. No production migration authorization or crash-atomic rollback guarantee. |
| Topology/offline integrated regressions (2026-11-07) | **Passed across `deploy/ansible/tests`**, plus full air-gapped `standard` VM qualification on **both Debian 13 AMD64 and Ubuntu 26.04 LTS AMD64**. | Includes signed local APT file mirrors, offline `uv` wheelhouse/Python `3.14.5`, offline Piper TTS WAV synthesis (`31066` bytes on Debian 13, `42212` bytes on Ubuntu 26.04), authentic UI login over trusted TLS (`302 -> https://caller.internal/`), negative-case manifest/checksum rejection, selective UI change (`changed=3`, `native.sha256` untouched, only `py-phone-caller-ui` restarted), and `changed=0` unchanged reruns. See [topology contract](topologies.md). |
| Topology/offline scoped lint (2026-11-01) | **32 role-prefix naming findings remain** in the 61-file scoped run; YAML formatting applied, no other final violation categories and no rule suppressions. | Includes new cross-role naming debt as well as existing findings; not a replacement count for the earlier 77-finding whole-tree snapshot. Mandatory rename facility remains unavailable. |
| Debian 13 AMD64 enterprise unchanged rerun (2026-11-01) | **Passed:** `changed=0`, no failures/unreachable hosts; identical start timestamps/restart counters for 17 tracked services and identical hashes for 147 files. | Real connected installation with APISIX/Keycloak behind Caddy. Seven API health checks, strict TLS, private gateway listeners and read-only OIDC discovery passed. Details below. |
| Ubuntu 26.04.1 LTS AMD64 enterprise unchanged rerun (2026-11-01) | **Passed:** `changed=0`, no failures/unreachable hosts; identical start timestamps/restart counters for 17 services and identical hashes for 136 files. | Official Ubuntu Asterisk; full frozen Python workspace, APISIX/Keycloak and Caddy. Seven API health checks, strict TLS, private listeners and read-only OIDC discovery passed. |
| Rocky 10.2 AMD64 Tucny PBX (`22.9.0-1.el10`) and enterprise qualification (2026-11-07) | **Passed:** signed DNF install of `asterisk-22.9.0-1.el10.x86_64` (`res_ari_events.so` and `res_stasis.so` complete symbol closure), `run_pbx_disposable.py --provider tucny` (`changed=0` rerun + provider-conflict rejection), `run_topology_disposable.py` (`enterprise`, `changed=0` rerun, `identical_evidence=true`), and live interactive Keycloak OIDC login (`https://caller.internal/login` -> `/realms/py-phone-caller/protocol/openid-connect/auth` -> `https://caller.internal/`, HTTP `200`) with SELinux **Enforcing**. | Upstream `22.10.1-1.el10` through `22.12.0-1.el10` remain excluded due to `stasis_app_claim_channel` undefined symbol in `res_ari_events.so`. Details below. |
| Post-Tucny integrated regressions (2026-11-07) | **All unit and packaging tests pass** across `deploy/ansible/tests` and `tests/`. | Includes signed-key identity/idempotence, exact DNF pins (`22.9.0-1.el10`), provider conflicts, Rocky platform boundaries, Step 5 obsolete-unit removal, and all 5 release-packaging pillars. |
| Post-Tucny scoped lint (2026-11-01) | **71 naming-only findings** across 67 processed files; three new Tucny task files separately pass. | Includes compatibility/public-provider namespaces; no suppression. This scoped count does not replace earlier whole-tree or topology-only counts. |
| Expanded topology VM matrix and cleanup (2026-11-07) | **Completed:** Debian 13 and Ubuntu 26.04 LTS `enterprise` and `standard` (`airgapped`) + Step 6 lifecycle/relocation rehearsals passed; Rocky 10.2 Tucny PBX (`22.9.0-1.el10`) + `enterprise` + live OIDC login passed; Step 5 obsolete duplicate systemd units removed. | All temporary VMs (`ppc-qual-debian-standard-20261107`, `ppc-qual-ubuntu-standard-20261107`, `ppc-qual-rocky-pbx-20261107`), boot disks, firewall rules, subnets and networks were deleted (`Listed 0 items` verified at `2026-11-07T19:28:58Z`). |

Sources: [release packaging contract/evidence](../../../src/openalert/packaging/README.md),
[`tests/test_openalert_contract.py`](../tests/test_openalert_contract.py),
[`tests/render.yml`](../tests/render.yml),
[`tests/disposable.yml`](../tests/disposable.yml) and
[`tests/Containerfile`](../tests/Containerfile). Test definitions are not execution
results. The recorded test counts are a snapshot, not a claim about tests added
concurrently after that evidence was supplied.

Runtime attempt identity: Ubuntu base
`sha256:678c6550cc43645e08669028bc177f50be4e7c5b8cca677067b1914d4afc7a03`,
AMD64 archive
`sha256:86f444506182b2e2ada4fc7efea1ea77a61752ec8f63daefef99de5d1ead5b40`,
release `0.2.0-2430f957717a-amd64-fa3b1b2b0ae7` (working-tree build).
The same archive passed both VM scenarios. Ubuntu used image
`ubuntu-os-cloud/ubuntu-2604-resolute-amd64-v20261021`, kernel
`7.0.0-1014-gcp`, 4 vCPUs / 16 GB RAM / 50 GB disk. Its temporary VM and boot disk
were deleted after testing. The separately supplied Debian test VM and its disk
were subsequently deleted at the user's request. The separately authorized
2026-11-01 topology batch is recorded below; no test VM remains running at this
stopping point. Further tests must respect that batch's remaining resource limits.
Production servers and field nodes were not touched. Test instances bind loopback
and have dispatch transports disabled.
See [test instructions](../tests/README.md) for exact reproduction commands and
the distinction between helper fixtures and service-runtime tests.

## Debian enterprise unchanged rerun — 2026-11-01

Target: `debian-cloud/debian-13-trixie-v20261027` (image ID
`8720841040681124690`), AMD64, `n2-standard-4` (4 vCPUs / 16 GB), 100 GB boot
disk, Python `3.14.5`. The existing shared credential-directory permission fix
was already applied; no installer changes were needed in this verification.

From `deploy/ansible`, using the configured controller interpreter:

```bash
python tests/run_topology_disposable.py \
  --inventory tests/.runtime/topology-cloud/inventory.yml \
  --host topology-debian-enterprise \
  --inputs tests/.runtime/topology-cloud/enterprise-inputs.json \
  --allow-disposable-changes --resume-rerun
```

- Exit status **0**; deployment recap: `ok=285 changed=0 unreachable=0 failed=0
  skipped=81 rescued=0 ignored=0`. Final result: `qualified=true`,
  `identical_evidence=true`, `actual_authentication_performed=false`.
- All eleven Python units, four gateway units, Caddy and Asterisk retained
  identical start timestamps and restart counters. All 147 inspected file
  hashes matched. Python units retained localhost-only egress restrictions.
- Seven API health responses were `200`; strict-TLS health/home/login responses
  were `200/200/302`. Private gateway listeners and OIDC discovery passed.
  Discovery and a login redirect do **not** establish interactive authentication.
- Sanitized evidence remains in
  `tests/.runtime/topology/topology-debian-enterprise/enterprise/` (gitignored).
  SHA-256 of canonical JSON runtime evidence (sorted keys, compact separators):
  `870a271db7b954b276eecb123ebd8a4a944fa191693dca7ad75a6f04c5165718`.
- The earlier overlapping run finished naturally; its lock was not bypassed
  and no process was killed. A subsequent complete runner invocation produced
  the successful final result above.
- Deleted `ppc-qual-debian-enterprise-20261101`, its boot disk, the batch IAP
  firewall rule, subnet and network. Filtered cloud queries confirmed no batch
  resources or reserved addresses remained at `2026-11-01T18:08:41Z`.
  Conservatively charged **3.54 cumulative VM-hours**, one installation, to the
  authorized batch. Production hosts and unrelated resources were untouched.

The command is an execution record, not an immediately reusable target: its VM
and generated test credentials have been removed. No calls, SMS, radio traffic,
model inference, air-gapped installation or ARM64 hardware tests were performed.
The topology step remains open; this closes only its Debian enterprise
unchanged-rerun gate.

## Ubuntu enterprise unchanged rerun — 2026-11-01

Target: `ubuntu-os-cloud/ubuntu-2604-resolute-amd64-v20261021` (image ID
`5898740419867771658`), Ubuntu **26.04.1 LTS**, AMD64, kernel
`7.0.0-1014-gcp`, `n2-standard-4` (4 vCPUs / 16 GB), 100 GB boot disk.
The installer and qualification assertions were unchanged. The private fixture
preparer/bootstrap were parameterized for the new isolated inventory.

- Official `resolute/universe` Asterisk and modules:
  `1:22.5.2~dfsg+~cs6.15.60671435-1`. The PBX runner passed authenticated ARI,
  PJSIP/IAX2 configuration, radio-module exclusion, unchanged rerun and
  provider-conflict rejection. No third-party Ubuntu PBX repository was used.
- Full frozen workspace installed with Python `3.14.5`; installed infrastructure
  included Caddy `2.11.7`, PostgreSQL `18.6-0ubuntu0.26.04.1` and Redis
  `5:8.0.5-1ubuntu0.1`. Gateway image digests match the Debian enterprise fixture.
  A dedicated Keycloak database and private test CA were prepared explicitly;
  all calls, SMS and radio transmissions remained disabled/unexercised.
- Installation passed: `ok=270 changed=54 unreachable=0 failed=0 skipped=89
  rescued=0 ignored=0`. The first command exceeded its 30-minute execution
  limit during the subsequent rerun, after saving the successful baseline.
  Its lock was confirmed free; the rerun resumed without resetting that baseline.
- Final runner exit **0**, with `ok=275 changed=0 unreachable=0 failed=0
  skipped=80 rescued=0 ignored=0`. All **17 services** retained identical
  start timestamps/restart counters; all **136 inspected file hashes** matched.
  All eleven Python units retained localhost-only egress restrictions.
- Seven API health responses were `200`; strict-TLS health/home/login responses
  were `200/200/302`. Private gateway listeners and read-only OIDC discovery
  passed. Interactive authentication was **not** performed.
- Sanitized evidence: `tests/.runtime/topology/topology-ubuntu-enterprise/enterprise/`
  and `tests/.runtime/pbx/topology-ubuntu-enterprise/distro/` (gitignored).
  Canonical runtime evidence SHA-256:
  `3966a9eb4f5a84ce37277e0a1c4ae09cd46f58971f0bddec8b9917179c317c9c`.
  Fourteen retained evidence/fixture files were checked against generated
  credential values; no matches were found. Generated credentials were removed.
- Deleted `ppc-qual-ubuntu-enterprise-20261101`, its boot disk and the
  `ppc-qual-20261101b` network/subnet/IAP rule. Filtered cloud queries confirmed
  no batch resources or reserved addresses remained at `2026-11-01T19:06:43Z`.
  Charge **0.90 VM-hours** conservatively for this continuation: batch totals
  **two main installations, zero Rocky-9 fallback installations, 4.44 VM-hours**.

Final command, from `deploy/ansible`, using the configured interpreter:

```bash
python tests/run_topology_disposable.py \
  --inventory tests/.runtime/topology-cloud/ubuntu.yml \
  --host topology-ubuntu-enterprise \
  --inputs tests/.runtime/topology-cloud/topology-ubuntu-enterprise-inputs.json \
  --allow-disposable-changes --resume-rerun
```

This is an execution record: the VM and private inputs have been removed.
It establishes the connected enterprise rerun gate only, not offline installation,
interactive login, model inference, production readiness or ARM64 qualification.

## Rocky provider review and Tucny runtime blocker — 2026-11-01

Public, non-empty AMD64 package-directory indexes were reviewed for
[Rocky 10 BaseOS](https://dl.rockylinux.org/pub/rocky/10/BaseOS/x86_64/os/Packages/a/),
[AppStream](https://dl.rockylinux.org/pub/rocky/10/AppStream/x86_64/os/Packages/a/),
[CRB](https://dl.rockylinux.org/pub/rocky/10/CRB/x86_64/os/Packages/a/) and
[EPEL 10](https://dl.fedoraproject.org/pub/epel/10/Everything/x86_64/Packages/a/).
No `asterisk*` packages were found. This is repository-index evidence, not an
installed Rocky host's DNF dependency-resolution test.

The authorized version-9 fallback was evaluated against the
[EPEL 9 index](https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64/Packages/a/):
it offers `asterisk-18.26.4-1.el9` and associated subpackages. Official
[Asterisk lifecycle documentation](https://docs.asterisk.org/About-the-Project/Asterisk-Versions/)
records **18.x end of life on 2025-10-20**. No downstream extended-security
commitment was established in this review; this does not prove that EPEL never
backports fixes, but does not justify calling it a maintained production provider.

The user subsequently selected [Tucny](https://ast.tucny.com) to keep installation
and updates DNF-managed without Asterisk compilation. An explicit opt-in provider
was implemented and tested on a fresh Rocky VM; no EPEL 9 fallback was used.

Target: `rocky-linux-cloud/rocky-linux-10-v20261026`, image ID
`4414299933099848315`, Rocky **10.2**, kernel `6.12.0-211.67.1.el10_2.x86_64`,
`n2-standard-4`, 100 GB boot disk, SELinux **Enforcing**.

- DNF resolved and installed signed `asterisk`, `asterisk-pjsip`, `asterisk-iax2`
  and `asterisk-curl`, all `22.11.0-1.el10.x86_64`, plus signed packaged English
  sounds. No Asterisk source compilation, COPR substitution, signature bypass,
  SELinux disabling, calls or radio activity occurred.
- Key import was corrected for the pinned Ansible `rpm_key` module's inability
  to enumerate an unrelated version-6 Rocky key. Only the vendored Tucny key and
  its installed counterpart are inspected; the full primary fingerprint is
  verified before import and after it. A real-GnuPG/synthetic-RPM regression
  covers collision rejection and idempotence without changing controller RPM trust.
- Additional Tucny module dependencies were added to the existing explicit
  allowlist. PJSIP and IAX2 then reported `Running`; authenticated ARI info passed.
- **Required ARI events failed:** `res_ari_events.so: undefined symbol:
  stasis_app_claim_channel`. Binary inspection confirmed that module's undefined
  reference and found no matching export in the installed Asterisk executable or
  the core/PJSIP module set. The role correctly rejected the installation as
  incomplete; this is not an enterprise or unchanged-rerun pass.
- Installed `res_ari_events.so` SHA-256:
  `6d5a378117648e476eb3a4836961a5124fe7bda414cf702bd3ca318686ad8c87`;
  `res_stasis.so` SHA-256:
  `18180008e46d2ba477fdbf96ac623761eae690d398fcb6359dace1597dbfdf15`.
  Sanitized evidence is in `tests/.runtime/topology-cloud/rocky-ari-blocker.log`
  and `tests/.runtime/pbx/topology-rocky-enterprise/tucny/install.log` (gitignored).
  Seven retained evidence/fixture files were checked against generated credential
  values with no matches; generated private inputs and credentials were removed.
- Deleted `ppc-qual-rocky-enterprise-20261101`, its boot disk and the
  `ppc-qual-20261101c` network/subnet/IAP rule. Absence checks passed at
  `2026-11-01T21:05:06Z`. Charge **0.50 VM-hours** conservatively: cumulative
  batch **three main attempts, zero fallback installations, 4.94 VM-hours**.

The [provider reference](asterisk-provider.md) records unsigned repository
metadata, signed RPM enforcement, same-host initial key trust, update semantics
and the lack of a security SLA. **Do not recommend the failed `22.11.0-1.el10`
candidate pin for production.** See the 2026-11-07 resolution below using
`22.9.0-1.el10`.

## Debian 13 & Ubuntu 26.04 LTS `standard` `airgapped` + Step 6 Lifecycle/Relocation Qualification — 2026-11-07

1. **Debian 13 AMD64 (`ppc-qual-debian-standard-20261107`, ID `7731059878785092817`, image `debian-cloud/debian-13-trixie-v20261102`, image ID `7871189740937143171`)**:
   - Prepared signed local APT file mirror, offline `uv` wheelhouse (`0.11.15`), Python `3.14.5`, AllStarLink Asterisk `2:22.10.1+asl3-3.10.8-1.deb13`, and Piper TTS voice models under `/var/cache/py-phone-caller-offline`.
   - Passed `run_topology_disposable.py` (`PASS install`, `PASS unchanged`, `changed=0`, `identical_evidence=true`).
   - Verified offline Piper TTS WAV synthesis (`31066` bytes), authentic UI login over trusted TLS (`302 -> https://caller.internal/`), negative-case manifest/checksum rejection, and selective UI change (`changed=3`, `native.sha256` untouched, only `py-phone-caller-ui` restarted).
   - Completed Step 6 OpenAlert systemd in-place adoption (`adopt-openalert-in-place`), account/path relocation (`relocate: true` / `adopt-openalert-relocate`) for root-run VPS (`User=root`, `/root/...`) and home-directory field layouts (`User=fieldops`, `/home/fieldops/...`), candidate-health failure recovery/quarantine, full `backup.yml` -> `restore.yml` (SQLite + PostgreSQL 17.6 `py_phone_caller_runtime`), and assets-only `rollback.yml`.
   - Deleted `ppc-qual-debian-standard-20261107` and network `ppc-qual-20261107a` at `2026-11-07T17:00:21Z`.

2. **Ubuntu 26.04 LTS AMD64 (`ppc-qual-ubuntu-standard-20261107`, ID `7200199661846718340`, image `ubuntu-os-cloud/ubuntu-2604-resolute-amd64-v20261107`, image ID `2618444879663161160`)**:
   - Prepared signed local APT file mirror, offline `uv` wheelhouse (`0.11.15`), Python `3.14.5`, official Ubuntu Asterisk `1:22.5.2~dfsg+~cs6.15.60671435-1`, and Piper TTS voice models under `/var/cache/py-phone-caller-offline`. Updated `stack_airgap_check.py` to accept APT 3.1 built-in `APT::Solver "3.0"`.
   - Passed `run_topology_disposable.py` (`PASS install`, `PASS unchanged`, `changed=0`, `identical_evidence=true`, canonical `report.json` SHA-256 `4563f1387481bc0a3f974fb8a63c46ee8aa5e915049982ef4da9b3cf94f6ca20`).
   - Verified offline Piper TTS WAV synthesis (`42212` bytes), authentic UI login over trusted TLS (`302 -> https://caller.internal/`), negative-case manifest/checksum rejection, and selective UI change (`changed=3`, `native.sha256` untouched, only `py-phone-caller-ui` restarted).
   - Completed Step 6 OpenAlert systemd in-place adoption (`ok=77 changed=22 failed=0`), `relocate: true` adoption of `hub` (`User=root`, `/root/openalert-hub`) and `edge` (`User=fieldops`, `/home/fieldops/openalert`) (`ok=157 changed=35 failed=0`), candidate-health failure recovery and quarantine on `openalertd-failreloc.service` (`ok=85 changed=21 failed=1 rescued=1`), ordinary `site.yml` unchanged rerun (`ok=130 changed=0 failed=0`), full `backup.yml` -> `restore.yml` (SQLite + PostgreSQL 18.6 `py_phone_caller_runtime`), assets-only `rollback.yml`, and incompatible-schema rollback refusal.
   - Deleted `ppc-qual-ubuntu-standard-20261107` and network `ppc-qual-20261107b` at `2026-11-07T18:40:10Z`.

## Rocky Linux 10.2 Tucny (`22.9.0-1.el10`) PBX & Connected Enterprise Qualification — 2026-11-07

Target: `ppc-qual-rocky-pbx-20261107` (ID `1390396107762355367`, image `rocky-linux-cloud/rocky-linux-10-v20261026`, image ID `4414299933099848315`, kernel `6.12.0-211.67.1.el10_2.x86_64`, `n2-standard-4`, 100 GB boot disk, SELinux **Enforcing**).

- Symbol inspection across all published RPMs in `https://ast.tucny.com/repo/asterisk-22/el10/x86_64/` established that `22.10.1-1.el10`, `22.11.0-1.el10`, and `22.12.0-1.el10` have an undefined symbol `stasis_app_claim_channel` in `res_ari_events.so` missing from `res_stasis.so`, whereas **`22.9.0-1.el10`** has complete symbol closure.
- Updated `asterisk_tucny_version: "22.9.0-1.el10"` and ran `run_pbx_disposable.py --provider tucny`:
  - `PASS installation, authenticated ARI, PJSIP/IAX2 configuration and radio exclusion`
  - `PASS unchanged rerun: zero changes and identical service timestamps`
  - `PASS conflicting provider rejected without changes; credential absent from diff/logs`
  - Installed packages: `asterisk-22.9.0-1.el10.x86_64`, `asterisk-curl-22.9.0-1.el10.x86_64`, `asterisk-iax2-22.9.0-1.el10.x86_64`, `asterisk-pjsip-22.9.0-1.el10.x86_64`, `asterisk-sounds-core-en-1.6.1-1.el10.noarch`, `asterisk-sounds-core-en-wav-1.6.1-1.el10.noarch`.
  - Installed module SHA-256 digests: `res_ari_events.so` `0858c006012948ab31f6ed481b91863156edf15477bd206e8012f7ca706f14bb`, `res_stasis.so` `43462358964ee2444bafbc319cb51b26f25dae30ac6b7b61412a4c10e2ce3620`.
  - Canonical PBX `report.json` SHA-256: `c6ca7e789114c916c42f15a7d3310d342a2bb178c3abf7888e08526df7a58aef`.
- Ran `run_topology_disposable.py` (`enterprise` profile):
  - `PASS install` (`ok=297 changed=1 failed=0 skipped=90`) and `PASS unchanged` (`ok=297 changed=0 failed=0 skipped=90`, `qualified=true`, `identical_evidence=true`).
  - Canonical enterprise `report.json` SHA-256: `3a9e54adc5869ea0f3008aca661b3f438d15673017d4536fabfc2b9ddcdcb031`.
- Executed live interactive Keycloak OIDC login roundtrip (`https://caller.internal/login` -> `/realms/py-phone-caller/protocol/openid-connect/auth` -> form POST -> `https://caller.internal/`, HTTP `200`, `81992` bytes) over trusted TLS with SELinux `Enforcing`.
- Removed private credentials and deleted `ppc-qual-rocky-pbx-20261107`, firewall rule `ppc-qual-20261107c-iap-ssh`, subnet `ppc-qual-20261107c`, and network `ppc-qual-20261107c` at `2026-11-07T19:28:58Z` (`Listed 0 items` verified for instances and disks in `jcf-gcloud`).

## Physical Orange Pi 5 Plus (RK3588) ARM64 Connected & Air-Gapped Qualification — 2026-11-19

Target: physical **Orange Pi 5 Plus** (Rockchip RK3588, 8 cores = 4× Cortex-A76 + 4× Cortex-A55, `aarch64`, 7.7 GiB RAM + 3.9 GiB zram swap, Fanxiang S501Q 512 GB NVMe `/dev/nvme0n1p1`), OS **Armbian 26.11.3 (`Ubuntu 26.04 LTS Resolute Raccoon`)**, kernel `6.1.115-vendor-rk35xx`, `systemd 259`, `cgroup2fs`.

- **Native ARM64 `openalertd v1.0.0` release bundle:** compiled natively on RK3588 with locked Rust `1.99.1 (58cf8f9c3 2026-10-13)` (`1m 19s`, peak `50.8°C`), packaged via `build_release_bundle.sh --target aarch64-unknown-linux-gnu`:
  - Archive: `src/openalert/dist/openalertd-v1.0.0-linux-aarch64.tar.gz` (`12 MB`), SHA-256 `b9a415c3819d656c5c589dc0d04538ac1c2f830c085bd3b80f0bdf6a091d55ab`.
  - Binary SHA-256: `2d8152a9f36e3b04612ef29080c4018a63d7531e05a1864a5a0b5317d0687aa0`, `release_id`: `1.0.0-ca3b56485033-arm64-2d8152a9f36e`, `minimum_glibc`: `2.38`, interpreter `/lib/ld-linux-aarch64.so.1`.
  - Fixed syntax typo in `src/openalert/src/ingress/nostr.rs` line 1063 (`amatch` → `match`).
- **Phase 1 — Connected (`online`) all-in-one appliance (`stack_deploy_py_phone_caller=true`, `stack_deploy_asterisk=true`, `stack_deploy_openalert=true`):**
  - Full frozen Python workspace (`uv 0.11.15`, standalone Python `3.14.5` `aarch64`, 217 wheels), native `rust_engine` (`maturin==1.9.6`), official Ubuntu Asterisk `1:22.5.2~dfsg+~cs6.15.60671435-1`, PostgreSQL `18.6`, Redis `8`, Caddy `2.11.9` (`internal` TLS), and `openalertd v1.0.0` (`arm64`, `3.3 MiB` RSS).
  - Resolved upstream `nvidia-cusparselt-cu13==0.8.1` `aarch64` `.dist-info/WHEEL` `manylinux2014_sbsa` tag mismatch in `deploy_py-phone-caller/tasks/install.yml` and `install_offline.yml`, and added immediate `meta: flush_handlers` after `configure.yml` in `asterisk_py_phone_caller/tasks/main.yml`.
  - Unchanged rerun: `ok=225 changed=0 unreachable=0 failed=0 skipped=123`, identical start timestamps and `NRestarts=0` across all 16 services; `verify.yml` `ok=11 changed=0 failed=0`.
  - Local Piper TTS (`en_US.onnx`, `num_of_cpus=2`): cold `7,438 ms`, warm `6,223 ms`, 8 kHz 16-bit mono PCM WAV, post-TTS peak `44.4°C`, steady RAM `2.5 GiB / 7.7 GiB`.
- **Phase 2 — 100% Air-Gapped (`airgapped`) all-in-one appliance:**
  - Built signed local `file:` ARM64 APT mirror (`20` packages, `signatures_verified: true`) and contract-validated `6.1 GB` ARM64 offline bundle (`contract_validated: true`, `bundle-manifest.json` SHA-256 `325a0a122608c98bd95e3c922fcaed7ad325c42c051cc1d5af57fcd88fb09fef`, `source-manifest.json` SHA-256 `c214d408d49c21c042a3a3cdf76a894eb5ef6794e42765086c03636628d1a6fa`).
  - Wiped `/opt/py-phone-caller/{venv,.uv,.cargo}` and downloaded models, then executed from-scratch offline `site.yml` inside `unshare --net`: `ok=276 changed=24 unreachable=0 failed=0 skipped=131`.
  - Unchanged air-gapped rerun: `ok=259 changed=0 unreachable=0 failed=0 skipped=143`, identical start timestamps and `NRestarts=0` across all 16 services.
  - Verified `IPAddressDeny=0.0.0.0/0 ::/0`, `IPAddressAllow=::1/128 127.0.0.0/8`, `PPC_OFFLINE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` across all 11 Python services; native `rust_engine.cpython-314-aarch64-linux-gnu.so` (`ELF 64-bit LSB shared object, ARM aarch64`) loaded cleanly; `ss -tulpn` confirmed strict loopback bindings except Caddy `:80`/`:443`.
  - Offline Piper TTS reading strictly from `/srv/offline/export-v1/py-phone-caller/models/piper/en_US`: cold `7,642 ms` (`86,828 B`), warm `6,372 ms` (`51,756 B`), `RIFF WAVE Microsoft PCM 16-bit mono 8000 Hz`, peak `45.3°C`.
  - Authentic Web UI login over Caddy strict TLS (`https://appliance.internal/login` → `302 -> https://appliance.internal/` → `200`, `80,859 B`, `<title>py-phone-caller Dashboard</title>`, PostgreSQL `last_login` updated).
  - **Cold-reboot recovery (`sudo reboot`):** all 16 services auto-started with `ActiveState=active` and `NRestarts=0` (`2.1 GiB / 7.7 GiB` RAM, `0 B` swap), Asterisk ARI `401`/`200` + Stasis app `py-phone-caller` auto-registered, OpenAlert `/health` `200`, and `verify.yml` `ok=11 changed=0 failed=0`.
- **Phase 3 — Physical USB GSM SMS delivery (`2026-11-20`, air-gapped `IPAddressDeny=any`):**
  - Attached physical **SimTech `SIMCOM_SIM7600E-H`** (`1e0e:9001`, firmware `SIM7600M22_V2.0.1`) via persistent `/dev/serial/by-id/...-if02-port0` (`ttyUSB2`), released from `ModemManager` via `ENV{ID_MM_DEVICE_IGNORE}="1"` udev rule.
  - Verified native ARM64 `rust_engine` startup (`Starting engine with 1 modem(s). Strategy: RoundRobin`) and live cellular SMS transmission via `POST http://127.0.0.1:8085/send_sms`: modem acknowledged `+CMGS` / `OK` on Attempt 1 (`14s` end-to-end), SQLite `/tmp/sms.db` recorded `status=2` (`retries=0`), PostgreSQL `sms` audit table recorded `carrier="on_premise", status="sent"`, and operator confirmed live handset receipt.
  - Fixed 4-field `ModemConfig` schema (`id`, `port`, `baud_rate`, `priority`) in `inventories/examples/appliance-orangepi5plus/hosts.yml` and documented the `ModemManager` udev rule in `deploy/docs/09-arm64-appliance-and-airgapped-deployment.md` and `deploy/docs/10-end-to-end-installation-validation.md`.
- **Phase 4 — Live VoIP/SIP voice call with offline Piper TTS playback (`2026-11-20`, air-gapped `IPAddressDeny=any`):**
  - Registered a LAN mobile SIP softphone (Linphone) to Asterisk 22 PJSIP extension `1000` (`Avail`) and triggered `POST http://127.0.0.1:8081/place_call` (`HTTP 200`).
  - Full live microservice pipeline verified end-to-end: `asterisk_caller` originated ARI channel `1795182162.0` → `caller_register` persisted `first_dial` in PostgreSQL → `Stasis(py-phone-caller)` invoked `asterisk_ws_monitor` → `generate_audio` synthesized a `123 KiB` (`RIFF WAVE Microsoft PCM 16-bit mono 8000 Hz`) WAV strictly from `/srv/offline/export-v1/py-phone-caller/models/piper/en_US/en_US.onnx` in `8.6s` → Asterisk (`asterisk-libcurl-agent/1.0`) fetched `GET /audio/b66709c2_en_US.wav` (`HTTP 200`) and streamed audio over RTP (`ANSWERED`, `34s` billsec) → dialplan called `GET /heard` (`HTTP 200`) updating `heard_at` in PostgreSQL; operator confirmed live voice reception.
  - Physical BLE, LoRa RF transmission, and external PSTN SIP trunk peering remain separately out of scope.

## Accepted target contract

| Requirement | Current boundary |
| --- | --- |
| Operating system | Debian **13** or Ubuntu **26.04**, plus Rocky **10 AMD64** (online `enterprise` with `asterisk_package_provider: tucny` pinned to `22.9.0-1.el10`), checked from managed-host facts. Other legacy distro/version paths do not extend this entry point. |
| Architecture | 64-bit `x86_64` → `amd64` or `aarch64` → `arm64`; matching GNU/Linux ELF release metadata and interpreter required. Controller architecture is irrelevant. |
| Init/runtime | Working `systemd`, managed-host Python **3.11+**, privilege escalation, release-compatible glibc and required native libraries. Containers without a functioning systemd environment are not equivalent test hosts. |
| Release provenance | Trusted inventory-pinned archive SHA-256, valid schema-1 bundle, checked assets and runtime metadata. A checksum fetched beside an untrusted release is insufficient. |
| Controller | Pinned `ansible-core==2.20.0` / `ansible-lint==25.12.2` from `tests/requirements-controller.txt`; pinned collections from `requirements.yml` installed into `.collections`. |
| Deployment scope | Explicit selectors and explicit reviewed inventory; no implicit/live inventory. Fresh or already role-owned instance identities only. |

The observed glibc 2.38 requirement belongs to the recorded AMD64 artifact; it
is not a universal minimum for all future bundles. Check each bundle's actual
runtime metadata and dependencies. The packaging guide recommends a recorded
Debian 13 builder/sysroot for initial Debian/Ubuntu qualification; the observed
openSUSE build does not replace that qualification work.

## Board and image requirements

An ARM64 CPU or a board name is not a support result. For Raspberry Pi,
Orange Pi (including Zero 3), or any other SBC, qualification must identify:

- Exact board model/revision, **64-bit** image vendor/version and image digest;
  a 32-bit userspace is not supported by the ARM64 bundle contract.
- Debian 13 or Ubuntu 26.04 userspace, kernel/version/configuration, functioning
  systemd and cgroups, Python 3.11+, GNU loader/glibc and package manifest.
- Exact release archive hash, source/build provenance and real native execution;
  emulation or synthetic architecture fixtures must be labeled separately.
- Available memory, CPU, storage capacity/endurance and power stability against
  the configured per-instance limits and expected persistence workload.
- Peripheral models/firmware, kernel drivers, BlueZ/D-Bus policy for BLE,
  serial device identities/permissions, supplementary groups and explicitly
  justified capabilities. Device presence alone does not prove functionality.
- For later authorized radio/modem/network tests, RF/regulatory constraints,
  approved destinations, network isolation, authentication/TLS/firewall policy,
  and recovery behavior. These tests must not be silently folded into deployment.

Record scenario-specific results on each exact board/image. The 2026-11-19
section above records real native ARM64 builds and physical execution on Orange
Pi 5 Plus (RK3588 / Armbian 26.11.3 / Ubuntu 26.04 LTS); no other SBC model,
BLE/LoRa/modem RF transmission, or unauthenticated public exposure qualification
is claimed here. The private `hub` and `public` examples both use loopback;
neither is a recipe for safe unauthenticated public service.

## Boundaries before any later rollout

Candidate validation runs as the service account and uses the packaged base
unit plus explicit privilege resets. This reduces particular risks but does
not prove every interaction with inherited systemd settings, host permissions,
network services or concurrently modified configuration. Review the
[current role contract](openalert.md) and its documented limits.

Before widening the evidence matrix, retain the exact controller/collection
versions, image identity, bundle checksum, reviewed inventory/template revision,
commands, final exit status and relevant redacted logs. Record negative cases
and rerun/isolation outcomes separately from initial startup. Do not promote a
partial integration run to a pass or extrapolate an AMD64 result to ARM64.

There is no production-qualified takeover of live accounts, units, configuration
or state. Do not disable conflict checks, fabricate ownership records, delete
live paths or run standalone installation scripts to bypass this boundary.
Phase 4 lifecycle procedures require isolated rehearsals and separate operator
authorization before any migration work. Removal must never be inferred from
an instance omitted from inventory.

---

## Multi-OS Cloud, Kubernetes & Air-Gap Compliance Verification — 2026-11-23

An end-to-end compliance sweep across Google Cloud (`europe-west2`) and isolated local KVM (`qemu:///system`) further verified and closed the following gates:

- **AlmaLinux 10.3 AMD64 (`SELinux Enforcing`)**: Enabled first-class `AlmaLinux` role assertions alongside Rocky 10 (`Tucny` Asterisk `22.9.0-1.el10`). Full `enterprise` `site.yml` (`ok=299 changed=56 failed=0`), `verify.yml`, unchanged rerun (`ok=302 changed=0`), live Keycloak OIDC + M2M Bearer `/api/cluster_health` HTTP `200`, and cold-reboot recovery (`ok=11`, `SELinux Enforcing`) passed. *(Note: minimal AlmaLinux 10 cloud images require `dnf install -y iptables-nft` prior to reverse-proxy preflight.)*
- **Four-OS Connected Qualification Refresh**: Re-verified Debian 13 (`AllStarLink 22.10.1+asl3`, `ok=241` / rerun `changed=0` / cold-reboot `ok=11`), Ubuntu 26.04 LTS (`ok=295` / rerun `changed=0`), and Rocky Linux 10 (`ok=299` / rerun `changed=0` / `SELinux Enforcing`).
- **Strict Air-Gapped Ubuntu 26.04 LTS + Day-2 Playbooks**: Verified full offline build & install (`site.yml` `ok=281 changed=63 failed=0`, rerun `ok=267 changed=0`, cold-reboot `verify.yml` `ok=11`) under `iptables` + `ip6tables` egress/DNS block, plus live `playbooks/backup.yml` -> `restore.yml` (`py_phone_caller` PostgreSQL + SQLite), `assets` `rollback.yml`, `playbooks/adopt.yml` (`adopt-openalert-in-place` and `adopt-openalert-relocate` root-to-unprivileged migration).
- **Container & Kubernetes Pillars**: Verified 15-container Docker Compose + Gateway (`apisix-dashboard` `RestartCount=0`), local `k3s` (`v1.37.2+k3s1`, Kustomize `18/18` Deployments + Helm `14/14` Deployments), and managed GCP `GKE` (`v1.36.4-gke.2377000`, `gateway.enabled=true`, `17/17` Deployments `Ready`, `3/3` PVCs `Bound`, cross-VPC Asterisk ARI Stasis registration). All ephemeral cloud and KVM test resources were destroyed and audited (`Listed 0 items`).