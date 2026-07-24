# ADR-AKDB-0004: Update imported canonical documents by stable DB identity

## Status

accepted

## Context

TTD transferred its architecture authority to AKDB and retired the former SAD/UML source trees. `import_documents` still required a physical file, so maintainers had to simulate a source overlay to change one existing canonical body. That could leave stale derived SAD children and links, update a generic UML body without its structured diagram record, or feed target-projected links back into canonical storage.

## Decision

Provide one typed `update_canonical_document` operation in `ImportExportService`, exposed through CLI, FastAPI, and MCP. It accepts a registered repository id, safe existing `repo_source_key`, complete body, supported encoding, and explicit `body_origin=canonical`. The operation requires exactly one body owner and preserves its item identity. It rejects an exact generated target projection when that text differs from the stored canonical body, removes stale outgoing links and imported SAD children before rebuilding them, prunes same-source legacy children whose recorded parent no longer exists, updates structured ADR state, and updates exactly one structured UML model matched by `repo_source_key`. SAD derivation recognizes simple, descriptive, and scoped numbered decision identifiers and preserves summary-table status when an inline status is absent. Unsafe paths, missing or ambiguous owners, classification changes, and missing or ambiguous UML structure fail closed.

Canonical writes use the normal dirty-target path; publication timing is governed by [ADR-AKDB-0005](adr-akdb-0005-db-native-canonical-creation-and-commit-bound-publication.md), so target I/O occurs only after the authoritative commit.

The normative runtime is [D-CANON-UPDATE in the self SAD](../architecture/architecture.md#d-canon-update-existing-canonical-documents-update-by-stable-db-identity) and the [canonical authoring sequence](../architecture/UML/sequence/canonical-document-update-sequence.puml).

## Consequences

- TTD canon maintenance no longer needs a temporary or resurrected source file.
- Stable owner identity and AKDB provenance survive content updates.
- Removed decisions, sections, and links do not linger as derived knowledge.
- Same-source SAD children from retired parent identities are pruned during update.
- Scoped decision IDs and table-only statuses round-trip without collapsing several decisions into one synthetic record.
- Generic UML/ADR bodies and their structured representations move together.
- Callers must assert canonical origin and cannot use an exact generated projection as edit input.
- Adding a new canonical file is governed by ADR-AKDB-0005 rather than this update-only decision.
- Full target verification remains the publication oracle after a batch.
