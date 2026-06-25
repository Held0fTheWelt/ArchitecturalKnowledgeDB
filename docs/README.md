# AKDB Documentation (public extra-tools surface)

This folder documents how to run and use ArchitecturalKnowledgeDB on the public extra-tools repository. It contains buyer-safe user documentation, MCP setup, and examples only.

Internal AKDB architecture specs, ADRs, contracts, schema reference, planning, and the maintainer runbook were evacuated to the private Tiny Tool Development `Git` repository after public leak remediation. See [INTERNAL_DOCS_RELOCATED.md](INTERNAL_DOCS_RELOCATED.md).

## Where To Start

| Need | Read |
| --- | --- |
| Understand the repository quickly | [Repository README](../README.md) |
| Run AKDB for the first time | [user/QUICKSTART.md](user/QUICKSTART.md) |
| Use the CLI/API/MCP workflows | [user/USER_MANUAL.md](user/USER_MANUAL.md) |
| Configure database paths and runtime settings | [user/SETTINGS_REFERENCE.md](user/SETTINGS_REFERENCE.md) |
| Fix a local run or MCP setup | [user/TROUBLESHOOTING.md](user/TROUBLESHOOTING.md) |
| Connect an MCP client | [operations/MCP.md](operations/MCP.md) |
| Internal docs relocation | [INTERNAL_DOCS_RELOCATED.md](INTERNAL_DOCS_RELOCATED.md) |

## Folder Map

| Folder | Contains |
| --- | --- |
| `user/` | Practical user documentation: quick start, manual, settings, troubleshooting, FAQ, third-party notes. |
| `operations/` | MCP setup and public operations notes. |
| `examples/` | Registry, compose, and standalone sample inputs. |

## Documentation Boundary

AKDB may index other repositories at runtime, but this `docs/` tree only documents public-safe AKDB usage. Generated exports and imported project corpora belong in ignored runtime folders or outside the repository.

In the Tiny Tool workspace, internal maintainer tools and cross-project architecture authority live in `D:\TinyToolDevelopment\Git`, not in this public extra-tools repository.
