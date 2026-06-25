from __future__ import annotations

import sqlite3
from typing import Any

from architectural_knowledge_db.services.knowledge import KnowledgeService, path_matches
from architectural_knowledge_db.services.projects import ProjectService


class GuardrailService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)

    def check_change(self, project_id: str, proposed: dict[str, Any]) -> dict[str, Any]:
        self.projects.require_project(project_id)
        path = proposed.get("path", "") or ""
        summary = proposed.get("summary", "") or ""
        haystack = f"{path}\n{summary}".lower()
        violations: list[dict[str, Any]] = []
        for rule in self.knowledge.list_items(project_id, include_types=["rule"], limit=1000):
            details = rule.get("details", {})
            applies_to = details.get("applies_to", [])
            if not applies_to or not any(path_matches(pattern, path) for pattern in applies_to):
                continue
            rule_id = details.get("rule_id") or rule["local_id"]
            for forbidden in details.get("forbidden_changes", []):
                if forbidden and forbidden.lower() in haystack:
                    violations.append({
                        "rule_id": rule_id,
                        "forbidden": forbidden,
                        "path": path,
                        "message": f"{rule_id} forbids '{forbidden}' on {path}.",
                    })
        return {"ok": not violations, "violations": violations}
