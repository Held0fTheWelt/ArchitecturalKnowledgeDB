from __future__ import annotations

import sqlite3
from typing import Any

from architectural_knowledge_db.services.completeness import CompletenessService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.reasoning import ReasoningService
from architectural_knowledge_db.services.staleness import StalenessService

_TOPIC_LINK_TYPES = ("spec_about_topic", "mvp_touches_topic", "question_about_topic")


class ReviewService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)

    def review(self, project_id: str, target_uid: str) -> dict[str, Any]:
        self.projects.require_project(project_id)
        target = self.knowledge.get_item_by_uid(target_uid)
        completeness = None
        if target["item_type"] == "spec":
            completeness = CompletenessService(self.conn).spec_validate(project_id, target_uid)

        placeholders = ",".join("?" for _ in _TOPIC_LINK_TYPES)
        topic_uids = [
            row["target_ref"]
            for row in self.conn.execute(
                f"""
                SELECT target_ref FROM knowledge_links
                WHERE project_id = ? AND source_item_uid = ? AND link_type IN ({placeholders})
                """,
                (project_id, target_uid, *_TOPIC_LINK_TYPES),
            ).fetchall()
        ]

        reasoning = ReasoningService(self.conn)
        tensions: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        seen_t: set[tuple] = set()
        seen_g: set[tuple] = set()
        for scope in (topic_uids or [None]):
            for tension in reasoning.tensions(project_id, topic_uid=scope):
                key = (tension["kind"], tension["conflicts_with"], tension["subject"])
                if key not in seen_t:
                    seen_t.add(key)
                    tensions.append(tension)
            for gap in reasoning.gaps(project_id, topic_uid=scope):
                key = (gap["kind"], gap["subject"])
                if key not in seen_g:
                    seen_g.add(key)
                    gaps.append(gap)

        staleness = StalenessService(self.conn).list_reports(project_id)
        sound = (completeness is None or completeness["ok"]) and not tensions
        return {
            "target": target_uid,
            "sound": sound,
            "completeness": completeness,
            "tensions": tensions,
            "gaps": gaps,
            "staleness": staleness,
        }
