# ArchitecturalKnowledgeDB Changelog

## [0.2.0] - 2026-07-23

### Added
- Optional PostgreSQL backend via `AKDB_DB_URL` (install `.[postgres]`). SQLite remains the default, zero-setup local-first backend.

### Changed
- Hardened SQLite connections with `busy_timeout` and `synchronous` settings on every connection.
- API runs migrations once at startup instead of per request.

## [0.1.1] - 2026-07-19

### Fixed
- Configured MCP stdin/stdout explicitly as UTF-8 so `tools/list` and tool responses remain valid on Windows hosts whose inherited console encoding is `cp1252`.
- Preserved and indexed multi-document YAML files instead of aborting a complete project reingest at the second document marker.
- Bounded imported SAD decisions at the next level-two arc42 section so the final D<n> record no longer absorbs quality requirements, risks, or glossary text.

### Verification
- Added a regression test that reconfigures a `cp1252` text stream and writes Unicode MCP JSON successfully.
- Added a structured-document import test for multi-document YAML boundaries and payload preservation.
- Added a SAD decision-boundary regression covering consecutive decisions and arc42 sections 10 through 12.
