# Ansible Release Bundle Packaging (`py-phone-caller-ansible`)

This directory contains the deterministic release builder for the native Ansible installer suite (`deploy/ansible`).

## Overview

`build_ansible_bundle.py` packages the canonical `site.yml` entrypoint, lifecycle playbooks (`adopt.yml`, `backup.yml`, `restore.yml`, `rollback.yml`), all 11 Ansible roles, documentation, operator-safe example inventories, configuration conversion tools, and compatibility wrappers into a reproducible `.tar.gz` archive with an accompanying `.sha256` checksum and embedded `release.json` manifest.

### Security & Hygiene Guarantees

1. **Allowlist Staging**: Only reviewed playbooks, roles, documentation, example inventories, and safe compatibility wrapper files are staged.
2. **Secret & Live-Inventory Scrubbing**: Build verification fails closed if any forbidden path or secret file is detected (e.g., `.vault_pass*`, `credentials/`, `secrets.yml`, `.secrets.toml`, `inventory`, `inventory.ini`, `.runtime/`, `.rendered/`).
3. **Deterministic Tarballs**: Archives normalize file ownership (`root:root`, `0:0`), timestamps (`mtime=0`), permissions, and sort order so identical commits produce identical SHA-256 digests.
4. **Offline Collection Bundling (`--with-collections` / `--install-collections`)**: Optionally verifies and bundles the exact Ansible Galaxy collection versions pinned in `requirements.yml` (`ansible.posix`, `community.general`, `community.postgresql`) under `.collections/ansible_collections/` for air-gapped Ansible controllers.

## Usage

### 1. Standard Release Bundle (Online Controller)

From the repository root:

```bash
uv run python deploy/ansible/packaging/build_ansible_bundle.py --force
```

Outputs:
- `deploy/ansible/dist/py-phone-caller-ansible-v1.0.0.tar.gz`
- `deploy/ansible/dist/py-phone-caller-ansible-v1.0.0.tar.gz.sha256`

### 2. Air-Gapped Controller Bundle (With Vendored Collections)

To bundle the pinned Ansible Galaxy collections from `deploy/ansible/.collections` (after verifying each collection's `MANIFEST.json` matches `requirements.yml`):

```bash
# If collections are already installed in deploy/ansible/.collections:
uv run python deploy/ansible/packaging/build_ansible_bundle.py --with-collections --force

# Or to automatically fetch & verify pinned collections during the build:
uv run python deploy/ansible/packaging/build_ansible_bundle.py --install-collections --force
```

Outputs:
- `deploy/ansible/dist/py-phone-caller-ansible-v1.0.0-offline.tar.gz`
- `deploy/ansible/dist/py-phone-caller-ansible-v1.0.0-offline.tar.gz.sha256`

## Operator Verification & Extraction

On the Ansible controller:

```bash
sha256sum -c py-phone-caller-ansible-v1.0.0.tar.gz.sha256
tar -xzf py-phone-caller-ansible-v1.0.0.tar.gz
cd py-phone-caller-ansible-v1.0.0

# Verify embedded per-file SHA-256 manifest:
python3 -c '
import hashlib, json, pathlib
meta = json.loads(pathlib.Path("release.json").read_text())
for rel, expected in meta["files"].items():
    actual = hashlib.sha256(pathlib.Path(rel).read_bytes()).hexdigest()
    assert actual == expected, f"Mismatch in {rel}"
print(f"Verified {len(meta[\"files\"])} files for {meta[\"release_id\"]}")
'
```
