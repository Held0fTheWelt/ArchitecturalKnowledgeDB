# ADR-AKDB-0004: Update imported canonical documents by stable DB identity

## Status

accepted

## Context

TTD transferred its architecture authority to AKDB and retired the former SAD/UML source trees. `import_documents` still required a physical file, so maintainers had to simulate a source overlay to change one existing canonical body. That could leave stale derived SAD children and links, or update a generic UML body without its structured diagram record.

## Decision

Provide one typed `update_canonical_document` operation in `ImportExportService`, exposed through CLI, FastAPI, and MCP. It accepts a registered repository id, safe existing `repo_source_key`, complete body, and supported encoding. The operation requires exactly one body owner and preserves its item identity. It removes stale outgoing links and imported SAD children before rebuilding them, updates an imported ADR decomposition, and updates exactly one structured UML model matched by `repo_source_key`. Unsafe paths, missing or ambiguous owners, classification changes, and missing or ambiguous UML structure fail closed. All writes occur in one deferred-export transaction and use the normal dirty-target publication path.

The normative runtime is [D-CANON-UPDATE in the self SAD](../architecture/architecture.md#d-canon-update-existing-canonical-documents-update-by-stable-db-identity) and the [canonical update sequence](../architecture/UML/sequence/canonical-document-update-sequence.puml).

## Consequences

- TTD canon maintenance no longer needs a temporary or resurrected source file.
- Stable owner identity and AKDB provenance survive content updates.
- Removed decisions, sections, and links do not linger as derived knowledge.
- Generic UML/ADR bodies and their structured representations move together.
- The operation updates existing bodies only; adding or renaming a canonical file remains a separate governed workflow.
- Full target verification remains the publication oracle after a batch.
