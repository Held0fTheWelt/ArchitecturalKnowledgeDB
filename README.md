# ArchitecturalKnowledgeDB

ArchitecturalKnowledgeDB (AKDB) is a local architecture knowledge database for projects that need searchable decisions, diagrams, rules, definitions, source-area notes, and read-only Git provenance. It gives humans and coding agents a project-aware context layer without turning the source repository itself into a database.

AKDB is a standalone Python tool. It is not an Unreal plugin, not a Fab package, and not the storage location for Tiny Tools SAD/UML material.

## What Is In This Repository

| Path | Purpose |
| --- | --- |
| `architectural_knowledge_db/` | Python package: CLI, FastAPI app, MCP stdio server, database migrations, and services. |
| `docs/` | Public user documentation, MCP note, examples, and relocation pointers. Internal AKDB specs/plans live in the private `Git` repository. |
| `scripts/` | Repo-local maintenance helpers for AKDB itself. |
| `tests/` | Pytest suite for import/export, search, Git provenance, drift, MCP, consistency, and setup behavior. |
| `Dockerfile`, `docker-compose.yml` | Local container entry points for the service. |
| `.akdb/`, `Temp/`, `exports/` | Local runtime output. These are ignored and should not be committed. |

## What AKDB Does

- Creates local SQLite-backed project knowledge bases.
- Imports ADRs, architecture documents, Markdown, YAML, JSON, CSV, PlantUML, and Mermaid.
- Keeps knowledge separated by project and explicit shared spaces.
- Searches via SQLite FTS and assembles authority-aware context packs.
- Registers source repositories and scans Git metadata read-only.
- Reports drift between documents, diagrams, source paths, symbols, and Git history.
- Exposes the same knowledge through CLI, FastAPI, and MCP stdio tools.

AKDB does not mutate registered Git repositories. It stores selected metadata and imported knowledge records, not a copy of another repository.

## Quick Start

From this repository:

```powershell
python -m pip install -e ".[test]"
python -m architectural_knowledge_db.cli setup --project my-project --name "My Project"
python -m architectural_knowledge_db.cli serve
```

The API is available at:

```text
http://127.0.0.1:8787
http://127.0.0.1:8787/health
```

The setup command creates starter architecture files under `docs/architecture` by default, creates the project in the SQLite database, and imports the generated ADR and diagram files.

After editing project docs, refresh the database with the relevant imports:

```powershell
python -m architectural_knowledge_db.cli adr import --project my-project --folder docs/architecture/adr
python -m architectural_knowledge_db.cli document import --project my-project --folder docs/architecture --exclude "adr/**"
python -m architectural_knowledge_db.cli uml import --project my-project --folder docs/architecture/uml
```

## Common Commands

```powershell
python -m architectural_knowledge_db.cli project import-registry docs/examples/architectural-knowledge-db.projects.yaml
python -m architectural_knowledge_db.cli search --project architectural-knowledge-db "SQLite primary state"
python -m architectural_knowledge_db.cli context-pack --project architectural-knowledge-db "Modify the ADR storage layer"
python -m architectural_knowledge_db.cli repo add --project architectural-knowledge-db --id akdb-main --path .
python -m architectural_knowledge_db.cli git scan --project architectural-knowledge-db
python -m architectural_knowledge_db.cli consistency check --project architectural-knowledge-db
python -m architectural_knowledge_db.cli stale run --project architectural-knowledge-db
python -m architectural_knowledge_db.cli mcp manifest
```

Use `AKDB_DATABASE_PATH` or the global `--db` option to choose a database file.

## Storage backends

SQLite is the default backend. Nothing extra to install or configure: data lives at `.akdb/architectural_knowledge_db.sqlite` (override with `AKDB_DATABASE_PATH` or `--db`).

PostgreSQL is an opt-in choice for concurrent or multi-writer use. Install the optional extra and set a DSN:

```bash
pip install ".[postgres]"
export AKDB_DB_URL=postgresql://user:pass@host:5432/akdb
```

Choose SQLite for single-user, local, or embedded runs. Choose PostgreSQL when multiple processes (API + CLI + MCP) or multiple agents write concurrently — PostgreSQL MVCC avoids SQLite’s single-writer `database is locked` failures.

Operations details: [docs/operations/postgres.md](docs/operations/postgres.md).

## Documentation Map

Start here:

- [Documentation index](docs/README.md)
- [Quick Start](docs/user/QUICKSTART.md)
- [User Manual](docs/user/USER_MANUAL.md)
- [Settings Reference](docs/user/SETTINGS_REFERENCE.md)
- [Troubleshooting](docs/user/TROUBLESHOOTING.md)
- [FAQ](docs/user/FAQ.md)
- [MCP Access](docs/operations/MCP.md)
- [PostgreSQL (opt-in)](docs/operations/postgres.md)
- [Dual-backend architecture](docs/architecture/dual-backend.md)
- [Architecture decisions](docs/adr/README.md)
- [Internal docs relocation note](docs/INTERNAL_DOCS_RELOCATED.md)

Public AKDB-specific architecture and decisions belong in this repository. Private planning,
cross-project SAD/UML, contracts, generated exports, and the maintainer runbook remain outside
it (see `INTERNAL_DOCS_RELOCATED.md`).

## Repository Boundary

Keep this repository focused on AKDB. Do not commit exported documentation, SADs, UML packages, generated corpora, or copied files from other Git repositories into AKDB.

In the Tiny Tool workspace, internal maintainer tools live in `D:\TinyToolDevelopment\Git\Tools`, user-facing showcase scripts live under `D:\TinyToolDevelopment\Git\Tools\User`, and cross-project SAD/UML authority lives in `D:\TinyToolDevelopment\Git\docs` plus `D:\TinyToolDevelopment\Git\UML`.

## Development

Run tests from the repository root:

```powershell
python -m pytest
```

The package entry points are:

- `akdb`
- `architectural-knowledge-db`
- `akdb-mcp`
