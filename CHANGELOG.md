# ArchitecturalKnowledgeDB Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-07-23

Arc42 self-documentation release: AKDB can export a deterministic `architecture.md` + `UML/`
mirror from the database (`export_sad`), stores SAD `##` sections as `sad_section` items, and
self-documents into `docs/architecture`. Builds on the 0.2.0 dual-backend release.

### Added

- **`export_sad`** — reassembles frontmatter, ordered `sad_section` items, and `sad_decision`
  records into a deterministic arc42 `architecture.md`, and exports diagrams under `UML/`
  (CLI `sad export`, MCP `akdb_export_sad`).
- **`sad_section` storage** — SAD import now persists each `##` main section alongside existing
  `document` / `sad_frontmatter` / `sad_decision` decomposition so export can round-trip prose.
- **AKDB self-documentation** — the `architectural-knowledge-db` project is ingested and
  exported into this repository's `docs/architecture` tree as a generated mirror (do not
  hand-edit; regenerate via `sad export --project architectural-knowledge-db --folder docs/architecture`).
- **Hyphenated SAD decision ids** — import accepts `D-<token>` decision headings (e.g. `D-DB`,
  `D-SoR`) in addition to `D1`-style ids.

### Changed

- **Package metadata**: version `0.3.0`; FastAPI `version=` aligned.
- **Default self-export target** convenience for AKDB's own project points at `docs/architecture`
  when configured for local maintainer workflows.

### Notes

- Phase 4 retired the hand-authored SAD under
  `Git/docs/architecture/plugins/ArchitecturalKnowledgeDB/architecture.md` after a normalized
  equivalence gate against this generated mirror. That Git folder keeps `product-facts.yml` and a
  pointer README; UML remains under `Git/UML/Plugins/ArchitecturalKnowledgeDB/`.

## [0.2.0] - 2026-07-23

Optional dual-backend release: SQLite remains the zero-setup default; PostgreSQL is an
opt-in path for concurrent multi-writer deployments (API + CLI + MCP, or multiple agents).
Design authority: [docs/architecture/dual-backend.md](docs/architecture/dual-backend.md),
[docs/adr/ADR-AKDB-0001-dual-backend.md](docs/adr/ADR-AKDB-0001-dual-backend.md), and
workspace ADR-TTD-0006. Operations: [docs/operations/postgres.md](docs/operations/postgres.md).

### Added

- **Opt-in PostgreSQL backend** selected by `AKDB_DB_URL` (DSN must start with `postgres`).
  Install with `pip install ".[postgres]"` (`psycopg[binary]`). PostgreSQL is never a core
  dependency; leaving `AKDB_DB_URL` unset keeps the existing SQLite path
  (`.akdb/architectural_knowledge_db.sqlite`, or `AKDB_DATABASE_PATH` / `--db`).
- **`Database` facade** (`architectural_knowledge_db/db/database.py`) that duck-types the
  sqlite3 surface services already use (`execute`, `executescript`, `commit`, `rollback`,
  `close`, `total_changes`). CLI, API, MCP, and services talk to the facade — not to
  `sqlite3` / `psycopg` directly for storage I/O.
- **`to_pyformat()`** placeholder rewriter (`?` → `%s`, with `%` escaped) plus
  `rewrite_sqlite_json_extract_for_pg()` so portable SQL keeps working on PostgreSQL.
- **PostgreSQL schema mirror** under `architectural_knowledge_db/db/schema/pg/` — seven
  migration files paralleling the SQLite set (`001`–`007`). Notable mappings: `BLOB` →
  `BYTEA` (including packed float embeddings), timestamp defaults as
  `(CURRENT_TIMESTAMP::text)`, and FTS via a generated `tsvector` column + GIN index
  instead of SQLite `fts5`.
- **Backend-aware migrations** (`db/migrations.py`): `run_migrations` selects
  `schema/` or `schema/pg/` from `db.is_postgres`, tracks applied files in shared
  `schema_migrations`, and applies DDL automatically on first connect / API startup.
- **Backend-aware full-text search** (`services/search.py`): SQLite keeps `fts5` /
  `MATCH` / `bm25` / `snippet`; PostgreSQL uses `websearch_to_tsquery` / `ts_rank` /
  `ts_headline`. Shared `_like_search` fallback uses `LIKE` (SQLite) or `ILIKE`
  (PostgreSQL). Ranking parity is approximate by design.
- **Docker Compose PostgreSQL override** (`docker-compose.postgres.yml`): `postgres:16`
  service, healthcheck, named volume, and `AKDB_DB_URL=postgresql://akdb:akdb@db:5432/akdb`
  on the AKDB service. Start with
  `docker compose -f docker-compose.yml -f docker-compose.postgres.yml up`.
  The image already installs the `postgres` extra (`Dockerfile`).
- **Parametrized dual-backend tests**: the `conn` fixture in `tests/conftest.py` runs
  over `sqlite` always and `postgres` when `AKDB_TEST_DB_URL` is set (otherwise Postgres
  params skip). Suite baseline reported in ADR-TTD-0006: SQLite-only ~141 passed /
  99 skipped; with live Postgres ~240 passed. Dedicated wrapper, migration, search, and
  import/export backend tests cover the five divergence seams.
- **Public docs and ADR** for storage backends: README “Storage backends”, settings for
  `AKDB_DB_URL`, ops guide, architecture note, and ADR-AKDB-0001 (accepted).

### Changed

- **SQLite connection hardening** on every connection from `connect()`:
  `PRAGMA busy_timeout = 5000` and `PRAGMA synchronous = NORMAL`, in addition to the
  existing `foreign_keys=ON` and `journal_mode=WAL`. Concurrent readers/writers still
  face SQLite’s single-writer lock under heavy multi-process load — that is the
  motivation for optional PostgreSQL — but short lock waits no longer fail immediately
  on API/CLI the way only MCP previously mitigated with `busy_timeout`.
- **API migrations once at startup** (`api/app.py`): `initialize_database` runs when the
  app is created and is keyed so it is not repeated per request. Request handlers still
  open short-lived connections via `connect()`.
- **Import/export backup discovery** (`services/import_export.py`): the SQLite-only
  `PRAGMA database_list` path is skipped on PostgreSQL; explicit export-root env vars
  remain honored. File-swap / `scripts/refresh_akdb_db.bat`-style refresh helpers stay
  SQLite-only — use `pg_dump` / `pg_restore` for Postgres (see ops guide).
- **Package metadata**: version `0.2.0`; optional `[postgres]` extra; package data includes
  `db/schema/pg/*.sql`. Local API default bind remains `127.0.0.1:8787`
  (`AKDB_HOST` / `AKDB_PORT`); container images bind `0.0.0.0:8787`.

### Confined divergences (architecture)

Backend-specific branches are limited to five seams (a sixth is a design violation):

1. `db/database.py` — facade, placeholders, `executescript` split, `total_changes`
2. `db/connection.py` — driver selection and SQLite PRAGMAs
3. `db/migrations.py` + `db/schema/pg/` — backend DDL
4. `services/search.py` — native FTS vs shared LIKE/ILIKE fallback
5. `services/import_export.py` — SQLite-only `PRAGMA database_list` guard

Portable upserts already use explicit `ON CONFLICT (<target>) DO UPDATE` and run on both
backends without a sixth branch. Embeddings remain Python-packed float blobs in
`BYTEA`/`BLOB`; **pgvector and connection pooling are deferred** (not in this release).

### Operator notes

- Fresh PostgreSQL: create the database/role, set `AKDB_DB_URL`, start API/CLI/MCP —
  migrations apply automatically; no manual schema load.
- Tests without Postgres: `python -m pytest` (SQLite only). With Postgres:
  set `AKDB_TEST_DB_URL` to a disposable DSN (tests drop/recreate `public`).
- Prefer SQLite for single-user / embedded; prefer PostgreSQL when multiple writers
  hit `database is locked`.

## [0.1.1] - 2026-07-19

### Fixed

- Configured MCP stdin/stdout explicitly as UTF-8 so `tools/list` and tool responses remain
  valid on Windows hosts whose inherited console encoding is `cp1252`.
- Preserved and indexed multi-document YAML files instead of aborting a complete project
  reingest at the second document marker.
- Bounded imported SAD decisions at the next level-two arc42 section so the final D\<n\>
  record no longer absorbs quality requirements, risks, or glossary text.

### Verification

- Added a regression test that reconfigures a `cp1252` text stream and writes Unicode MCP
  JSON successfully.
- Added a structured-document import test for multi-document YAML boundaries and payload
  preservation.
- Added a SAD decision-boundary regression covering consecutive decisions and arc42
  sections 10 through 12.
