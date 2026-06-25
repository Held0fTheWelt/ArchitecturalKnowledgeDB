# ADR-0002: Keep ADR, UML, and specs linked

## Status

accepted

## Context

Architecture documents become hard to trust when decisions, diagrams, and implementation notes drift apart. The starter set should make the relationship explicit from day one:

- ADRs explain why a design choice exists.
- UML diagrams show the current structure or flow.
- Specs record the operational facts a contributor needs before changing the system.

## Decision

Every meaningful architecture change should update at least one of the three artifacts:

- an ADR when a tradeoff or policy changes,
- a UML diagram when structure, ownership, or communication changes,
- a spec when setup, boundaries, source areas, or expected behavior changes.

Use file paths and stable names from `specs/ARCHITECTURE_SPEC.md` inside ADRs and diagrams so ArchitecturalKnowledgeDB can surface related context during search.

## Consequences

The knowledge base starts small but stays navigable. Reviewers can ask whether ADR, UML, and specs still agree. Drift checks become more useful because the database has explicit architecture artifacts to compare with source and Git provenance.
