from __future__ import annotations

import sqlite3
from typing import Any

from architectural_knowledge_db.models import KnowledgeSpace, ProjectUpsert


SHARED_PROJECT_ID = "shared"


class ProjectService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert_project(self, request: ProjectUpsert) -> dict[str, Any]:
        self.conn.execute(
            """
            INSERT INTO projects(project_id, display_name, description, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(project_id) DO UPDATE SET
              display_name = excluded.display_name,
              description = excluded.description,
              updated_at = CURRENT_TIMESTAMP
            """,
            (request.project_id, request.display_name, request.description),
        )
        self.ensure_project_space(request.project_id, request.display_name, request.description)
        for imported_space in request.imports:
            self.ensure_shared_space(imported_space, imported_space)
            self.import_space(request.project_id, imported_space)
        return self.get_project(request.project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT project_id, display_name, description, status, created_at, updated_at
            FROM projects
            ORDER BY project_id
            """
        ).fetchall()
        return [dict(row) | {"imports": self.list_imports(row["project_id"])} for row in rows]

    def get_project(self, project_id: str) -> dict[str, Any]:
        self.require_project(project_id)
        row = self.conn.execute(
            """
            SELECT project_id, display_name, description, status, created_at, updated_at
            FROM projects
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        result = dict(row)
        result["imports"] = self.list_imports(project_id)
        return result

    def require_project(self, project_id: str | None) -> None:
        if not project_id:
            raise ValueError("project_id is required; global queries are not allowed")
        row = self.conn.execute("SELECT 1 FROM projects WHERE project_id = ?", (project_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown project_id: {project_id}")

    def ensure_project_space(
        self, project_id: str, display_name: str | None = None, description: str | None = None
    ) -> str:
        self.require_project(project_id)
        space_id = project_space_id(project_id)
        self.conn.execute(
            """
            INSERT INTO knowledge_spaces(space_id, project_id, space_type, display_name, description)
            VALUES (?, ?, 'project', ?, ?)
            ON CONFLICT(space_id) DO UPDATE SET
              display_name = excluded.display_name,
              description = excluded.description
            """,
            (space_id, project_id, display_name or project_id, description),
        )
        return space_id

    def ensure_shared_project(self) -> None:
        self.conn.execute(
            """
            INSERT INTO projects(project_id, display_name, description)
            VALUES (?, ?, ?)
            ON CONFLICT(project_id) DO NOTHING
            """,
            (SHARED_PROJECT_ID, "Shared Knowledge", "Synthetic project for shared spaces."),
        )

    def ensure_shared_space(
        self, space_id: str, display_name: str | None = None, description: str | None = None
    ) -> str:
        self.ensure_shared_project()
        self.conn.execute(
            """
            INSERT INTO knowledge_spaces(space_id, project_id, space_type, display_name, description)
            VALUES (?, ?, 'shared', ?, ?)
            ON CONFLICT(space_id) DO UPDATE SET
              display_name = excluded.display_name,
              description = excluded.description
            """,
            (space_id, SHARED_PROJECT_ID, display_name or space_id, description),
        )
        return space_id

    def upsert_space(self, request: KnowledgeSpace) -> dict[str, Any]:
        if request.space_type == "shared":
            self.ensure_shared_space(request.space_id, request.display_name, request.description)
        else:
            if request.project_id is None:
                raise ValueError("project_id is required for project and archive spaces")
            self.require_project(request.project_id)
            self.conn.execute(
                """
                INSERT INTO knowledge_spaces(space_id, project_id, space_type, display_name, description)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(space_id) DO UPDATE SET
                  project_id = excluded.project_id,
                  space_type = excluded.space_type,
                  display_name = excluded.display_name,
                  description = excluded.description
                """,
                (
                    request.space_id,
                    request.project_id,
                    request.space_type,
                    request.display_name,
                    request.description,
                ),
            )
        return dict(
            self.conn.execute("SELECT * FROM knowledge_spaces WHERE space_id = ?", (request.space_id,)).fetchone()
        )

    def import_space(self, project_id: str, imported_space_id: str) -> None:
        self.require_project(project_id)
        if self.conn.execute("SELECT 1 FROM knowledge_spaces WHERE space_id = ?", (imported_space_id,)).fetchone() is None:
            raise ValueError(f"Unknown imported space: {imported_space_id}")
        self.conn.execute(
            """
            INSERT INTO project_imports(project_id, imported_space_id, import_policy)
            VALUES (?, ?, 'read_only')
            ON CONFLICT(project_id, imported_space_id) DO NOTHING
            """,
            (project_id, imported_space_id),
        )

    def list_imports(self, project_id: str) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT imported_space_id
            FROM project_imports
            WHERE project_id = ?
            ORDER BY imported_space_id
            """,
            (project_id,),
        ).fetchall()
        return [row["imported_space_id"] for row in rows]

    def scope_space_ids(self, project_id: str, include_shared: bool = True) -> list[str]:
        self.require_project(project_id)
        spaces = [project_space_id(project_id)]
        if include_shared:
            spaces.extend(self.list_imports(project_id))
        return spaces


def project_space_id(project_id: str) -> str:
    return f"{project_id}.project"
