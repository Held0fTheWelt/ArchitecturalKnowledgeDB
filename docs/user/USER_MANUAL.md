# User Manual

AKDB is a local knowledge service for architecture-heavy projects. It stores structured knowledge in SQLite, imports readable project documents, and exposes search/context tools through CLI, HTTP, and MCP.

## Core Concepts

| Concept | Meaning |
| --- | --- |
| Project | A named knowledge space, such as `architectural-knowledge-db` or `my-project`. |
| Shared space | Knowledge intentionally imported into multiple projects. Shared spaces are explicit, not automatic. |
| Knowledge item | A stored ADR, rule, definition, source area, document, diagram, element, or other indexed record. |
| Repository | A source repository registered read-only for Git provenance. |
| Context pack | A compact answer bundle for humans or agents working on a specific task. |
| Drift report | A report that points to likely mismatches between docs, diagrams, source paths, symbols, and Git history. |

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
| `/mcp/manifest` | MCP manifest. |
| `/mcp/dispatch` | HTTP dispatch helper for MCP-style calls. |

## MCP

Use `akdb-mcp` for stdio MCP clients. See [../operations/MCP.md](../operations/MCP.md).

## Data Ownership

AKDB runtime output belongs in `.akdb/`, `Temp/`, or `exports/`, which are ignored. Do not commit generated project corpora or copied files from other repositories into AKDB.
