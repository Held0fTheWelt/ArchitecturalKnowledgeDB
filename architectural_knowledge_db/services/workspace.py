"""Workspace / multi-repo cross-reference resolution (autark AKDB capability).

Extends the existing `repositories` table with a per-repository path inventory
(`repository_files`) so `resolve_reference()` can answer any `<repo>/<path>#<anchor>`
reference from the database alone — the target repository need not be checked out.
Generic, reusable by any multi-git project (design spec §3.1).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from architectural_knowledge_db.services.markdown_anchors import heading_slugs
from architectural_knowledge_db.services.repositories import RepositoryService, resolve_local_path_alias


class WorkspaceService:
    def __init__(self, conn: Any):
        self.conn = conn
        self.repositories = RepositoryService(conn)

    def scan_inventory(self, project_id: str, repository_id: str) -> dict[str, Any]:
        repo = self.repositories.get_repository(project_id, repository_id)
        local_path = resolve_local_path_alias(repo["local_path"])
        files = _list_repo_files(local_path)
        head_sha = _git_head(local_path)
        self.conn.execute("DELETE FROM repository_files WHERE repository_id = ?", (repository_id,))
        for path in files:
            anchors: list[str] = []
            if path.lower().endswith((".md", ".markdown")):
                try:
                    text = (Path(local_path) / path).read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    text = ""
                anchors = sorted(heading_slugs(text))
            self.conn.execute(
                "INSERT INTO repository_files (repository_id, path, anchors_json) VALUES (?, ?, ?)",
                (repository_id, path, json.dumps(anchors)),
            )
        self.conn.execute(
            "DELETE FROM repository_inventory_meta WHERE repository_id = ?", (repository_id,)
        )
        self.conn.execute(
            "INSERT INTO repository_inventory_meta (repository_id, head_sha, scanned_at) VALUES (?, ?, ?)",
            (repository_id, head_sha, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()
        return {"repository_id": repository_id, "files": len(files), "head_sha": head_sha}

    def resolve_reference(
        self, project_id: str, ref: str, *, aliases: dict[str, str] | None = None
    ) -> dict[str, Any]:
        aliases = aliases or {}
        raw = ref.strip()
        target = raw.split("#", 1)[0].replace("\\", "/").strip()
        anchor = raw.split("#", 1)[1].strip() if "#" in raw else None
        if "/" not in target:
            return {"resolved": False, "repository_id": None, "path": None, "reason": "not_cross_repo"}
        head, path = target.split("/", 1)
        repository_id = aliases.get(head, head)
        known = self.conn.execute(
            "SELECT 1 FROM repository_files WHERE repository_id = ? LIMIT 1", (repository_id,)
        ).fetchone()
        if known is None:
            return {"resolved": False, "repository_id": repository_id, "path": path,
                    "reason": "repository_not_registered"}
        row = self.conn.execute(
            "SELECT anchors_json FROM repository_files WHERE repository_id = ? AND path = ?",
            (repository_id, path),
        ).fetchone()
        if row is None:
            return {"resolved": False, "repository_id": repository_id, "path": path,
                    "reason": "path_not_in_inventory"}
        if anchor and path.lower().endswith((".md", ".markdown")):
            slugs = set(json.loads(row["anchors_json"] or "[]"))
            if anchor.lower() not in slugs:
                return {"resolved": False, "repository_id": repository_id, "path": path,
                        "reason": "anchor_not_found"}
        return {"resolved": True, "repository_id": repository_id, "path": path, "reason": "ok"}

    def export_manifest(self, project_id: str, folder: str | Path) -> str:
        repos: dict[str, Any] = {}
        rows = self.conn.execute(
            "SELECT repository_id, path, anchors_json FROM repository_files ORDER BY repository_id, path"
        ).fetchall()
        for row in rows:
            entry = repos.setdefault(row["repository_id"], {"files": [], "anchors": {}})
            entry["files"].append(row["path"])
            anchors = json.loads(row["anchors_json"] or "[]")
            if anchors:
                entry["anchors"][row["path"]] = anchors
        for repo_id, entry in repos.items():
            meta = self.conn.execute(
                "SELECT head_sha FROM repository_inventory_meta WHERE repository_id = ?", (repo_id,)
            ).fetchone()
            scanned_sha = meta["head_sha"] if meta else None
            try:
                repository = self.repositories.get_repository(project_id, repo_id)
            except ValueError:
                live_sha = None
            else:
                live_sha = _git_head(
                    resolve_local_path_alias(repository["local_path"])
                )
            entry["sha"] = live_sha or scanned_sha
        manifest = {"format_version": 1, "project_id": project_id, "repositories": repos}
        target = Path(folder)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8", newline="\n",
        )
        return str(target)


def _list_repo_files(path: str) -> list[str]:
    """Inventory a workspace repository's files: prefer `git ls-files` (respects
    .gitignore, matches the SoR); fall back to a plain recursive filesystem walk for
    repositories that are not (or not yet) a git checkout in this environment, so a
    registered-but-non-git repository still gets a real inventory instead of a crash.
    """
    try:
        out = subprocess.run(
            ["git", "-C", path, "ls-files"], capture_output=True, text=True, check=True
        ).stdout
        return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        root = Path(path)
        return sorted(
            str(p.relative_to(root)).replace("\\", "/")
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(root).parts
        )


def _git_head(path: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip() or None
    except subprocess.CalledProcessError:
        return None
