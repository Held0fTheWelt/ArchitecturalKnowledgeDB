from __future__ import annotations

import sqlite3
import re
from collections import defaultdict, deque
from typing import Any

from architectural_knowledge_db.ids import digest_uid
from architectural_knowledge_db.models import KnowledgeLinkInput
from architectural_knowledge_db.services.jsonutil import dumps, loads
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
AUTHORITY_ORDER = {
    "hard_guardrail": 0,
    "accepted_adr": 1,
    "active_rule": 2,
    "canonical_definition": 3,
    "current_uml_model": 4,
    "source_area_evidence": 5,
    "evidence": 9,
}
ADR_ID_RE = re.compile(r"\bADR(?:-[A-Z][A-Z0-9]{1,12})?-\d{4,6}\b", re.IGNORECASE)


class ConsistencyService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)

    def check(
        self,
        project_id: str,
        scope: str | None = None,
        types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        enabled = set(types or ["supersede", "broken_links", "adr_uml", "overlap", "orphans"])
        findings: list[dict[str, Any]] = []
        if "supersede" in enabled:
            findings.extend(self._check_supersede(project_id))
        if "broken_links" in enabled:
            findings.extend(self._check_broken_links(project_id))
        if "adr_uml" in enabled:
            findings.extend(self._check_adr_uml(project_id))
        if "overlap" in enabled:
            findings.extend(self._check_overlap(project_id))
        if "orphans" in enabled:
            findings.extend(self._check_orphans(project_id))
        if scope:
            findings = [finding for finding in findings if scope in finding["target_ref"] or scope in finding["message"]]
        self.conn.execute("DELETE FROM consistency_findings WHERE project_id = ?", (project_id,))
        for finding in findings:
            self._persist_finding(project_id, finding)
        return sorted(findings, key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9), item["finding_type"], item["target_ref"]))

    def impact_of(self, project_id: str, target: str, depth: int = 3) -> dict[str, Any]:
        self.projects.require_project(project_id)
        graph = self._graph(project_id)
        inbound = defaultdict(list)
        for source, edges in graph.items():
            for edge in edges:
                inbound[edge["target_ref"]].append(edge | {"source_ref": source})

        visited = {target}
        queue = deque([(target, 0)])
        impacted = []
        while queue:
            current, distance = queue.popleft()
            if distance >= depth:
                continue
            for edge in graph.get(current, []):
                if edge["target_ref"] not in visited:
                    visited.add(edge["target_ref"])
                    impacted.append(edge | {"direction": "outbound", "distance": distance + 1})
                    queue.append((edge["target_ref"], distance + 1))
            for edge in inbound.get(current, []):
                if edge["source_ref"] not in visited:
                    visited.add(edge["source_ref"])
                    impacted.append(edge | {"direction": "inbound", "distance": distance + 1})
                    queue.append((edge["source_ref"], distance + 1))

        return {
            "project_id": project_id,
            "target": target,
            "depth": depth,
            "impacted_count": len(impacted),
            "impacted": impacted,
        }

    def link(self, project_id: str, source: str, target: str, link_type: str, evidence: str | None = None) -> dict[str, Any]:
        self.projects.require_project(project_id)
        source_uid = self._resolve_source_uid(project_id, source)
        return self.knowledge.upsert_link(
            project_id,
            KnowledgeLinkInput(
                source_item_uid=source_uid,
                target_ref=target,
                link_type=link_type,
                authority_level="evidence",
                confidence="explicit",
                evidence=evidence or "manual",
            ),
        )

    def get_links(
        self,
        project_id: str,
        target: str | None = None,
        direction: str = "both",
    ) -> dict[str, Any]:
        self.projects.require_project(project_id)
        params: list[Any] = [project_id]
        outbound_clause = ""
        inbound_clause = ""
        if target:
            source_uid = self._try_resolve_source_uid(project_id, target)
            outbound_clause = "AND source_item_uid = ?" if source_uid else "AND 1 = 0"
            inbound_clause = "AND target_ref = ?"
            if source_uid:
                params_out = [project_id, source_uid]
            else:
                params_out = [project_id]
            params_in = [project_id, target]
        else:
            params_out = params_in = params
        outbound = []
        inbound = []
        if direction in {"outbound", "both"}:
            outbound = [
                hydrate_link(row)
                for row in self.conn.execute(
                    f"SELECT * FROM knowledge_links WHERE project_id = ? {outbound_clause} ORDER BY link_type",
                    params_out,
                ).fetchall()
            ]
        if direction in {"inbound", "both"}:
            inbound = [
                hydrate_link(row)
                for row in self.conn.execute(
                    f"SELECT * FROM knowledge_links WHERE project_id = ? {inbound_clause} ORDER BY link_type",
                    params_in,
                ).fetchall()
            ]
        return {"project_id": project_id, "target": target, "direction": direction, "outbound": outbound, "inbound": inbound}

    def list_findings(
        self,
        project_id: str,
        finding_type: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if finding_type:
            clauses.append("finding_type = ?")
            params.append(finding_type)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM consistency_findings
            WHERE {' AND '.join(clauses)}
            ORDER BY
              CASE severity
                WHEN 'critical' THEN 0
                WHEN 'high' THEN 1
                WHEN 'medium' THEN 2
                WHEN 'low' THEN 3
                ELSE 4
              END,
              finding_type,
              target_ref
            """,
            params,
        ).fetchall()
        return [hydrate_finding(row) for row in rows]

    def _check_supersede(self, project_id: str) -> list[dict[str, Any]]:
        adrs = self.knowledge.list_adrs(project_id, limit=5000)
        by_id = {adr["adr_id"]: adr for adr in adrs}
        findings = []
        superseded_by_target: dict[str, list[str]] = defaultdict(list)
        for adr in adrs:
            for target in adr.get("supersedes", []):
                superseded_by_target[target].append(adr["adr_id"])
                if target not in by_id:
                    findings.append(
                        finding(
                            "supersede_dangling",
                            adr["item_uid"],
                            "high",
                            f"{adr['adr_id']} supersedes missing ADR {target}.",
                            {"adr_id": adr["adr_id"], "missing": target},
                        )
                    )
                elif by_id[target]["status"].lower() in {"accepted", "active"}:
                    findings.append(
                        finding(
                            "supersede_status",
                            by_id[target]["item_uid"],
                            "medium",
                            f"{target} is superseded by {adr['adr_id']} but still marked {by_id[target]['status']}.",
                            {"superseded_by": adr["adr_id"]},
                        )
                    )
        for target, sources in superseded_by_target.items():
            active_sources = [source for source in sources if by_id.get(source, {}).get("status", "").lower() in {"accepted", "active"}]
            if len(active_sources) > 1:
                findings.append(
                    finding(
                        "supersede_duplicate",
                        target,
                        "medium",
                        f"Multiple active ADRs supersede {target}: {', '.join(active_sources)}.",
                        {"sources": active_sources},
                    )
                )
        for adr in adrs:
            seen = set()
            cursor = adr
            while cursor.get("supersedes"):
                nxt = cursor["supersedes"][0]
                if nxt in seen:
                    findings.append(
                        finding("supersede_cycle", adr["item_uid"], "critical", f"Supersede cycle starts at {adr['adr_id']}.", {})
                    )
                    break
                seen.add(nxt)
                cursor = by_id.get(nxt, {})
                if not cursor:
                    break
        return findings

    def _check_broken_links(self, project_id: str) -> list[dict[str, Any]]:
        findings = []
        rows = self.conn.execute("SELECT * FROM knowledge_links WHERE project_id = ?", (project_id,)).fetchall()
        for row in rows:
            target = row["target_ref"]
            if looks_like_source_path(target):
                continue
            if row["link_type"] == "references_adr" and looks_like_adr_id(target):
                continue
            if not self._ref_exists(project_id, target):
                findings.append(
                    finding(
                        "broken_link",
                        target,
                        "high",
                        f"Link {row['link_uid']} targets missing reference {target}.",
                        {"link_uid": row["link_uid"], "source_item_uid": row["source_item_uid"]},
                    )
                )
        return findings

    def _check_adr_uml(self, project_id: str) -> list[dict[str, Any]]:
        findings = []
        rows = self.conn.execute(
            """
            SELECT kl.*, ki.item_type, ki.local_id, ki.status
            FROM knowledge_links kl
            JOIN knowledge_items ki ON ki.item_uid = kl.source_item_uid
            WHERE kl.project_id = ?
              AND (kl.link_type LIKE '%uml%' OR kl.target_ref LIKE '%uml_%' OR kl.target_ref LIKE 'uml:%')
            """,
            (project_id,),
        ).fetchall()
        for row in rows:
            if looks_like_source_path(row["target_ref"]):
                continue
            if row["item_type"] == "adr" and not self._ref_exists(project_id, row["target_ref"]):
                findings.append(
                    finding(
                        "adr_uml_missing",
                        row["target_ref"],
                        "high",
                        f"ADR {row['local_id']} references missing UML target {row['target_ref']}.",
                        {"source_item_uid": row["source_item_uid"]},
                    )
                )
            if row["item_type"] == "uml_element":
                source_item = self.knowledge.get_item_by_uid(row["source_item_uid"])
                if source_item.get("status", "").lower() in {"superseded", "rejected"}:
                    findings.append(
                        finding(
                            "uml_linked_to_inactive_adr",
                            row["source_item_uid"],
                            "medium",
                            f"UML element is linked to inactive ADR target {row['target_ref']}.",
                            {},
                        )
                    )
        return findings

    def _check_overlap(self, project_id: str) -> list[dict[str, Any]]:
        findings = []
        conflict_links = self.conn.execute(
            """
            SELECT *
            FROM knowledge_links
            WHERE project_id = ? AND link_type = 'conflicts_with'
            """,
            (project_id,),
        ).fetchall()
        for row in conflict_links:
            findings.append(
                finding(
                    "explicit_conflict",
                    row["target_ref"],
                    "high",
                    f"{row['source_item_uid']} explicitly conflicts with {row['target_ref']}.",
                    {"link_uid": row["link_uid"], "evidence": row["evidence"]},
                )
            )
        rules = self.knowledge.list_items(project_id, include_types=["rule"], include_shared=False, limit=5000)
        for index, left in enumerate(rules):
            for right in rules[index + 1 :]:
                left_paths = set(left["details"].get("applies_to", []))
                right_paths = set(right["details"].get("applies_to", []))
                if left_paths and right_paths and left_paths.intersection(right_paths):
                    left_forbidden = set(text.lower() for text in left["details"].get("forbidden_changes", []))
                    right_text = right["details"].get("rule_text", "").lower()
                    if any(term and term in right_text for term in left_forbidden):
                        findings.append(
                            finding(
                                "overlapping_rule_conflict",
                                right["item_uid"],
                                "medium",
                                f"Rule {left['local_id']} may conflict with {right['local_id']} over shared scope.",
                                {"left": left["item_uid"], "right": right["item_uid"], "paths": sorted(left_paths & right_paths)},
                            )
                        )
        return findings

    def _check_orphans(self, project_id: str) -> list[dict[str, Any]]:
        findings = []
        rows = self.conn.execute(
            """
            SELECT ki.*
            FROM knowledge_items ki
            LEFT JOIN knowledge_links outgoing ON outgoing.source_item_uid = ki.item_uid
            LEFT JOIN knowledge_links incoming ON incoming.target_ref = ki.item_uid OR incoming.target_ref = ki.local_id
            WHERE ki.project_id = ?
              AND ki.item_type IN ('adr', 'uml_element')
            GROUP BY ki.item_uid
            HAVING COUNT(outgoing.link_uid) = 0 AND COUNT(incoming.link_uid) = 0
            """,
            (project_id,),
        ).fetchall()
        for row in rows:
            severity = "low" if row["item_type"] == "adr" else "info"
            findings.append(
                finding(
                    "orphan",
                    row["item_uid"],
                    severity,
                    f"{row['item_type']} {row['local_id']} has no knowledge links.",
                    {"item_type": row["item_type"], "local_id": row["local_id"]},
                )
            )
        return findings

    def _persist_finding(self, project_id: str, item: dict[str, Any]) -> None:
        finding_uid = digest_uid(
            "finding",
            project_id,
            item["finding_type"],
            item["target_ref"],
            item["message"],
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
            (
                finding_uid,
                project_id,
                item["finding_type"],
                item["target_ref"],
                item["severity"],
                item["message"],
                dumps(item.get("evidence", {})),
            ),
        )
        item["finding_uid"] = finding_uid

    def _graph(self, project_id: str) -> dict[str, list[dict[str, Any]]]:
        rows = self.conn.execute("SELECT * FROM knowledge_links WHERE project_id = ?", (project_id,)).fetchall()
        graph: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            graph[row["source_item_uid"]].append(hydrate_link(row))
        return graph

    def _resolve_source_uid(self, project_id: str, source: str) -> str:
        uid = self._try_resolve_source_uid(project_id, source)
        if uid is None:
            raise ValueError(f"Unknown source knowledge item: {source}")
        return uid

    def _try_resolve_source_uid(self, project_id: str, source: str) -> str | None:
        row = self.conn.execute(
            """
            SELECT item_uid
            FROM knowledge_items
            WHERE project_id = ?
              AND (item_uid = ? OR local_id = ? OR printf('%s:%s:%s', project_id, item_type, local_id) = ?)
            LIMIT 1
            """,
            (project_id, source, source, source),
        ).fetchone()
        return row["item_uid"] if row else None

    def _ref_exists(self, project_id: str, ref: str) -> bool:
        if self._try_resolve_source_uid(project_id, ref):
            return True
        if ref.startswith("uml:"):
            ref = ref.split(":", 1)[1]
        return (
            self.conn.execute(
                "SELECT 1 FROM uml_diagrams WHERE project_id = ? AND diagram_id = ?",
                (project_id, ref),
            ).fetchone()
            is not None
            or self.conn.execute(
                "SELECT 1 FROM uml_elements WHERE project_id = ? AND element_id = ?",
                (project_id, ref),
            ).fetchone()
            is not None
        )


def finding(
    finding_type: str,
    target_ref: str,
    severity: str,
    message: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "finding_type": finding_type,
        "target_ref": target_ref,
        "severity": severity,
        "message": message,
        "evidence": evidence,
    }


def hydrate_link(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "link_uid": row["link_uid"],
        "project_id": row["project_id"],
        "source_item_uid": row["source_item_uid"],
        "target_ref": row["target_ref"],
        "link_type": row["link_type"],
        "authority_level": row["authority_level"],
        "confidence": row["confidence"],
        "evidence": row["evidence"],
        "metadata": loads(row["metadata_json"], {}),
    }


def hydrate_finding(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "finding_uid": row["finding_uid"],
        "project_id": row["project_id"],
        "finding_type": row["finding_type"],
        "target_ref": row["target_ref"],
        "severity": row["severity"],
        "message": row["message"],
        "evidence": loads(row["evidence_json"], {}),
        "created_at": row["created_at"],
    }


def looks_like_source_path(ref: str) -> bool:
    return "/" in ref or "\\" in ref or ref.endswith((".py", ".ts", ".js", ".cpp", ".h", ".md", ".puml"))


def looks_like_adr_id(ref: str) -> bool:
    return bool(ADR_ID_RE.fullmatch(ref.strip()))
