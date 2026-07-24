from __future__ import annotations

import re
from typing import Any

from architectural_knowledge_db.models import ChangeItemInput
from architectural_knowledge_db.services.authoring import AuthoringService


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
