# ArchitecturalKnowledgeDB Changelog

## Unreleased

### Fixed
- Configured MCP stdin/stdout explicitly as UTF-8 so `tools/list` and tool responses remain valid on Windows hosts whose inherited console encoding is `cp1252`.

### Verification
- Added a regression test that reconfigures a `cp1252` text stream and writes Unicode MCP JSON successfully.
