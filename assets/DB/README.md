# Database Setup & Automation

In `py-phone-caller`, schema creation, table definitions, and migrations are **fully automated and managed dynamically by Piccolo ORM** through `caller_register`.

---

## 1. Unattended Automated Database Setup (Recommended)

When PostgreSQL administrative credentials (`postgres` superuser) are available, you can provision the role, database, privileges, and required extensions unattended in a single command:

```bash
uv run python assets/scripts/db/init_postgres_db.py \
  --admin-host postgresql.lan \
  --admin-user postgres \
  --admin-password my-secret-admin-password
```

Or via shell:
```bash
PGHOST=postgresql.lan PGUSER=postgres PGPASSWORD=secret ./assets/scripts/db/init_postgres_db.sh
```

Or in Ansible (`assets/ansible/on-vm_py-phone-caller` or `assets/ansible/deploy_all`):
- Set `py_phone_caller_db_admin_password` (e.g. via `vault_db_admin_password`), and Ansible will automatically provision the database and role during playbook execution.

---

## 2. Manual SQL Setup (`db-role.sql`)

If you prefer to create the role and database manually via `psql`:

```bash
psql -U postgres -h postgresql.lan -f assets/DB/db-role.sql
```

After the database and user are created, start `caller_register` (or start the container stack):
Piccolo ORM will automatically apply all schema migrations on startup.
