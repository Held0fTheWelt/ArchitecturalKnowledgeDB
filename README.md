# ArchitecturalKnowledgeDB

ArchitecturalKnowledgeDB (AKDB) is a local architecture knowledge database for projects that need searchable decisions, diagrams, rules, definitions, source-area notes, and read-only Git provenance. It gives humans and coding agents a project-aware context layer without turning the source repository itself into a database.

AKDB is a standalone Python tool. It is not an Unreal plugin, not a Fab package, and not the
storage location for the **Tiny Tool Development platform** SAD/UML material. It **does** hold
and generate **its own** architecture self-mirror under `docs/architecture`.

## What Is In This Repository

| Path | Purpose |
| --- | --- |
| `architectural_knowledge_db/` | Python package: CLI, FastAPI app, MCP stdio server, database migrations, and services. |
| `docs/` | Public user documentation, operations notes, ADRs, and the generated AKDB-owned SAD/UML projection. |
| `scripts/` | Repo-local maintenance helpers for AKDB itself. |
| `tests/` | Pytest suite for import/export, search, Git provenance, drift, MCP, consistency, and setup behavior. |
| `Dockerfile`, `docker-compose.yml` | Local container entry points for the service. |
| `.akdb/`, `Temp/`, `exports/` | Local runtime output. These are ignored and should not be committed. |

## What AKDB Does

- Creates local SQLite-backed or opt-in PostgreSQL project knowledge bases.
- Authors structured SAD documents, sections, decisions, and UML directly in AKDB.
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

## DB-native architecture authoring

For architecture owned by AKDB, write to the database through CLI, API, or MCP and export only
for review and publication. A minimal CLI flow is:

```powershell
akdb sad upsert --project my-project --document architecture --title "My Project Architecture" --source-key architecture.md --preamble "# My Project Architecture"
akdb sad section-set --project my-project --document architecture --id goals --title "1. Introduction & Goals" --order 0 --body "Goals and stakeholders."
akdb sad decision-set --project my-project --document architecture --id D1 --title "DB-native authoring" --order 0 --status accepted --body "The database owns this architecture."
akdb uml create --project my-project --diagram context --title "System Context" --kind component --source-key UML/components/context.puml --sad-document architecture
akdb sad export --project my-project --folder docs/architecture
```

Use `sad list/get` and `uml list/get` to inspect the canonical records. The equivalent FastAPI
routes and `akdb_*` MCP tools use the same services. File import remains available for projects
whose authority still lives outside AKDB; do not import an AKDB-owned export back as an editing loop.

## Self-documentation

`docs/architecture` (the root arc42 SAD, subsystem SADs, and their associated `UML/` trees) is
**generated from the AKDB database — do not hand-edit**. Regenerate with:

```powershell
python -m architectural_knowledge_db.cli sad export --project architectural-knowledge-db --folder docs/architecture
```

The generated `.akdb-sad-export.json` manifest lets a later full export remove stale managed files
after a SAD/UML rename or deletion while preserving supporting notes such as `dual-backend.md`.

Supporting notes that are not part of that export (for example
[docs/architecture/dual-backend.md](docs/architecture/dual-backend.md)) may still be maintained
as ordinary docs. The former hand-authored SAD under
`Git/docs/architecture/plugins/ArchitecturalKnowledgeDB` was retired in Phase 4 after equivalence
verification; that folder now holds product facts + a pointer README. See
[docs/INTERNAL_DOCS_RELOCATED.md](docs/INTERNAL_DOCS_RELOCATED.md).

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
- [Generated architecture mirror](docs/architecture/architecture.md)
- [Dual-backend architecture](docs/architecture/dual-backend.md)
- [Architecture decisions](docs/adr/README.md)
- [Internal docs relocation note](docs/INTERNAL_DOCS_RELOCATED.md)

Public AKDB-specific architecture and decisions belong in this repository as a database-backed
projection under `docs/architecture`. Private planning, other products' SAD/UML, contracts,
runtime databases, imported corpora, generated exports for other projects, and the maintainer
runbook remain outside it (see `INTERNAL_DOCS_RELOCATED.md`).

## Repository Boundary

Keep this repository focused on AKDB. Commit only AKDB code, tests, operations/documentation, and
the deterministic SAD/UML projection owned by the `architectural-knowledge-db` project. Do not
commit runtime databases, backups, embeddings, imported corpora, exports for other projects, or
copied files from other repositories.

Tiny Tool Observatory and other framework tools may index or consume AKDB exports, but their code,
data, and architecture remain in their own repositories.

## Development

Run tests from the repository root:

```powershell
python -m pytest
```

The package entry points are:

- `akdb`
- `architectural-knowledge-db`
- `akdb-mcp`
