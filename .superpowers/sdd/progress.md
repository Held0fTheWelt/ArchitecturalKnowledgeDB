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

## Local merge to `main` (Step 2 of the runway ORDER)

Merged `feat/auto-export` → `main` locally at `4aa5be6` (fast-forward not used; `--no-ff`
merge commit, no push). Full suite re-verified green on `main`: 202 passed, 146 skipped.

**Real gap found+fixed:** the runway prompt assumed "editable install already does" reflect
merged code via the `akdb` console-script. In fact `architectural-knowledge-db` was **not
installed at all** in this machine's Python (`pip show` found nothing, `akdb` was not on
PATH — CLI tests only ever exercised the code via `python -m architectural_knowledge_db.cli`
/ direct module import, never the installed script). Ran `pip install -e .` from the AKDB
repo root; `akdb export --help` now lists `target-add`/`target-list`/`flush`/`sync`/
`target-verify` on PATH, which Plan B's freshness gate needs (it shells out to `akdb`, never
imports AKDB internals).

## Real bug found+fixed during Plan B (post-merge, direct `main` commit `80475d6`)

Registering `ttd-canon` via `akdb export target-add --dest docs/architecture/_generated`
from Windows stored `dest_root` as `docs\architecture\_generated` (typer's `Path` renders
with the OS separator). Plan B Task 7.3's CI job runs on `ubuntu-latest`, where `Path(...)`
does NOT treat `\` as a separator -- `_mirror_path`/`export_incremental`/`verify_export`
would have silently treated the whole string as one path segment there, breaking the
freshness gate in CI while working fine locally. Fixed with a TDD regression test:
`ExportTargetsService.register_target` now normalizes `dest_root` to POSIX (`/`) on write
(`_normalize_dest_root`), so DB rows are portable regardless of which OS registered them.
Full suite re-verified green (203 passed, 147 skipped) before committing.

## BLOCKED: `akdb-self` export target — do NOT sync (destructive, disabled defensively)

Plan B Task 6.1 step 2 registers a second target, `akdb-self`, project
`architectural-knowledge-db`, `dest_root=docs/architecture` (the AKDB tool repo's OWN
self-authored architecture docs, per `config.py::self_export_target()`).

**Investigated before syncing (per "STOP, do not guess past it") and found a real, would-be-
destructive mismatch:** all 313 existing `architectural-knowledge-db`-project knowledge items
(verified via direct read-only query against `.akdb/architectural_knowledge_db.sqlite`) have
`metadata.repo_source_key = NULL` and `metadata.body_text = NULL` — EXCEPT one
`product_fact_sheet`. These items were created by the OLDER self-ingest path documented in
`docs/superpowers/evidence/2026-07-23-akdb-self-ingest.md` (`document import` / SAD
decomposition against `Git/docs/architecture/plugins/ArchitecturalKnowledgeDB`), which
predates this runway and never populates `repo_source_key`/`body_text` — only the NEW generic
`import_documents`/`import_adrs` paths (Plan A) do that.

Consequence: `_expected_mirror_files("architectural-knowledge-db", dest_root)` (used by BOTH
`verify_export` and `export_sync`) would compute an **empty** expected set for this project
(no item has `body_text`). `export_sync` would then treat every real file currently under
`ArchitecturalKnowledgeDB/docs/architecture/**` (the hand-authored `architecture.md`,
`dual-backend.md`, the whole `subsystems/**` and `UML/**` trees — this repo's own real,
committed architecture documentation) as "extra" and **delete all of it**. `verify_export`
would likewise report 100% of those files as spurious "extra" (harmless to run, but
misleading/useless as a check here).

**Action taken:** registered the target (harmless, a DB row) then immediately
`set_enabled(..., False)` so no accidental future `export sync`/`export verify` call touches
it, and so the (inert, since no item there carries `repo_source_key`) auto-flush hook can
never activate for it either. **Did NOT run `export_sync`/`export_incremental`/`verify_export`
against `akdb-self`** — no data was touched or lost.

**Not fixed here** (out of scope for Plan A/B/C's task list, and NOT a "guess past it" fix
appropriate to make silently on a live production DB): making AKDB's own self-docs flow
through the new generic byte-exact path would mean re-ingesting
`ArchitecturalKnowledgeDB/docs/architecture/**` via `import_documents`/`import_adrs` (so items
gain `repo_source_key`/`body_text`), which changes item identity/shape for 313 existing items
and needs its own reviewed plan + human go-ahead, not a side-effect of this runway.

**Open question forwarded to the human** (also in the final report): should a follow-up task
re-ingest AKDB's own self-docs through the generic export path so `akdb-self` becomes usable,
or should self-hosting stay on the old SAD-decomposition path indefinitely (in which case
`akdb-self` should probably be deleted/never enabled rather than left dormant)?

Plan B/C below proceed with `ttd-canon` only, which IS on the correct byte-exact path (all
its items — SAD/UML/ADR imported via `import_documents`/`import_adrs` — DO carry
`repo_source_key` + `body_text`, confirmed above for the 10 real ADRs and consistent with how
Phase 4 of the canon migration ingested `docs/architecture` + `UML` into `tiny-tool-
development`).

Next: hand off to Plan B on the TTD side (`chore/auto-export-mirror` off `5.4`).
