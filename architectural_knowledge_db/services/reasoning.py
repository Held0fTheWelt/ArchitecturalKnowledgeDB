from __future__ import annotations

import sqlite3
from typing import Any

from architectural_knowledge_db.ids import digest_uid
from architectural_knowledge_db.services.jsonutil import dumps, loads
from architectural_knowledge_db.services.knowledge import path_matches
from architectural_knowledge_db.services.projects import ProjectService

# items whose inbound reference to a superseded item is not itself a tension
_HISTORICAL_AUTHORITY = ("historical_context", "superseded_decision", "deprecated_compatibility")


class ReasoningService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)

    def _title(self, item_uid: str) -> str:
        row = self.conn.execute(
            "SELECT title FROM knowledge_items WHERE item_uid = ?", (item_uid,)
        ).fetchone()
        return (row["title"] if row and row["title"] else item_uid)

    def _neighbours(self, project_id: str, node: str) -> list[tuple[str, str, str]]:
        rows = self.conn.execute(
            """
            SELECT target_ref AS nbr, link_type, 'outbound' AS direction
            FROM knowledge_links WHERE project_id = ? AND source_item_uid = ?
            UNION ALL
            SELECT source_item_uid AS nbr, link_type, 'inbound' AS direction
            FROM knowledge_links WHERE project_id = ? AND target_ref = ?
            """,
            (project_id, node, project_id, node),
        ).fetchall()
        neighbours: list[tuple[str, str, str]] = []
        for row in rows:
            if self.conn.execute(
                "SELECT 1 FROM knowledge_items WHERE item_uid = ?", (row["nbr"],)
            ).fetchone():
                neighbours.append((row["nbr"], row["link_type"], row["direction"]))
        return neighbours

    def connect(self, project_id: str, a_uid: str, b_uid: str, max_hops: int = 4) -> dict[str, Any]:
        self.projects.require_project(project_id)
        if a_uid == b_uid:
            return {"found": True, "path": [], "explanation": self._title(a_uid)}
        visited = {a_uid}
        parent: dict[str, tuple[str, str, str]] = {}
        frontier = [a_uid]
        found = False
        hops = 0
        while frontier and hops < max_hops and not found:
            hops += 1
            next_frontier: list[str] = []
            for node in frontier:
                for nbr, link_type, direction in self._neighbours(project_id, node):
                    if nbr in visited:
                        continue
                    visited.add(nbr)
                    parent[nbr] = (node, link_type, direction)
                    if nbr == b_uid:
                        found = True
                        break
                    next_frontier.append(nbr)
                if found:
                    break
            frontier = next_frontier
        if not found:
            return {"found": False, "path": [], "explanation": ""}
        path: list[dict[str, str]] = []
        cursor = b_uid
        while cursor != a_uid:
            prev, link_type, direction = parent[cursor]
            path.append({"from": prev, "link_type": link_type, "direction": direction, "to": cursor})
            cursor = prev
        path.reverse()
        explanation = self._title(a_uid)
        for step in path:
            explanation += f" --{step['link_type']}--> {self._title(step['to'])}"
        return {"found": True, "path": path, "explanation": explanation}

    def _topic_member_uids(self, project_id: str, topic_uid: str) -> set[str]:
        rows = self.conn.execute(
            """
            SELECT source_item_uid AS uid FROM knowledge_links WHERE project_id = ? AND target_ref = ?
            UNION
            SELECT target_ref AS uid FROM knowledge_links WHERE project_id = ? AND source_item_uid = ?
            """,
            (project_id, topic_uid, project_id, topic_uid),
        ).fetchall()
        return {row["uid"] for row in rows} | {topic_uid}

    def tensions(self, project_id: str, topic_uid: str | None = None) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        scope = self._topic_member_uids(project_id, topic_uid) if topic_uid else None
        tensions: list[dict[str, Any]] = []

        placeholders = ",".join("?" for _ in _HISTORICAL_AUTHORITY)
        superseded = self.conn.execute(
            """
            SELECT item_uid, local_id FROM knowledge_items
            WHERE project_id = ? AND (lower(status) = 'superseded' OR authority_level = 'superseded_decision')
            """,
            (project_id,),
        ).fetchall()
        for sub in superseded:
            referers = self.conn.execute(
                f"""
                SELECT ki.item_uid, ki.local_id
                FROM knowledge_links kl
                JOIN knowledge_items ki ON ki.item_uid = kl.source_item_uid
                WHERE kl.project_id = ? AND kl.target_ref = ?
                  AND ki.authority_level NOT IN ({placeholders})
                  AND lower(ki.status) != 'superseded'
                """,
                (project_id, sub["item_uid"], *_HISTORICAL_AUTHORITY),
            ).fetchall()
            for referer in referers:
                if scope is not None and referer["item_uid"] not in scope:
                    continue
                tensions.append({
                    "kind": "superseded_still_referenced",
                    "subject": referer["item_uid"],
                    "conflicts_with": sub["item_uid"],
                    "message": f"{referer['local_id']} still references superseded {sub['local_id']}.",
                })

        rules = self.conn.execute(
            """
            SELECT r.item_uid, r.forbidden_changes_json
            FROM rules r JOIN knowledge_items ki ON ki.item_uid = r.item_uid
            WHERE ki.project_id = ?
            """,
            (project_id,),
        ).fetchall()
        for rule in rules:
            forbidden = loads(rule["forbidden_changes_json"], [])
            if not forbidden:
                continue
            linked = self.conn.execute(
                """
                SELECT DISTINCT target_ref AS ref FROM knowledge_links
                WHERE project_id = ? AND source_item_uid = ?
                UNION
                SELECT DISTINCT source_item_uid AS ref FROM knowledge_links
                WHERE project_id = ? AND target_ref = ?
                """,
                (project_id, rule["item_uid"], project_id, rule["item_uid"]),
            ).fetchall()
            for link in linked:
                item = self.conn.execute(
                    "SELECT item_uid, item_type, local_id, source_uri FROM knowledge_items WHERE item_uid = ?",
                    (link["ref"],),
                ).fetchone()
                if item is None or item["item_type"] == "rule":
                    continue
                ref = item["source_uri"] or item["local_id"]
                if scope is not None and item["item_uid"] not in scope:
                    continue
                if any(path_matches(pattern, ref) for pattern in forbidden):
                    tensions.append({
                        "kind": "rule_forbidden_hit",
                        "subject": item["item_uid"],
                        "conflicts_with": rule["item_uid"],
                        "message": f"{item['local_id']} hits a forbidden_change of rule {rule['item_uid']}.",
                    })

        self._persist_tensions(project_id, tensions)
        return tensions

    def gaps(self, project_id: str, topic_uid: str | None = None, archetype: str | None = None) -> list[dict[str, Any]]:
        from architectural_knowledge_db.services.completeness import CompletenessService
        from architectural_knowledge_db.services.staleness import StalenessService

        self.projects.require_project(project_id)
        scope = self._topic_member_uids(project_id, topic_uid) if topic_uid else None
        gaps: list[dict[str, Any]] = []

        topics = self.conn.execute(
            """
            SELECT t.item_uid, t.topic_id FROM topics t
            JOIN knowledge_items ki ON ki.item_uid = t.item_uid
            WHERE ki.project_id = ? ORDER BY t.topic_id
            """,
            (project_id,),
        ).fetchall()
        for topic in topics:
            if scope is not None and topic["item_uid"] not in scope:
                continue
            has_spec = self.conn.execute(
                "SELECT 1 FROM knowledge_links WHERE project_id = ? AND target_ref = ? AND link_type = 'spec_about_topic' LIMIT 1",
                (project_id, topic["item_uid"]),
            ).fetchone()
            if not has_spec:
                gaps.append({"kind": "topic_without_spec", "subject": topic["item_uid"],
                             "message": f"Topic {topic['topic_id']} has no spec."})

        mvps = self.conn.execute(
            """
            SELECT m.item_uid, m.mvp_id FROM mvps m
            JOIN knowledge_items ki ON ki.item_uid = m.item_uid
            WHERE ki.project_id = ? ORDER BY m.seq
            """,
            (project_id,),
        ).fetchall()
        for mvp in mvps:
            if scope is not None and mvp["item_uid"] not in scope:
                continue
            has_spec = self.conn.execute(
                "SELECT 1 FROM specs WHERE mvp_uid = ? LIMIT 1", (mvp["item_uid"],)
            ).fetchone()
            if not has_spec:
                gaps.append({"kind": "mvp_without_spec", "subject": mvp["item_uid"],
                             "message": f"MVP {mvp['mvp_id']} has no spec."})

        completeness = CompletenessService(self.conn)
        spec_rows = self.conn.execute(
            """
            SELECT s.item_uid, s.spec_id, s.archetype FROM specs s
            JOIN knowledge_items ki ON ki.item_uid = s.item_uid
            WHERE ki.project_id = ? ORDER BY s.spec_id
            """,
            (project_id,),
        ).fetchall()
        for spec in spec_rows:
            if archetype is not None and spec["archetype"] != archetype:
                continue
            if scope is not None and spec["item_uid"] not in scope:
                continue
            if not completeness.spec_validate(project_id, spec["item_uid"])["ok"]:
                gaps.append({"kind": "spec_incomplete", "subject": spec["item_uid"],
                             "message": f"Spec {spec['spec_id']} is not complete."})

        for report in StalenessService(self.conn).list_reports(project_id, status_filter=["likely_stale"]):
            subject = report.get("target_ref")
            if scope is not None and subject not in scope:
                continue
            gaps.append({"kind": "stale_uml", "subject": subject,
                         "message": f"{subject} is likely stale."})

        return gaps

    def _persist_tensions(self, project_id: str, tensions: list[dict[str, Any]]) -> None:
        self.conn.execute(
            "DELETE FROM consistency_findings WHERE project_id = ? AND finding_type LIKE 'tension:%'",
            (project_id,),
        )
        for tension in tensions:
            finding_type = f"tension:{tension['kind']}"
            finding_uid = digest_uid(
                "finding", project_id, finding_type, tension["conflicts_with"], tension["message"]
            )
            self.conn.execute(
                """
                INSERT INTO consistency_findings(
                  finding_uid, project_id, finding_type, target_ref, severity, message, evidence_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(finding_uid) DO UPDATE SET
                  severity = excluded.severity,
                  message = excluded.message,
                  evidence_json = excluded.evidence_json,
                  created_at = CURRENT_TIMESTAMP
                """,
                (finding_uid, project_id, finding_type, tension["conflicts_with"], "medium",
                 tension["message"], dumps({"subject": tension["subject"]})),
            )
