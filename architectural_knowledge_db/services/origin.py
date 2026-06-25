from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from architectural_knowledge_db.models import OriginExplainRequest
from architectural_knowledge_db.services.jsonutil import loads
from architectural_knowledge_db.services.knowledge import KnowledgeService, normalize_path
from architectural_knowledge_db.services.projects import ProjectService


class OriginService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)

    def explain(self, project_id: str, request: OriginExplainRequest) -> dict[str, Any]:
        self.projects.require_project(project_id)
        if request.target_type == "source_path":
            return self._explain_source_path(project_id, request.target)
        return self._explain_knowledge_target(project_id, request.target, request.target_type)

    def git_provenance(self, project_id: str, target: str, limit_commits: int = 10) -> dict[str, Any]:
        self.projects.require_project(project_id)
        source_path = normalize_path(target)
        return {
            "project_id": project_id,
            "target": source_path,
            "file_history": self._file_history(project_id, source_path),
            "recent_commits": self._recent_commits(project_id, source_path, limit=limit_commits),
            "frequently_cochanged_files": self._frequent_cochanges(project_id, source_path, limit=limit_commits),
            "authority_note": "Git provenance is evidence, not architecture authority.",
        }

    def _explain_source_path(self, project_id: str, target: str) -> dict[str, Any]:
        source_path = normalize_path(target)
        explicit_links = self._explicit_links(project_id, source_path)
        file_history = self._file_history(project_id, source_path)
        recent_commits = self._recent_commits(project_id, source_path)
        cochanged = self._frequent_cochanges(project_id, source_path)
        source_areas = self.knowledge.matching_source_areas(project_id, source_path)
        rules = self.knowledge.matching_rules_for_path(project_id, source_path)
        staleness = self._staleness(project_id, source_path)
        return {
            "project_id": project_id,
            "target": source_path,
            "target_type": "source_path",
            "summary": _source_summary(source_path, file_history, source_areas, rules),
            "explicit_knowledge_links": explicit_links,
            "related_source_areas": source_areas,
            "related_rules": rules,
            "git_file_history": file_history,
            "recent_commits": recent_commits,
            "frequently_cochanged_files": cochanged,
            "staleness_warnings": staleness,
            "authority_note": "Git history and co-change records are evidence, not architecture authority.",
        }

    def _explain_knowledge_target(self, project_id: str, target: str, target_type: str) -> dict[str, Any]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM knowledge_items
            WHERE project_id = ?
              AND (item_uid = ? OR local_id = ? OR (? = 'adr' AND item_type = 'adr' AND local_id = ?))
            LIMIT 10
            """,
            (project_id, target, target, target_type, target),
        ).fetchall()
        items = [self.knowledge.get_item_by_uid(row["item_uid"]) for row in rows]
        links = []
        for item in items:
            links.extend(self._links_for_item(project_id, item["item_uid"]))
        return {
            "project_id": project_id,
            "target": target,
            "target_type": target_type,
            "summary": f"Found {len(items)} matching knowledge items.",
            "knowledge_items": items,
            "knowledge_links": links,
            "authority_note": "Explicit links outrank inferred Git evidence.",
        }

    def _explicit_links(self, project_id: str, target_ref: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT kl.*, ki.item_type, ki.local_id, ki.title
            FROM knowledge_links kl
            JOIN knowledge_items ki ON ki.item_uid = kl.source_item_uid
            WHERE kl.project_id = ?
              AND kl.target_ref = ?
            ORDER BY kl.confidence, kl.link_type
            """,
            (project_id, target_ref),
        ).fetchall()
        return [_hydrate_link(row) for row in rows]

    def _links_for_item(self, project_id: str, item_uid: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT kl.*, ki.item_type, ki.local_id, ki.title
            FROM knowledge_links kl
            JOIN knowledge_items ki ON ki.item_uid = kl.source_item_uid
            WHERE kl.project_id = ?
              AND kl.source_item_uid = ?
            ORDER BY kl.link_type
            """,
            (project_id, item_uid),
        ).fetchall()
        return [_hydrate_link(row) for row in rows]

    def _file_history(self, project_id: str, path: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM git_file_history
            WHERE project_id = ? AND file_path = ?
            ORDER BY last_changed_at DESC
            """,
            (project_id, path),
        ).fetchall()
        return [dict(row) for row in rows]

    def _recent_commits(self, project_id: str, path: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT c.repository_id, c.commit_hash, c.short_hash, c.committed_at,
                   c.author_name, c.message_subject, f.change_type, f.previous_path
            FROM git_commit_files f
            JOIN git_commits c ON c.commit_uid = f.commit_uid
            WHERE f.project_id = ? AND f.file_path = ?
            ORDER BY c.committed_at DESC
            LIMIT ?
            """,
            (project_id, path, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def _frequent_cochanges(self, project_id: str, path: str, limit: int = 10) -> list[dict[str, Any]]:
        commit_rows = self.conn.execute(
            """
            SELECT commit_uid
            FROM git_commit_files
            WHERE project_id = ? AND file_path = ?
            """,
            (project_id, path),
        ).fetchall()
        commit_uids = [row["commit_uid"] for row in commit_rows]
        if not commit_uids:
            return []
        rows = self.conn.execute(
            f"""
            SELECT file_path
            FROM git_commit_files
            WHERE project_id = ?
              AND commit_uid IN ({','.join('?' for _ in commit_uids)})
              AND file_path <> ?
            """,
            [project_id, *commit_uids, path],
        ).fetchall()
        counter = Counter(row["file_path"] for row in rows)
        return [
            {
                "file_path": file_path,
                "cochange_count": count,
                "confidence": "medium" if count > 1 else "weak",
                "authority_level": "git_provenance_evidence",
            }
            for file_path, count in counter.most_common(limit)
        ]

    def _staleness(self, project_id: str, target_ref: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT report_uid, target_ref, target_type, status, reason, evidence_json, created_at
            FROM staleness_reports
            WHERE project_id = ? AND target_ref = ?
            ORDER BY created_at DESC
            """,
            (project_id, target_ref),
        ).fetchall()
        return [dict(row) | {"evidence": loads(row["evidence_json"], {})} for row in rows]


def _hydrate_link(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "link_uid": row["link_uid"],
        "source_item_uid": row["source_item_uid"],
        "source_item_type": row["item_type"],
        "source_local_id": row["local_id"],
        "source_title": row["title"],
        "target_ref": row["target_ref"],
        "link_type": row["link_type"],
        "authority_level": row["authority_level"],
        "confidence": row["confidence"],
        "evidence": row["evidence"],
        "metadata": loads(row["metadata_json"], {}),
    }


def _source_summary(
    source_path: str,
    file_history: list[dict[str, Any]],
    source_areas: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> str:
    if not file_history:
        history = "no scanned Git history"
    else:
        history = f"{sum(row['change_count'] for row in file_history)} recorded changes"
    return (
        f"{source_path} has {history}, "
        f"{len(source_areas)} matching source areas, and {len(rules)} matching rules."
    )
