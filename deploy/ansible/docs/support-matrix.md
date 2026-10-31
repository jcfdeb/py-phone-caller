# Native deployment support and evidence matrix

**No production-ready claim or live migration
authorization is made.** Platform acceptance in `site.yml`, synthetic fixtures,
a built archive and a prepared test host are different kinds of evidence.

This snapshot records checks executed on **2026-10-30**. Phases 1–2 are complete
for the recorded milestone. The rootless-container limitation was resolved by
using separately authorized Debian 13 and Ubuntu 26.04 Google Cloud VMs.
Phase 3 runtime checks below are complete; formal closure remains open for
recorded lint naming findings. Do not infer broader platform qualification from
these scenario-specific results.

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
| Debian 13 / Ubuntu 26.04 ARM64 runtime | **Not qualified. Real ARM64 build and execution untested.** | Architecture mapping and synthetic fixtures exist; they do not establish native ARM64 compatibility. |
| Python-only and same-host Python/PBX/two-instance OpenAlert, Debian 13 and Ubuntu 26.04.1 AMD64 | **Passed:** full frozen workspace installation with uv 0.11.15 / Python 3.14.5, eleven application units, seven API health endpoints and UI; unchanged reruns `changed=0`, identical service timestamps. | Synthetic configuration, private listeners, empty test database/queue, loopback-only application egress. No TTS generation, calls, SMS or alert dispatch. Python-only leaves the existing test PBX/OpenAlert unmanaged. |
| PJSIP + IAX2 on both AMD64 VMs | **Passed:** required modules, local PJSIP endpoint/context, IAX peer/context/private UDP listener and protected credential file; ARI 200/401; zero-change reruns, secret redaction and provider-conflict rejection. | Debian uses the pinned AllStarLink set; Ubuntu uses official `resolute/universe` `asterisk`/`asterisk-modules` **`1:22.5.2~dfsg+~cs6.15.60671435-1`**. No third-party Ubuntu repository. No endpoint registration or calls were generated. |
| Externally managed database/queue mode, both AMD64 VMs | **Passed:** database/queue management disabled, configuration checksums unchanged, PostgreSQL/Redis/PBX/OpenAlert start timestamps unchanged; zero-change application rerun. | Existing loopback services treated as externally managed. This does not test a database/queue on another machine or remote TLS/firewall policy. |
| Legacy commands | **Passed:** Python wrapper on Ubuntu and combined wrapper on Debian, including zero-change reruns and unchanged timestamps. | Synthetic top-level test playbooks isolate checked-in live-site variables. Offline tests also cover legacy PBX host selection and variable loading. |
| Git/local source delivery | **Passed:** local-copy deployment on both VMs; pinned Git deployment/rerun on Ubuntu at `4484f140326f444791c691e795973ee41f469ccb`. | Public commit's `uv.lock` matches local SHA-256 `47374806a893485e66e5c3a3f8d44a9fda0154b5f2f717a2a8e4e35a1d365893`. An unpublished local commit was correctly rejected before retrying the available pin. Offline parity/state-preservation tests also pass. |
| Phase 3 automated regressions | **Passed: 110 tests, 709 subtests**, including six TOML-converter tests; no test warnings. | Real Ansible syntax/preflight/rendering, source and restart selection, gateway API idempotence/failure stamps, protected output, PBX/IAX/provider checks and release-contract tests. Gateway fixtures are not production-container qualification. |
| Whole native-tree lint | **Not clean: 77 `var-naming[no-role-prefix]` findings**, no other violations in the final standalone run. No rule was disabled to hide them. | Public legacy namespaces must remain compatible; internal renames are blocked by the unavailable required rename facility. This remains a Phase 3 closure item. |
| BLE, LoRa, serial modems, clock stepping, Wi-Fi AP/SOS exposure | **Hardware and exposure scenarios untested/unqualified here.** | Group/device/capability checks are not physical functional tests; the role does not provision Wi-Fi APs. |
| Radio transmission, calls or SMS dispatch | **Not tested by the installation probe.** | The role probes only loopback health with GET, never a dispatch endpoint. No functional delivery claim. |
| Existing installation adoption, removal, live migration, rollback/lifecycle operations | **Not implemented; deferred to Phase 4.** | Fresh conflicts fail; omission leaves instances untouched. No migration authorization or rollback guarantee. |

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
were deleted after testing; the separately supplied Debian test VM remains.
Production servers and field nodes were not touched. Test instances bind loopback
and have dispatch transports disabled.
See [test instructions](../tests/README.md) for exact reproduction commands and
the distinction between helper fixtures and service-runtime tests.

## Accepted target contract

| Requirement | Current boundary |
| --- | --- |
| Operating system | Debian **13** or Ubuntu **26.04**, checked from managed-host facts. Other distro/version paths in legacy roles do not extend this entry point. |
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

Record scenario-specific results on that exact board/image. No real ARM64 build,
physical board, BLE/LoRa/modem or public exposure qualification is claimed here.
The private `hub` and `public` examples both use loopback; neither is a recipe
for safe unauthenticated public service.

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

There is no supported takeover of live accounts, units, configuration or state.
Do not disable conflict checks, fabricate ownership records, delete live paths
or run standalone installation scripts to bypass this boundary. Phase 4 must
define explicit adoption/removal/lifecycle procedures and separate operator
authorization before any migration work.