from __future__ import annotations

import sqlite3
from typing import Any

from architectural_knowledge_db.models import RecallRequest
from architectural_knowledge_db.services.authoring import AuthoringService
from architectural_knowledge_db.services.cognition import CognitionService
from architectural_knowledge_db.services.completeness import CompletenessService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.reasoning import ReasoningService
from architectural_knowledge_db.services.roadmap import RoadmapService


class SurveyService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)

    def survey(self, project_id: str, detail: str = "compact", tail: int = 10) -> dict[str, Any]:
        self.projects.require_project(project_id)
        roadmap = RoadmapService(self.conn).roadmap(project_id)
        changelog_tail = roadmap[-tail:]

        topics: list[dict[str, Any]] = []
        topic_rows = self.conn.execute(
            """
            SELECT t.item_uid, t.topic_id FROM topics t
            JOIN knowledge_items ki ON ki.item_uid = t.item_uid
            WHERE ki.project_id = ? ORDER BY t.topic_id
            """,
            (project_id,),
        ).fetchall()
        for topic in topic_rows:
            mvp_rows = self.conn.execute(
                """
                SELECT m.mvp_id, m.seq FROM knowledge_links kl
                JOIN mvps m ON m.item_uid = kl.source_item_uid
                WHERE kl.project_id = ? AND kl.link_type = 'mvp_touches_topic' AND kl.target_ref = ?
                ORDER BY m.seq DESC
                """,
                (project_id, topic["item_uid"]),
            ).fetchall()
            open_spec_count = self.conn.execute(
                """
                SELECT COUNT(*) AS c FROM knowledge_links kl
                JOIN specs s ON s.item_uid = kl.source_item_uid
                WHERE kl.project_id = ? AND kl.link_type = 'spec_about_topic' AND kl.target_ref = ?
                  AND s.lifecycle IN ('draft', 'ready')
                """,
                (project_id, topic["item_uid"]),
            ).fetchone()["c"]
            topics.append({
                "topic_id": topic["topic_id"],
                "mvp_count": len(mvp_rows),
                "latest_mvp": mvp_rows[0]["mvp_id"] if mvp_rows else None,
                "open_spec_count": open_spec_count,
            })

        specs_by_status: dict[str, dict[str, int]] = {}
        for row in self.conn.execute(
            """
            SELECT s.archetype, s.lifecycle, COUNT(*) AS c FROM specs s
            JOIN knowledge_items ki ON ki.item_uid = s.item_uid
            WHERE ki.project_id = ? GROUP BY s.archetype, s.lifecycle
            """,
            (project_id,),
        ).fetchall():
            specs_by_status.setdefault(row["archetype"], {})[row["lifecycle"]] = row["c"]

        reasoning = ReasoningService(self.conn)
        completeness = CompletenessService(self.conn)
        topicless_mvps = self.conn.execute(
            """
            SELECT COUNT(*) AS c FROM mvps m
            JOIN knowledge_items ki ON ki.item_uid = m.item_uid
            WHERE ki.project_id = ?
              AND NOT EXISTS (
                SELECT 1 FROM knowledge_links kl
                WHERE kl.project_id = ki.project_id AND kl.source_item_uid = m.item_uid
                  AND kl.link_type = 'mvp_touches_topic'
              )
            """,
            (project_id,),
        ).fetchone()["c"]
        spec_uids = [
            row["item_uid"]
            for row in self.conn.execute(
                """
                SELECT s.item_uid FROM specs s
                JOIN knowledge_items ki ON ki.item_uid = s.item_uid
                WHERE ki.project_id = ?
                """,
                (project_id,),
            ).fetchall()
        ]
        specs_blocked = sum(
            1 for uid in spec_uids if not completeness.spec_validate(project_id, uid)["ok"]
        )
        health = {
            "tensions": len(reasoning.tensions(project_id)),
            "gaps": len(reasoning.gaps(project_id)),
            "topicless_mvps": topicless_mvps,
            "specs_blocked": specs_blocked,
        }

        return {
            "topics": topics,
            "changelog_tail": changelog_tail,
            "specs_by_status": specs_by_status,
            "health": health,
        }

    def _topic_linked_items(self, project_id: str, topic_uid: str, item_type: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT DISTINCT ki.item_uid FROM knowledge_links kl
            JOIN knowledge_items ki ON ki.item_uid = kl.source_item_uid
            WHERE kl.project_id = ? AND kl.target_ref = ? AND ki.item_type = ?
            UNION
            SELECT DISTINCT ki.item_uid FROM knowledge_links kl
            JOIN knowledge_items ki ON ki.item_uid = kl.target_ref
            WHERE kl.project_id = ? AND kl.source_item_uid = ? AND ki.item_type = ?
            """,
            (project_id, topic_uid, item_type, project_id, topic_uid, item_type),
        ).fetchall()
        knowledge = KnowledgeService(self.conn)
        return [knowledge.get_item_by_uid(row["item_uid"]) for row in rows]

    def spec_authoring_context(self, project_id: str, topic_uid: str, archetype: str | None = None) -> dict[str, Any]:
        self.projects.require_project(project_id)
        knowledge = KnowledgeService(self.conn)
        topic = knowledge.get_item_by_uid(topic_uid)
        timeline = RoadmapService(self.conn).topic_timeline(project_id, topic_uid)
        related = CognitionService(self.conn).recall(
            project_id, RecallRequest(query=topic.get("title") or topic_uid)
        ).get("neighbours", [])
        contract = CompletenessService(self.conn).contract(archetype) if archetype else None
        source_areas = [
            {"source_area_id": item["local_id"], "title": item["title"]}
            for item in knowledge.list_items(project_id, include_types=["source_area"], limit=200)
        ]
        reusable_elements = AuthoringService(self.conn).find_reuse(project_id, topic.get("title") or topic_uid)
        return {
            "topic": {"item_uid": topic_uid, "title": topic.get("title"),
                      "topic_id": topic["details"].get("topic_id")},
            "timeline": timeline,
            "related": related,
            "contract": contract,
            "source_areas": source_areas,
            "reusable_elements": reusable_elements,
        }

    def brief(self, project_id: str, topic_uid: str) -> dict[str, Any]:
        self.projects.require_project(project_id)
        knowledge = KnowledgeService(self.conn)
        topic = knowledge.get_item_by_uid(topic_uid)
        key_decisions = [
            {"adr_id": adr["details"].get("adr_id") or adr["local_id"], "title": adr["title"]}
            for adr in self._topic_linked_items(project_id, topic_uid, "adr")
        ]
        open_questions = [
            {"item_uid": q["item_uid"], "title": q["title"]}
            for q in self._topic_linked_items(project_id, topic_uid, "question")
            if q["details"].get("status") == "open"
        ]
        return {
            "topic": {"item_uid": topic_uid, "title": topic.get("title"),
                      "topic_id": topic["details"].get("topic_id")},
            "what": topic.get("summary") or topic.get("title"),
            "key_decisions": key_decisions,
            "lineage": RoadmapService(self.conn).topic_timeline(project_id, topic_uid),
            "open_questions": open_questions,
            "blind_spots": ReasoningService(self.conn).gaps(project_id, topic_uid=topic_uid),
        }
