# `py-phone-caller` & `openalertd` Deployment Documentation Hub (`v1.1.0`)

Welcome to the centralized deployment and operations documentation hub for **`py-phone-caller`** and **`openalertd`**.

Our mission with these guides is to give operators, system administrators, and DevOps engineers a clear, **verified, step-by-step path** to install, configure, secure, and verify the suite across bare-metal servers, virtual machines, containers, or Kubernetes clusters.

> [!IMPORTANT]
> **Live Cloud VM, Kubernetes & Physical ARM64 Hardware Qualification (`2026-11-07` – `2026-11-23`)**
> Every deployment pillar documented in `deploy/docs/` has been tested end-to-end on real Google Cloud & local KVM AMD64 virtual machines (**Debian 13 `trixie`**, **Ubuntu 26.04 LTS `resolute`**, **Rocky Linux 10**, and **AlmaLinux 10** with `SELinux Enforcing`), managed & edge Kubernetes (`GKE v1.36` & `k3s v1.37`) with `helm`, Docker Compose (+ APISIX/Keycloak Gateway), **and a physical Orange Pi 5 Plus (RK3588 `aarch64`, Armbian 26.11.3 / Ubuntu 26.04 LTS)** in both **connected (`online`)** and **100% air-gapped (`airgapped`)** modes—including offline Piper TTS synthesis, authentic strict-TLS Web UI login, unified `/api/docs` OpenAPI specs, Day-2 `backup`/`restore`/`rollback`/`adopt`, `changed=0` idempotency reruns, and full cold-reboot recovery.

> [!TIP]
> **New here? Don't read all 10 guides at once — pick your tier:**
> 1. **Fastest evaluation (containers + existing PBX)** → [Guide 03 (Docker Compose)](03-docker-compose-deployment.md)
> 2. **Turnkey single-host or air-gapped appliance (VM or ARM64 SBC)** → [Guide 02 (Native Ansible)](02-ansible-deployment.md) or [Guide 09 (ARM64 & Air-Gapped)](09-arm64-appliance-and-airgapped-deployment.md)
> 3. **Kubernetes / Enterprise OIDC SSO** → [Guide 04 (Kubernetes & Helm)](04-kubernetes-and-helm-deployment.md) + [Guide 07 (Gateway & Observability)](07-enterprise-gateway-and-observability.md)
>
> Every optional layer (`asterisk`, `openalertd`, `gateway`) is independently selectable — start minimal and enable extras only when needed.

---

## Which Deployment Pillar Should I Choose?

| Deployment Guide | Target Environment | Best For | Manages Asterisk PBX? | Manages PostgreSQL & Redis? |
| :--- | :--- | :--- | :--- | :--- |
| **[01. Architecture, Prerequisites & Configuration](01-architecture-and-prerequisites.md)** | All environments | Understanding the 12 services, ports, Asterisk ARI dialplan, `settings.toml`, `.secrets.toml`, TTS models, and USB GSM modems | Reference | Reference |
| **[02. Native Ansible Deployment](02-ansible-deployment.md)** | Debian 13, Ubuntu 26.04 LTS, Rocky Linux 10, AlmaLinux 10 (Bare-Metal / VMs / ARM64) | **Turnkey Production & Air-Gapped Hosts** — Full lifecycle management (install, idempotent updates, backup, restore, rollback, and OpenAlert instance adoption) | **Yes** (AllStarLink, Ubuntu official, or Tucny `22.9.0-1.el10`) or External | **Yes** (Local systemd or External) |
| **[03. Docker & Docker Compose Deployment](03-docker-compose-deployment.md)** | Any Linux host with Docker Engine 24+ or Podman 4.5+ | **Single-Host Container Stack** — Fast evaluation or production container deployment with optional USB GSM/LoRa/BLE hardware passthrough and APISIX/Keycloak gateway | External PBX | **Yes** (`postgres:17-alpine` & `redis:7-alpine` containers) |
| **[04. Kubernetes & Helm v3 Deployment](04-kubernetes-and-helm-deployment.md)** | Kubernetes (`k3s`, `EKS`, `GKE`, `AKS`, `OpenShift`, `kubeadm`) | **Cloud-Native & Clustered Operations** — Declarative Kustomize manifests (`43` resources) or parameterized Helm v3 chart (`py-phone-caller-1.1.0.tgz`) | External PBX (`Service` + `EndpointSlice` bridge) | **Yes** (In-cluster `Stateful`/PVC or External) |
| **[05. Native Linux Packages (`.deb` & `.rpm`)](05-linux-deb-rpm-deployment.md)** | Debian/Ubuntu (`apt`) & RHEL/Rocky/AlmaLinux (`dnf`) | **Traditional Linux Sysadmin Workflows** — Installing prebuilt `.deb` and `.rpm` system packages with offline wheel bundles in `/opt/py-phone-caller/wheels` | External or Co-located | Installed via OS `apt`/`dnf` |
| **[06. Python Wheels (`PyPI`) & Systemd Deployment](06-pypi-and-systemd-deployment.md)** | Any Linux host with Python 3.14+ and `systemd` | **Custom Virtualenvs & Private PyPI Mirrors** — Installing `py-phone-caller[all]==1.1.0` via `uv` or `pip` and wiring `deploy/systemd/` units | External or Co-located | Installed via OS or External |
| **[07. Enterprise Gateway (`APISIX` + `Keycloak`) & Observability](07-enterprise-gateway-and-observability.md)** | Ansible, Docker Compose, or Kubernetes | **Zero-Trust SSO, RBAC & NOC Monitoring** — Apache APISIX rate-limiting, Keycloak OIDC (`alert-admin`, `alert-operator`, `alert-viewer`), Prometheus & Grafana | N/A | Uses PostgreSQL |
| **[08. Building & Verifying Release Artifacts](08-release-packaging.md)** | Release Engineers & CI/CD | Reproducibly building all 33 artifacts in `dist/` (`SHA256SUMS`, `RELEASE_MANIFEST.json`) and running the 335-test (`1,247`-subtest) verification suite | N/A | N/A |
| **[09. ARM64 Appliance & Air-Gapped Deployment](09-arm64-appliance-and-airgapped-deployment.md)** | Orange Pi 5 Plus (RK3588) & 64-bit ARM64 SBCs | **All-in-One Field & Air-Gapped Appliances** — Native ARM64 `openalertd` build, signed `file:` APT mirror, offline bundle (`unshare --net`), tuned cgroup v2 limits, and RK3588 benchmarks | **Yes** (Local Asterisk 22) | **Yes** (Local PostgreSQL 18 + Redis 8) |
| **[10. End-to-End Installation Validation Checklist](10-end-to-end-installation-validation.md)** | All deployed hosts (AMD64 & ARM64, Online & Air-Gapped) | **12-Gate Post-Install Proof** — Copy-pasteable commands validating systemd, `ss -tulpn`, DB/Redis, Asterisk ARI/Stasis, OpenAlert, Rust SMS, Piper TTS WAVs, strict-TLS Web UI login, air-gap isolation, `changed=0` rerun, and reboot recovery | Validated (Gate 5) | Validated (Gate 4) |

---

## Directory Map of `deploy/`

```text
deploy/
├── docs/                       # <-- You are here: Centralized modular deployment guides
│   ├── README.md
│   ├── 01-architecture-and-prerequisites.md
│   ├── 02-ansible-deployment.md
│   ├── 03-docker-compose-deployment.md
│   ├── 04-kubernetes-and-helm-deployment.md
│   ├── 05-linux-deb-rpm-deployment.md
│   ├── 06-pypi-and-systemd-deployment.md
│   ├── 07-enterprise-gateway-and-observability.md
│   ├── 08-release-packaging.md
│   ├── 09-arm64-appliance-and-airgapped-deployment.md
│   └── 10-end-to-end-installation-validation.md
├── ansible/                    # Modular native Ansible installer (site.yml, roles/, playbooks/, tools/)
├── compose/                    # Docker / Podman Compose stack + hardware & gateway overlays
├── dashboards/                 # Turnkey Grafana NOC/SRE observability dashboard JSON
├── gateway/                    # Apache APISIX & Keycloak OIDC realm/route provisioning scripts
├── helm/                       # Production Helm v3 chart (deploy/helm/py-phone-caller)
├── k8s/                        # Raw Kubernetes manifests & Kustomization (deploy/k8s)
├── packaging/                  # Unified release builders (build_all_releases.py, pypi/, linux/, k8s/)
└── systemd/                    # Native systemd units (on-system/) and rootless container units (as-non-root-container/)
```

---

## Recommended Reading Order for New Operators

1. **Start with [01. Architecture, Prerequisites & Configuration](01-architecture-and-prerequisites.md)** to understand how the 11 Python services and `openalertd` communicate, how Asterisk ARI (`:8088`) is wired, and which parameters in `settings.toml` and `.secrets.toml` you must set.
2. **Pick your installation guide (`02` through `06`, or `09` for ARM64 / Air-Gapped appliances)** matching your infrastructure and follow the numbered steps from top to bottom.
3. **Validate the entire stack with [10. End-to-End Installation Validation Checklist](10-end-to-end-installation-validation.md)** to confirm every service, audio synthesis, strict-TLS login, idempotency, and reboot recovery before going live.
4. **Optionally add [07. Enterprise Gateway & Observability](07-enterprise-gateway-and-observability.md)** to enable Keycloak Single Sign-On (OIDC), Apache APISIX route protection, Prometheus scraping, and the Grafana dashboard.
