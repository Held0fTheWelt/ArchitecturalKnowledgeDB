# Troubleshooting

## `akdb` Is Not Found

Install the package from the repository root:

```powershell
python -m pip install -e ".[test]"
```

Then reopen the terminal or call the module directly:

```powershell
python -m architectural_knowledge_db.cli --help
```

## The Service Does Not Open

Check whether port `8787` is already in use:

```powershell
Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue
```

Run on another port if needed:

```powershell
akdb serve --host 127.0.0.1 --port 8788
```

## Search Returns No Results

Check:

- the project exists: `akdb project list`
- the expected docs were imported
- the query is not too narrow
- the command uses the same database as the import command

For a starter project, rerun:

```powershell
akdb adr import --project my-project --folder docs/architecture/adr
akdb document import --project my-project --folder docs/architecture --exclude "adr/**"
akdb uml import --project my-project --folder docs/architecture/uml
```

## Git Scan Finds Nothing

Check:

- `git` is available on PATH
- the repository was registered with the right path
- `include_patterns` and `exclude_patterns` are not filtering everything
- portable `/sources/...` paths resolve through `AKDB_SOURCE_ROOT`

## Database Is Locked Or Copy Fails

SQLite allows one writer. Use the AKDB CLI, API, or MCP authoring operations against the live
database; do not replace the whole database from a generated import snapshot. Stop `akdb serve` and
close MCP clients only when taking or restoring an operator-controlled backup, then restart clients
so they reopen the database.

## MCP Tools Do Not Appear

Check:

- the MCP client config points to `akdb-mcp` or `python -m architectural_knowledge_db.mcp_stdio`
- `AKDB_DATABASE_PATH` points to an existing SQLite DB
- `AKDB_DEFAULT_PROJECT` is set if you want to omit `project_id`
- the MCP client was restarted after config changes

## MCP Output Is Too Small

Bulk tools use compact output by default. Pass `"detail": "full"` where supported, or use targeted read tools such as `akdb_get_adr` and `akdb_get_diagram`.

## External Repository Content Appears Under `exports/`

Generated exports are ignored, but they still clutter the working tree and can confuse readers. Move or delete external project exports after use. Do not commit them to AKDB.

## Tiny Tools SAD Or UML Is Missing From AKDB

That is expected. AKDB can index those records at runtime, but the authoritative Tiny Tools SAD/UML files live in the public showcase/Git repository, not inside AKDB.
