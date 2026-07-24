# Architectural ADRs

Public decisions that govern AKDB itself live here. Cross-project and private Tiny Tool
Development decisions remain outside this repository; see
[INTERNAL_DOCS_RELOCATED.md](../INTERNAL_DOCS_RELOCATED.md).

AKDB-authored ADR files are generated from project `architectural-knowledge-db`; do not
hand-edit their decision content.

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-AKDB-0001](ADR-AKDB-0001-dual-backend.md) | SQLite default, PostgreSQL opt-in via a Database facade | Accepted |
| [ADR-AKDB-0002](adr-akdb-0002-bind-relative-export-destinations-to-registered-repositories.md) | Bind relative export destinations to registered repositories | Accepted |

Public operator guidance: [operations/postgres.md](../operations/postgres.md).
