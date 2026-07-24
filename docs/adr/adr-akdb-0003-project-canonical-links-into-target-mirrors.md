# ADR-AKDB-0003: Project canonical links into target mirrors

## Status

accepted

## Context

Canonical documents are imported with a repository-relative `repo_source_key`, and their relative Markdown links are valid at that source location. TTD publishes the same documents below `docs/architecture/_generated`, while UML and ADR inputs are additionally remapped into `UML/` and `ADR/` subtrees. A verbatim copy therefore left links pointing at the wrong depth and produced thousands of unresolved references. Incremental export could also select an arbitrary row when both a generic imported document and a structured derivative shared the same `repo_source_key`.

## Decision

Store canonical document text unchanged and interpret relative links from the canonical `repo_source_key`. Verification, incremental export, and full synchronization use one projection function. For Markdown outside fenced code blocks, it resolves a relative source target and then maps exportable `docs/architecture`, `docs/ADR`, and `UML` targets into the target mirror layout. Non-exported repository targets are addressed relative to the registered repository when the export destination is repository-relative. External URLs, fragments, and explicit repository-root references remain unchanged. An absolute destination whose route back to non-mirrored repository content is unknowable preserves the original source link.

For any `repo_source_key`, exactly one knowledge item may carry the canonical `body_text`. Structured SAD/UML derivatives can share the source key without owning a second payload. Export aborts on multiple payload owners instead of depending on database row order.

The normative behavior is [D-PROJECTION in the self SAD](../architecture/architecture.md#d-projection-target-mirrors-rebase-canonical-links-and-require-one-body-owner) and the [authoring/export sequence](../architecture/UML/sequence/sad-authoring-export-sequence.puml).

## Consequences

- Canonical database content stays independent of any particular mirror location.
- Generated SAD, ADR, and UML links resolve within the mirror when the referenced artifact is exported.
- Links to source code and descriptors continue to reach the registered repository from repository-relative targets.
- Incremental export, synchronization, and freshness verification compare the same projected bytes.
- Fenced documentation examples are not silently rewritten.
- Ambiguous payload ownership fails visibly and must be repaired in the database.
- The supported inline-link grammar is intentionally narrow; unresolved reference-style or unusual Markdown remains detectable by downstream link gates.
