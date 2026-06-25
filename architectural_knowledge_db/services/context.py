from __future__ import annotations

import re
import sqlite3
import uuid
from typing import Any

from architectural_knowledge_db.models import ContextPackRequest, model_dump
from architectural_knowledge_db.services.jsonutil import dumps
from architectural_knowledge_db.services.knowledge import KnowledgeService, normalize_path
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.search import SearchService


AUTHORITY_ORDER = {
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

NORMATIVE_LEVELS = {
    "hard_guardrail",
    "accepted_adr",
    "active_rule",
    "canonical_definition",
    "current_uml_model",
}


class ContextPackBuilder:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.search = SearchService(conn)
        self.knowledge = KnowledgeService(conn)

    def build(self, project_id: str, request: ContextPackRequest) -> dict[str, Any]:
        self.projects.require_project(project_id)
        include_types = request.include
        query_parts = [request.task, *request.source_paths]
        results = self.search.search(
            project_id,
            " ".join(query_parts),
            include_types=include_types,
            include_shared=True,
            limit=max(request.max_items, 1),
        )
        item_map = {result["item_uid"]: result for result in results}

        for source_path in request.source_paths:
            for item in self.knowledge.matching_rules_for_path(project_id, source_path):
                item_map.setdefault(item["item_uid"], item)
            for area in self.knowledge.matching_source_areas(project_id, source_path):
                knowledge_item = area.get("knowledge_item")
                if knowledge_item:
                    item_map.setdefault(knowledge_item["item_uid"], knowledge_item)

        items = sorted(
            item_map.values(),
            key=lambda item: (
                AUTHORITY_ORDER.get(item.get("authority_level", "project_note"), 99),
                item.get("item_type", ""),
                item.get("local_id", ""),
            ),
        )[: request.max_items]

        pack = {
            "context_pack_id": str(uuid.uuid4()),
            "project_id": project_id,
            "task": request.task,
            "summary": self._summary(project_id, request, items),
            "hard_guardrails": [],
            "accepted_adrs": [],
            "active_rules": [],
            "canonical_definitions": [],
            "uml_diagrams": [],
            "uml_elements": [],
            "source_areas": [],
            "notes": [],
            "evidence": {
                "git_provenance": [],
                "staleness": [],
            },
            "excluded": {
                "superseded": [],
            },
            "items": [],
            "authority_note": "Normative knowledge is separated from Git and co-change evidence.",
        }

        for item in items:
            normalized = normalize_item(item)
            if _is_superseded(item):
                pack["excluded"]["superseded"].append(normalized)
                continue
            authority = item.get("authority_level")
            if authority == "hard_guardrail":
                pack["hard_guardrails"].append(normalized)
            elif item.get("item_type") == "adr":
                pack["accepted_adrs"].append(normalized)
            elif authority == "active_rule" or item.get("item_type") == "rule":
                pack["active_rules"].append(normalized)
            elif item.get("item_type") == "definition":
                pack["canonical_definitions"].append(normalized)
            elif item.get("item_type") == "uml_diagram":
                pack["uml_diagrams"].append(normalized)
            elif item.get("item_type") == "uml_element":
                pack["uml_elements"].append(normalized)
            elif item.get("item_type") == "source_area":
                pack["source_areas"].append(normalized)
            else:
                pack["notes"].append(normalized)
            pack["items"].append(normalized)

        if request.include_git_provenance:
            pack["evidence"]["git_provenance"] = self._git_evidence(project_id, request.source_paths)
        if request.include_staleness:
            pack["evidence"]["staleness"] = self._staleness(project_id, request.source_paths)

        self.conn.execute(
            """
            INSERT INTO context_pack_runs(context_pack_id, project_id, task, request_json, response_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                pack["context_pack_id"],
                project_id,
                request.task,
                dumps(model_dump(request)),
                dumps(pack),
            ),
        )
        return pack

    def validate_task_context(
        self, project_id: str, task: str, source_paths: list[str] | None = None
    ) -> dict[str, Any]:
        request = ContextPackRequest(task=task, source_paths=source_paths or [], max_items=30)
        pack = self.build(project_id, request)
        findings: list[dict[str, Any]] = []
        task_lower = task.lower()
        seen: set[str] = set()

        # 1) Hard conflicts: a rule with an explicit forbidden_changes entry the task names.
        for rule in pack["active_rules"]:
            for forbidden in rule.get("details", {}).get("forbidden_changes", []):
                if forbidden and forbidden.lower() in task_lower:
                    findings.append(
                        {
                            "kind": "conflict",
                            "severity": rule.get("details", {}).get("severity", "high"),
                            "item_uid": rule["item_uid"],
                            "title": rule.get("title"),
                            "message": f"Task mentions forbidden change: {forbidden}",
                        }
                    )
                    seen.add(rule["item_uid"])

        # 2) Advisory: normative decisions (guardrails, ADRs, rules) whose own text
        #    overlaps the task. These govern the task even when no forbidden_changes
        #    list exists — so the agent is pointed at the decisions to read, instead
        #    of a falsely reassuring "all clear".
        terms = _significant_terms(task)
        normative = pack["hard_guardrails"] + pack["accepted_adrs"] + pack["active_rules"]
        advisory_count = 0
        for item in normative:
            uid = item.get("item_uid")
            if not uid or uid in seen:
                continue
            if _item_matches_terms(item, terms):
                findings.append(
                    {
                        "kind": "advisory",
                        "severity": "advisory",
                        "item_uid": uid,
                        "title": item.get("title"),
                        "authority_level": item.get("authority_level"),
                        "message": f"Relevant {item.get('authority_level') or 'decision'} — review before proceeding.",
                        "snippet": item.get("snippet"),
                    }
                )
                seen.add(uid)
                advisory_count += 1
                if advisory_count >= 8:
                    break

        has_conflict = any(f["kind"] == "conflict" for f in findings)
        has_advisory = any(f["kind"] == "advisory" for f in findings)
        verdict = "review" if has_conflict else ("review_advised" if has_advisory else "no_known_conflict")
        return {
            "project_id": project_id,
            "verdict": verdict,
            "findings": findings,
            "context_pack_id": pack["context_pack_id"],
        }

    def _summary(self, project_id: str, request: ContextPackRequest, items: list[dict[str, Any]]) -> str:
        return (
            f"Context pack for project '{project_id}' with {len(items)} knowledge items "
            f"for task: {request.task}"
        )

    def _git_evidence(self, project_id: str, source_paths: list[str]) -> list[dict[str, Any]]:
        if not source_paths:
            return []
        evidence = []
        for source_path in source_paths:
            rows = self.conn.execute(
                """
                SELECT repository_id, file_path, first_seen_commit_hash, first_seen_at,
                       last_changed_commit_hash, last_changed_at, change_count
                FROM git_file_history
                WHERE project_id = ? AND file_path = ?
                ORDER BY last_changed_at DESC
                """,
                (project_id, normalize_path(source_path)),
            ).fetchall()
            for row in rows:
                evidence.append(dict(row) | {"authority_level": "git_provenance_evidence"})
        return evidence

    def _staleness(self, project_id: str, source_paths: list[str]) -> list[dict[str, Any]]:
        params: list[Any] = [project_id]
        clause = ""
        if source_paths:
            normalized = [normalize_path(path) for path in source_paths]
            clause = f"AND target_ref IN ({','.join('?' for _ in normalized)})"
            params.extend(normalized)
        rows = self.conn.execute(
            f"""
            SELECT report_uid, target_ref, target_type, status, reason, evidence_json, created_at
            FROM staleness_reports
            WHERE project_id = ?
              {clause}
            ORDER BY created_at DESC
            LIMIT 20
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_uid": item.get("item_uid"),
        "project_id": item.get("project_id"),
        "space_id": item.get("space_id"),
        "item_type": item.get("item_type"),
        "local_id": item.get("local_id"),
        "title": item.get("title"),
        "status": item.get("status"),
        "authority_level": item.get("authority_level"),
        "authority_kind": "normative" if item.get("authority_level") in NORMATIVE_LEVELS else "evidence",
        "summary": item.get("summary"),
        "details": item.get("details", {}),
        "snippet": item.get("snippet"),
    }


_VALIDATE_STOPWORDS = frozenset(
    {
        "that", "this", "with", "from", "into", "make", "convert", "directly", "project",
        "files", "file", "using", "should", "would", "could", "without", "change", "changes",
        "update", "updates", "create", "remove", "delete", "service", "system", "support",
        "implement", "implementation", "feature", "module", "class", "function", "method",
        "value", "values", "bypassing", "bypass", "adding", "added",
    }
)


def _significant_terms(task: str) -> list[str]:
    terms = []
    for raw in re.findall(r"[A-Za-z0-9_]{4,}", task.lower()):
        if raw not in _VALIDATE_STOPWORDS and raw not in terms:
            terms.append(raw)
    return terms[:12]


def _item_matches_terms(item: dict[str, Any], terms: list[str]) -> bool:
    if not terms:
        return False
    haystack = " ".join(
        str(part)
        for part in (
            item.get("title"),
            item.get("summary"),
            item.get("snippet"),
            dumps(item.get("details", {})),
        )
        if part
    ).lower()
    return any(term in haystack for term in terms)


def _is_superseded(item: dict[str, Any]) -> bool:
    if item.get("authority_level") == "superseded_decision":
        return True
    details = item.get("details", {})
    superseded_by = details.get("superseded_by", [])
    return bool(superseded_by) or str(item.get("status", "")).lower() in {"superseded", "deprecated"}
