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

## Phase 4 residual (hand-authored SAD not retired)

Equivalence between the generated self-mirror and the hand-authored SAD in the private `Git`
repository has **not** yet been proven, so the hand-authored folder was **not** deleted:

- `Git/docs/architecture/plugins/ArchitecturalKnowledgeDB/`

Until Phase 4 retirement completes, that hand-authored SAD remains a residual reference copy.
Do not treat deletion of that folder as done. Prefer the database + exported mirror for
ongoing self-documentation work; close the equivalence gap before retiring the hand-authored
copy.

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
