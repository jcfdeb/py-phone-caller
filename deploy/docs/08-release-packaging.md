# 08. Release Packaging & Verification Guide (`deploy/packaging`)

This guide documents how to reproducibly build, inspect, and verify all **33 distributable release archives/packages** (`1` Ansible bundle + `26` PyPI packages [`13` `.whl` + `13` `.tar.gz`] + `4` Linux native packages [`2` `.deb` + `2` `.rpm`] + `2` Kubernetes/Helm bundles = **33**, excluding per-directory `SHA256SUMS`, `.sha256`, `release.json`, and top-level `dist/SHA256SUMS` / `dist/RELEASE_MANIFEST.json` integrity files).

---

## Step 1: Build All Release Artifacts in One Command

From the **repository root**:

```bash
uv run python deploy/packaging/build_all_releases.py
```

If you have already compiled `openalertd` in release mode (`cargo build --release --manifest-path src/openalert/Cargo.toml`), you can pass the binary explicitly to skip recompilation:

```bash
uv run python deploy/packaging/build_all_releases.py \
  --openalert-binary src/openalert/target/release/openalertd
```

---

## Step 2: Individual Pillar Builders

You can also invoke each pillar's deterministic builder independently:

| Pillar | Builder Script | Output Directory | Generated Artifacts |
| :--- | :--- | :--- | :--- |
| **1. Ansible Release Bundle** | `deploy/ansible/packaging/build_ansible_bundle.py --force`<br>*(or `--with-collections`)* | `dist/ansible/` | • `py-phone-caller-ansible-v1.1.0.tar.gz`<br>• `py-phone-caller-ansible-v1.1.0.tar.gz.sha256`<br>• `py-phone-caller-ansible-v1.1.0-offline.tar.gz` *(when `.collections` is present)* |
| **2. PyPI Wheels & Source Distributions** | `deploy/packaging/pypi/build_pypi_packages.py --force` | `dist/pypi/` | • 13 `.whl` wheels (`py_phone_caller` meta-package + 12 workspace packages)<br>• 13 `.tar.gz` source distributions<br>• `SHA256SUMS` & `release.json` |
| **3. Native Linux Packages (`.deb` & `.rpm`)** | `deploy/packaging/linux/build_linux_packages.py --force` | `dist/linux/` | • `py-phone-caller_1.1.0-1_all.deb`<br>• `py-phone-caller-1.1.0-1.noarch.rpm`<br>• `openalertd_1.1.0-1_amd64.deb`<br>• `openalertd-1.1.0-1.x86_64.rpm`<br>• `SHA256SUMS` & `release.json` |
| **4. Kubernetes & Helm v3 Bundle** | `deploy/packaging/k8s/build_k8s_bundle.py --force` | `dist/k8s/` | • `py-phone-caller-1.1.0.tgz` (Helm v3 chart)<br>• `py-phone-caller-k8s-manifests-v1.1.0.tar.gz`<br>• `SHA256SUMS` & `release.json` |

---

## Step 3: Verify Checksums & Run the Automated Packaging Test Suite

1. **Verify All Checksums in `dist/SHA256SUMS`**:
   ```bash
   (cd dist && sha256sum -c SHA256SUMS)
   ```

2. **Run the Automated Packaging, Kubernetes, Compose & Ansible Verification Suite (`335` Tests / `1,247` Subtests)**:
   ```bash
   .venv/bin/python -m pytest \
     tests/test_pypi_packaging.py \
     tests/test_linux_packaging.py \
     tests/test_k8s_and_compose_packaging.py \
     tests/test_airgap_preparation.py \
     deploy/ansible/tests/test_*.py \
     src/openalert/packaging/tests/test_release_bundle.py -q
   ```

---

## Summary of Live Cloud VM Qualification (`2026-11-08`)

Every artifact produced by `deploy/packaging/build_all_releases.py` was tested on real Google Cloud AMD64 virtual machines (`jcf-gcloud`, `us-central1-a`):

| Pillar | Qualified Environment | Key Fixes & Verification |
| :--- | :--- | :--- |
| **Ansible (`dist/ansible/`)** | Debian 13, Ubuntu 26.04 LTS, Rocky Linux 10.2 (`SELinux Enforcing`) | Full `standard` (`online` & `airgapped`) and `enterprise` (`APISIX` + `Keycloak OIDC`) qualification; `changed=0` idempotent reruns; OpenAlert systemd adoption/relocation. |
| **RPM / DEB (`dist/linux/`)** | Debian 13 (`apt-get install`) & Rocky Linux 10.2 (`dnf install`, `SELinux Enforcing`) | Emits full RPMv4 `RPMTAG_HEADERSIGNATURES` (`62`), `RPMTAG_HEADERIMMUTABLE` (`63`), `RPMTAG_SHA256HEADER` (`273`), `PAYLOADDIGEST` (`5092`/`5097`), and file metadata tables (`1028`..`1118`) while excluding OS-owned directories. Zero warnings on `dnf`/`apt` install. |
| **PyPI (`dist/pypi/`)** | Debian 13 & Rocky Linux 10.2 (Python 3.14.10) | Offline installation of `py-phone-caller[services,ui]==1.1.0` + `rust_sms_engine` into `/opt/py-phone-caller/venv`; verified `py-phone-caller list-services`, `ppc-*` entrypoints, and systemd units. |
| **Docker Compose (`deploy/compose/`)** | Debian 13 (Docker Engine `29.2.1`, Compose `v5.0.0`) | Built all 12 images from source; started all 15 core containers + APISIX Gateway overlay (`pyphonecaller-etcd`, `pyphonecaller-gateway`); verified `:8081`–`:8087/health`, `:5000/health`, `:5000/login`, and `:8090/api/v1/status`. |
| **Kubernetes & Helm (`dist/k8s/`)** | Debian 13 (`k3s v1.37.2+k3s1`, `helm v3.22.1`) | Server-side validated all 43 Kubernetes objects (`kubectl apply -k --dry-run=server`), linted (`helm lint`), and installed `py-phone-caller-1.1.0.tgz`; all 13 core Deployments (`11` Python + PostgreSQL + Redis, with optional `openalertd`/`gateway` disabled) reached `1/1 Running` (`0` restarts) with `Bound` PVCs and `200 OK` `ClusterIP` health probes (see [Guide 04](04-kubernetes-and-helm-deployment.md) for the full 14/17/18 Deployment matrix). |
