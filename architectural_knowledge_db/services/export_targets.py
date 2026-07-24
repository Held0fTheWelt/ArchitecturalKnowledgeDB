from __future__ import annotations

import os
import sqlite3
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from architectural_knowledge_db.services.jsonutil import dumps, loads
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import (
    detect_remote_url,
    resolve_local_path_alias,
    sanitize_remote_url,
)


class ExportTargetsService:
    """Registry of export targets + a batched dirty-tracking queue.

    An export target says "for project P, export content kinds K in layout L
    to <repository dest_root>." The dirty queue is a speed optimization for
    incremental export -- correctness always rests on `verify_export`'s full
    byte compare (see the import_export module).
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)

    def register_target(
        self,
        project_id: str,
        target_id: str,
        *,
        repository_id: str,
        dest_root: str,
        layout: str,
        content_kinds: list[str],
        auto_export: bool = True,
        enabled: bool = True,
    ) -> None:
        self.projects.require_project(project_id)
        self.conn.execute(
            """
            INSERT INTO export_targets(
              project_id, target_id, repository_id, dest_root, layout,
              content_kinds, auto_export, enabled, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(project_id, target_id) DO UPDATE SET
              repository_id = excluded.repository_id,
              dest_root = excluded.dest_root,
              layout = excluded.layout,
              content_kinds = excluded.content_kinds,
              auto_export = excluded.auto_export,
              enabled = excluded.enabled,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                project_id,
                target_id,
                repository_id,
                _normalize_dest_root(dest_root),
                layout,
                dumps(content_kinds),
                _bool_param(self.conn, auto_export),
                _bool_param(self.conn, enabled),
            ),
        )

    def get_target(self, project_id: str, target_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT * FROM export_targets WHERE project_id = ? AND target_id = ?
            """,
            (project_id, target_id),
        ).fetchone()
        if row is None:
            return None
        return _hydrate_target(row)

    def list_targets(self, project_id: str, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM export_targets WHERE project_id = ?"
        params: list[Any] = [project_id]
        if enabled_only:
            sql += " AND enabled = ?"
            params.append(_bool_param(self.conn, True))
        sql += " ORDER BY target_id"
        rows = self.conn.execute(sql, params).fetchall()
        return [_hydrate_target(row) for row in rows]

    def resolve_dest_root(self, project_id: str, target_id: str) -> Path:
        target = self.get_target(project_id, target_id)
        if target is None:
            raise ValueError(f"Unknown export target {target_id} in project {project_id}")
        configured = Path(target["dest_root"])
        if configured.is_absolute():
            return configured

        repository = self.conn.execute(
            """
            SELECT local_path, remote_url_sanitized
            FROM repositories
            WHERE project_id = ? AND repository_id = ?
            """,
            (project_id, target["repository_id"]),
        ).fetchone()
        if repository is None:
            raise ValueError(
                f"Relative export target {target_id} requires registered repository "
                f"{target['repository_id']} in project {project_id}"
            )

        registered_root = Path(resolve_local_path_alias(repository["local_path"]))
        if registered_root.is_dir():
            return registered_root / configured

        source_root = os.getenv("AKDB_SOURCE_ROOT")
        if source_root:
            source_candidate = Path(source_root) / target["repository_id"]
            if _matches_registered_repository(source_candidate, repository):
                return source_candidate / configured

        # CI restores a portable DB snapshot whose registered workstation path
        # does not exist. Accept its checkout root only when the Git remote proves
        # that it is the repository named by the export target.
        cwd_candidate = Path.cwd()
        if _matches_registered_repository(cwd_candidate, repository):
            return cwd_candidate / configured
        raise ValueError(
            f"Cannot resolve repository {target['repository_id']} for relative export "
            f"target {target_id}; registered path does not exist and the current "
            "checkout does not match its remote"
        )

    def set_enabled(self, project_id: str, target_id: str, enabled: bool) -> None:
        self.conn.execute(
            """
            UPDATE export_targets SET enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE project_id = ? AND target_id = ?
            """,
            (_bool_param(self.conn, enabled), project_id, target_id),
        )

    def delete_target(self, project_id: str, target_id: str) -> dict[str, Any]:
        target = self.get_target(project_id, target_id)
        if target is None:
            raise ValueError(
                f"Unknown export target {target_id} in project {project_id}"
            )
        self.conn.execute(
            """
            DELETE FROM export_dirty
            WHERE project_id = ? AND target_id = ?
            """,
            (project_id, target_id),
        )
        self.conn.execute(
            """
            DELETE FROM export_targets
            WHERE project_id = ? AND target_id = ?
            """,
            (project_id, target_id),
        )
        return {
            "project_id": project_id,
            "target_id": target_id,
            "deleted": True,
        }

    # -- dirty tracking -----------------------------------------------------

    def mark_dirty(
        self,
        project_id: str,
        item_kind: str,
        item_ref: str,
        op: str = "upsert",
        target_id: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO export_dirty(project_id, target_id, item_kind, item_ref, op)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, target_id, item_kind, item_ref, op),
        )

    def drain_dirty(self, project_id: str, target_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM export_dirty
            WHERE project_id = ? AND (target_id = ? OR target_id IS NULL)
            ORDER BY id
            """,
            (project_id, target_id),
        ).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            self.conn.execute(
                f"DELETE FROM export_dirty WHERE id IN ({placeholders})",
                ids,
            )
        return [dict(row) for row in rows]

    def peek_dirty(self, project_id: str, target_id: str | None = None) -> list[dict[str, Any]]:
        if target_id is None:
            rows = self.conn.execute(
                "SELECT * FROM export_dirty WHERE project_id = ? ORDER BY id",
                (project_id,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM export_dirty
                WHERE project_id = ? AND (target_id = ? OR target_id IS NULL)
                ORDER BY id
                """,
                (project_id, target_id),
            ).fetchall()
        return [dict(row) for row in rows]


def _normalize_dest_root(dest_root: str) -> str:
    # Registration can happen on Windows (typer.Path str() renders "\\"), while the
    # freshness gate / CI may later run `Path(dest_root) / ...` on Linux, where "\\"
    # is not a path separator. Store POSIX-style so it resolves on either OS.
    normalized = str(dest_root).strip().replace("\\", "/")
    if not normalized:
        raise ValueError("Export destination must not be empty.")
    if any(part in {".", ".."} for part in normalized.split("/")):
        raise ValueError("Export destination must not contain current or parent path segments.")

    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(normalized)
    if (posix_path.is_absolute() and len(posix_path.parts) == 1) or (
        windows_path.is_absolute() and len(windows_path.parts) == 1
    ):
        raise ValueError("Export destination must not be a filesystem root.")
    return posix_path.as_posix()


def _matches_registered_repository(candidate: Path, repository: Any) -> bool:
    if not candidate.is_dir():
        return False
    expected_remote = repository["remote_url_sanitized"]
    if not expected_remote:
        return False
    actual_remote = detect_remote_url(str(candidate))
    if not actual_remote:
        return False
    return sanitize_remote_url(actual_remote).casefold() == str(expected_remote).casefold()


def _bool_param(conn: Any, value: bool) -> Any:
    if getattr(conn, "is_postgres", False):
        return bool(value)
    return 1 if value else 0


def _hydrate_target(row: Any) -> dict[str, Any]:
    result = dict(row)
    raw_kinds = result["content_kinds"]
    result["content_kinds"] = raw_kinds if isinstance(raw_kinds, list) else loads(raw_kinds, [])
    result["auto_export"] = bool(result["auto_export"])
    result["enabled"] = bool(result["enabled"])
    return result
