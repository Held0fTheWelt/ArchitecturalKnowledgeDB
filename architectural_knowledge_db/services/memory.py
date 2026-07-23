from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from architectural_knowledge_db.services.projects import ProjectService


class MemoryService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)

    def record_use(self, project_id: str, item_uids: list[str], boost: float = 1.0) -> None:
        self.projects.require_project(project_id)
        now = datetime.now(timezone.utc).isoformat()
        for item_uid in item_uids:
            self.conn.execute(
                """
                INSERT INTO item_memory(item_uid, use_count, last_used_at, pinned, salience)
                VALUES (?, 1, ?, 0, ?)
                ON CONFLICT(item_uid) DO UPDATE SET
                  use_count = item_memory.use_count + 1,
                  last_used_at = excluded.last_used_at,
                  salience = item_memory.salience + excluded.salience
                """,
                (item_uid, now, boost),
            )

    def pin(self, project_id: str, item_uid: str, pinned: bool = True) -> None:
        self.projects.require_project(project_id)
        self.conn.execute(
            """
            INSERT INTO item_memory(item_uid, use_count, last_used_at, pinned, salience)
            VALUES (?, 0, NULL, ?, 0.0)
            ON CONFLICT(item_uid) DO UPDATE SET pinned = excluded.pinned
            """,
            (item_uid, 1 if pinned else 0),
        )

    def decay(self, project_id: str, factor: float = 0.5) -> None:
        self.projects.require_project(project_id)
        self.conn.execute(
            """
            UPDATE item_memory SET salience = salience * ?
            WHERE pinned = 0 AND item_uid IN (
              SELECT item_uid FROM knowledge_items WHERE project_id = ?
            )
            """,
            (factor, project_id),
        )

    def state(self, item_uid: str) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT use_count, last_used_at, pinned, salience FROM item_memory WHERE item_uid = ?",
            (item_uid,),
        ).fetchone()
        if row is None:
            return {"use_count": 0, "pinned": 0, "salience": 0.0, "last_used_at": None}
        return {
            "use_count": row["use_count"],
            "pinned": row["pinned"],
            "salience": row["salience"],
            "last_used_at": row["last_used_at"],
        }
