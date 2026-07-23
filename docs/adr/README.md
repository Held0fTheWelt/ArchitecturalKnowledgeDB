# Architectural ADRs

Public decisions that govern AKDB itself live here. Cross-project and private Tiny Tool
Development decisions remain outside this repository; see
[INTERNAL_DOCS_RELOCATED.md](../INTERNAL_DOCS_RELOCATED.md).

## Dual-backend storage

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-AKDB-0001](ADR-AKDB-0001-dual-backend.md) | SQLite default, PostgreSQL opt-in via a Database facade | Accepted |

Public operator guidance: [operations/postgres.md](../operations/postgres.md).
