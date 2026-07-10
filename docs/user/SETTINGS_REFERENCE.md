# Settings Reference

AKDB is configured with CLI options and environment variables. Defaults are local-first and write into ignored runtime folders.

## CLI Options

Global database override:

```powershell
akdb --db .akdb\architectural_knowledge_db.sqlite search --project my-project "query"
```

Service binding:

```powershell
akdb serve --host 127.0.0.1 --port 8787
```

## Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AKDB_DATA_ROOT` | `.akdb` | Runtime data directory used when `AKDB_DATABASE_PATH` is not set. |
| `AKDB_DATABASE_PATH` | `.akdb\architectural_knowledge_db.sqlite` | SQLite database file. |
| `AKDB_HOST` | `127.0.0.1` | Default service host for environment-based settings. |
| `AKDB_PORT` | `8787` | Default service port for environment-based settings. |
| `AKDB_SOURCE_ROOT` | unset | Resolves portable `/sources/...` registry paths. |
| `AKDB_DEFAULT_PROJECT` | unset | MCP default project when a tool call omits `project_id`. |
| `AKDB_AUTO_EXPORT` | workspace default | Set to `0`, `false`, `no`, or `off` to disable automatic corpus export after imports. Set to truthy without a root to use `<AKDB_DATA_ROOT>\exports`. |
| `AKDB_AUTO_EXPORT_ROOT` | Tiny Tool live DB: `D:\TinyToolDevelopment\AKDB\export` | Export folder for the automatic full corpus mirror after imports. |
| `AKDB_EXPORT_ROOT` | unset | Backward-compatible alias for `AKDB_AUTO_EXPORT_ROOT`. |
| `AKDB_STORE_AUTHOR_EMAIL_HASH` | false | Enables storage of hashed author email metadata during Git provenance scans. |
| `AKDB_INCLUDE_COMMIT_BODY` | false | Includes commit body text in stored Git provenance metadata. |
| `AKDB_RECALL_BACKEND` | unset | Optional semantic recall backend mode. FTS remains available when unset. |
| `AKDB_EMBED_URL` | unset | Optional embedding endpoint for semantic recall. |
| `AKDB_EMBED_MODEL` | `default` | Optional embedding model name when `AKDB_EMBED_URL` is used. |

## Project Registry Fields

Project registries can be imported with:

```powershell
akdb project import-registry docs/examples/architectural-knowledge-db.projects.yaml
```

Common fields:

| Field | Purpose |
| --- | --- |
| `shared_spaces` | Named shared knowledge spaces available to projects that import them. |
| `projects` | Project records with display names, descriptions, imports, repositories, and source folders. |
| `repositories` | Per-project repository registrations for read-only Git provenance. |
| `include_patterns` | Optional path globs included in provenance scans. |
| `exclude_patterns` | Optional path globs excluded from provenance scans. |

Portable paths under `/sources/...` are resolved with `AKDB_SOURCE_ROOT` when possible. If the target cannot be resolved, AKDB preserves the configured path instead of guessing.

## Runtime Folders

| Folder | Commit? | Purpose |
| --- | --- | --- |
| `.akdb/` | No | Local SQLite DB, backups, server logs. |
| `Temp/` | No | Temporary databases and local experiments. |
| `exports/` | No | Generated exports. Keep external project exports out of Git. |
| `docs/` | Yes | AKDB documentation and AKDB-owned specs only. |

## Tiny Tool Workspace Note

Within the local Tiny Tool workspace, public showcase/user scripts are maintained outside AKDB in `D:\TinyToolDevelopment\Git\Tools`. AKDB docs may point there, but must not copy those files into this repository.
