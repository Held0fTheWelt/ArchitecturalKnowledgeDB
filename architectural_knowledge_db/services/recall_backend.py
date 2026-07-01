from __future__ import annotations

import math
import sqlite3
import struct
from typing import Any, Protocol

from architectural_knowledge_db.services.search import SearchService


class RecallBackend(Protocol):
    def resolve(
        self, project_id: str, query: str, spaces: list[str] | None, limit: int
    ) -> list[tuple[str, float]]:
        """Return (item_uid, score) pairs, higher score = better match."""
        ...


def _in_spaces(conn: sqlite3.Connection, item_uid: str, spaces: list[str]) -> bool:
    placeholders = ",".join("?" for _ in spaces)
    row = conn.execute(
        f"SELECT 1 FROM knowledge_items WHERE item_uid = ? AND space_id IN ({placeholders})",
        (item_uid, *spaces),
    ).fetchone()
    return row is not None


class FtsBackend:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.search = SearchService(conn)

    def resolve(
        self, project_id: str, query: str, spaces: list[str] | None, limit: int
    ) -> list[tuple[str, float]]:
        hits = self.search.search(project_id, query, limit=limit)
        results: list[tuple[str, float]] = []
        position = 0
        for hit in hits:
            if spaces and not _in_spaces(self.conn, hit["item_uid"], spaces):
                continue
            results.append((hit["item_uid"], 1.0 / (1 + position)))
            position += 1
        return results


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class VectorBackend:
    def __init__(self, conn: sqlite3.Connection, client: EmbeddingClient, model: str = "default"):
        self.conn = conn
        self.client = client
        self.model = model

    def _text_for(self, row: sqlite3.Row) -> str:
        text = " ".join(part for part in (row["title"], row["summary"]) if part)
        return text or row["item_uid"]

    def embed_project(self, project_id: str) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT item_uid, title, summary FROM knowledge_items WHERE project_id = ? ORDER BY item_uid",
            (project_id,),
        ).fetchall()
        embedded = 0
        for row in rows:
            vector = self.client.embed([self._text_for(row)])[0]
            blob = struct.pack(f"{len(vector)}f", *vector)
            self.conn.execute(
                """
                INSERT INTO item_embeddings(item_uid, model, dim, vector)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(item_uid) DO UPDATE SET
                  model = excluded.model, dim = excluded.dim, vector = excluded.vector
                """,
                (row["item_uid"], self.model, len(vector), blob),
            )
            embedded += 1
        return {"project_id": project_id, "embedded": embedded}

    def resolve(
        self, project_id: str, query: str, spaces: list[str] | None, limit: int
    ) -> list[tuple[str, float]]:
        query_vector = self.client.embed([query])[0]
        # Only rank against embeddings from the currently-configured model:
        # a cross-space union or a model switch can leave foreign-model vectors
        # in the table, and cosine across different embedding spaces (or a dim
        # mismatch, which silently scores 0.0) is meaningless.
        params: list[Any] = [project_id, self.model]
        space_clause = ""
        if spaces:
            space_clause = f"AND ki.space_id IN ({','.join('?' for _ in spaces)})"
            params.extend(spaces)
        rows = self.conn.execute(
            f"""
            SELECT e.item_uid, e.dim, e.vector
            FROM item_embeddings e
            JOIN knowledge_items ki ON ki.item_uid = e.item_uid
            WHERE ki.project_id = ? AND e.model = ? {space_clause}
            """,
            params,
        ).fetchall()
        scored: list[tuple[str, float]] = []
        for row in rows:
            vector = list(struct.unpack(f"{row['dim']}f", row["vector"]))
            scored.append((row["item_uid"], _cosine(query_vector, vector)))
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:limit]


class LLMStoreEmbeddingClient:
    """Live embedding client — POSTs to the LLMStore/IIS bridge. Constructed lazily, only when configured."""

    def __init__(self, url: str, model: str = "default"):
        self.url = url
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        import json
        import urllib.error
        import urllib.request

        payload = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise RuntimeError(f"embedding request to {self.url} failed: {exc}") from exc
        if isinstance(data, dict):
            if "data" in data:
                return [item["embedding"] for item in data["data"]]
            if "embeddings" in data:
                return data["embeddings"]
        raise RuntimeError(f"unexpected embedding response from {self.url}")
