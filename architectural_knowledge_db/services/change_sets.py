from __future__ import annotations

import re
from typing import Any

from architectural_knowledge_db.models import AdrInput, ChangeItemInput, SadDecisionInput
from architectural_knowledge_db.services.authoring import AuthoringService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.sad import SadService
from architectural_knowledge_db.services.uml import UMLService


class ImpactParseError(ValueError):
    """Raised when an Architektur-Impact bullet is ambiguous or invalid."""


_OPS = {"add", "modify", "supersede", "remove"}


def _target(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"SAD:(\S+)\s+(decision|section)\s+(\S+)", value)
    if match:
        kind = "sad_decision" if match.group(2) == "decision" else "sad_section"
        return kind, f"{match.group(1)}:{match.group(3)}"
    if re.fullmatch(r"ADR-[A-Za-z0-9_.-]+(?:\s+\S.*)?", value):
        return "adr", value.split()[0]
    match = re.fullmatch(r"UML:element\s+(.+?)(?:\s+in\s+(\S+))?", value)
    if match:
        name, diagram = match.group(1), match.group(2)
        return "uml_element", f"{diagram}:{name}" if diagram else name
    match = re.fullmatch(r"UML:rel\s+(.+?)->(.+?)(?:\s+in\s+(\S+))?", value)
    if match:
        source, target, diagram = match.groups()
        rel = f"{source.strip()}->{target.strip()}"
        return "uml_relationship", f"{diagram}:{rel}" if diagram else rel
    match = re.fullmatch(r"rule\s+(.+)", value)
    if match:
        return "rule", match.group(1).strip()
    match = re.fullmatch(r"def\s+(.+)", value)
    if match:
        return "definition", match.group(1).strip()
    raise ImpactParseError(f"unknown or malformed impact target: {value}")


def parse_impact_section(markdown: str) -> list[ChangeItemInput]:
    lines = markdown.splitlines()
    start = next(
        (i + 1 for i, line in enumerate(lines) if re.fullmatch(r"##\s+Architektur-Impact\s*", line)),
        None,
    )
    if start is None:
        return []
    result: list[ChangeItemInput] = []
    for line in lines[start:]:
        if re.match(r"^#{1,6}\s+", line):
            break
        if not line.strip():
            continue
        if not re.match(r"^\s*-\s+", line):
            raise ImpactParseError(f"malformed impact line: {line}")
        body = re.sub(r"^\s*-\s+", "", line, count=1).strip()
        target_text, separator, note = body.partition("—")
        if not separator:
            target_text, separator, note = body.partition("â€”")
        parts = target_text.strip().split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in _OPS:
            op = parts[0] if parts else ""
            raise ImpactParseError(f"unknown or malformed impact operation: {op}")
        kind, ref = _target(parts[1].strip())
        op = parts[0]
        if op in {"remove", "supersede"} and kind in {"rule", "definition"}:
            raise ImpactParseError(
                f"{op} of {kind} is not supported in v1 (no delete path)"
            )
        result.append(
            ChangeItemInput(
                op=op,
                target_kind=kind,
                target_ref=ref,
                note=note.strip() or None,
            )
        )
    return result


def _rows(rows) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


class ChangeSetService:
    def __init__(self, conn):
        self.conn = conn

    def _items(self, project_id: str, spec_uid: str) -> list[dict[str, Any]]:
        return _rows(
            self.conn.execute(
                """
                SELECT id, project_id, spec_uid, op, target_kind, target_ref, state, note,
                       created_at, updated_at
                FROM change_items
                WHERE project_id = ? AND spec_uid = ?
                ORDER BY id
                """,
                (project_id, spec_uid),
            ).fetchall()
        )

    def ingest_impact(self, project_id: str, spec_uid: str, markdown: str) -> dict[str, Any]:
        parsed = parse_impact_section(markdown)
        created = 0
        updated = 0
        for item in parsed:
            exists = self.conn.execute(
                """
                SELECT id FROM change_items
                WHERE project_id=? AND spec_uid=? AND op=? AND target_kind=? AND target_ref=?
                """,
                (project_id, spec_uid, item.op, item.target_kind, item.target_ref),
            ).fetchone()
            self.conn.execute(
                """
                INSERT INTO change_items(project_id,spec_uid,op,target_kind,target_ref,state,note)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(project_id,spec_uid,op,target_kind,target_ref) DO UPDATE SET
                  note=excluded.note,
                  updated_at=CURRENT_TIMESTAMP
                """,
                (
                    project_id,
                    spec_uid,
                    item.op,
                    item.target_kind,
                    item.target_ref,
                    item.state,
                    item.note,
                ),
            )
            if exists:
                updated += 1
            else:
                created += 1
        return {"created": created, "updated": updated, "items": self._items(project_id, spec_uid)}

    def open_work_orders(self, project_id: str) -> list[dict[str, Any]]:
        specs = self.conn.execute(
            """
            SELECT DISTINCT ci.spec_uid, s.spec_id, ki.title, s.lifecycle
            FROM change_items ci
            JOIN specs s ON s.item_uid=ci.spec_uid
            JOIN knowledge_items ki ON ki.item_uid=ci.spec_uid
            WHERE ci.project_id=? AND ci.state!='done'
            ORDER BY s.spec_id
            """,
            (project_id,),
        ).fetchall()
        result = []
        for spec in specs:
            items = self._items(project_id, spec["spec_uid"])
            counts = {state: sum(i["state"] == state for i in items) for state in ("proposed", "in_progress", "done")}
            result.append(
                {
                    "spec_uid": spec["spec_uid"],
                    "spec_id": spec["spec_id"],
                    "title": spec["title"],
                    "lifecycle": spec["lifecycle"],
                    "open": counts["proposed"] + counts["in_progress"],
                    "in_progress": counts["in_progress"],
                    "done": counts["done"],
                    "items": items,
                }
            )
        return result

    def plan_basis(self, project_id: str, spec_uid: str) -> dict[str, Any]:
        spec = AuthoringService(self.conn).knowledge.get_item_by_uid(spec_uid)
        plan = AuthoringService(self.conn).spec_to_plan(project_id, spec_uid)
        return {
            "spec": spec,
            "change_items": self._items(project_id, spec_uid),
            "file_tasks": plan.get("tasks", []),
            "checkpoints": plan.get("checkpoints", []),
            **({"spec_to_plan_refused": plan.get("validation")} if plan.get("refused") else {}),
        }

    def set_item_state(self, project_id: str, change_item_id: int, state: str) -> dict[str, Any]:
        if state not in {"proposed", "in_progress", "done"}:
            raise ValueError(f"invalid change item state: {state}")
        before = self.conn.execute(
            "SELECT state FROM change_items WHERE project_id=? AND id=?",
            (project_id, change_item_id),
        ).fetchone()
        if not before:
            raise KeyError(f"change item not found: {change_item_id}")
        self.conn.execute(
            "UPDATE change_items SET state=?, updated_at=CURRENT_TIMESTAMP WHERE project_id=? AND id=?",
            (state, project_id, change_item_id),
        )
        item = dict(
            self.conn.execute(
                "SELECT * FROM change_items WHERE project_id=? AND id=?",
                (project_id, change_item_id),
            ).fetchone()
        )
        return {"changed": before["state"] != state, "item": item}

    # -- promote (reconcile two target classes into the Ist) --------------

    _CLOSING_OPS = {"supersede", "remove"}

    def promote(self, project_id: str, spec_uid: str, force: bool = False) -> dict[str, Any]:
        """One transaction: guard on open items, verify every target exists,
        apply status-flip/presence-verify/delete per kind, then close out.
        No mutation happens until every target has been resolved (§8/D3).
        """
        items = self._items(project_id, spec_uid)
        if not force and any(item["state"] != "done" for item in items):
            return {"refused": True, "reason": "open items"}

        resolved: list[tuple[dict[str, Any], Any]] = []
        for item in items:
            target = self._resolve_target(project_id, item)
            if target is None:
                return {"refused": True, "reason": f"target {item['target_ref']} not present"}
            resolved.append((item, target))

        promoted = []
        for item, target in resolved:
            self._apply_promotion(project_id, item, target)
            promoted.append(
                {
                    "id": item["id"],
                    "op": item["op"],
                    "target_kind": item["target_kind"],
                    "target_ref": item["target_ref"],
                }
            )

        for item in items:
            self.set_item_state(project_id, item["id"], "done")

        spec_result = AuthoringService(self.conn).set_spec_status(project_id, spec_uid, "implemented")
        return {"promoted": promoted, "spec": spec_result["spec"]}

    def _resolve_target(self, project_id: str, item: dict[str, Any]) -> Any:
        kind = item["target_kind"]
        ref = item["target_ref"]
        if kind == "adr":
            return self._resolve_adr(project_id, ref)
        if kind == "sad_decision":
            return self._resolve_sad_decision(project_id, ref)
        if kind == "sad_section":
            return self._resolve_sad_section(project_id, ref)
        if kind == "rule":
            return self._resolve_by_local_id(project_id, "rule", ref)
        if kind == "definition":
            return self._resolve_by_local_id(project_id, "definition", ref)
        if kind == "uml_element":
            return self._resolve_uml_element(project_id, ref)
        if kind == "uml_relationship":
            return self._resolve_uml_relationship(project_id, ref)
        raise ValueError(f"unknown change_item target_kind: {kind}")

    def _resolve_adr(self, project_id: str, adr_id: str) -> dict[str, Any] | None:
        try:
            return KnowledgeService(self.conn).get_adr(project_id, adr_id)
        except ValueError:
            return None

    def _resolve_by_local_id(self, project_id: str, item_type: str, local_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT item_uid FROM knowledge_items WHERE project_id=? AND item_type=? AND local_id=?",
            (project_id, item_type, local_id),
        ).fetchone()
        if row is None:
            return None
        return KnowledgeService(self.conn).get_item_by_uid(row["item_uid"])

    def _resolve_sad_decision(self, project_id: str, ref: str) -> dict[str, Any] | None:
        document_id, _, decision_id = ref.partition(":")
        try:
            document = SadService(self.conn).get_document(project_id, document_id)
        except ValueError:
            return None
        for decision in document["decisions"]:
            if (decision.get("metadata") or {}).get("decision_id") == decision_id:
                return decision
        return None

    def _resolve_sad_section(self, project_id: str, ref: str) -> dict[str, Any] | None:
        document_id, _, section_id = ref.partition(":")
        try:
            document = SadService(self.conn).get_document(project_id, document_id)
        except ValueError:
            return None
        for section in document["sections"]:
            if (section.get("metadata") or {}).get("section_id") == section_id:
                return section
        return None

    def _resolve_uml_element(self, project_id: str, ref: str) -> dict[str, Any] | None:
        uml = UMLService(self.conn)
        diagram_id, sep, name = ref.rpartition(":")
        if sep:
            try:
                diagram = uml.get_diagram(project_id, diagram_id)
            except ValueError:
                diagram = None
            if diagram:
                for element in diagram.get("elements", []):
                    if element["name"] == name or element["element_id"] == name:
                        return element
        try:
            return uml.get_element(project_id, ref)
        except ValueError:
            return None

    def _resolve_uml_relationship(self, project_id: str, ref: str) -> dict[str, Any] | None:
        match = re.fullmatch(r"(?:(?P<diagram>[^:]+):)?(?P<source>.+?)->(?P<target>.+)", ref)
        if not match:
            return None
        diagram_id = match.group("diagram")
        source_name = match.group("source").strip()
        target_name = match.group("target").strip()
        uml = UMLService(self.conn)
        if diagram_id:
            try:
                diagrams = [uml.get_diagram(project_id, diagram_id)]
            except ValueError:
                diagrams = []
        else:
            diagrams = [uml.get_diagram(project_id, d["diagram_id"]) for d in uml.list_diagrams(project_id, limit=5000)]
        for diagram in diagrams:
            elements = diagram.get("elements", [])
            source = next((e for e in elements if e["name"] == source_name or e["element_id"] == source_name), None)
            target = next((e for e in elements if e["name"] == target_name or e["element_id"] == target_name), None)
            if not source or not target:
                continue
            for relationship in diagram.get("relationships", []):
                if (
                    relationship["source_element_id"] == source["element_id"]
                    and relationship["target_element_id"] == target["element_id"]
                ):
                    return relationship
        return None

    def _apply_promotion(self, project_id: str, item: dict[str, Any], target: Any) -> None:
        kind = item["target_kind"]
        op = item["op"]
        ref = item["target_ref"]
        closing = op in self._CLOSING_OPS

        if kind == "adr":
            self._reupsert_adr(project_id, target, "superseded" if closing else "accepted")
            return
        if kind == "sad_decision":
            document_id, _, decision_id = ref.partition(":")
            self._reupsert_sad_decision(
                project_id, document_id, decision_id, target, "superseded" if closing else "current"
            )
            return
        if not closing:
            # presence-based, add|modify: presence already verified above — no status write.
            return
        if kind == "sad_section":
            document_id, _, section_id = ref.partition(":")
            SadService(self.conn).delete_section(project_id, document_id, section_id)
        elif kind == "uml_element":
            UMLService(self.conn).delete_element(project_id, target["element_id"])
        elif kind == "uml_relationship":
            UMLService(self.conn).delete_relationship(project_id, target["relationship_uid"])
        # rule/definition supersede|remove cannot occur here — rejected at parse (Task P2a).

    def _reupsert_adr(self, project_id: str, adr_item: dict[str, Any], status: str) -> None:
        KnowledgeService(self.conn).upsert_adr(
            project_id,
            AdrInput(
                adr_id=adr_item["adr_id"],
                title=adr_item["title"],
                status=status,
                context_md=adr_item.get("context_md"),
                decision_md=adr_item.get("decision_md"),
                consequences_md=adr_item.get("consequences_md"),
                supersedes=adr_item.get("supersedes", []),
                superseded_by=adr_item.get("superseded_by", []),
                authority_level=adr_item.get("authority_level") or "accepted_adr",
                summary=adr_item.get("summary"),
                source_uri=adr_item.get("source_uri"),
                metadata=adr_item.get("metadata", {}),
                raw_source=adr_item.get("raw_source"),
                sections=adr_item.get("sections", []),
            ),
        )

    def _reupsert_sad_decision(
        self, project_id: str, document_id: str, decision_id: str, decision_item: dict[str, Any], status: str
    ) -> None:
        metadata = decision_item.get("metadata") or {}
        title = decision_item["title"]
        prefix = f"{decision_id}: "
        if title.startswith(prefix):
            title = title[len(prefix):]
        SadService(self.conn).upsert_decision(
            project_id,
            SadDecisionInput(
                document_id=document_id,
                decision_id=decision_id,
                title=title,
                order=metadata.get("order", 0),
                status=status,
                body_md=metadata.get("body_md", ""),
                summary=decision_item.get("summary"),
            ),
        )
