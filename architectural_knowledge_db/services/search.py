from __future__ import annotations

import re
import sqlite3
from typing import Any

from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService


class SearchService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.knowledge = KnowledgeService(conn)

    def search(
        self,
        project_id: str,
        query: str,
        include_types: list[str] | None = None,
        include_shared: bool = True,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not query or not query.strip():
            raise ValueError("query is required")
        spaces = self.projects.scope_space_ids(project_id, include_shared=include_shared)
        terms = _query_terms(query)
        if not terms:
            return self._like_search(project_id, query, include_types, include_shared, limit)

        type_clause = ""
        params: list[Any] = [_fts_match(terms), *spaces]
        if include_types:
            type_clause = f"AND ki.item_type IN ({','.join('?' for _ in include_types)})"
            params.extend(include_types)
        params.append(limit)
        sql = f"""
            SELECT f.item_uid, f.item_type, f.title,
                   snippet(fts_knowledge, 4, '[', ']', '...', 16) AS snippet,
                   bm25(fts_knowledge) AS score,
                   ki.project_id, ki.space_id, ki.local_id, ki.authority_level, ki.status, ki.summary
            FROM fts_knowledge f
            JOIN knowledge_items ki ON ki.item_uid = f.item_uid
            WHERE fts_knowledge MATCH ?
              AND ki.space_id IN ({','.join('?' for _ in spaces)})
              {type_clause}
            ORDER BY score
            LIMIT ?
        """
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return self._like_search(project_id, query, include_types, include_shared, limit)

        results = []
        for row in rows:
            item = self.knowledge.get_item_by_uid(row["item_uid"])
            results.append(
                {
                    "item_uid": row["item_uid"],
                    "project_id": row["project_id"],
                    "space_id": row["space_id"],
                    "item_type": row["item_type"],
                    "local_id": row["local_id"],
                    "title": row["title"],
                    "authority_level": row["authority_level"],
                    "status": row["status"],
                    "summary": row["summary"],
                    "snippet": row["snippet"],
                    "score": row["score"],
                    "details": item.get("details", {}),
                }
            )
        return results

    def _like_search(
        self,
        project_id: str,
        query: str,
        include_types: list[str] | None,
        include_shared: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        spaces = self.projects.scope_space_ids(project_id, include_shared=include_shared)
        pattern = f"%{query.strip()}%"
        params: list[Any] = [*spaces, pattern, pattern]
        type_clause = ""
        if include_types:
            type_clause = f"AND ki.item_type IN ({','.join('?' for _ in include_types)})"
            params.extend(include_types)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT ki.*, f.body
            FROM knowledge_items ki
            JOIN fts_knowledge f ON f.item_uid = ki.item_uid
            WHERE ki.space_id IN ({','.join('?' for _ in spaces)})
              AND (ki.title LIKE ? OR f.body LIKE ?)
              {type_clause}
            ORDER BY ki.updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            {
                "item_uid": row["item_uid"],
                "project_id": row["project_id"],
                "space_id": row["space_id"],
                "item_type": row["item_type"],
                "local_id": row["local_id"],
                "title": row["title"],
                "authority_level": row["authority_level"],
                "status": row["status"],
                "summary": row["summary"],
                "snippet": (row["body"] or "")[:240],
                "score": None,
                "details": self.knowledge.get_item_by_uid(row["item_uid"]).get("details", {}),
            }
            for row in rows
        ]


def _query_terms(query: str) -> list[str]:
    return [term.lower() for term in re.findall(r"[A-Za-z0-9_:-]{2,}", query)[:12]]


def _fts_match(terms: list[str]) -> str:
    return " OR ".join(f'"{term}"' for term in terms)
