# Unattended PostgreSQL Database & Role Provisioning

This folder contains automated, unattended database provisioning tools for `py-phone-caller`.

When administrative credentials (e.g. `postgres` superuser) are available, these tools automatically:
1. Create or update the application PostgreSQL user/role (`py_phone_caller`) with `LOGIN` and the configured password.
2. Create the application database (`py_phone_caller`) owned by the application user.
3. Grant all database and schema privileges (including future default table/sequence privileges).
4. Enable required PostgreSQL extensions (`uuid-ossp` and `pgcrypto`).
5. Verify end-to-end connectivity using the newly provisioned application credentials.

---

## 1. Python Automation Tool (`init_postgres_db.py`)

Using `uv` (recommended):
```bash
uv run python assets/scripts/db/init_postgres_db.py \
  --admin-host postgresql.lan \
  --admin-port 5432 \
  --admin-user postgres \
  --admin-password my-secret-admin-password \
  --app-db-name py_phone_caller \
  --app-db-user py_phone_caller \
  --app-db-password my-app-password
```

Environment variables are also supported:
```bash
export PGHOST=postgresql.lan
export PGPORT=5432
export PGUSER=postgres
export PGPASSWORD=my-secret-admin-password
export APP_DB_NAME=py_phone_caller
export APP_DB_USER=py_phone_caller
export APP_DB_PASSWORD=my-app-password

uv run python assets/scripts/db/init_postgres_db.py
```

Dry-run mode (validate actions without modifying the database):
```bash
uv run python assets/scripts/db/init_postgres_db.py --dry-run
```

---

## 2. Shell Automation Script (`init_postgres_db.sh`)

For environments with `psql` available:
```bash
./assets/scripts/db/init_postgres_db.sh \
  --admin-host postgresql.lan \
  --admin-port 5432 \
  --admin-user postgres \
  --admin-password my-secret-admin-password
```

Or via environment variables:
```bash
PGHOST=postgresql.lan PGUSER=postgres PGPASSWORD=secret ./assets/scripts/db/init_postgres_db.sh
```

---

## 3. Ansible Automation

In the Ansible deployment playbook (`assets/ansible/on-vm_py-phone-caller` or `assets/ansible/deploy_all`):
- Pass `py_phone_caller_db_admin_user` (default: `postgres`) and `py_phone_caller_db_admin_password` (via Ansible Vault `vault_db_admin_password`).
- Ansible automatically provisions the role, database, privileges, and extensions unattended before starting the services.
- When `caller_register` starts, Piccolo ORM automatically applies migrations and ensures all tables and models are up to date.
