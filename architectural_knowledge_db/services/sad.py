from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from architectural_knowledge_db.models import SadDecisionInput, SadDocumentInput, SadSectionInput
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService


def sad_uri(project_id: str, document_id: str) -> str:
    return f"akdb://{project_id}/sad/{document_id}"


def _safe_source_key(value: str) -> str:
    key = str(PurePosixPath(value.replace("\\", "/")))
    parts = PurePosixPath(key).parts
    if (
        key.startswith("/")
        or not parts
        or any(part in {"", ".", ".."} or ":" in part for part in parts)
    ):
        raise ValueError(f"SAD source_key must stay inside the export root: {value}")
    if not key.lower().endswith(".md"):
        raise ValueError("SAD source_key must name a Markdown file.")
    return key


def _local_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-").lower()
    if not token:
        raise ValueError("Identifier must contain letters or digits.")
    return token


class SadService:
    """DB-native authoring surface for arc42 SAD documents and their children."""

    def __init__(self, conn: Any):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)

    def list_documents(self, project_id: str) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        rows = self.conn.execute(
            """
            SELECT item_uid FROM knowledge_items
            WHERE project_id = ? AND item_type = 'sad'
            ORDER BY local_id
            """,
            (project_id,),
        ).fetchall()
        return [self.knowledge.get_item_by_uid(row["item_uid"]) for row in rows]

    def get_document(self, project_id: str, document_id: str) -> dict[str, Any]:
        self.projects.require_project(project_id)
        row = self.conn.execute(
            """
            SELECT item_uid FROM knowledge_items
            WHERE project_id = ? AND item_type = 'sad' AND local_id = ?
            """,
            (project_id, document_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown SAD document in project {project_id}: {document_id}")
        document = self.knowledge.get_item_by_uid(row["item_uid"])
        document["preamble"] = self._children(project_id, document["item_uid"], "sad_preamble")
        document["frontmatter"] = self._children(project_id, document["item_uid"], "sad_frontmatter")
        document["sections"] = self._children(project_id, document["item_uid"], "sad_section")
        document["decisions"] = self._children(project_id, document["item_uid"], "sad_decision")
        return document

    def upsert_document(self, project_id: str, request: SadDocumentInput) -> dict[str, Any]:
        self.projects.require_project(project_id)
        if _local_token(request.document_id) != request.document_id.lower():
            raise ValueError(
                "SAD document_id may contain only letters, digits, dots, underscores, and hyphens."
            )
        source_key = _safe_source_key(request.source_key)
        collision = self.conn.execute(
            """
            SELECT local_id FROM knowledge_items
            WHERE project_id = ? AND item_type = 'sad'
              AND json_extract(metadata_json, '$.source_key') = ?
              AND local_id <> ?
            """,
            (project_id, source_key, request.document_id),
        ).fetchone()
        if collision is not None:
            raise ValueError(
                f"SAD source_key is already used by document {collision['local_id']}: {source_key}"
            )
        uri = sad_uri(project_id, request.document_id)
        uid = self.knowledge._upsert_item(
            project_id=project_id,
            space_id=None,
            item_type="sad",
            local_id=request.document_id,
            title=request.title,
            status=request.status,
            authority_level="active_rule",
            summary=request.summary or request.title,
            source_uri=uri,
            metadata={
                "document_id": request.document_id,
                "source_key": source_key,
                "format": "markdown",
                "doc_kind": "sad",
                "authored_in": "akdb",
            },
        )
        self.knowledge._index_item(uid)
        if request.preamble_md is not None:
            self.set_preamble(project_id, request.document_id, request.preamble_md)
        if request.frontmatter:
            self.set_frontmatter(project_id, request.document_id, request.frontmatter)
        return self.get_document(project_id, request.document_id)

    def set_preamble(self, project_id: str, document_id: str, body_md: str) -> dict[str, Any]:
        parent = self.get_document(project_id, document_id)
        uid = self.knowledge._upsert_item(
            project_id=project_id,
            space_id=parent["space_id"],
            item_type="sad_preamble",
            local_id=f"{document_id}:preamble",
            title=f"{parent['title']} preamble",
            status=None,
            authority_level="project_note",
            summary=next((line.lstrip("# ").strip() for line in body_md.splitlines() if line.strip()), parent["title"]),
            source_uri=sad_uri(project_id, document_id),
            metadata=self._child_metadata(parent, {"body_md": body_md.strip("\n")}),
        )
        self.knowledge._index_item(uid)
        return self.knowledge.get_item_by_uid(uid)

    def set_frontmatter(
        self, project_id: str, document_id: str, frontmatter: dict[str, Any]
    ) -> dict[str, Any]:
        parent = self.get_document(project_id, document_id)
        uid = self.knowledge._upsert_item(
            project_id=project_id,
            space_id=parent["space_id"],
            item_type="sad_frontmatter",
            local_id=f"{document_id}:frontmatter",
            title=f"{parent['title']} frontmatter",
            status=str(frontmatter.get("status") or "current"),
            authority_level="active_rule",
            summary=", ".join(sorted(frontmatter)[:8]),
            source_uri=sad_uri(project_id, document_id),
            metadata=self._child_metadata(parent, {"frontmatter": frontmatter}),
        )
        self.knowledge._index_item(uid)
        return self.knowledge.get_item_by_uid(uid)

    def upsert_section(self, project_id: str, request: SadSectionInput) -> dict[str, Any]:
        parent = self.get_document(project_id, request.document_id)
        local_id = f"{request.document_id}:section:{_local_token(request.section_id)}"
        uid = self.knowledge._upsert_item(
            project_id=project_id,
            space_id=parent["space_id"],
            item_type="sad_section",
            local_id=local_id,
            title=request.title,
            status=None,
            authority_level="project_note",
            summary=request.title,
            source_uri=sad_uri(project_id, request.document_id),
            metadata=self._child_metadata(
                parent,
                {
                    "section_id": request.section_id,
                    "order": request.order,
                    "level": request.level,
                    "role": request.role,
                    "body_md": request.body_md.strip("\n"),
                },
            ),
        )
        self.knowledge._index_item(uid)
        return self.knowledge.get_item_by_uid(uid)

    def delete_section(self, project_id: str, document_id: str, section_id: str) -> dict[str, Any]:
        return self._delete_child(
            project_id, document_id, "sad_section", f"{document_id}:section:{_local_token(section_id)}"
        )

    def upsert_decision(self, project_id: str, request: SadDecisionInput) -> dict[str, Any]:
        parent = self.get_document(project_id, request.document_id)
        body = request.body_md.strip("\n")
        body = re.sub(r"(?m)^\*\*Status:\*\*\s*[^\n]+\n*", "", body, count=1).lstrip("\n")
        uid = self.knowledge._upsert_item(
            project_id=project_id,
            space_id=parent["space_id"],
            item_type="sad_decision",
            local_id=f"{request.document_id}:decision:{_local_token(request.decision_id)}",
            title=f"{request.decision_id}: {request.title}",
            status=request.status,
            authority_level="active_rule",
            summary=request.summary or request.title,
            source_uri=sad_uri(project_id, request.document_id),
            metadata=self._child_metadata(
                parent,
                {
                    "decision_id": request.decision_id,
                    "order": request.order,
                    "body_md": body,
                },
            ),
        )
        self.knowledge._index_item(uid)
        return self.knowledge.get_item_by_uid(uid)

    def delete_decision(self, project_id: str, document_id: str, decision_id: str) -> dict[str, Any]:
        return self._delete_child(
            project_id, document_id, "sad_decision", f"{document_id}:decision:{_local_token(decision_id)}"
        )

    def delete_document(self, project_id: str, document_id: str) -> dict[str, Any]:
        parent = self.get_document(project_id, document_id)
        child_rows = self.conn.execute(
            """
            SELECT item_uid FROM knowledge_items
            WHERE project_id = ? AND item_type IN
              ('sad_preamble','sad_frontmatter','sad_section','sad_decision')
              AND metadata_json LIKE ?
            """,
            (project_id, f'%"parent_item_uid": "{parent["item_uid"]}"%'),
        ).fetchall()
        for row in child_rows:
            self._delete_item(row["item_uid"])
        self._delete_item(parent["item_uid"])
        return {"project_id": project_id, "document_id": document_id, "deleted": True}

    def _children(
        self, project_id: str, parent_uid: str, item_type: str
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT item_uid FROM knowledge_items
            WHERE project_id = ? AND item_type = ? AND metadata_json LIKE ?
            ORDER BY local_id
            """,
            (project_id, item_type, f'%"parent_item_uid": "{parent_uid}"%'),
        ).fetchall()
        items = [self.knowledge.get_item_by_uid(row["item_uid"]) for row in rows]
        return sorted(
            items,
            key=lambda item: (
                (item.get("metadata") or {}).get("order", 0),
                item["local_id"],
            ),
        )

    @staticmethod
    def _child_metadata(parent: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_key": (parent.get("metadata") or {}).get("source_key", "architecture.md"),
            "parent_item_uid": parent["item_uid"],
            "authored_in": "akdb",
            **extra,
        }

    def _delete_child(
        self, project_id: str, document_id: str, item_type: str, local_id: str
    ) -> dict[str, Any]:
        parent = self.get_document(project_id, document_id)
        row = self.conn.execute(
            """
            SELECT item_uid, metadata_json FROM knowledge_items
            WHERE project_id = ? AND item_type = ? AND local_id = ?
            """,
            (project_id, item_type, local_id),
        ).fetchone()
        if row is None or parent["item_uid"] not in row["metadata_json"]:
            raise ValueError(f"Unknown {item_type} in SAD {document_id}: {local_id}")
        self._delete_item(row["item_uid"])
        return {"project_id": project_id, "document_id": document_id, "local_id": local_id, "deleted": True}

    def _delete_item(self, item_uid: str) -> None:
        self.conn.execute(
            "DELETE FROM knowledge_links WHERE source_item_uid = ? OR target_ref = ?",
            (item_uid, item_uid),
        )
        self.conn.execute("DELETE FROM fts_knowledge WHERE item_uid = ?", (item_uid,))
        self.conn.execute("DELETE FROM knowledge_items WHERE item_uid = ?", (item_uid,))
