from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator

from architectural_knowledge_db.services.export_targets import ExportTargetsService

# Batches auto-flush across a bulk operation (e.g. import_documents looping over
# hundreds of files) so a single transaction-scoped operation performs ONE
# incremental export pass per touched target instead of one per mutated item
# (spec section 6, "batched, not per-row"). A depth counter supports nesting;
# only the outermost deferred_export() block owns the pending-target set and
# performs the flush on exit.
_DEFERRED_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "akdb_export_deferred_depth", default=0
)
_PENDING_TARGETS: contextvars.ContextVar[set[tuple[str, str]] | None] = contextvars.ContextVar(
    "akdb_export_pending_targets", default=None
)


def is_deferred() -> bool:
    return _DEFERRED_DEPTH.get() > 0


@contextmanager
def deferred_export(conn: Any) -> Iterator[None]:
    """Coalesce auto-flush to a single pass per touched target on block exit."""
    depth = _DEFERRED_DEPTH.get()
    depth_token = _DEFERRED_DEPTH.set(depth + 1)
    pending_token = None
    if depth == 0:
        pending_token = _PENDING_TARGETS.set(set())
    try:
        yield
    finally:
        _DEFERRED_DEPTH.reset(depth_token)
        if depth == 0:
            pending = _PENDING_TARGETS.get() or set()
            assert pending_token is not None
            _PENDING_TARGETS.reset(pending_token)
            _flush_pending(conn, pending)


def notify_item_write(
    conn: Any,
    project_id: str,
    item_kind: str,
    metadata: dict[str, Any] | None,
    op: str = "upsert",
) -> None:
    """Single write-choke-point hook: mark dirty + auto-flush enabled targets.

    Called from KnowledgeService._upsert_item() (the real single write choke
    point for every exportable item in this codebase -- see
    .superpowers/sdd/progress.md "Adaptation note" for why this replaces the
    spec's hypothetical AkdbApp facade hook).
    """
    repo_source_key = (metadata or {}).get("repo_source_key")
    if not repo_source_key:
        return
    targets_service = ExportTargetsService(conn)
    targets_service.mark_dirty(project_id, item_kind, repo_source_key, op, target_id=None)
    enabled_targets = [
        t for t in targets_service.list_targets(project_id, enabled_only=True) if t["auto_export"]
    ]
    if not enabled_targets:
        return
    if is_deferred():
        pending = _PENDING_TARGETS.get()
        if pending is not None:
            for target in enabled_targets:
                pending.add((project_id, target["target_id"]))
        return
    _flush_pending(conn, {(project_id, target["target_id"]) for target in enabled_targets})


def _flush_pending(conn: Any, pending: set[tuple[str, str]]) -> None:
    if not pending:
        return
    register = getattr(conn, "add_transaction_callback", None)
    if callable(register):
        state = getattr(conn, "_akdb_pending_export_targets", None)
        if state is None:
            state = set()
            setattr(conn, "_akdb_pending_export_targets", state)

            def after_commit() -> None:
                queued = set(state)
                state.clear()
                _flush_pending_now(conn, queued)

            def after_rollback() -> None:
                state.clear()

            register(
                "akdb-export-target-flush",
                after_commit=after_commit,
                after_rollback=after_rollback,
            )
        state.update(pending)
        return
    _flush_pending_now(conn, pending)


def _flush_pending_now(conn: Any, pending: set[tuple[str, str]]) -> None:
    if not pending:
        return
    from architectural_knowledge_db.services.import_export import ImportExportService

    ies = ImportExportService(conn)
    for project_id, target_id in pending:
        ies.export_incremental(project_id, target_id)
