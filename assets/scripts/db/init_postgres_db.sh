#!/usr/bin/env bash
# ==============================================================================
# Unattended PostgreSQL Database & Role Provisioner for py-phone-caller (Shell)
#
# Usage:
#   PGHOST=postgresql.lan PGUSER=postgres PGPASSWORD=secret ./init_postgres_db.sh
#   ./init_postgres_db.sh --admin-host postgresql.lan --admin-user postgres --admin-password secret
# ==============================================================================
set -euo pipefail

ADMIN_HOST="${PGHOST:-127.0.0.1}"
ADMIN_PORT="${PGPORT:-5432}"
ADMIN_USER="${PGUSER:-postgres}"
ADMIN_PASSWORD="${PGPASSWORD:-}"
ADMIN_DB="${PGDATABASE:-postgres}"

APP_DB_NAME="${APP_DB_NAME:-py_phone_caller}"
APP_DB_USER="${APP_DB_USER:-py_phone_caller}"
APP_DB_PASSWORD="${APP_DB_PASSWORD:-py_phone_caller_password}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --admin-host)
      ADMIN_HOST="$2"
      shift 2
      ;;
    --admin-port)
      ADMIN_PORT="$2"
      shift 2
      ;;
    --admin-user)
      ADMIN_USER="$2"
      shift 2
      ;;
    --admin-password)
      ADMIN_PASSWORD="$2"
      shift 2
      ;;
    --admin-db)
      ADMIN_DB="$2"
      shift 2
      ;;
    --app-db-name)
      APP_DB_NAME="$2"
      shift 2
      ;;
    --app-db-user)
      APP_DB_USER="$2"
      shift 2
      ;;
    --app-db-password)
      APP_DB_PASSWORD="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: $0 [options]"
      echo "  --admin-host HOST      PostgreSQL admin host (default: 127.0.0.1)"
      echo "  --admin-port PORT      PostgreSQL admin port (default: 5432)"
      echo "  --admin-user USER      PostgreSQL admin user (default: postgres)"
      echo "  --admin-password PASS  PostgreSQL admin password"
      echo "  --admin-db DB          Admin maintenance db (default: postgres)"
      echo "  --app-db-name DB       App database name (default: py_phone_caller)"
      echo "  --app-db-user USER     App database user (default: py_phone_caller)"
      echo "  --app-db-password PASS App database password"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if ! command -v psql &>/dev/null; then
  echo "Error: 'psql' client utility is not installed or not in PATH." >&2
  exit 1
fi

export PGPASSWORD="$ADMIN_PASSWORD"

echo "Connecting to PostgreSQL as '$ADMIN_USER' at $ADMIN_HOST:$ADMIN_PORT/$ADMIN_DB..."

# 1. Create or update application role
psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" -v ON_ERROR_STOP=1 <<EOF
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${APP_DB_USER}') THEN
    CREATE ROLE "${APP_DB_USER}" WITH LOGIN ENCRYPTED PASSWORD '${APP_DB_PASSWORD}';
    RAISE NOTICE 'Role % created successfully', '${APP_DB_USER}';
  ELSE
    ALTER ROLE "${APP_DB_USER}" WITH LOGIN ENCRYPTED PASSWORD '${APP_DB_PASSWORD}';
    RAISE NOTICE 'Role % updated successfully', '${APP_DB_USER}';
  END IF;
END
\$\$;
EOF

# 2. Create application database if not exists
DB_EXISTS=$(psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" -tAc "SELECT 1 FROM pg_database WHERE datname='${APP_DB_NAME}'")
if [ "$DB_EXISTS" != "1" ]; then
  echo "Creating database '${APP_DB_NAME}' owned by '${APP_DB_USER}'..."
  psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${APP_DB_NAME}\" OWNER \"${APP_DB_USER}\" ENCODING 'UTF8';"
else
  echo "Database '${APP_DB_NAME}' already exists; ensuring ownership by '${APP_DB_USER}'..."
  psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" -v ON_ERROR_STOP=1 -c "ALTER DATABASE \"${APP_DB_NAME}\" OWNER TO \"${APP_DB_USER}\";"
fi

# 3. Grant privileges and setup extensions
echo "Configuring schema privileges and extensions in '${APP_DB_NAME}'..."
psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$APP_DB_NAME" -v ON_ERROR_STOP=1 <<EOF
GRANT ALL PRIVILEGES ON DATABASE "${APP_DB_NAME}" TO "${APP_DB_USER}";
GRANT ALL ON SCHEMA public TO "${APP_DB_USER}";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "${APP_DB_USER}";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "${APP_DB_USER}";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
EOF

# 4. Verify connectivity as application user
export PGPASSWORD="$APP_DB_PASSWORD"
echo "Verifying application connection as '${APP_DB_USER}'..."
psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$APP_DB_USER" -d "$APP_DB_NAME" -tAc "SELECT 'Verification SUCCESS: Connected as ' || current_user || ' to database ' || current_database();"

echo "Unattended PostgreSQL provisioning completed successfully."
