# AKDB Auto-Export — AKDB-side SDD progress ledger

Branch: `feat/auto-export` (off `main`, base `a3bee24`). No merge to `main` without the
hard-gate step in the runway prompt (local-only merge permitted after Plan A Done-check,
per the executor's ORDER step 2 — still never pushed).
Backend: SQLite default; postgres parametrized via `AKDB_TEST_DB_URL` (unset on this
machine — postgres half skips, per plan).

Spec: `Git/docs/superpowers/specs/2026-07-23-akdb-auto-export-mirror-design.md`
Plan A: `Git/docs/superpowers/plans/2026-07-23-akdb-auto-export-phase-A-akdb-capability.md`

## Adaptation note (read before continuing — affects Task 2.2 and any facade references)

Plan A Task 2.2 (and the spec §4.1 write-path hook) assume an `AkdbApp` facade class in
`architectural_knowledge_db/api/app.py` with methods `upsert_sad`/`upsert_adr`/`upsert_link`/
`deferred_export()` that CLI + MCP + HTTP funnel through. **This class does not exist in this
codebase.** `api/app.py` only contains FastAPI route *functions* (not a callable facade) that
each construct a service (`SadService`, `KnowledgeService`, ...) directly from a raw `conn` —
the CLI (`cli.py`) and MCP dispatcher do the same, independently, each via their own `_conn()`
helper. There is no intermediate object to hook.

The REAL single write choke point (verified by code inspection) is
`KnowledgeService._upsert_item()` (`services/knowledge.py:435`) — every exportable item write
(import_documents, import_adrs → upsert_adr, SadService.upsert_document/section/decision, ...)
funnels through this one method to write the `knowledge_items` row. This is a *stronger*
choke point than the hypothetical `AkdbApp` (it's one level lower, below any facade).

Implemented accordingly:
- Dirty-marking + auto-flush hook lives in `services/export_flush.py`, called from
  `KnowledgeService._upsert_item()` (upsert) — keyed off `metadata["repo_source_key"]`.
- `deferred_export(conn)` is a module-level contextvar-based context manager (not a method
  on a nonexistent app object); `import_documents()`/`import_adrs()` wrap their per-file loop
  in it so a bulk import flushes once, matching the spec's batching requirement.
- Task 2.2's test file exercises the REAL entry points (`ImportExportService.import_documents`
  for the bulk case, `KnowledgeService.upsert_adr` for the single-mutation case) instead of a
  fictional `AkdbApp.upsert_sad(...)` call — same behavioral assertions as the plan intended.

## Real bug found (Phase 4 prerequisite, discovered while auditing the choke point)

`import_adrs()` / `KnowledgeService.upsert_adr()` never put the ADR's verbatim source text
into `metadata["body_text"]` — only into the separate `adrs.raw_source` DB column, which
`list_items()`/`export_canon()` never join. This means **ADRs were silently invisible to
`export_canon()`/`verify_canon()` all along** (not just to the new mirror) — anticipated by
Plan A Task 4.1 ("if `upsert_adr` decomposes ADRs into structured fields, ALSO retain the raw
bytes"). Fixed in Task 4.1: `import_adrs()` now also sets `metadata["body_text"]` +
`metadata["body_encoding"]` so ADRs flow through the same generic byte-exact path as SAD/docs.

## Progress
(updated per task as work proceeds)

- Phase 1 (schema 009 + `ExportTargetsService`): DONE.
- Phase 2 (`_mirror_path`/`export_incremental` + batched dirty-hook via `export_flush.py`): DONE.
- Phase 3 (`verify_export` + `export_sync`): DONE.
- Phase 4 (ADR verbatim ingest + ADR-in-mirror): DONE (bug fix above).
- Phase 5 (CLI `akdb export target-add/target-list/flush/sync/target-verify`; MCP
  `akdb_export_flush`/`akdb_verify_export`/`akdb_export_sync`; `auto_export` flag honored;
  full suite green): DONE.

**Plan A Done-check: GREEN.** `pytest -q` → 202 passed, 146 skipped (postgres half skips,
`AKDB_TEST_DB_URL` unset on this machine — expected per plan). No xfails, no errors.

CLI naming note: the plan's `akdb export verify` collides with an existing unrelated `export
verify` command in this codebase, so the new target-based commands are named `export
target-add`, `export target-list`, `export target-verify` (flush/sync are unambiguous, kept
as-is: `export flush`, `export sync`).

Next: merge `feat/auto-export` → `main` LOCALLY (no push), reinstall editable CLI if entry
points changed, then hand off to Plan B on the TTD side.
