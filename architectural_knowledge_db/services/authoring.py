from __future__ import annotations

import json
import sqlite3
from typing import Any

from architectural_knowledge_db.models import (
    KnowledgeLinkInput,
    MvpInput,
    QuestionInput,
    SpecInput,
    TopicInput,
)
from architectural_knowledge_db.services.completeness import CompletenessService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.search import SearchService


class AuthoringService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)
        self.search = SearchService(conn)

    def propose_topic(self, project_id: str, topic_id: str, title: str, summary: str | None = None) -> dict[str, Any]:
        self.projects.require_project(project_id)
        dups = [
            {"item_uid": h["item_uid"], "title": h["title"]}
            for h in self.search.search(project_id, title, include_types=["topic"], limit=5)
        ]
        if dups:
            return {"created": False, "topic": None, "duplicates": dups}
        topic = self.knowledge.upsert_topic(project_id, TopicInput(topic_id=topic_id, title=title, summary=summary))
        return {"created": True, "topic": topic, "duplicates": []}

    def _next_seq(self, project_id: str) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(MAX(m.seq), 0) + 1 AS nxt
            FROM mvps m JOIN knowledge_items ki ON ki.item_uid = m.item_uid
            WHERE ki.project_id = ?
            """,
            (project_id,),
        ).fetchone()
        return int(row["nxt"])

    def _latest_mvp_on_topic(self, project_id: str, topic_uid: str, exclude_uid: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT m.item_uid, m.mvp_id, m.seq
            FROM knowledge_links kl
            JOIN mvps m ON m.item_uid = kl.source_item_uid
            WHERE kl.project_id = ? AND kl.link_type = 'mvp_touches_topic'
              AND kl.target_ref = ? AND kl.source_item_uid != ?
            ORDER BY m.seq DESC LIMIT 1
            """,
            (project_id, topic_uid, exclude_uid),
        ).fetchone()
        return dict(row) if row else None

    def create_mvp(self, project_id, mvp_id, title, intent_md=None, topic_uid=None) -> dict[str, Any]:
        self.projects.require_project(project_id)
        seq = self._next_seq(project_id)
        mvp = self.knowledge.upsert_mvp(project_id, MvpInput(mvp_id=mvp_id, title=title, seq=seq, intent_md=intent_md))
        suggested = None
        if topic_uid:
            self.knowledge.upsert_link(project_id, KnowledgeLinkInput(
                source_item_uid=mvp["item_uid"], target_ref=topic_uid, link_type="mvp_touches_topic"))
            pred = self._latest_mvp_on_topic(project_id, topic_uid, mvp["item_uid"])
            if pred:
                suggested = {"item_uid": pred["item_uid"], "mvp_id": pred["mvp_id"], "edge": "mvp_extends"}
        return {"mvp": mvp, "seq": seq, "suggested_predecessor": suggested}

    def create_spec(self, project_id, spec_id, title, archetype, mvp_uid, topic_uid=None) -> dict[str, Any]:
        self.projects.require_project(project_id)
        spec = self.knowledge.upsert_spec(
            project_id, SpecInput(spec_id=spec_id, title=title, archetype=archetype, mvp_uid=mvp_uid))
        if mvp_uid:
            self.knowledge.upsert_link(project_id, KnowledgeLinkInput(
                source_item_uid=spec["item_uid"], target_ref=mvp_uid, link_type="spec_for_mvp"))
        if topic_uid:
            self.knowledge.upsert_link(project_id, KnowledgeLinkInput(
                source_item_uid=spec["item_uid"], target_ref=topic_uid, link_type="spec_about_topic"))
        return spec

    def open_question(self, project_id, question_id, title, topic_uid=None) -> dict[str, Any]:
        self.projects.require_project(project_id)
        question = self.knowledge.upsert_question(project_id, QuestionInput(question_id=question_id, title=title))
        if topic_uid:
            self.knowledge.upsert_link(project_id, KnowledgeLinkInput(
                source_item_uid=question["item_uid"], target_ref=topic_uid, link_type="question_about_topic"))
        return question

    def resolve_question(self, project_id, question_uid, by_ref) -> dict[str, Any]:
        self.projects.require_project(project_id)
        current = self.knowledge.get_item_by_uid(question_uid)
        question = self.knowledge.upsert_question(project_id, QuestionInput(
            question_id=current["details"]["question_id"], title=current["title"], status="answered"))
        self.knowledge.upsert_link(project_id, KnowledgeLinkInput(
            source_item_uid=question["item_uid"], target_ref=by_ref, link_type="question_resolved_by"))
        return question

    def map_element_to_file(self, project_id, element_uid, path, symbol=None) -> dict[str, Any]:
        self.projects.require_project(project_id)
        return self.knowledge.upsert_link(project_id, KnowledgeLinkInput(
            source_item_uid=element_uid, target_ref=path, link_type="element_maps_to_file",
            metadata={"symbol": symbol}))

    def set_spec_status(self, project_id, spec_uid, status) -> dict[str, Any]:
        self.projects.require_project(project_id)
        spec = self.knowledge.get_item_by_uid(spec_uid)
        if status == "ready":
            validation = CompletenessService(self.conn).spec_validate(project_id, spec_uid)
            if not validation["ok"]:
                return {"changed": False, "validation": validation}
        updated = self.knowledge.upsert_spec(project_id, SpecInput(
            spec_id=spec["details"]["spec_id"], title=spec["title"], archetype=spec["details"]["archetype"],
            lifecycle=status, mvp_uid=spec["details"].get("mvp_uid"),
            sections=spec["details"].get("sections", [])))
        return {"changed": True, "spec": updated}

    def scaffold_spec(self, project_id, archetype, topic_uid=None) -> dict[str, Any]:
        self.projects.require_project(project_id)
        contract = CompletenessService(self.conn).contract(archetype)
        reuse: list[dict[str, Any]] = []
        if topic_uid:
            topic = self.knowledge.get_item_by_uid(topic_uid)
            reuse = self.find_reuse(project_id, topic.get("title") or "")
        return {
            "archetype": archetype,
            "required_diagrams": list(contract["required_diagrams"]),
            "file_map_stub": [{"element": "<component-name>", "path": "<relative/source/path>", "symbol": "<symbol>"}],
            "reuse": reuse,
        }

    def find_reuse(self, project_id, query, limit=10) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        return self.search.search(project_id, query, include_types=["spec", "uml_element"], limit=limit)

    def spec_to_plan(self, project_id, spec_uid) -> dict[str, Any]:
        self.projects.require_project(project_id)
        comp = CompletenessService(self.conn)
        validation = comp.spec_validate(project_id, spec_uid)
        if not validation["ok"]:
            return {"refused": True, "validation": validation}
        spec = self.knowledge.get_item_by_uid(spec_uid)
        contract = comp.contract(spec["details"].get("archetype"))
        source_uids = [spec_uid]
        realized = self.conn.execute(
            """
            SELECT target_ref FROM knowledge_links
            WHERE project_id = ? AND source_item_uid = ? AND link_type = 'spec_realizes_uml'
            ORDER BY target_ref
            """,
            (project_id, spec_uid),
        ).fetchall()
        for row in realized:
            item = comp._resolve_item(project_id, row["target_ref"])
            if item and item["item_type"] == "uml_element":
                source_uids.append(item["item_uid"])
        targets: dict[str, str | None] = {}
        for source_uid in source_uids:
            for link in self.conn.execute(
                """
                SELECT target_ref, metadata_json FROM knowledge_links
                WHERE project_id = ? AND source_item_uid = ? AND link_type = 'element_maps_to_file'
                """,
                (project_id, source_uid),
            ).fetchall():
                targets.setdefault(link["target_ref"], json.loads(link["metadata_json"] or "{}").get("symbol"))
        tasks = [
            {
                "order": index + 1,
                "title": f"Implement {path}",
                "target_path": path,
                "symbol": symbol,
                "steps": ["write failing test", "run → fail", "implement", "run → pass", "commit"],
            }
            for index, (path, symbol) in enumerate(sorted(targets.items()))
        ]
        return {
            "refused": False,
            "spec_uid": spec_uid,
            "tasks": tasks,
            "checkpoints": list(contract["required_diagrams"]),
        }
