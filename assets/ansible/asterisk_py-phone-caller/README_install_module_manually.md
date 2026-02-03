# Manual Installation of Ansible Roles (Direct Method)

This guide explains how to install an Ansible role by manually copying its files into your local environment, bypassing `ansible-galaxy` or Git. This method is the most straightforward for quick testing or offline development.

---

## 1. Prepare the Directory
Ansible looks for roles in several predefined paths. For a standard Linux user, the default local directory is the hidden `.ansible/roles` folder within your Home directory.

Run this command to ensure the directory exists:

```bash
mkdir -p ~/.ansible/roles
```

## 2. Copy the Role Files
You need to copy the entire role directory into the location created above.

**Example:** If the `asterisk_py_phone_caller` folder is located on your Desktop:

```bash
cp -r ~/Desktop/asterisk_py_phone_caller ~/.ansible/roles/
```

## 3. Verify the Structure (Crucial)
Ensure that the folder structure is not nested incorrectly. The role's main tasks file should be reachable at exactly this path:

`~/.ansible/roles/asterisk_py_phone_caller/tasks/main.yml`

### Correct Hierarchy:
```text
~/.ansible/roles/
└── asterisk_py_phone_caller/
    ├── defaults/
    │   └── main.yml
    ├── meta/
    │   └── main.yml
    ├── tasks/
    │   └── main.yml
    └── vars/
        ├── Debian.yml
        └── RedHat.yml
```

## 4. Verify the Installation
To confirm that Ansible successfully recognizes the manually copied role, run:

```bash
ansible-galaxy role list
```

You should see `asterisk_py_phone_caller` listed under the `/home/<YOUR_USER>/.ansible/roles` path.

## 5. Usage Example
Create a `playbook.yml` file and reference the role by its name:

```yaml
---
- name: Test Manual Role Installation
  hosts: localhost
  roles:
    - asterisk_py_phone_caller
```

---

**💡 Note for Python/Rust Developers:** Since you likely value Open Source and efficient development, remember that manual copying does **not** handle Python dependencies automatically. If the role depends on specific Python libraries, ensure you install them manually using `pip`.