# AKDB Documentation (public extra-tools surface)

This folder documents how to run, use, operate, and understand ArchitecturalKnowledgeDB.

Public AKDB-specific architecture and decisions live here. Private planning, cross-project
SAD/UML, contracts, generated exports, and the maintainer runbook remain outside this
repository. See [INTERNAL_DOCS_RELOCATED.md](INTERNAL_DOCS_RELOCATED.md).

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
| `architecture/` | Public AKDB component and backend architecture. |
| `adr/` | Public decisions governing AKDB itself. |
| `examples/` | Registry, compose, and standalone sample inputs. |

## Documentation Boundary

AKDB may index other repositories at runtime, but this `docs/` tree only documents public-safe AKDB usage. Generated exports and imported project corpora belong in ignored runtime folders or outside the repository.

In the Tiny Tool workspace, internal maintainer tools and cross-project architecture authority live in `D:\TinyToolDevelopment\Git`, not in this public extra-tools repository.
