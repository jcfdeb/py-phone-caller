# Native Linux Packaging — RPM & DEB (`deploy/packaging/linux`)

> **Centralized Step-by-Step Guide**: See **[`deploy/docs/05-linux-deb-rpm-deployment.md`](../../docs/05-linux-deb-rpm-deployment.md)** (and the **[Deployment Documentation Hub](../../docs/README.md)**) for the complete step-by-step OS prerequisite, database, `/opt/py-phone-caller/venv`, and systemd activation guide.

This directory contains native Debian (`.deb`) and Red Hat / Rocky / AlmaLinux / openSUSE (`.rpm`) packaging specifications and the deterministic package builder for both **`py-phone-caller`** and **`openalertd`**.

## Contents

- `build_linux_packages.py` / `build_linux_packages.sh`: Self-contained, deterministic `.deb` (`ar` + `control.tar.gz` + `data.tar.gz`) and `.rpm` (`RPMv4` Lead/Signature/Header + `cpio.gz`) builder.
- `nfpm/`: GoReleaser `nFPM` configuration files (`py-phone-caller.yaml`, `openalertd.yaml`).
- `rpm/`: Native RPM `.spec` files (`py-phone-caller.spec`, `openalertd.spec`) for `rpmbuild`.
- `deb/`: Debian package control scripts (`postinst`, `prerm`, `postrm`, `conffiles`).

## Generated Artifacts (`dist/linux/`)

| Artifact | Format | Architecture | Contents |
| :--- | :--- | :--- | :--- |
| `py-phone-caller_1.1.0-1_all.deb` | Debian `.deb` | `all` | `/opt/py-phone-caller` workspace + wheels, `/etc/py-phone-caller/settings.toml`, 11 systemd `.service` units + `py-phone-caller.target` |
| `py-phone-caller-1.1.0-1.noarch.rpm` | RPMv4 `.rpm` | `noarch` | Same payload formatted for RHEL / Rocky / AlmaLinux / openSUSE |
| `openalertd_1.1.0-1_<arch>.deb` | Debian `.deb` | `amd64` / `arm64` | `/usr/local/bin/openalertd`, `/etc/openalertd/openalertd.toml`, `/etc/openalertd/profiles/`, `/usr/share/openalertd/`, `/lib/systemd/system/openalertd.service` |
| `openalertd-1.1.0-1.<arch>.rpm` | RPMv4 `.rpm` | `x86_64` / `aarch64` | Same payload formatted for RHEL / Rocky / AlmaLinux / openSUSE |

## Building Packages

```bash
uv run python deploy/packaging/linux/build_linux_packages.py --force
```

## Installing Packages

### Debian / Ubuntu

```bash
sudo apt install ./dist/linux/py-phone-caller_1.1.0-1_all.deb ./dist/linux/openalertd_1.1.0-1_amd64.deb
```

### RHEL / Rocky Linux / AlmaLinux / openSUSE

```bash
sudo dnf install ./dist/linux/py-phone-caller-1.1.0-1.noarch.rpm ./dist/linux/openalertd-1.1.0-1.x86_64.rpm
```

After installing the package, initialize `/opt/py-phone-caller/venv` from the bundled `/opt/py-phone-caller/wheels` and configure `/etc/py-phone-caller/.secrets.toml` as detailed in **[`deploy/docs/05-linux-deb-rpm-deployment.md`](../../docs/05-linux-deb-rpm-deployment.md)**.
