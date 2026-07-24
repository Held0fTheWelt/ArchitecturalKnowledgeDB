# User Manual

AKDB is a local knowledge service for architecture-heavy projects. It stores structured knowledge
in SQLite or opt-in PostgreSQL, supports DB-native SAD/UML authoring, imports externally owned
documents, and exposes the same services through CLI, HTTP, and MCP.

## Core Concepts

| Concept | Meaning |
| --- | --- |
| Project | A named knowledge space, such as `architectural-knowledge-db` or `my-project`. |
| Shared space | Knowledge intentionally imported into multiple projects. Shared spaces are explicit, not automatic. |
| Knowledge item | A stored ADR, rule, definition, source area, document, diagram, element, or other indexed record. |
| Repository | A source repository registered read-only for Git provenance. |
| Context pack | A compact answer bundle for humans or agents working on a specific task. |
| Drift report | A report that points to likely mismatches between docs, diagrams, source paths, symbols, and Git history. |
| DB-native SAD | A document, preamble, frontmatter, ordered sections, and decisions authored in AKDB. |
| Projection | A deterministic SAD/UML file tree exported from DB-owned records for review or publication. |

## Create Or Update A Project

```powershell
akdb setup --project my-project --name "My Project"
```

Useful options:

| Option | Purpose |
| --- | --- |
| `--target PATH` | Where starter ADR, spec, and diagram files are written. Default: `docs\architecture`. |
| `--template NAME` | Template set name. Default: `starter`. |
| `--overwrite` | Replace existing starter files. |
| `--no-import` | Create files but skip the immediate import. |

## Import Knowledge

Use import when another repository or file corpus remains the source of truth. For an architecture
owned by AKDB, use the DB-native workflow below instead.

ADRs:

```powershell
akdb adr import --project my-project --folder docs/architecture/adr
```

Documents:

```powershell
akdb document import --project my-project --folder docs/architecture --exclude "adr/**"
```

Diagrams:

```powershell
akdb uml import --project my-project --folder docs/architecture/uml
```

Document import recognizes Markdown plus structured architecture files such as YAML, JSON, CSV, contracts, evidence reports, schemas, and project facts. ADR import preserves domain IDs and skips catalog/template files that are not real ADR records.

After a corpus transfers authority to AKDB, do not recreate a retired source tree merely to edit one
file. Update the existing canonical body by stable identity:

```powershell
akdb document update-canonical --project my-project --repository main --source-key docs/architecture/project/system/architecture.md --body-file updated-architecture.md
```

AKDB rejects unsafe, missing, or ambiguous identities and reconciles derived SAD, ADR, and UML state.

## Author SAD And UML In AKDB

Create a root SAD and structured children:

```powershell
akdb sad upsert --project my-project --document architecture --title "My Project Architecture" --source-key architecture.md --preamble "# My Project Architecture"
akdb sad section-set --project my-project --document architecture --id goals --title "1. Introduction & Goals" --order 0 --body "Goals, stakeholders, and quality priorities."
akdb sad section-set --project my-project --document architecture --id decisions --title "9. Architecture Decisions" --order 8 --role decisions
akdb sad decision-set --project my-project --document architecture --id D1 --title "DB-native authority" --order 0 --status accepted --body "Maintain this SAD in AKDB."
```

Add a subsystem SAD by giving it a nested `source_key`, then associate UML with the owning SAD:

```powershell
akdb sad upsert --project my-project --document authoring --title "Authoring Subsystem" --source-key subsystems/authoring/architecture.md --preamble "# Authoring Subsystem"
akdb uml create --project my-project --diagram authoring-context --title "Authoring Context" --kind component --source-key subsystems/authoring/UML/context.puml --sad-document authoring
akdb uml update --project my-project --diagram authoring-context --raw-source "@startuml`ncomponent Authoring`n@enduml`n"
```

Inspect and publish:

```powershell
akdb sad list --project my-project
akdb sad get --project my-project --document architecture
akdb uml list --project my-project
akdb sad export --project my-project --folder docs/architecture
```

`source_key` values must be safe relative paths and unique per project. A UML association must
name an existing SAD. Multiple SADs export hierarchically; only diagrams associated with a selected
SAD are included. A full export maintains `.akdb-sad-export.json` and removes only stale files from
the previous managed set. Do not edit and re-import generated files for a DB-owned project.

## Register Repositories

```powershell
akdb repo add --project my-project --id my-project-main --path .
akdb git scan --project my-project
```

The Git scan is read-only. AKDB stores selected metadata and links knowledge back to source files; it does not copy `.git` or mutate the repository.

## Search

```powershell
akdb search --project my-project "SQLite primary state"
```

Use search when you need quick discovery across imported records.

## Build Context Packs

```powershell
akdb context-pack --project my-project "Modify the ADR storage layer"
```

Use context packs before agent work. They combine search results, linked decisions, relevant diagrams, staleness/provenance information, and compact source references.

## Check Consistency And Drift

```powershell
akdb consistency check --project my-project
akdb stale status-quo --project my-project
akdb stale compute --project my-project --mode git_timeline
akdb stale run --project my-project
```

`stale run` is the broad local check: it computes current status-quo drift, Git-timeline staleness, persists reports, and returns a prioritized summary.

## Serve HTTP

```powershell
akdb serve --host 127.0.0.1 --port 8787
```

Useful endpoints:

| Endpoint | Purpose |
| --- | --- |
| `/` | Minimal local admin UI. |
| `/health` | Service/database health. |
| `/projects` | Project list and creation. |
| `/projects/{project_id}/search` | Search endpoint. |
| `/projects/{project_id}/context-pack` | Context-pack endpoint. |
| `/projects/{project_id}/sads` | List DB-native SAD documents. |
| `/projects/{project_id}/sads/{document_id}` | Read/create/update/delete one SAD. |
| `/projects/{project_id}/sads/{document_id}/sections/{section_id}` | Update/delete a SAD section. |
| `/projects/{project_id}/sads/{document_id}/decisions/{decision_id}` | Update/delete a SAD decision. |
| `/projects/{project_id}/uml/diagrams` | List or create DB-native UML diagrams. |
| `/projects/{project_id}/uml/diagrams/{diagram_id}` | Read/update/delete a UML diagram. |
| `/mcp/manifest` | MCP manifest. |
| `/mcp/dispatch` | HTTP dispatch helper for MCP-style calls. |

## MCP

Use `akdb-mcp` for stdio MCP clients. See [../operations/MCP.md](../operations/MCP.md).

## Data Ownership

AKDB runtime output belongs in `.akdb/`, `Temp/`, or `exports/`, which are ignored. Commit a
generated SAD/UML projection only in the repository that owns that architecture. Do not commit
runtime databases, imported corpora, exports for other projects, or copied files from other
repositories into AKDB.
