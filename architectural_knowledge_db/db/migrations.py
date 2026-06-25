from __future__ import annotations

import sqlite3
from importlib import resources


def run_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    package = "architectural_knowledge_db.db.schema"
    schema_dir = resources.files(package)
    for sql_file in sorted(path for path in schema_dir.iterdir() if path.name.endswith(".sql")):
        version = sql_file.name
        already_applied = conn.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
        ).fetchone()
        if already_applied:
            continue
        conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
    conn.commit()
