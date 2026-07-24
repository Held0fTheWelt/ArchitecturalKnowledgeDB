# ADR-AKDB-0005: DB-native canonical creation and commit-bound publication

## Status

accepted

## Context

AKDB could update an existing imported canonical body by stable database identity, but creating a new canonical SAD, ADR, or UML file still required a source-side file or private item writes. The update input also did not state whether its complete body was canonical authoring text, so a generated target projection could be fed back and have already-projected links rebased again. Auto-export previously ran while the authoritative transaction was still open, which allowed a mirror write to survive a later database rollback.

The AKDB self-project uses structured `SadService`, `UMLService`, and ADR records exported to `docs`; repository target mirrors instead project canonical `repo_source_key` body owners. A generic self target mixed these distinct models and was obsolete.

## Decision

Provide typed canonical create and update operations through CLI, FastAPI, and MCP. Both require `body_origin=canonical`; callers must read the AKDB body owner rather than a generated mirror. Update preserves exactly one existing owner and rejects an exact generated projection when it differs from stored canonical text. Create requires that no body owner exists, rejects identity collisions, creates the body owner and links, derives SAD records, creates a structured ADR for ADR paths, and creates a structured UML record for supported UML paths.

Supported public surfaces use the `Database` facade. Canonical writes and dirty-queue rows commit first. A coalesced transaction callback performs incremental target publication only after that commit. Rollback discards callbacks and writes no mirror. If post-commit publication fails, the canonical commit remains authoritative and the dirty-queue drain rolls back so a later flush can repair the projection. Full target verification remains the publication oracle.

The self-project keeps its structured SAD/UML and ADR export workflow; the obsolete generic self target is removed instead of pretending those structured records are `repo_source_key` body owners.

The normative runtime is [D-CANON-CREATE and D-COMMIT-EXPORT in the self SAD](../architecture/architecture.md#d-canon-create-new-canonical-documents-are-db-owned-from-the-first-write) and the [canonical authoring sequence](../architecture/UML/sequence/canonical-document-update-sequence.puml).

## Consequences

- New SAD, ADR, and UML canon can originate in AKDB without a temporary source-side authoring file.
- Generated projections are outputs only; explicit origin is required at every canonical create or update boundary.
- Database rollback cannot leave a mirror ahead of authoritative state.
- A publication failure after commit is visible as stale projection plus retained dirty work, not lost canonical data.
- Canonical ADR creation now writes body and structured ADR state together.
- Structured AKDB self-export and repository target mirrors remain separate, truthful workflows.
