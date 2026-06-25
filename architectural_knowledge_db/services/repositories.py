from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from architectural_knowledge_db.models import RepositoryRegistration
from architectural_knowledge_db.services.jsonutil import loads
from architectural_knowledge_db.services.projects import ProjectService


class RepositoryService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)

    def register_repository(self, project_id: str, request: RepositoryRegistration) -> dict[str, Any]:
        self.projects.require_project(project_id)
        local_path = resolve_local_path_alias(request.local_path)
        remote_url = request.remote_url_sanitized or detect_remote_url(local_path)
        sanitized_remote = sanitize_remote_url(remote_url) if remote_url else None
        self.conn.execute(
            """
            INSERT INTO repositories(
              repository_id, project_id, local_path, remote_url_sanitized, default_branch,
              scan_policy, include_patterns_json, exclude_patterns_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repository_id) DO UPDATE SET
              project_id = excluded.project_id,
              local_path = excluded.local_path,
              remote_url_sanitized = excluded.remote_url_sanitized,
              default_branch = excluded.default_branch,
              scan_policy = excluded.scan_policy,
              include_patterns_json = excluded.include_patterns_json,
              exclude_patterns_json = excluded.exclude_patterns_json
            """,
            (
                request.repository_id,
                project_id,
                local_path,
                sanitized_remote,
                request.default_branch,
                request.scan_policy,
                json.dumps(request.include_patterns),
                json.dumps(request.exclude_patterns),
            ),
        )
        return self.get_repository(project_id, request.repository_id)

    def list_repositories(self, project_id: str) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        rows = self.conn.execute(
            """
            SELECT *
            FROM repositories
            WHERE project_id = ?
            ORDER BY repository_id
            """,
            (project_id,),
        ).fetchall()
        return [hydrate_repository(row) for row in rows]

    def get_repository(self, project_id: str, repository_id: str) -> dict[str, Any]:
        self.projects.require_project(project_id)
        row = self.conn.execute(
            """
            SELECT *
            FROM repositories
            WHERE project_id = ? AND repository_id = ?
            """,
            (project_id, repository_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown repository {repository_id} in project {project_id}")
        return hydrate_repository(row)

    def mark_scan_status(self, repository_id: str, status: str) -> None:
        self.conn.execute(
            """
            UPDATE repositories
            SET last_scanned_at = CURRENT_TIMESTAMP,
                last_scan_status = ?
            WHERE repository_id = ?
            """,
            (status, repository_id),
        )


def hydrate_repository(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["include_patterns"] = loads(result.pop("include_patterns_json"), [])
    result["exclude_patterns"] = loads(result.pop("exclude_patterns_json"), [])
    return result


def detect_remote_url(local_path: str) -> str | None:
    path = Path(local_path)
    if not path.exists():
        return None
    try:
        completed = subprocess.run(
            ["git", "-C", str(path), "config", "--get", "remote.origin.url"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def resolve_local_path_alias(local_path: str) -> str:
    expanded = Path(local_path).expanduser()
    if expanded.exists():
        return str(expanded)

    normalized = local_path.replace("\\", "/")
    if not normalized.startswith("/sources/"):
        return str(expanded)

    suffix = normalized.removeprefix("/sources/").strip("/")
    candidates = []
    source_root = os.getenv("AKDB_SOURCE_ROOT")
    if source_root:
        candidates.append(Path(source_root) / suffix)
    cwd = Path.cwd().resolve()
    for base in [cwd, *cwd.parents]:
        candidates.append(base / suffix)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(expanded)


def sanitize_remote_url(remote_url: str) -> str:
    remote_url = remote_url.strip()
    if "://" not in remote_url:
        return remote_url
    parsed = urlsplit(remote_url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, ""))
