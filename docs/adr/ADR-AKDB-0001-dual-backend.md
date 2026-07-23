# ADR-AKDB-0001: SQLite default and PostgreSQL opt-in

- Status: Accepted
- Date: 2026-07-23

## Context

SQLite gives AKDB a zero-configuration, local-first deployment, but its single-writer model
causes lock contention when API, CLI, MCP, or multiple agents write concurrently. PostgreSQL
supports those multi-writer deployments, while requiring additional operational setup.

AKDB's SQL and connection usage are sufficiently portable that a small compatibility facade
can isolate the backend differences without an ORM or a repository-layer rewrite.

## Decision

SQLite remains AKDB's default embedded backend. PostgreSQL is an opt-in backend selected by
`AKDB_DB_URL`. All application code talks to the `Database` facade rather than directly to
`sqlite3` or `psycopg`.

Backend divergence is limited to connection and facade handling, migrations and PostgreSQL
DDL, full-text search, and the SQLite-only file-backup guard. PostgreSQL support remains an
optional package extra.

## Consequences

- Existing SQLite installations require no configuration change.
- Concurrent server deployments can use PostgreSQL.
- Both backends must pass the same behavioral test suite.
- Search ranking is backend-native and therefore approximately, not numerically, equivalent.
- Embeddings remain portable binary values; pgvector and connection pooling are deferred.

See [Dual-backend architecture](../architecture/dual-backend.md) for the component boundary
and [PostgreSQL operations](../operations/postgres.md) for deployment details.
