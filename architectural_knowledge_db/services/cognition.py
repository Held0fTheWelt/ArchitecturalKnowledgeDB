from __future__ import annotations

import sqlite3
from typing import Any

from architectural_knowledge_db.models import (
    ExploreRequest,
    KnowledgeLinkInput,
    RecallRequest,
    RememberRequest,
)
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.memory import MemoryService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.recall_backend import FtsBackend, RecallBackend
from architectural_knowledge_db.services.search import SearchService

# Lower rank = higher authority (mirrors KnowledgeService.list_items ordering).
_AUTHORITY_RANK = {
    "hard_guardrail": 0,
    "accepted_adr": 1,
    "active_rule": 2,
    "canonical_definition": 3,
    "current_uml_model": 4,
    "source_area_evidence": 5,
    "git_provenance_evidence": 6,
    "historical_context": 7,
    "superseded_decision": 8,
    "deprecated_compatibility": 9,
    "project_note": 10,
    "evidence": 11,
}
_CONFIDENCE_RANK = {"explicit": 0, "high": 1, "inferred": 2, "low": 3}


class CognitionService:
    def __init__(self, conn: sqlite3.Connection, backend: RecallBackend | None = None):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)
        self.search = SearchService(conn)
        self.memory = MemoryService(conn)
        self.backend = backend

    def remember(self, project_id: str, req: RememberRequest) -> dict[str, Any]:
        self.projects.require_project(project_id)
        added_alias = False
        note_uid: str | None = None
        if req.wording:
            self.knowledge.upsert_link(
                project_id,
                KnowledgeLinkInput(
                    source_item_uid=req.target,
                    target_ref=req.wording,
                    link_type="alias",
                    confidence="explicit",
                ),
            )
            self.knowledge._index_item(req.target)
            added_alias = True
        if req.note:
            note = self.knowledge._upsert_item(
                project_id=project_id,
                space_id=None,
                item_type="note",
                local_id=f"note-{abs(hash((req.target, req.note))) % (10**10)}",
                title=req.note[:80],
                status="active",
                authority_level="project_note",
                summary=req.note,
                source_uri=None,
                metadata={"about": req.target},
            )
            self.knowledge._index_item(note)
            self.knowledge.upsert_link(
                project_id,
                KnowledgeLinkInput(source_item_uid=note, target_ref=req.target, link_type="note_about"),
            )
            note_uid = note
        return {"target": req.target, "added_alias": added_alias, "note_uid": note_uid}

    def _neighbours(self, project_id: str, item_uid: str, follow: list[str] | None = None) -> list[dict[str, Any]]:
        clause = ""
        params: list[Any] = [project_id, item_uid, project_id, item_uid]
        if follow:
            placeholders = ",".join("?" for _ in follow)
            clause = f"AND link_type IN ({placeholders})"
            params = [project_id, item_uid, *follow, project_id, item_uid, *follow]
        rows = self.conn.execute(
            f"""
            SELECT target_ref AS ref, link_type, confidence, 'outbound' AS direction
            FROM knowledge_links WHERE project_id = ? AND source_item_uid = ? {clause}
            UNION ALL
            SELECT source_item_uid AS ref, link_type, confidence, 'inbound' AS direction
            FROM knowledge_links WHERE project_id = ? AND target_ref = ? {clause}
            """,
            params,
        ).fetchall()
        neighbours: list[dict[str, Any]] = []
        for row in rows:
            try:
                item = self.knowledge.get_item_by_uid(row["ref"])
            except ValueError:
                continue  # target_ref may be a string (e.g. alias wording / file path), not an item
            mem = self.memory.state(item["item_uid"])
            neighbours.append(
                {
                    "item_uid": item["item_uid"],
                    "title": item.get("title"),
                    "item_type": item["item_type"],
                    "link_type": row["link_type"],
                    "direction": row["direction"],
                    "authority_level": item.get("authority_level"),
                    "source_uri": item.get("source_uri"),
                    "summary": item.get("summary"),
                    "pinned": mem["pinned"],
                    "salience": mem["salience"],
                    "_updated_at": item.get("updated_at") or "",
                    "_confidence": row["confidence"],
                }
            )
        neighbours.sort(
            key=lambda n: (
                -int(n["pinned"]),
                _AUTHORITY_RANK.get(n["authority_level"], 99),
                -float(n["salience"]),
                _negated(n.pop("_updated_at")),
                _CONFIDENCE_RANK.get(n.pop("_confidence"), 9),
            )
        )
        return neighbours

    def _hybrid_hits(self, project_id: str, req: RecallRequest) -> list[dict[str, Any]]:
        scores: dict[str, float] = {}
        for uid, score in FtsBackend(self.conn).resolve(project_id, req.query, req.spaces, req.limit):
            scores[uid] = max(scores.get(uid, 0.0), score)
        for uid, score in self.backend.resolve(project_id, req.query, req.spaces, req.limit):
            scores[uid] = max(scores.get(uid, 0.0), score)
        ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[: req.limit]
        hits: list[dict[str, Any]] = []
        for uid, _score in ordered:
            try:
                item = self.knowledge.get_item_by_uid(uid)
            except ValueError:
                continue
            hits.append({
                "item_uid": item["item_uid"],
                "title": item.get("title"),
                "item_type": item["item_type"],
                "authority_level": item.get("authority_level"),
                "local_id": item.get("local_id"),
            })
        return hits

    def recall(self, project_id: str, req: RecallRequest) -> dict[str, Any]:
        self.projects.require_project(project_id)
        if req.semantic and self.backend is not None:
            hits = self._hybrid_hits(project_id, req)
        else:
            hits = self.search.search(
                project_id, req.query, include_shared=req.include_shared, limit=req.limit
            )
        if not hits:
            return {"query": req.query, "concepts": [], "neighbours": [],
                    "hint": "no match; coin a wording with akdb_remember(target, wording=...)"}
        concepts = [
            {"item_uid": h["item_uid"], "title": h["title"], "item_type": h["item_type"],
             "authority_level": h["authority_level"], "local_id": h.get("local_id")}
            for h in hits[: max(1, req.limit // 4)]
        ]
        neighbours = self._neighbours(project_id, hits[0]["item_uid"])
        self.memory.record_use(project_id, [hits[0]["item_uid"], *[n["item_uid"] for n in neighbours]])
        return {"query": req.query, "concepts": concepts, "neighbours": neighbours}

    def explore(self, project_id: str, req: ExploreRequest) -> dict[str, Any]:
        self.projects.require_project(project_id)
        follow = req.follow or None
        seen: set[str] = {req.source}
        frontier = [req.source]
        collected: list[dict[str, Any]] = []
        for _ in range(max(1, req.hops)):
            next_frontier: list[str] = []
            for node in frontier:
                for n in self._neighbours(project_id, node, follow):
                    if n["item_uid"] in seen:
                        continue
                    seen.add(n["item_uid"])
                    collected.append(n)
                    next_frontier.append(n["item_uid"])
            frontier = next_frontier
            if not frontier:
                break
        return {"source": req.source, "follow": req.follow, "neighbours": collected}

    def recall_delta(self, project_id: str, since: str) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        threshold = since
        mvp_row = self.conn.execute(
            """
            SELECT ki.updated_at FROM mvps m
            JOIN knowledge_items ki ON ki.item_uid = m.item_uid
            WHERE ki.project_id = ? AND m.mvp_id = ?
            """,
            (project_id, since),
        ).fetchone()
        if mvp_row:
            threshold = mvp_row["updated_at"]
        rows = self.conn.execute(
            """
            SELECT item_uid, title, item_type, updated_at FROM knowledge_items
            WHERE project_id = ? AND updated_at > ?
            ORDER BY updated_at DESC, item_uid
            """,
            (project_id, threshold),
        ).fetchall()
        return [
            {"item_uid": r["item_uid"], "title": r["title"], "item_type": r["item_type"],
             "updated_at": r["updated_at"]}
            for r in rows
        ]

    def working_set(self, project_id: str, action: str, ref: str | None = None,
                    label: str = "default") -> dict[str, Any]:
        self.projects.require_project(project_id)
        ws_uid = self.knowledge._upsert_item(
            project_id=project_id, space_id=None, item_type="working_set", local_id=label,
            title=label, status="active", authority_level="project_note",
            summary=None, source_uri=None, metadata={},
        )
        if action == "add":
            if not ref:
                raise ValueError("working_set add requires ref")
            self.knowledge.upsert_link(project_id, KnowledgeLinkInput(
                source_item_uid=ws_uid, target_ref=ref, link_type="in_working_set"))
        elif action == "clear":
            self.conn.execute(
                "DELETE FROM knowledge_links WHERE project_id = ? AND source_item_uid = ? AND link_type = 'in_working_set'",
                (project_id, ws_uid),
            )
        members: list[dict[str, Any]] = []
        for row in self.conn.execute(
            """
            SELECT target_ref FROM knowledge_links
            WHERE project_id = ? AND source_item_uid = ? AND link_type = 'in_working_set'
            ORDER BY target_ref
            """,
            (project_id, ws_uid),
        ).fetchall():
            try:
                item = self.knowledge.get_item_by_uid(row["target_ref"])
            except ValueError:
                continue
            members.append({"item_uid": item["item_uid"], "title": item.get("title"),
                            "item_type": item["item_type"]})
        return {"label": label, "action": action, "members": members}


def _negated(timestamp: str) -> str:
    # invert lexical order so newer updated_at (larger string) sorts first
    return "".join(chr(255 - ord(c)) for c in timestamp)
