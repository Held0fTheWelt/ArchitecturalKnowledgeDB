# AKDB Documentation (public extra-tools surface)

This folder documents how to run, use, operate, and understand ArchitecturalKnowledgeDB.

Public AKDB-specific architecture and decisions live here (including the generated
`architecture/` self-mirror). Private planning, platform SAD/UML, contracts, generated
exports for other projects, and the maintainer runbook remain outside this repository.
See [INTERNAL_DOCS_RELOCATED.md](INTERNAL_DOCS_RELOCATED.md).

## Where To Start

| Need | Read |
| --- | --- |
| Understand the repository quickly | [Repository README](../README.md) |
| Run AKDB for the first time | [user/QUICKSTART.md](user/QUICKSTART.md) |
| Use the CLI/API/MCP workflows | [user/USER_MANUAL.md](user/USER_MANUAL.md) |
| Configure database paths and runtime settings | [user/SETTINGS_REFERENCE.md](user/SETTINGS_REFERENCE.md) |
| Fix a local run or MCP setup | [user/TROUBLESHOOTING.md](user/TROUBLESHOOTING.md) |
| Connect an MCP client | [operations/MCP.md](operations/MCP.md) |
| Use PostgreSQL (opt-in) | [operations/postgres.md](operations/postgres.md) |
| Understand the storage architecture | [architecture/dual-backend.md](architecture/dual-backend.md) |
| Review AKDB decisions | [adr/README.md](adr/README.md) |
| Internal docs relocation | [INTERNAL_DOCS_RELOCATED.md](INTERNAL_DOCS_RELOCATED.md) |

## Folder Map

| Folder | Contains |
| --- | --- |
| `user/` | Practical user documentation: quick start, manual, settings, troubleshooting, FAQ, third-party notes. |
| `operations/` | MCP setup, PostgreSQL opt-in ops, and public operations notes. |
| `architecture/` | Generated root/subsystem arc42 projection and associated UML, plus supporting notes (e.g. dual-backend). Author in AKDB; do not hand-edit the projection. |
| `adr/` | Public decisions governing AKDB itself. |
| `examples/` | Registry, compose, and standalone sample inputs. |

## Documentation Boundary

AKDB may index other repositories at runtime, but this `docs/` tree only documents public-safe AKDB usage. Generated exports and imported project corpora belong in ignored runtime folders or outside the repository.

Tiny Tool Observatory and other framework tools may consume AKDB through API/MCP or the generated
projection, but their architecture and data stay in their own repositories.
