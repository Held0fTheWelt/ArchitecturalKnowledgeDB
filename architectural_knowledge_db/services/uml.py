from __future__ import annotations

import re
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any

from architectural_knowledge_db.ids import digest_uid, stable_uid
from architectural_knowledge_db.models import (
    KnowledgeLinkInput,
    UMLDiagramInput,
    UMLDiagramUpdate,
    UMLElementInput,
    UMLElementUpdate,
    UMLRelationshipInput,
    UMLRelationshipUpdate,
)
from architectural_knowledge_db.services.jsonutil import dumps, loads
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService, project_space_id


ELEMENT_RE = re.compile(
    r'^\s*(?P<kind>abstract\s+class|class|interface|enum|actor|usecase|state|participant|database|queue|object|component)\s+'
    r'(?P<name>"[^"]+"|[A-Za-z0-9_.:/ -]+?)'
    r'(?:\s+as\s+(?P<alias>[A-Za-z0-9_.:-]+))?'
    r'(?:\s+(?P<stereotype><<[^>]+>>))?'
    r'\s*(?:\{)?\s*$',
    re.IGNORECASE,
)
RELATIONSHIP_RE = re.compile(
    r"^\s*(?P<source>\"[^\"]+\"|[A-Za-z0-9_.:-]+)\s+"
    r"(?P<arrow>[.<|*o+]?[-.=]+[->.<|*o+]+|-->|->|<--|<-|--|\.\.>)\s+"
    r"(?P<target>\"[^\"]+\"|[A-Za-z0-9_.:-]+)"
    r"(?:\s*:\s*(?P<label>.*))?\s*$"
)
TITLE_RE = re.compile(r"^\s*title\s+(?P<title>.+?)\s*$", re.IGNORECASE)
MERMAID_EDGE_RE = re.compile(
    r"^\s*(?P<source>[A-Za-z0-9_]+)(?:\[[^\]]+\])?\s*[-.=]+>\s*(?:\|(?P<label>[^|]+)\|)?\s*(?P<target>[A-Za-z0-9_]+)(?:\[[^\]]+\])?"
)
MERMAID_NODE_RE = re.compile(r"(?P<id>[A-Za-z0-9_]+)\[(?P<label>[^\]]+)\]")


class UMLService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)

    def import_diagrams(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        self.projects.require_project(project_id)
        root = Path(folder)
        if not root.exists():
            raise ValueError(f"UML folder does not exist: {root}")
        imported = []
        diagram_paths = sorted(
            [
                *root.rglob("*.puml"),
                *root.rglob("*.plantuml"),
                *root.rglob("*.mmd"),
                *root.rglob("*.mermaid"),
            ]
        )
        skipped = []
        for path in diagram_paths:
            source_key = path.relative_to(root).as_posix()
            if is_template_or_include_path(source_key):
                skipped.append(source_key)
                continue
            text = _read_text_exact(path)
            if path.suffix.lower() in {".mmd", ".mermaid"}:
                parsed = parse_mermaid(text, source_uri=str(path), source_key=source_key)
            else:
                parsed = parse_plantuml(text, source_uri=str(path), source_key=source_key)
            parsed["model"]["repo_source_key"] = repo_relative_key(path)
            imported.append(self.upsert_diagram(project_id, parsed))
        result = {
            "project_id": project_id,
            "folder": str(root),
            "imported": len(imported),
            "skipped": skipped,
            "diagrams": [{"diagram_id": item["diagram_id"], "title": item["title"]} for item in imported],
        }
        from architectural_knowledge_db.services.import_export import ImportExportService

        return ImportExportService(self.conn)._with_auto_export(project_id, result)

    def export_diagrams(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        self.projects.require_project(project_id)
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        exported = []
        for diagram in self.list_diagrams(project_id, limit=5000):
            filename = diagram.get("model", {}).get("source_key") or f"{safe_filename(diagram['diagram_id'])}.puml"
            path = _target_for_source_key(root, filename, f"{safe_filename(diagram['diagram_id'])}.puml")
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_text_exact(path, self.render_diagram(project_id, diagram["diagram_id"]))
            exported.append(str(path))
        return {"project_id": project_id, "folder": str(root), "exported": len(exported), "files": exported}

    def upsert_diagram(self, project_id: str, parsed: dict[str, Any]) -> dict[str, Any]:
        self.projects.require_project(project_id)
        space_id = project_space_id(project_id)
        if self.conn.execute("SELECT 1 FROM knowledge_spaces WHERE space_id = ?", (space_id,)).fetchone() is None:
            self.projects.ensure_project_space(project_id)

        diagram_uid = stable_uid(project_id, "uml_diagram_record", parsed["diagram_id"])
        self.conn.execute(
            """
            INSERT INTO uml_diagrams(
              diagram_uid, project_id, space_id, diagram_id, title, notation,
              source_uri, model_json, last_model_update_at, raw_source, diagram_kind
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT(project_id, diagram_id) DO UPDATE SET
              title = excluded.title,
              notation = excluded.notation,
              source_uri = excluded.source_uri,
              model_json = excluded.model_json,
              last_model_update_at = CURRENT_TIMESTAMP,
              raw_source = excluded.raw_source,
              diagram_kind = excluded.diagram_kind
            """,
            (
                diagram_uid,
                project_id,
                space_id,
                parsed["diagram_id"],
                parsed["title"],
                parsed.get("notation", "plantuml"),
                parsed.get("source_uri"),
                dumps(parsed["model"]),
                parsed.get("raw_source"),
                parsed.get("diagram_kind", "unknown"),
            ),
        )
        item_uid = self.knowledge._upsert_item(
            project_id=project_id,
            space_id=space_id,
            item_type="uml_diagram",
            local_id=parsed["diagram_id"],
            title=parsed["title"],
            status="current",
            authority_level="current_uml_model",
            summary=f"{parsed.get('diagram_kind', 'unknown')} PlantUML diagram",
            source_uri=parsed.get("source_uri"),
            metadata={
                "diagram_uid": diagram_uid,
                "source_key": parsed.get("model", {}).get("source_key"),
                "repo_source_key": parsed.get("model", {}).get("repo_source_key"),
                "sad_document_id": parsed.get("model", {}).get("sad_document_id"),
                "authored_in": parsed.get("model", {}).get("authored_in"),
            },
        )
        self.knowledge._index_item(item_uid)
        if parsed.get("model", {}).get("repo_source_key"):
            self.knowledge.upsert_link(
                project_id,
                KnowledgeLinkInput(
                    source_item_uid=item_uid,
                    target_ref=parsed["model"]["repo_source_key"],
                    link_type="defined_in",
                    authority_level="evidence",
                    confidence="explicit",
                    evidence="UML import source path",
                    metadata={"importer": "uml"},
                ),
            )

        self.conn.execute(
            "DELETE FROM uml_relationships WHERE project_id = ? AND metadata_json LIKE ?",
            (project_id, f'%"diagram_id": "{parsed["diagram_id"]}"%'),
        )
        existing = self.conn.execute(
            "SELECT element_uid FROM uml_elements WHERE project_id = ? AND diagram_uid = ?",
            (project_id, diagram_uid),
        ).fetchall()
        for row in existing:
            self.conn.execute(
                "DELETE FROM knowledge_links WHERE project_id = ? AND source_item_uid = ?",
                (project_id, row["element_uid"]),
            )
            self.conn.execute("DELETE FROM fts_knowledge WHERE item_uid = ?", (row["element_uid"],))
            self.conn.execute("DELETE FROM knowledge_items WHERE item_uid = ?", (row["element_uid"],))
        self.conn.execute("DELETE FROM uml_elements WHERE project_id = ? AND diagram_uid = ?", (project_id, diagram_uid))

        for element in parsed["elements"]:
            self.add_element(project_id, UMLElementInput(diagram_id=parsed["diagram_id"], **element), mark_dirty=False)
        for relationship in parsed["relationships"]:
            self.add_relationship(
                project_id,
                UMLRelationshipInput(diagram_id=parsed["diagram_id"], **relationship),
                mark_dirty=False,
            )
        return self.get_diagram(project_id, parsed["diagram_id"])

    def list_diagrams(self, project_id: str, kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        params: list[Any] = [project_id]
        kind_clause = ""
        if kind:
            kind_clause = "AND diagram_kind = ?"
            params.append(kind)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM uml_diagrams
            WHERE project_id = ?
              {kind_clause}
            ORDER BY diagram_id
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._hydrate_diagram(row, include_children=False) for row in rows]

    def get_diagram(self, project_id: str, diagram_id: str) -> dict[str, Any]:
        self.projects.require_project(project_id)
        row = self.conn.execute(
            "SELECT * FROM uml_diagrams WHERE project_id = ? AND diagram_id = ?",
            (project_id, diagram_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown UML diagram in project {project_id}: {diagram_id}")
        return self._hydrate_diagram(row, include_children=True)

    def create_diagram(self, project_id: str, request: UMLDiagramInput) -> dict[str, Any]:
        try:
            self.get_diagram(project_id, request.diagram_id)
        except ValueError:
            pass
        else:
            raise ValueError(f"UML diagram already exists in project {project_id}: {request.diagram_id}")
        if request.notation not in {"plantuml", "mermaid"}:
            raise ValueError("DB-native UML authoring supports plantuml and mermaid notation.")
        model = dict(request.model)
        source_key = model.get("source_key") or (
            f"UML/{safe_filename(request.diagram_id)}.mmd"
            if request.notation == "mermaid"
            else f"UML/{safe_filename(request.diagram_id)}.puml"
        )
        model["source_key"] = _safe_authored_source_key(source_key)
        self._require_available_source_key(project_id, request.diagram_id, model["source_key"])
        self._require_sad_document(project_id, model.get("sad_document_id"))
        raw = request.raw_source
        if not raw:
            if request.notation == "mermaid":
                raw = f"flowchart TD\n  Root[{request.title}]\n"
            else:
                raw = f"@startuml {request.diagram_id}\ntitle {request.title}\n@enduml\n"
        parsed = (
            parse_mermaid(
                raw,
                source_uri=f"akdb://{project_id}/uml/{request.diagram_id}",
                source_key=model["source_key"],
            )
            if request.notation == "mermaid"
            else parse_plantuml(
                raw,
                source_uri=f"akdb://{project_id}/uml/{request.diagram_id}",
                source_key=model["source_key"],
            )
        )
        parsed.update(
            {
                "diagram_id": request.diagram_id,
                "title": request.title,
                "notation": request.notation,
                "diagram_kind": request.diagram_kind,
                "source_uri": f"akdb://{project_id}/uml/{request.diagram_id}",
            }
        )
        parsed["model"].update(model)
        parsed["model"]["authored_in"] = "akdb"
        return self.upsert_diagram(project_id, parsed)

    def update_diagram(
        self, project_id: str, diagram_id: str, changes: UMLDiagramUpdate
    ) -> dict[str, Any]:
        current = self.get_diagram(project_id, diagram_id)
        if changes.notation is not None and changes.notation not in {"plantuml", "mermaid"}:
            raise ValueError("DB-native UML authoring supports plantuml and mermaid notation.")
        if changes.source_key is not None:
            source_key = _safe_authored_source_key(changes.source_key)
            self._require_available_source_key(project_id, diagram_id, source_key)
        else:
            source_key = (current.get("model") or {}).get("source_key")
        self._require_sad_document(project_id, changes.sad_document_id)
        if changes.raw_source is not None:
            notation = changes.notation or current["notation"]
            source_key = source_key or (
                f"UML/{safe_filename(diagram_id)}.mmd"
                if notation == "mermaid"
                else f"UML/{safe_filename(diagram_id)}.puml"
            )
            parsed = (
                parse_mermaid(
                    changes.raw_source,
                    source_uri=f"akdb://{project_id}/uml/{diagram_id}",
                    source_key=source_key,
                )
                if notation == "mermaid"
                else parse_plantuml(
                    changes.raw_source,
                    source_uri=f"akdb://{project_id}/uml/{diagram_id}",
                    source_key=source_key,
                )
            )
            parsed["diagram_id"] = diagram_id
            parsed["title"] = changes.title or current["title"]
            parsed["notation"] = notation
            parsed["diagram_kind"] = changes.diagram_kind or parsed["diagram_kind"]
            parsed["model"]["sad_document_id"] = (
                changes.sad_document_id
                if changes.sad_document_id is not None
                else (current.get("model") or {}).get("sad_document_id")
            )
            current_repo_source_key = (current.get("model") or {}).get(
                "repo_source_key"
            )
            if current_repo_source_key:
                parsed["model"]["repo_source_key"] = current_repo_source_key
            parsed["model"]["authored_in"] = "akdb"
            return self.upsert_diagram(project_id, parsed)

        model = dict(current.get("model") or {})
        if changes.source_key is not None:
            model["source_key"] = source_key
        if changes.sad_document_id is not None:
            model["sad_document_id"] = changes.sad_document_id
        model["authored_in"] = "akdb"
        self.conn.execute(
            """
            UPDATE uml_diagrams
            SET title = COALESCE(?, title),
                notation = COALESCE(?, notation),
                diagram_kind = COALESCE(?, diagram_kind),
                source_uri = ?,
                model_json = ?,
                last_model_update_at = CURRENT_TIMESTAMP
            WHERE project_id = ? AND diagram_id = ?
            """,
            (
                changes.title,
                changes.notation,
                changes.diagram_kind,
                f"akdb://{project_id}/uml/{diagram_id}",
                dumps(model),
                project_id,
                diagram_id,
            ),
        )
        item_uid = stable_uid(project_id, "uml_diagram", diagram_id)
        self.conn.execute(
            """
            UPDATE knowledge_items
            SET title = COALESCE(?, title), source_uri = ?, summary = ?, metadata_json = ?
            WHERE item_uid = ?
            """,
            (
                changes.title,
                f"akdb://{project_id}/uml/{diagram_id}",
                f"{changes.diagram_kind or current['diagram_kind']} {changes.notation or current['notation']} diagram",
                dumps(
                    {
                        "diagram_uid": current["diagram_uid"],
                        "source_key": model.get("source_key"),
                        "sad_document_id": model.get("sad_document_id"),
                        "authored_in": "akdb",
                    }
                ),
                item_uid,
            ),
        )
        self.knowledge._index_item(item_uid)
        return self.get_diagram(project_id, diagram_id)

    def _require_available_source_key(
        self, project_id: str, diagram_id: str, source_key: str
    ) -> None:
        row = self.conn.execute(
            """
            SELECT diagram_id FROM uml_diagrams
            WHERE project_id = ?
              AND json_extract(model_json, '$.source_key') = ?
              AND diagram_id <> ?
            """,
            (project_id, source_key, diagram_id),
        ).fetchone()
        if row is not None:
            raise ValueError(
                f"UML source_key is already used by diagram {row['diagram_id']}: {source_key}"
            )

    def _require_sad_document(self, project_id: str, document_id: str | None) -> None:
        if document_id is None:
            return
        row = self.conn.execute(
            """
            SELECT 1 FROM knowledge_items
            WHERE project_id = ? AND item_type = 'sad' AND local_id = ?
            """,
            (project_id, document_id),
        ).fetchone()
        if row is None:
            raise ValueError(
                f"Unknown SAD document in project {project_id}: {document_id}"
            )

    def delete_diagram(self, project_id: str, diagram_id: str) -> dict[str, Any]:
        diagram = self.get_diagram(project_id, diagram_id)
        element_rows = self.conn.execute(
            "SELECT element_uid FROM uml_elements WHERE project_id = ? AND diagram_uid = ?",
            (project_id, diagram["diagram_uid"]),
        ).fetchall()
        element_uids = [row["element_uid"] for row in element_rows]
        for uid in element_uids:
            self.conn.execute(
                "DELETE FROM uml_relationships WHERE source_element_uid = ? OR target_element_uid = ?",
                (uid, uid),
            )
            self.conn.execute(
                "DELETE FROM knowledge_links WHERE source_item_uid = ? OR target_ref = ?",
                (uid, uid),
            )
            self.conn.execute("DELETE FROM fts_knowledge WHERE item_uid = ?", (uid,))
            self.conn.execute("DELETE FROM knowledge_items WHERE item_uid = ?", (uid,))
        self.conn.execute(
            "DELETE FROM uml_elements WHERE project_id = ? AND diagram_uid = ?",
            (project_id, diagram["diagram_uid"]),
        )
        item_uid = stable_uid(project_id, "uml_diagram", diagram_id)
        self.conn.execute(
            "DELETE FROM knowledge_links WHERE source_item_uid = ? OR target_ref = ?",
            (item_uid, item_uid),
        )
        self.conn.execute("DELETE FROM fts_knowledge WHERE item_uid = ?", (item_uid,))
        self.conn.execute("DELETE FROM knowledge_items WHERE item_uid = ?", (item_uid,))
        self.conn.execute(
            "DELETE FROM uml_diagrams WHERE project_id = ? AND diagram_id = ?",
            (project_id, diagram_id),
        )
        return {"project_id": project_id, "diagram_id": diagram_id, "deleted": True}

    def add_element(self, project_id: str, request: UMLElementInput, mark_dirty: bool = True) -> dict[str, Any]:
        diagram = self.get_diagram(project_id, request.diagram_id)
        element_id = request.element_id or local_element_id(request.diagram_id, request.name)
        element_uid = stable_uid(project_id, "uml_element", element_id)
        metadata = request.metadata | {"diagram_id": request.diagram_id}
        self.conn.execute(
            """
            INSERT INTO uml_elements(
              element_uid, project_id, diagram_uid, element_id, element_type, name, description, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, element_id) DO UPDATE SET
              diagram_uid = excluded.diagram_uid,
              element_type = excluded.element_type,
              name = excluded.name,
              description = excluded.description,
              metadata_json = excluded.metadata_json
            """,
            (
                element_uid,
                project_id,
                diagram["diagram_uid"],
                element_id,
                request.element_type,
                request.name,
                request.description,
                dumps(metadata),
            ),
        )
        item_uid = self.knowledge._upsert_item(
            project_id=project_id,
            space_id=diagram["space_id"],
            item_type="uml_element",
            local_id=element_id,
            title=request.name,
            status="current",
            authority_level="current_uml_model",
            summary=request.description,
            source_uri=diagram.get("source_uri"),
            metadata={"diagram_id": request.diagram_id, "diagram_uid": diagram["diagram_uid"]},
        )
        self.knowledge._index_item(item_uid)
        self.knowledge.upsert_link(
            project_id,
            KnowledgeLinkInput(
                source_item_uid=item_uid,
                target_ref=request.diagram_id,
                link_type="part_of_diagram",
                authority_level="evidence",
                confidence="derived",
                evidence="UML element imported from diagram",
                metadata={"diagram_id": request.diagram_id},
            ),
        )
        if mark_dirty:
            self._mark_dirty(project_id, request.diagram_id)
        return self.get_element(project_id, element_id)

    def update_element(self, project_id: str, element_id: str, changes: UMLElementUpdate) -> dict[str, Any]:
        current = self.get_element(project_id, element_id)
        metadata = current["metadata"]
        if changes.metadata is not None:
            metadata.update(changes.metadata)
        self.conn.execute(
            """
            UPDATE uml_elements
            SET element_type = COALESCE(?, element_type),
                name = COALESCE(?, name),
                description = COALESCE(?, description),
                metadata_json = ?
            WHERE project_id = ? AND element_id = ?
            """,
            (
                changes.element_type,
                changes.name,
                changes.description,
                dumps(metadata),
                project_id,
                element_id,
            ),
        )
        self.conn.execute(
            """
            UPDATE knowledge_items
            SET title = COALESCE(?, title),
                summary = COALESCE(?, summary),
                metadata_json = ?
            WHERE item_uid = ?
            """,
            (
                changes.name,
                changes.description,
                dumps({"diagram_id": current["diagram_id"], "diagram_uid": current["diagram_uid"]}),
                current["element_uid"],
            ),
        )
        self.knowledge._index_item(current["element_uid"])
        self._mark_dirty(project_id, current["diagram_id"])
        return self.get_element(project_id, element_id)

    def delete_element(self, project_id: str, element_id: str) -> dict[str, Any]:
        current = self.get_element(project_id, element_id)
        self.conn.execute(
            "DELETE FROM uml_relationships WHERE source_element_uid = ? OR target_element_uid = ?",
            (current["element_uid"], current["element_uid"]),
        )
        self.conn.execute(
            "DELETE FROM knowledge_links WHERE source_item_uid = ? OR target_ref = ?",
            (current["element_uid"], current["element_uid"]),
        )
        self.conn.execute("DELETE FROM fts_knowledge WHERE item_uid = ?", (current["element_uid"],))
        self.conn.execute("DELETE FROM knowledge_items WHERE item_uid = ?", (current["element_uid"],))
        self.conn.execute(
            "DELETE FROM uml_elements WHERE project_id = ? AND element_id = ?",
            (project_id, element_id),
        )
        self._mark_dirty(project_id, current["diagram_id"])
        return {"project_id": project_id, "element_id": element_id, "deleted": True}

    def get_element(self, project_id: str, element_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT e.*, d.diagram_id
            FROM uml_elements e
            LEFT JOIN uml_diagrams d ON d.diagram_uid = e.diagram_uid
            WHERE e.project_id = ? AND e.element_id = ?
            """,
            (project_id, element_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown UML element in project {project_id}: {element_id}")
        return hydrate_element(row)

    def add_relationship(
        self, project_id: str, request: UMLRelationshipInput, mark_dirty: bool = True
    ) -> dict[str, Any]:
        diagram = self.get_diagram(project_id, request.diagram_id)
        source = self.get_element(project_id, request.source_element_id)
        target = self.get_element(project_id, request.target_element_id)
        relationship_uid = digest_uid(
            "uml_relationship",
            project_id,
            request.diagram_id,
            request.source_element_id,
            request.target_element_id,
            request.relationship_type,
            request.label or "",
        )
        self.conn.execute(
            """
            INSERT INTO uml_relationships(
              relationship_uid, project_id, source_element_uid, target_element_uid,
              relationship_type, label, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(relationship_uid) DO UPDATE SET
              relationship_type = excluded.relationship_type,
              label = excluded.label,
              metadata_json = excluded.metadata_json
            """,
            (
                relationship_uid,
                project_id,
                source["element_uid"],
                target["element_uid"],
                request.relationship_type,
                request.label,
                dumps(request.metadata | {"diagram_id": request.diagram_id}),
            ),
        )
        if mark_dirty:
            self._mark_dirty(project_id, request.diagram_id)
        return dict(self.conn.execute("SELECT * FROM uml_relationships WHERE relationship_uid = ?", (relationship_uid,)).fetchone())

    def update_relationship(
        self, project_id: str, relationship_uid: str, changes: UMLRelationshipUpdate
    ) -> dict[str, Any]:
        current = self._get_relationship(project_id, relationship_uid)
        metadata = loads(current["metadata_json"], {})
        if changes.metadata is not None:
            metadata.update(changes.metadata)
        self.conn.execute(
            """
            UPDATE uml_relationships
            SET relationship_type = COALESCE(?, relationship_type),
                label = COALESCE(?, label),
                metadata_json = ?
            WHERE project_id = ? AND relationship_uid = ?
            """,
            (
                changes.relationship_type,
                changes.label,
                dumps(metadata),
                project_id,
                relationship_uid,
            ),
        )
        diagram_id = metadata.get("diagram_id")
        if diagram_id:
            self._mark_dirty(project_id, diagram_id)
        return dict(self._get_relationship(project_id, relationship_uid))

    def delete_relationship(self, project_id: str, relationship_uid: str) -> dict[str, Any]:
        current = self._get_relationship(project_id, relationship_uid)
        metadata = loads(current["metadata_json"], {})
        self.conn.execute(
            "DELETE FROM uml_relationships WHERE project_id = ? AND relationship_uid = ?",
            (project_id, relationship_uid),
        )
        if metadata.get("diagram_id"):
            self._mark_dirty(project_id, metadata["diagram_id"])
        return {"project_id": project_id, "relationship_uid": relationship_uid, "deleted": True}

    def _get_relationship(self, project_id: str, relationship_uid: str) -> Any:
        row = self.conn.execute(
            """
            SELECT * FROM uml_relationships
            WHERE project_id = ? AND relationship_uid = ?
            """,
            (project_id, relationship_uid),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown UML relationship in project {project_id}: {relationship_uid}")
        return row

    def render_diagram(self, project_id: str, diagram_id: str) -> str:
        diagram = self.get_diagram(project_id, diagram_id)
        model = diagram.get("model", {})
        if diagram.get("raw_source") and not model.get("dirty"):
            raw = diagram["raw_source"]
            return raw if raw.endswith("\n") else f"{raw}\n"
        if diagram.get("notation") == "mermaid":
            raw = diagram.get("raw_source") or ""
            return raw if raw.endswith("\n") else f"{raw}\n"

        lines: list[str] = []
        lines.append(model.get("start_line") or "@startuml\n")
        for passthrough in model.get("header_passthrough", []):
            lines.append(_line(passthrough))
        if diagram.get("title") and not any(line.lower().startswith("title ") for line in model.get("header_passthrough", [])):
            lines.append(f"title {diagram['title']}\n")
        for element in diagram["elements"]:
            lines.append(render_element(element))
        for relationship in diagram["relationships"]:
            lines.append(render_relationship(relationship))
        for passthrough in model.get("body_passthrough", []):
            if passthrough.strip().lower() not in {"@enduml", ""}:
                lines.append(_line(passthrough))
        lines.append(model.get("end_line") or "@enduml\n")
        return "".join(lines)

    def check_roundtrip(self, folder: str | Path) -> dict[str, Any]:
        root = Path(folder)
        checked = []
        for path in sorted(root.rglob("*.puml")):
            text = _read_text_exact(path)
            parsed = parse_plantuml(text, source_uri=str(path), source_key=str(path.relative_to(root)))
            rendered = render_parsed_passthrough(parsed)
            reparsed = parse_plantuml(rendered, source_uri=str(path), source_key=str(path.relative_to(root)))
            checked.append(
                {
                    "file": str(path),
                    "diagram_id": parsed["diagram_id"],
                    "model_equal": comparable_model(parsed) == comparable_model(reparsed),
                    "raw_preserved": parsed["raw_source"] == text,
                }
            )
        return {
            "folder": str(root),
            "checked": len(checked),
            "passed": all(item["model_equal"] and item["raw_preserved"] for item in checked),
            "files": checked,
        }

    def _hydrate_diagram(self, row: sqlite3.Row, include_children: bool) -> dict[str, Any]:
        result = dict(row)
        result["model"] = loads(result.pop("model_json"), {})
        if include_children:
            result["elements"] = [
                hydrate_element(element)
                for element in self.conn.execute(
                    """
                    SELECT e.*, d.diagram_id
                    FROM uml_elements e
                    JOIN uml_diagrams d ON d.diagram_uid = e.diagram_uid
                    WHERE e.project_id = ? AND e.diagram_uid = ?
                    ORDER BY e.element_id
                    """,
                    (result["project_id"], result["diagram_uid"]),
                ).fetchall()
            ]
            result["relationships"] = [
                hydrate_relationship(relationship)
                for relationship in self.conn.execute(
                    """
                    SELECT r.*, se.element_id AS source_element_id, te.element_id AS target_element_id
                    FROM uml_relationships r
                    JOIN uml_elements se ON se.element_uid = r.source_element_uid
                    JOIN uml_elements te ON te.element_uid = r.target_element_uid
                    WHERE r.project_id = ?
                      AND json_extract(r.metadata_json, '$.diagram_id') = ?
                    ORDER BY r.relationship_uid
                    """,
                    (result["project_id"], result["diagram_id"]),
                ).fetchall()
            ]
        return result

    def _mark_dirty(self, project_id: str, diagram_id: str) -> None:
        row = self.conn.execute(
            "SELECT model_json FROM uml_diagrams WHERE project_id = ? AND diagram_id = ?",
            (project_id, diagram_id),
        ).fetchone()
        if row is None:
            return
        model = loads(row["model_json"], {})
        model["dirty"] = True
        self.conn.execute(
            """
            UPDATE uml_diagrams
            SET model_json = ?, last_model_update_at = CURRENT_TIMESTAMP
            WHERE project_id = ? AND diagram_id = ?
            """,
            (dumps(model), project_id, diagram_id),
        )


def parse_plantuml(text: str, source_uri: str | None = None, source_key: str | None = None) -> dict[str, Any]:
    source_key = source_key or (Path(source_uri).name if source_uri else "diagram.puml")
    diagram_id = re.sub(r"[^A-Za-z0-9]+", "-", str(Path(source_key).with_suffix(""))).strip("-").lower()
    lines = text.splitlines(keepends=True)
    title = Path(source_key).stem
    start_line = "@startuml\n"
    end_line = "@enduml\n"
    header_passthrough: list[str] = []
    body_passthrough: list[str] = []
    elements: list[dict[str, Any]] = []
    relationships: list[dict[str, Any]] = []
    seen_structural = False

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("@startuml"):
            start_line = line
            continue
        if lower.startswith("@enduml"):
            end_line = line
            continue
        title_match = TITLE_RE.match(line)
        if title_match:
            title = title_match.group("title").strip()
            header_passthrough.append(line)
            continue
        element_match = ELEMENT_RE.match(line)
        if element_match:
            seen_structural = True
            name = unquote(element_match.group("name").strip())
            alias = element_match.group("alias")
            element_type = element_match.group("kind").lower().replace("abstract ", "abstract_")
            element_id = local_element_id(diagram_id, alias or name)
            elements.append(
                {
                    "element_id": element_id,
                    "element_type": element_type,
                    "name": name,
                    "metadata": {
                        "alias": alias,
                        "stereotype": element_match.group("stereotype"),
                        "source_line": line,
                    },
                }
            )
            continue
        relationship_match = RELATIONSHIP_RE.match(line)
        if relationship_match:
            seen_structural = True
            arrow = relationship_match.group("arrow")
            relationships.append(
                {
                    "source_element_id": local_element_id(diagram_id, unquote(relationship_match.group("source"))),
                    "target_element_id": local_element_id(diagram_id, unquote(relationship_match.group("target"))),
                    "relationship_type": relationship_type_from_arrow(arrow),
                    "label": relationship_match.group("label"),
                    "metadata": {"arrow": arrow, "source_line": line},
                }
            )
            continue
        if stripped:
            if not seen_structural:
                header_passthrough.append(line)
            else:
                body_passthrough.append(line)

    element_ids = {element["element_id"] for element in elements}
    for relationship in relationships:
        for side in ("source_element_id", "target_element_id"):
            if relationship[side] not in element_ids:
                element_ids.add(relationship[side])
                elements.append(
                    {
                        "element_id": relationship[side],
                        "element_type": "implicit",
                        "name": relationship[side].split(":", 1)[-1],
                        "metadata": {"implicit": True},
                    }
                )

    return {
        "diagram_id": diagram_id,
        "title": title,
        "notation": "plantuml",
        "diagram_kind": detect_kind(text, elements, relationships),
        "source_uri": source_uri,
        "raw_source": text,
        "model": {
            "source_key": source_key,
            "start_line": start_line,
            "end_line": end_line,
            "header_passthrough": header_passthrough,
            "body_passthrough": body_passthrough,
            "dirty": False,
        },
        "elements": elements,
        "relationships": relationships,
    }


def parse_mermaid(text: str, source_uri: str | None = None, source_key: str | None = None) -> dict[str, Any]:
    source_key = source_key or (Path(source_uri).name if source_uri else "diagram.mmd")
    diagram_id = re.sub(r"[^A-Za-z0-9]+", "-", str(Path(source_key).with_suffix(""))).strip("-").lower()
    title = Path(source_key).stem.replace("_", " ").replace("-", " ").title()
    elements_by_id: dict[str, dict[str, Any]] = {}
    relationships: list[dict[str, Any]] = []
    for line in text.splitlines():
        for node_match in MERMAID_NODE_RE.finditer(line):
            node_id = node_match.group("id")
            elements_by_id[node_id] = {
                "element_id": local_element_id(diagram_id, node_id),
                "element_type": "mermaid_node",
                "name": node_match.group("label"),
                "metadata": {"mermaid_id": node_id},
            }
        edge_match = MERMAID_EDGE_RE.match(line)
        if edge_match:
            source = edge_match.group("source")
            target = edge_match.group("target")
            elements_by_id.setdefault(
                source,
                {
                    "element_id": local_element_id(diagram_id, source),
                    "element_type": "mermaid_node",
                    "name": source,
                    "metadata": {"mermaid_id": source, "implicit": True},
                },
            )
            elements_by_id.setdefault(
                target,
                {
                    "element_id": local_element_id(diagram_id, target),
                    "element_type": "mermaid_node",
                    "name": target,
                    "metadata": {"mermaid_id": target, "implicit": True},
                },
            )
            relationships.append(
                {
                    "source_element_id": local_element_id(diagram_id, source),
                    "target_element_id": local_element_id(diagram_id, target),
                    "relationship_type": "flow",
                    "label": edge_match.group("label"),
                    "metadata": {"source_line": line},
                }
            )
    first_line = next((line.strip().lower() for line in text.splitlines() if line.strip()), "")
    diagram_kind = "flowchart" if first_line.startswith(("flowchart", "graph")) else "unknown"
    return {
        "diagram_id": diagram_id,
        "title": title,
        "notation": "mermaid",
        "diagram_kind": diagram_kind,
        "source_uri": source_uri,
        "raw_source": text,
        "model": {"source_key": source_key, "dirty": False, "mermaid": True},
        "elements": list(elements_by_id.values()),
        "relationships": relationships,
    }


def render_parsed_passthrough(parsed: dict[str, Any]) -> str:
    raw = parsed.get("raw_source")
    return raw if raw.endswith("\n") else f"{raw}\n"


def comparable_model(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "diagram_id": parsed["diagram_id"],
        "diagram_kind": parsed["diagram_kind"],
        "elements": sorted((item["element_id"], item["element_type"], item["name"]) for item in parsed["elements"]),
        "relationships": sorted(
            (item["source_element_id"], item["target_element_id"], item["relationship_type"], item.get("label"))
            for item in parsed["relationships"]
        ),
    }


def hydrate_element(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "element_uid": row["element_uid"],
        "project_id": row["project_id"],
        "diagram_uid": row["diagram_uid"],
        "diagram_id": row["diagram_id"],
        "element_id": row["element_id"],
        "element_type": row["element_type"],
        "name": row["name"],
        "description": row["description"],
        "metadata": loads(row["metadata_json"], {}),
    }


def hydrate_relationship(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "relationship_uid": row["relationship_uid"],
        "project_id": row["project_id"],
        "source_element_uid": row["source_element_uid"],
        "target_element_uid": row["target_element_uid"],
        "source_element_id": row["source_element_id"],
        "target_element_id": row["target_element_id"],
        "relationship_type": row["relationship_type"],
        "label": row["label"],
        "metadata": loads(row["metadata_json"], {}),
    }


def local_element_id(diagram_id: str, name_or_alias: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", name_or_alias.strip()).strip("-").lower()
    return f"{diagram_id}:{cleaned}"


def detect_kind(text: str, elements: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> str:
    lower = text.lower()
    types = {element["element_type"] for element in elements}
    if {"class", "interface", "enum", "abstract_class"} & types:
        return "class"
    if {"actor", "usecase"} & types or "usecase" in lower:
        return "usecase"
    if {"state"} & types or "[*]" in lower:
        return "state"
    if {"object"} & types:
        return "object"
    if {"participant"} & types:
        return "sequence"
    if "start" in lower and "stop" in lower:
        return "activity"
    return "unknown"


def relationship_type_from_arrow(arrow: str) -> str:
    if "<|--" in arrow or "--|>" in arrow:
        return "extends"
    if "*--" in arrow or "--*" in arrow:
        return "composition"
    if "o--" in arrow or "--o" in arrow:
        return "aggregation"
    if "..>" in arrow:
        return "dependency"
    if "-->" in arrow or "->" in arrow:
        return "message"
    return "association"


def render_element(element: dict[str, Any]) -> str:
    metadata = element.get("metadata", {})
    alias = metadata.get("alias")
    stereotype = metadata.get("stereotype")
    name = quote_if_needed(element["name"])
    alias_part = f" as {alias}" if alias else ""
    stereotype_part = f" {stereotype}" if stereotype else ""
    return f"{element['element_type'].replace('abstract_', 'abstract ')} {name}{alias_part}{stereotype_part}\n"


def render_relationship(relationship: dict[str, Any]) -> str:
    arrow = relationship.get("metadata", {}).get("arrow") or arrow_for_relationship(relationship["relationship_type"])
    label = f" : {relationship['label']}" if relationship.get("label") else ""
    source = relationship["source_element_id"].split(":", 1)[-1]
    target = relationship["target_element_id"].split(":", 1)[-1]
    return f"{source} {arrow} {target}{label}\n"


def arrow_for_relationship(relationship_type: str) -> str:
    return {
        "extends": "--|>",
        "implements": "..|>",
        "dependency": "..>",
        "composition": "*--",
        "aggregation": "o--",
        "message": "->",
        "transition": "-->",
        "include": "..>",
        "extend": "..>",
    }.get(relationship_type, "--")


def quote_if_needed(value: str) -> str:
    return f'"{value}"' if " " in value else value


def unquote(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-").lower() or "diagram"


def _safe_authored_source_key(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    candidate = PurePosixPath(normalized)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or any(part in {"", ".", ".."} or ":" in part for part in candidate.parts)
    ):
        raise ValueError(f"UML source_key must stay inside the export root: {value}")
    if candidate.suffix.lower() not in {".puml", ".plantuml", ".mmd", ".mermaid"}:
        raise ValueError("UML source_key must use a PlantUML or Mermaid extension.")
    return str(candidate)


def _line(value: str) -> str:
    return value if value.endswith("\n") else f"{value}\n"


def is_template_or_include_path(source_key: str) -> bool:
    parts = {part.lower() for part in Path(source_key).parts}
    return "_includes" in parts or "_templates" in parts or "_template" in parts


def _read_text_exact(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_text_exact(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _target_for_source_key(root: Path, source_key: str, fallback: str) -> Path:
    normalized = source_key.replace("\\", "/").strip()
    candidate = PurePosixPath(normalized) if normalized else PurePosixPath(fallback)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} or ":" in part for part in candidate.parts):
        candidate = PurePosixPath(fallback)
    return root / Path(*candidate.parts)


def repo_relative_key(path: Path) -> str:
    resolved = path.resolve()
    repo_root = find_repository_root(resolved)
    if repo_root:
        try:
            return resolved.relative_to(repo_root).as_posix()
        except ValueError:
            pass
    return resolved.as_posix()


def find_repository_root(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    for parent in [probe, *probe.parents]:
        if (parent / ".git").exists() or ((parent / "docs").is_dir() and (parent / "PluginProject.uproject").exists()):
            return parent
    return None
