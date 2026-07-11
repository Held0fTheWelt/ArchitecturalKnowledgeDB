# ArchitecturalKnowledgeDB Changelog

## Unreleased

### Fixed
- Configured MCP stdin/stdout explicitly as UTF-8 so `tools/list` and tool responses remain valid on Windows hosts whose inherited console encoding is `cp1252`.
- Preserved and indexed multi-document YAML files instead of aborting a complete project reingest at the second document marker.

### Verification
- Added a regression test that reconfigures a `cp1252` text stream and writes Unicode MCP JSON successfully.
- Added a structured-document import test for multi-document YAML boundaries and payload preservation.
