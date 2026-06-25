# ADR-0001: Bootstrap the architecture knowledge base

## Status

accepted

## Context

{{project_name}} needs a small, versionable architecture memory that people can understand before they run a service or talk to an agent. The first download should include enough structure to capture decisions, diagrams, and project-specific specs without inventing a document layout from scratch.

The starter content lives in three folders:

- `adr/` for decisions and their consequences.
- `uml/` for PlantUML or Mermaid diagrams that can be imported as structured UML records.
- `specs/` for the project facts that decisions and diagrams should refer to.

## Decision

Use ArchitecturalKnowledgeDB as the local architecture memory for {{project_name}} and start with importable ADR and UML templates. The generated templates are editable source files and should be committed with the project that owns the architecture knowledge.

Run `akdb setup --project {{project_id}} --name "{{project_name}}"` for a new local setup. After edits, refresh the database with `akdb adr import --project {{project_id}} --folder adr` and `akdb uml import --project {{project_id}} --folder uml` from this folder.

## Consequences

New contributors have a concrete place to put architecture decisions and diagrams. Agents can retrieve the same knowledge through search and context packs after the templates are imported. The team still has to keep the files current when the architecture changes.
