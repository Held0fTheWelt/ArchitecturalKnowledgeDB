# AKDB MCP Access

The `akdb-mcp` console script is a spec-compliant stdio MCP server over the AKDB knowledge database. It works with any MCP client. Register it once per client. All configuration is via environment variables; nothing client-specific is hard-coded.

The server explicitly configures stdin/stdout as UTF-8 before the JSON-RPC loop. This is required on
Windows, where inherited console encodings such as `cp1252` cannot represent every Unicode character
that may occur in tool descriptions or architecture content.

## Environment Variables

| Variable | Purpose | Windows example | WSL example |
| --- | --- | --- | --- |
| `AKDB_DATABASE_PATH` | SQLite file to serve | `D:\TinyToolDevelopment\ArchitecturalKnowledgeDB\.akdb\architectural_knowledge_db.sqlite` | `/mnt/d/TinyToolDevelopment/ArchitecturalKnowledgeDB/.akdb/architectural_knowledge_db.sqlite` |
| `AKDB_SOURCE_ROOT` | Resolves `/sources/...` registry paths | `D:\TinyToolDevelopment` | `/mnt/d/TinyToolDevelopment` |
| `AKDB_DEFAULT_PROJECT` | Project used when a tool call omits `project_id` | `tiny-tool-development` | `tiny-tool-development` |

## Claude Code (WSL) - project `.mcp.json`

```json
{
  "mcpServers": {
    "akdb": {
      "command": "/usr/bin/python3",
      "args": ["-m", "architectural_knowledge_db.mcp_stdio"],
      "env": {
        "PYTHONPATH": "/mnt/d/TinyToolDevelopment/ArchitecturalKnowledgeDB",
        "AKDB_DATABASE_PATH": "/mnt/d/TinyToolDevelopment/ArchitecturalKnowledgeDB/.akdb/architectural_knowledge_db.sqlite",
        "AKDB_SOURCE_ROOT": "/mnt/d/TinyToolDevelopment",
        "AKDB_DEFAULT_PROJECT": "tiny-tool-development"
      }
    }
  }
}
```

## Cursor (Windows) - `.cursor/mcp.json` (project or global)

```json
{
  "mcpServers": {
    "akdb": {
      "command": "akdb-mcp",
      "env": {
        "AKDB_DATABASE_PATH": "D:\\TinyToolDevelopment\\Tools\\ArchitecturalKnowledgeDB\\.akdb\\architectural_knowledge_db.sqlite",
        "AKDB_SOURCE_ROOT": "D:\\TinyToolDevelopment",
        "AKDB_DEFAULT_PROJECT": "tiny-tool-development"
      }
    }
  }
}
```

If `akdb-mcp` is not on PATH, use the full interpreter form:

```json
{
  "command": "C:\\Users\\YvesT\\AppData\\Local\\Programs\\Python\\Python314\\python.exe",
  "args": ["-m", "architectural_knowledge_db.mcp_stdio"]
}
```

Set `PYTHONPATH` in `env` when the package is not installed in that interpreter.

## Codex (Windows) - `~/.codex/config.toml`

```toml
[mcp_servers.akdb]
command = "akdb-mcp"

[mcp_servers.akdb.env]
AKDB_DATABASE_PATH = "D:\\TinyToolDevelopment\\Tools\\ArchitecturalKnowledgeDB\\.akdb\\architectural_knowledge_db.sqlite"
AKDB_SOURCE_ROOT = "D:\\TinyToolDevelopment"
AKDB_DEFAULT_PROJECT = "tiny-tool-development"
```

## Generic / Claude Desktop

Use the same `mcpServers` JSON block as Cursor, in that client's config location.

## Tools

`tools/list` advertises every tool from the AKDB MCP manifest, for example `architectural_knowledge_db_search`, `architectural_knowledge_db_get_context_pack`, `architectural_knowledge_db_run_drift_check`, `akdb_list_adrs`, `akdb_list_diagrams`, `akdb_check_consistency`, and `akdb_impact_of`. When `AKDB_DEFAULT_PROJECT` is set, `project_id` may be omitted from arguments.

**Compact output (default).** Bulk/list/search tools (`architectural_knowledge_db_search`, `get_context_pack`, `get_staleness_report`, `find_status_quo_drifts`, `run_drift_check`, `akdb_list_adrs`, `akdb_list_diagrams`) strip large `raw_source`, `sections`, and prose blobs by default so a single call fits an agent's token budget. Pass `"detail": "full"` for complete records, or use targeted tools such as `akdb_get_adr` and `akdb_get_diagram` to read one item in full.

**Refresh the DB yourself.** `akdb_reingest_project` rebuilds a project's knowledge from its source folders, then rescans Git provenance. It defaults to the standard layout under `AKDB_SOURCE_ROOT`. It writes to the database, so run it against a DB the agent owns, or stop the `:8787` service first. SQLite has one writer; a shared DB held by the service cannot be overwritten safely.

**Conflict-aware planning.** `architectural_knowledge_db_validate_task_context` returns `review` for an explicit forbidden-change hit, `review_advised` with relevant ADRs/guardrails when a normative decision governs the task, or `no_known_conflict` otherwise.

**After registering, restart the client.** MCP servers are loaded at client startup.

## Workspace Boundary

AKDB MCP can read imported knowledge about external repositories, but this repository must not keep copied SAD/UML exports or public showcase files as committed docs. In the Tiny Tool workspace, public showcase/user scripts live in `D:\TinyToolDevelopment\Git\Tools`, with user scripts under `D:\TinyToolDevelopment\Git\Tools\User`.
