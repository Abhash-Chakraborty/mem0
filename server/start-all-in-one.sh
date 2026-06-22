#!/bin/bash
set -euo pipefail

export PGDATA="${PGDATA:-/var/lib/postgresql/data}"
export POSTGRES_HOST="${POSTGRES_HOST:-127.0.0.1}"
export POSTGRES_PORT="${POSTGRES_PORT:-5432}"
export POSTGRES_USER="${POSTGRES_USER:-postgres}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
export POSTGRES_DB="${POSTGRES_DB:-postgres}"
export APP_DB_NAME="${APP_DB_NAME:-mem0_app}"
export POSTGRES_COLLECTION_NAME="${POSTGRES_COLLECTION_NAME:-memories}"
export API_INTERNAL_URL="${API_INTERNAL_URL:-http://127.0.0.1:8000}"
export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-/api}"
export NEXT_PUBLIC_INSTANCE_NAME="${NEXT_PUBLIC_INSTANCE_NAME:-Abhash Memory}"

mkdir -p "$PGDATA" /run/postgresql /app/history
chown -R postgres:postgres "$PGDATA" /run/postgresql

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  su postgres -c "/usr/lib/postgresql/15/bin/initdb -D '$PGDATA' --username='$POSTGRES_USER'"
  {
    echo "listen_addresses = '127.0.0.1'"
    echo "shared_preload_libraries = ''"
  } >> "$PGDATA/postgresql.conf"
fi

su postgres -c "/usr/lib/postgresql/15/bin/pg_ctl -D '$PGDATA' -o '-p $POSTGRES_PORT' -w start"

psql=(
  psql
  -v ON_ERROR_STOP=1
  --set=postgres_password="$POSTGRES_PASSWORD"
  --username "$POSTGRES_USER"
  --host 127.0.0.1
  --port "$POSTGRES_PORT"
)
"${psql[@]}" --dbname postgres <<SQL
ALTER USER "$POSTGRES_USER" WITH PASSWORD :'postgres_password';
CREATE EXTENSION IF NOT EXISTS vector;
SELECT 'CREATE DATABASE $APP_DB_NAME'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$APP_DB_NAME')\gexec
SQL
"${psql[@]}" --dbname "$APP_DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;"

python scripts/ensure_app_db.py
alembic upgrade head

(
  cd /app/dashboard
  export PORT="${DASHBOARD_INTERNAL_PORT:-3001}"
  export HOSTNAME="${DASHBOARD_INTERNAL_HOST:-127.0.0.1}"
  printenv | grep '^NEXT_PUBLIC_' | while IFS='=' read -r key value; do
    escaped=$(printf '%s' "$value" | sed -e 's/[\\&|]/\\&/g')
    find .next/ -type f -exec sed -i "s|$key|$escaped|g" {} \;
  done
  node server.js
) &
uvicorn main:app --host 0.0.0.0 --port 8000 &
nginx -g "daemon off;"
