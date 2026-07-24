# ADR-AKDB-0002: Bind relative export destinations to registered repositories

## Status

accepted

## Context

Export targets previously stored a destination path but export, synchronization, and verification interpreted relative paths against the process working directory. Running AKDB from its own repository therefore created a Tiny Tool Development canon mirror inside the AKDB repository. Storing a workstation-specific absolute path fixed that machine but made the database snapshot non-portable.

## Decision

An export target binds `repository_id` and `dest_root`. Explicit absolute destinations remain supported after path-traversal and filesystem-root validation. Relative destinations resolve against the registered repository's existing `local_path`.

When a restored snapshot contains a workstation path that does not exist, `AKDB_SOURCE_ROOT` candidates and the current checkout are accepted only if their sanitized Git remote equals the registered remote. A missing registration, unsafe destination, or unproven repository identity aborts before any write. Incremental export, full synchronization, and verification use the same resolver.

The normative runtime is documented by [D-EXPORT in the self SAD](../architecture/architecture.md#d-export-relative-export-destinations-are-repository-bound-and-fail-closed) and the [repository-bound export sequence](../architecture/UML/sequence/sad-authoring-export-sequence.puml).

## Consequences

- Repository-relative targets remain portable across local workstations and CI snapshots.
- Export cannot silently project one repository's canon into another repository.
- Relative targets require a repository registration; fallback resolution additionally requires remote identity metadata.
- Existing targets must reference the canonical repository id rather than an ad-hoc folder label.
- Tests cover registered roots, explicit absolute destinations, unsafe paths, matching snapshot checkouts, and unrelated-checkout rejection.
