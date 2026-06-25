from __future__ import annotations

import sqlite3
from typing import Any

from architectural_knowledge_db.services.projects import ProjectService

_MVP_EDGE_TYPES = ("mvp_extends", "supersedes", "revises", "depends_on")


class RoadmapService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)

    def roadmap(self, project_id: str) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        rows = self.conn.execute(
            """
            SELECT m.item_uid, m.mvp_id, m.seq, m.lifecycle, m.shipped_at, ki.title
            FROM mvps m JOIN knowledge_items ki ON ki.item_uid = m.item_uid
            WHERE ki.project_id = ?
            ORDER BY m.seq
            """,
            (project_id,),
        ).fetchall()
        return [self._entry(project_id, row) for row in rows]

    def topic_timeline(self, project_id: str, topic_uid: str) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        rows = self.conn.execute(
            """
            SELECT m.item_uid, m.mvp_id, m.seq, m.lifecycle, m.shipped_at, ki.title
            FROM knowledge_links kl
            JOIN mvps m ON m.item_uid = kl.source_item_uid
            JOIN knowledge_items ki ON ki.item_uid = m.item_uid
            WHERE kl.project_id = ? AND kl.link_type = 'mvp_touches_topic' AND kl.target_ref = ?
            ORDER BY m.seq
            """,
            (project_id, topic_uid),
        ).fetchall()
        return [self._entry(project_id, row) for row in rows]

    def _entry(self, project_id: str, row: sqlite3.Row) -> dict[str, Any]:
        mvp_uid = row["item_uid"]
        return {
            "item_uid": mvp_uid,
            "seq": row["seq"],
            "mvp_id": row["mvp_id"],
            "title": row["title"],
            "lifecycle": row["lifecycle"],
            "shipped_at": row["shipped_at"],
            "topics": self._topics_for(project_id, mvp_uid),
            "specs": self._specs_for(project_id, mvp_uid),
            "edges": self._edges_for(project_id, mvp_uid),
        }

    def _topics_for(self, project_id: str, mvp_uid: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT t.item_uid, t.topic_id, ki.title
            FROM knowledge_links kl
            JOIN topics t ON t.item_uid = kl.target_ref
            JOIN knowledge_items ki ON ki.item_uid = t.item_uid
            WHERE kl.project_id = ? AND kl.link_type = 'mvp_touches_topic' AND kl.source_item_uid = ?
            ORDER BY t.topic_id
            """,
            (project_id, mvp_uid),
        ).fetchall()
        return [{"item_uid": r["item_uid"], "topic_id": r["topic_id"], "title": r["title"]} for r in rows]

    def _specs_for(self, project_id: str, mvp_uid: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT s.item_uid, s.spec_id, s.archetype, s.lifecycle, ki.title
            FROM specs s JOIN knowledge_items ki ON ki.item_uid = s.item_uid
            WHERE ki.project_id = ? AND s.mvp_uid = ?
            ORDER BY s.spec_id
            """,
            (project_id, mvp_uid),
        ).fetchall()
        return [
            {"item_uid": r["item_uid"], "spec_id": r["spec_id"], "archetype": r["archetype"],
             "lifecycle": r["lifecycle"], "title": r["title"]}
            for r in rows
        ]

    def _edges_for(self, project_id: str, mvp_uid: str) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in _MVP_EDGE_TYPES)
        rows = self.conn.execute(
            f"""
            SELECT link_type, target_ref
            FROM knowledge_links
            WHERE project_id = ? AND source_item_uid = ? AND link_type IN ({placeholders})
            ORDER BY link_type, target_ref
            """,
            (project_id, mvp_uid, *_MVP_EDGE_TYPES),
        ).fetchall()
        return [{"link_type": r["link_type"], "target_ref": r["target_ref"]} for r in rows]
