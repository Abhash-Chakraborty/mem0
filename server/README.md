# Abhash Memory Self-Hosted Server

Abhash Memory is this fork's private self-hosted Mem0 server plus dashboard. It is secure by default, supports dashboard login and API keys, and exposes OpenAPI docs at `/docs`.

Upstream Mem0 remains Apache-2.0 licensed. This fork keeps the upstream license intact and adds personal deployment assets for Abhash's private infrastructure.

## Production VPS Deployment

This fork deploys only the `server/` stack in production:

- FastAPI API container
- Next.js dashboard container
- PostgreSQL 17 with pgvector
- No OpenMemory deployment in v1
- No Neo4j/graph deployment until Phase 2

Production images are built by GitHub Actions on pushes to `abhash-main`, pushed to GitHub Container Registry, and pulled by the VPS over SSH. The VPS does not build images.

### Branch flow

1. Work on feature branches.
2. Merge tested changes into `staging`.
3. Merge `staging` into `abhash-main` only when you want to publish and deploy.
4. Only `abhash-main` runs `.github/workflows/server-deploy.yml`.

### Upstream sync

`.github/workflows/upstream-sync.yml` runs weekly (and on demand via
**Actions → Upstream Sync → Run workflow**). It fetches `mem0ai/mem0`, rebases
`abhash-main` onto `upstream/main` on an `integration/upstream-sync-<date>`
branch, and opens a PR:

- **Clean rebase** → a normal PR titled `sync upstream <date>`.
- **Conflicts** → a **draft** PR whose branch merges upstream with conflict
  markers committed, plus a comment listing the conflicted files. Resolve them
  locally, push, then mark the PR ready. Nothing is auto-resolved.

Fork customizations live under `server/` (+ workflows and `ABHASH.md`), so most
upstream changes touch unrelated paths and rebase cleanly.

### One-time VPS setup

Clone the fork on the VPS and create the production env file:

```bash
git clone <your-fork-url> ~/abhash-memory
cd ~/abhash-memory/server
```

Edit `.env.production`:

```env
GHCR_OWNER=<your-github-owner-lowercase>
DASHBOARD_URL=https://memory.example.com
NEXT_PUBLIC_API_URL=https://memory.example.com/api
POSTGRES_PASSWORD=<long-random-password>
JWT_SECRET=<openssl rand -base64 48>
OPENAI_API_KEY=<your-provider-key>
AUTH_DISABLED=false
MEM0_TELEMETRY=false
```

Generate secrets:

```bash
openssl rand -base64 48   # JWT_SECRET
openssl rand -base64 32   # POSTGRES_PASSWORD
```

The production compose file binds the API and dashboard to `127.0.0.1` for a host reverse proxy. It does not publish Postgres. Keep the VPS firewall closed for database ports.

### Reverse proxy

Put HTTPS in front of the dashboard and API. Route dashboard traffic to port `3000`, and route `/api/*` to the API container on port `8000`.

Example Caddy shape:

```caddyfile
memory.example.com {
  reverse_proxy /api/* localhost:8000 {
    uri strip_prefix /api
  }

  reverse_proxy localhost:3000
}
```

The API is published as `127.0.0.1:${API_PORT:-8000}:8000` and the dashboard as `127.0.0.1:${DASHBOARD_PORT:-3000}:3000`, so the reverse proxy can reach them locally without exposing either port publicly.

### GitHub secrets

Set these repository secrets:

| Secret | Purpose |
| --- | --- |
| `VPS_HOST` | VPS hostname or IP |
| `VPS_USER` | SSH user |
| `VPS_SSH_KEY` | Private key with access to the VPS |
| `VPS_PORT` | Optional SSH port, defaults to `22` |
| `VPS_DEPLOY_PATH` | Optional path, defaults to `~/abhash-memory` |

The deploy workflow logs in to GHCR, pulls `abhash-memory-api:latest` and `abhash-memory-dashboard:latest`, restarts the compose stack, and runs API/dashboard health checks.

### First admin and API key

After the first deploy, open the dashboard and complete setup:

```text
https://memory.example.com/setup
```

Setup creates the only initial admin. Once a user exists, registration is blocked. Programmatic clients should use API keys created from the dashboard and send them with:

```bash
X-API-Key: <your-api-key>
```

To reset the admin password from the VPS:

```bash
cd ~/abhash-memory/server
docker compose --env-file .env.production -f docker-compose.prod.yaml exec -T \
  -e EMAIL="you@example.com" \
  -e PASSWORD="new-strong-password" \
  -e PYTHONPATH=/app \
  mem0 python scripts/reset_admin_password.py
```

### Manual production commands

```bash
cd ~/abhash-memory/server

export GHCR_OWNER=<your-github-owner-lowercase>
export IMAGE_TAG=latest

docker compose --env-file .env.production -f docker-compose.prod.yaml pull
docker compose --env-file .env.production -f docker-compose.prod.yaml up -d
docker compose --env-file .env.production -f docker-compose.prod.yaml ps
docker compose --env-file .env.production -f docker-compose.prod.yaml logs -f
```

### Backups and retention

Back up both the memory database and app/auth database:

```bash
cd ~/abhash-memory/server
docker compose --env-file .env.production -f docker-compose.prod.yaml exec -T postgres \
  pg_dumpall -U postgres > mem0_backup.sql
```

Prune request logs periodically:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yaml exec -T \
  -e REQUEST_LOG_RETENTION_DAYS=30 \
  -e PYTHONPATH=/app \
  mem0 python scripts/prune_request_logs.py
```

Wire that prune command into cron or a systemd timer.

> **Upgrading?** The Postgres image changed from the archived `ankane/pgvector:v0.5.1`
> to the official `pgvector/pgvector:pg17`, and `POSTGRES_PASSWORD` is now a required
> env var. If you have an existing install, see
> [Migrating from ankane/pgvector to pgvector/pgvector](#migrating-from-ankanepgvector-to-pgvectorpgvector)
> before running `docker compose up`.

## Quick Start

### Prerequisites

Set your OpenAI API key in the local env file:

```bash
cd server
# Edit .env and set:
# OPENAI_API_KEY=sk-...
```

The repo already includes generated local values for `POSTGRES_PASSWORD`, `JWT_SECRET`, and `ADMIN_API_KEY` in `server/.env`. You can replace them if you want, but you only need to bring your own OpenAI API key before testing memory creation.

Recommended defaults for this fork:

```env
MEM0_DEFAULT_LLM_MODEL=gpt-5.4-nano
MEM0_DEFAULT_EMBEDDER_MODEL=text-embedding-3-small
MEM0_CATEGORY_LLM_MODEL=gpt-5.4-mini
```

`gpt-5.4-nano` is the cheapest current flagship text model listed on OpenAI's pricing page, and `text-embedding-3-small` is the cheapest practical OpenAI embedding default for this stack. Categories use `gpt-5.4-mini` by default because classification quality matters more there.

### Run and test locally

Start Docker Desktop first, then:

```bash
cd server
make bootstrap
```

`make bootstrap` will:

1. Build and start the API, dashboard, and Postgres.
2. Run database migrations.
3. Create the first admin account.
4. Print the dashboard URL, admin email/password, and first API key.

Open:

```text
http://localhost:3000
```

Use the printed admin email/password to log in. Save the printed API key; it is only shown once.

Smoke-test the API:

```bash
curl -X POST http://localhost:8888/memories \
  -H "X-API-Key: <printed-api-key>" \
  -H "Content-Type: application/json" \
  -d "{\"messages\": [{\"role\": \"user\", \"content\": \"I like quiet focused work blocks.\"}], \"user_id\": \"abhash-local\"}"

curl -X POST http://localhost:8888/search \
  -H "X-API-Key: <printed-api-key>" \
  -H "Content-Type: application/json" \
  -d "{\"query\": \"How do I like to work?\", \"filters\": {\"user_id\": \"abhash-local\"}}"
```

Useful local commands:

```bash
make health
make logs
make down
make clean  # wipes local Postgres data
```

If you lose the admin password:

```bash
make reset-admin-password EMAIL=<admin-email> PASSWORD=<new-strong-password>
```

### Required keys and passwords

| Value | File | Required? | Where to get it |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | `server/.env`, `server/.env.production` | Yes | Create one in the OpenAI API dashboard: https://platform.openai.com/api-keys |
| `POSTGRES_PASSWORD` | `server/.env`, `server/.env.production` | Yes | Already generated locally; for production, replace with `openssl rand -base64 32` |
| `JWT_SECRET` | `server/.env`, `server/.env.production` | Yes | Already generated locally; for production, replace with `openssl rand -base64 48` |
| `ADMIN_API_KEY` | `server/.env`, `server/.env.production` | Optional | Already generated locally; dashboard-issued API keys are preferred after setup |
| Admin password | Created by `make bootstrap` or setup page | Yes | Let bootstrap generate it, or pass `PASSWORD='your-strong-password'` |

For OpenAI billing safety, set a project budget/limit in the OpenAI dashboard before heavy testing.

### Agent-first

Run one command; the terminal prints the admin email, password, and first API key.

```bash
cd server
make bootstrap
```

This starts the stack, waits for the API and dashboard to be ready, creates the first admin, and generates the first API key.

> The generated credentials print once in the `=== Ready ===` block. Save the password and API key before closing the terminal — the API key cannot be recovered afterwards.

> `make bootstrap` skips the setup wizard, so the use-case → custom-instructions step doesn't run. To add custom instructions afterwards, `POST /configure` with `{"custom_instructions": "..."}`, or run the Browser-first flow on a fresh install.

You can override the generated credentials:

```bash
cd server
make bootstrap EMAIL=admin@company.com PASSWORD='strong-password' NAME='Admin'
```

For machine-readable output:

```bash
cd server
OUTPUT=json make seed
```

Teardown:

```bash
# Stop the stack
cd server && make down

# Wipe all data (including the Postgres volume)
cd server && make clean
```

### Browser-first

Start the stack and finish setup by walking through the wizard in your browser.

```bash
cd server
make up
```

Then open `http://localhost:3000` and complete the setup wizard.

## Security Defaults

- Dashboard login uses JWTs.
- Programmatic access uses `X-API-Key`.
- Auth is enabled by default.
- `AUTH_DISABLED=true` exists for local development only and should not be used in production.

## Forgotten password

Reset an admin password from the host while the stack is running:

```bash
cd server
make reset-admin-password EMAIL=admin@example.com PASSWORD='new-strong-password'
```

This is the supported recovery path. Anyone with shell access to the host already has full access to the database and secrets, so this command does not expand the attack surface.

## Request log retention

The `request_logs` table is append-only and grows with traffic (~864k rows/day at 10 req/s). Prune it periodically:

```bash
cd server
make prune-logs                               # defaults to 30 days
make prune-logs REQUEST_LOG_RETENTION_DAYS=7  # shorter window
```

Wire the command into cron or a systemd timer in production. The `created_at` column uses a BRIN index, so range deletes stay cheap even on large tables.

## Local URLs

- Dashboard: `http://localhost:3000`
- API: `http://localhost:8888`
- OpenAPI docs: `http://localhost:8888/docs`

## Dashboard

Once logged in, the dashboard exposes:

- **Requests** — live audit log of API calls (method, path, status, latency).
- **Memories** — browse memories, filter by user ID.
- **Entities** — list every `user_id`, `agent_id`, and `run_id` that owns memories, with counts. Delete an entity to cascade-delete its memories.
- **API Keys** — create, label, and revoke per-user keys.
- **Categories** — create local categories, manually assign memories, and reclassify memories with `MEM0_CATEGORY_LLM_MODEL` (`gpt-5.4-mini` by default).
- **Webhooks** — create signed event endpoints, enable or disable them, send test deliveries, rotate secrets, and inspect retry history.
- **Analytics** — local request volume, success rate, latency, top endpoints, category distribution, memory counts, and webhook delivery health.
- **Export** — download JSON or CSV exports filtered by `user_id`, `agent_id`, `run_id`, or category.
- **Configuration** — runtime LLM and embedder override. Changes persist to the app database and reapply on restart, layered over the values from your `.env`.
- **Settings** — account profile and password.

Webhook payloads are signed with `X-Mem0-Signature-256: sha256=<hmac>`, using the endpoint secret shown at creation time. Failed deliveries retry with exponential backoff until `MEM0_WEBHOOK_MAX_ATTEMPTS` is reached.

## Telemetry

Enabled by default, matching the Mem0 OSS library. Sends at most two events per install to the same anonymous PostHog project the library uses:

- `admin_registered` — fired when the first admin is created (wizard or direct API call). Properties: email domain, server version, install UUID.
- `onboarding_completed` — fired when the setup wizard reaches its final success state. Carries the same properties plus the freeform `use_case` the operator entered. API-only bootstraps never emit this event.

Set `MEM0_TELEMETRY=false` to opt out.

## Security headers

The dashboard sets the following response headers on every path (see `server/dashboard/next.config.mjs`):

- `X-Frame-Options: DENY`
- `Content-Security-Policy: frame-ancestors 'none'`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`

Together these prevent iframe embedding, sniffing of mislabelled MIME types, and cross-origin referrer leaks. Harden further behind your own reverse proxy if needed.

## Migrating from `ankane/pgvector` to `pgvector/pgvector`

The `ankane/pgvector` Docker image is archived and no longer maintained. This release
replaces it with the official `pgvector/pgvector:pg17` image (PostgreSQL 17, pgvector 0.8.0).

**What changed:**

| | Before | After |
|---|---|---|
| Docker image | `ankane/pgvector:v0.5.1` | `pgvector/pgvector:pg17` |
| PostgreSQL version | 15 | 17 |
| pgvector version | 0.5.1 | 0.8.0 |
| Credentials | Hardcoded `postgres`/`postgres` | Driven by `POSTGRES_USER` / `POSTGRES_PASSWORD` env vars |

### Fresh installs (no existing data)

No migration needed. Edit `.env`, set `OPENAI_API_KEY`, verify `POSTGRES_PASSWORD`, and run:

```bash
cd server
make up
```

### Existing installs (preserving data)

PostgreSQL 17 cannot read data files written by PostgreSQL 15 directly.
You must export your data first, then import it into the new container.

**1. Export your data from the old container**

With the old stack still running:

```bash
cd server

# Dump all databases (mem0 memories + mem0_app auth/config data)
docker compose exec -T postgres pg_dumpall -U postgres > mem0_backup.sql
```

Verify the dump file is non-empty:

```bash
ls -lh mem0_backup.sql
```

**2. Stop the old stack and remove the old volume**

```bash
# Stop containers
docker compose down

# Remove the old Postgres data volume
docker compose down -v
```

> **Warning:** `docker compose down -v` deletes the `postgres_db` volume permanently.
> Only run this after you have verified your backup.

**3. Update your `.env`**

The Postgres credentials are no longer hardcoded in `docker-compose.yaml`.
Add them to your `.env` file (or verify they match your old setup):

```bash
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<your-password>    # required — compose will refuse to start without it
POSTGRES_COLLECTION_NAME=memories
```

If you previously relied on the hardcoded defaults (`postgres`/`postgres`), set
`POSTGRES_PASSWORD=postgres` to keep the same credentials.

**4. Start only Postgres**

Start **only** the Postgres container first — do not start the mem0 API yet.
The API runs `alembic upgrade head` on startup, which creates empty tables that
would conflict with the restore.

```bash
docker compose up -d postgres
```

Wait for the Postgres healthcheck to pass:

```bash
docker compose exec -T postgres pg_isready -q && echo "ready" || echo "not ready"
```

**5. Restore your data**

```bash
docker compose exec -T postgres psql -U postgres < mem0_backup.sql
```

You may see notices like `role "postgres" already exists` — these are harmless.

> **Important:** You must restore before starting the mem0 API container. The API
> runs database migrations on startup which create empty tables — restoring after
> that would fail with duplicate-key errors and lose your API keys and settings.

**6. Start the API**

Now start the mem0 API container. Alembic will detect the existing tables and
only apply any new migrations:

```bash
docker compose up -d mem0
```

**7. Verify**

```bash
# Check the API is healthy
make health

# Confirm your memories are present
curl -s http://localhost:8888/memories?user_id=<your-user-id> -H "X-API-Key: <your-api-key>"
```

### Rollback

If you need to revert, restore the old image tag in `docker-compose.yaml`:

```yaml
postgres:
    image: ankane/pgvector:v0.5.1
```

Then `docker compose down -v`, `docker compose up -d --build`, and restore from
`mem0_backup.sql` into the old container the same way.

## Reference

Additional product and API documentation lives at [docs.mem0.ai](https://docs.mem0.ai/open-source/overview).
