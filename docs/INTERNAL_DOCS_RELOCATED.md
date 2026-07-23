# Internal documentation boundary

## AKDB's own architecture (system of record)

AKDB's architecture for the `architectural-knowledge-db` project is authored and maintained
**in the AKDB database**. A deterministic arc42 projection is exported to
[docs/architecture](architecture/) (root and subsystem SADs plus their associated UML) via:

```powershell
python -m architectural_knowledge_db.cli sad export --project architectural-knowledge-db --folder docs/architecture
```

Treat that mirror as **generated**. Do not hand-edit `docs/architecture/architecture.md` or
the exported UML tree to change product architecture; change the database and re-export.
Use the `sad upsert/section-set/decision-set` and `uml create/update` CLI commands, the
equivalent FastAPI routes, or the `akdb_*` MCP authoring tools.

Public decisions that govern AKDB packaging and ops (for example dual-backend) also live under
[docs/adr](adr/) and supporting notes such as [architecture/dual-backend.md](architecture/dual-backend.md).

## Phase 4 complete (hand-authored SAD retired)

The hand-authored SAD copy under
`Git/docs/architecture/plugins/ArchitecturalKnowledgeDB/architecture.md` was retired after a
normalized equivalence gate against this generated mirror (evidence:
`docs/superpowers/evidence/2026-07-23-akdb-retire-verify.md`, gitignored).

That Git folder now keeps only:

- `product-facts.yml` (website / Atlas projection; `sad:` points at this repo's generated mirror)
- `README.md` (relocation pointer)

The AKDB-owned UML source of truth is now in AKDB and its public projection is in this repository.
Any remaining Tiny Tool Development copies are compatibility pointers or downstream projections,
not an authoring surface.

## Private planning and cross-project authority

Private implementation planning, cross-project architecture, contracts, and the maintainer
runbook live in the private Tiny Tool Development repository, including:

- `Git/docs/superpowers/` for private specs/plans (project-specific subtrees as used by TTD)
- `Git/docs/ADR/` for cross-project decisions
- `Git/docs/` and `Git/UML/` for platform (Context B) SAD/UML authority

This public repository does not contain imported project corpora, generated exports from other
repositories, credentials, or runtime databases (`.akdb/`, `Temp/`, `exports/` stay ignored).
