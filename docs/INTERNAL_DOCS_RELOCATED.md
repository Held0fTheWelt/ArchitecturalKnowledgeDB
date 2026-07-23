# Internal documentation boundary

## AKDB's own architecture (system of record)

AKDB's architecture for the `architectural-knowledge-db` project is authored and maintained
**in the AKDB database**. A deterministic arc42 mirror is exported to
[docs/architecture](architecture/) (`architecture.md` + `UML/`) via:

```powershell
python -m architectural_knowledge_db.cli sad export --project architectural-knowledge-db --folder docs/architecture
```

Treat that mirror as **generated**. Do not hand-edit `docs/architecture/architecture.md` or
the exported UML tree to change product architecture; change the database and re-export.

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

UML remains under `Git/UML/Plugins/ArchitecturalKnowledgeDB/`.

## Private planning and cross-project authority

Private implementation planning, cross-project architecture, contracts, and the maintainer
runbook live in the private Tiny Tool Development repository, including:

- `Git/docs/superpowers/` for private specs/plans (project-specific subtrees as used by TTD)
- `Git/docs/ADR/` for cross-project decisions
- `Git/docs/` and `Git/UML/` for platform (Context B) SAD/UML authority

Older pointers to empty paths such as
`Git/docs/superpowers/specs/architectural-knowledge-db/` or
`.../plans/architectural-knowledge-db/` are stale; AKDB self-doc specs/plans for this initiative
live under this repository's `docs/superpowers/` when present.

This public repository does not contain imported project corpora, generated exports from other
repositories, credentials, or runtime databases (`.akdb/`, `Temp/`, `exports/` stay ignored).
