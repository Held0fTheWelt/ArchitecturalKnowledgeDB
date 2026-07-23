# PostgreSQL backend (opt-in)

SQLite remains AKDB’s default, zero-setup backend. Use PostgreSQL only when you need concurrent writers (API + CLI + MCP, or multiple agents). PostgreSQL is never required.

## Prerequisites

- PostgreSQL 16 (or compatible)
- Optional dependency: `pip install ".[postgres]"` (installs `psycopg`)

## DSN

Set `AKDB_DB_URL` to a PostgreSQL URL. When this variable is set, AKDB uses PostgreSQL instead of the SQLite file path.

```bash
export AKDB_DB_URL=postgresql://user:pass@host:5432/akdb
```

Compose example (service network):

```text
postgresql://akdb:akdb@db:5432/akdb
```

Leave `AKDB_DB_URL` unset to keep the SQLite default (`.akdb/architectural_knowledge_db.sqlite`, or `AKDB_DATABASE_PATH` / `--db`).

## First run

On startup, AKDB applies migrations automatically into an empty database. Create the target database (and role) first; then start the API, CLI, or MCP process with `AKDB_DB_URL` set. No manual schema load is required for a fresh database.

## Docker Compose

From the repository root:

```bash
docker compose -f docker-compose.yml -f docker-compose.postgres.yml up
```

The override adds a `postgres:16` service, sets `AKDB_DB_URL` on the AKDB service, and waits for Postgres health before starting AKDB. The image already installs the `postgres` extra.

## Backups

**PostgreSQL:** use `pg_dump` / `pg_restore` (or your usual Postgres backup tooling).

**SQLite-only patterns (do not use with PostgreSQL):**

- Stop the service and swap the `.sqlite` file
- `scripts/refresh_akdb_db.bat` and similar file-copy refresh helpers

Those assume a single SQLite file on disk and are not valid for a Postgres DSN.

## v1 limitations

- Embeddings use the portable `BYTEA` path. **pgvector is a future upgrade**, not part of v1.
- Full-text search ranking differs slightly from SQLite `bm25` (PostgreSQL uses `tsvector` / `ts_rank`). The LIKE/ILIKE fallback remains shared. Ranking parity is approximate and acceptable for v1.

## Related

- [Repository README — Storage backends](../../README.md#storage-backends)
- Design: `docs/superpowers/specs/2026-07-23-akdb-dual-backend-sqlite-postgres-design.md`
- Decision record: `Git/docs/ADR/Project/governance/adr-ttd-0006-akdb-sqlite-default-postgres-opt-in.md` (workspace-relative from `TinyToolDevelopment`)
