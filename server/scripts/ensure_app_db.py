import os

import psycopg


postgres_db = os.environ.get("POSTGRES_DB", "postgres")
app_db = os.environ.get("APP_DB_NAME", "mem0_app")
host = os.environ.get("POSTGRES_HOST", "postgres")
port = os.environ.get("POSTGRES_PORT", "5432")
user = os.environ.get("POSTGRES_USER", "postgres")
password = os.environ.get("POSTGRES_PASSWORD", "postgres")

with psycopg.connect(
    host=host,
    port=port,
    dbname=postgres_db,
    user=user,
    password=password,
    autocommit=True,
) as conn:
    exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (app_db,)).fetchone()
    if not exists:
        conn.execute(f'CREATE DATABASE "{app_db}"')
