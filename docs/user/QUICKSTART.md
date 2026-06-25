# Quick Start

This guide gets AKDB running locally, creates one project knowledge base, and proves search works.

## 1. Requirements

- Python 3.11 or newer
- Git on PATH if you want provenance scans
- A local checkout of this repository

## 2. Install For Local Development

From the AKDB repository root:

```powershell
python -m pip install -e ".[test]"
```

This installs the CLI entry points `akdb`, `architectural-knowledge-db`, and `akdb-mcp`.

## 3. Create A Project

```powershell
akdb setup --project my-project --name "My Project"
```

AKDB creates starter files under `docs/architecture`, creates or updates the project record, and imports the generated ADR and diagram files.

## 4. Start The Service

```powershell
akdb serve
```

Open:

```text
http://127.0.0.1:8787
http://127.0.0.1:8787/health
```

Expected result: `/health` returns an OK response with database information.

## 5. Search The Knowledge Base

```powershell
akdb search --project my-project "architecture"
```

Expected result: AKDB returns matching knowledge records from the starter files.

## 6. Build An Agent Context Pack

```powershell
akdb context-pack --project my-project "change the architecture docs"
```

Expected result: AKDB returns a compact bundle of relevant decisions, documents, diagrams, links, and provenance fields that can be given to an agent before it edits a project.

## 7. Add Git Provenance

From inside the project you want to track:

```powershell
akdb repo add --project my-project --id my-project-main --path .
akdb git scan --project my-project
akdb stale run --project my-project
```

The Git scanner is read-only. It stores selected commit and file metadata in AKDB; it does not write to the registered repository.

## 8. Optional: Connect MCP

Read [../operations/MCP.md](../operations/MCP.md) when an MCP client should call AKDB tools directly.
