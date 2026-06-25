from __future__ import annotations

import sqlite3
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from architectural_knowledge_db.ids import digest_uid
from architectural_knowledge_db.services.jsonutil import dumps
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService

# contract "blocking" keys → spec_validate issue categories
_BLOCKING_CATEGORY = {
    "required_diagrams": "missing_required_diagrams",
    "file_map": "unresolved_file_map",
    "requires": "requires",
}
_COMPONENT_LEVEL = {"component", "container"}


@lru_cache(maxsize=1)
def _load_contracts() -> dict[str, Any]:
    text = resources.files("architectural_knowledge_db.completeness").joinpath(
        "archetype_requirements.yml"
    ).read_text(encoding="utf-8")
    return yaml.safe_load(text)


class CompletenessService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)

    def contract(self, archetype: str) -> dict[str, Any]:
        contracts = _load_contracts()
        if archetype not in contracts:
            raise ValueError(f"Unknown archetype: {archetype}")
        contract = dict(contracts[archetype])
        contract.setdefault("required_diagrams", [])
        contract.setdefault("file_map", "optional")
        contract.setdefault("blocking", [])
        contract.setdefault("requires", [])
        return contract

    def _resolve_item(self, project_id: str, ref: str) -> dict[str, Any] | None:
        try:
            return self.knowledge.get_item_by_uid(ref)
        except ValueError:
            pass
        row = self.conn.execute(
            "SELECT item_uid FROM knowledge_items WHERE project_id = ? AND local_id = ? LIMIT 1",
            (project_id, ref),
        ).fetchone()
        return self.knowledge.get_item_by_uid(row["item_uid"]) if row else None

    def _maps_to_files(self, project_id: str, item_uid: str) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT target_ref FROM knowledge_links
            WHERE project_id = ? AND source_item_uid = ? AND link_type = 'element_maps_to_file'
            ORDER BY target_ref
            """,
            (project_id, item_uid),
        ).fetchall()
        return [row["target_ref"] for row in rows]

    def spec_validate(self, project_id: str, spec_uid: str) -> dict[str, Any]:
        self.projects.require_project(project_id)
        spec = self.knowledge.get_item_by_uid(spec_uid)
        archetype = spec["details"].get("archetype")
        contract = self.contract(archetype)

        realized_kinds: set[str] = set()
        realized_elements: list[dict[str, Any]] = []
        dangling: list[str] = []
        links = self.conn.execute(
            """
            SELECT target_ref FROM knowledge_links
            WHERE project_id = ? AND source_item_uid = ? AND link_type = 'spec_realizes_uml'
            ORDER BY target_ref
            """,
            (project_id, spec_uid),
        ).fetchall()
        for link in links:
            item = self._resolve_item(project_id, link["target_ref"])
            if item is None:
                dangling.append(link["target_ref"])
                continue
            if item["item_type"] == "uml_diagram":
                kind = item["details"].get("diagram_kind")
                if kind:
                    realized_kinds.add(kind)
            elif item["item_type"] == "uml_element":
                realized_elements.append(item)

        missing_required_diagrams = [
            req for req in contract["required_diagrams"]
            if not any(alt in realized_kinds for alt in req.split("|"))
        ]

        filemap_targets: list[str] = []
        unresolved_file_map: list[str] = []
        for source_uid in [element["item_uid"] for element in realized_elements] + [spec_uid]:
            for target in self._maps_to_files(project_id, source_uid):
                filemap_targets.append(target)
                if not self.knowledge.matching_source_areas(project_id, target):
                    unresolved_file_map.append(target)
        if contract["file_map"] == "required" and not filemap_targets:
            unresolved_file_map.append("<no file-map>")

        requires_missing = [
            field for field in contract["requires"]
            if not (spec.get("metadata") or {}).get(field)
        ]

        uncovered_elements = [
            element["item_uid"]
            for element in realized_elements
            if str(element["details"].get("element_type", "")).lower() in _COMPONENT_LEVEL
            and not self._maps_to_files(project_id, element["item_uid"])
        ]

        all_issues = {
            "missing_required_diagrams": missing_required_diagrams,
            "unresolved_file_map": unresolved_file_map,
            "requires": requires_missing,
            "uncovered_elements": uncovered_elements,
            "dangling_refs": dangling,
        }
        blocking_categories = {_BLOCKING_CATEGORY.get(key, key) for key in contract["blocking"]}
        blocking = {cat: issues for cat, issues in all_issues.items() if cat in blocking_categories and issues}
        warnings = {cat: issues for cat, issues in all_issues.items() if cat not in blocking_categories and issues}

        self._persist(project_id, spec_uid, blocking, warnings)
        return {
            "spec_uid": spec_uid,
            "archetype": archetype,
            "blocking": blocking,
            "warnings": warnings,
            "ok": not any(blocking.values()),
        }

    def _persist(self, project_id: str, spec_uid: str, blocking: dict, warnings: dict) -> None:
        self.conn.execute(
            "DELETE FROM consistency_findings WHERE project_id = ? AND finding_type LIKE 'completeness:%' AND target_ref = ?",
            (project_id, spec_uid),
        )
        for severity, bucket in (("high", blocking), ("low", warnings)):
            for category, issues in bucket.items():
                for issue in issues:
                    message = f"{category}: {issue}"
                    finding_uid = digest_uid("finding", project_id, f"completeness:{category}", spec_uid, message)
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
                        (finding_uid, project_id, f"completeness:{category}", spec_uid, severity, message,
                         dumps({"spec_uid": spec_uid, "issue": str(issue)})),
                    )
