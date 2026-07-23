from __future__ import annotations

from importlib import resources

from architectural_knowledge_db.db.database import Database


def run_migrations(db: Database) -> None:
    default_ts = "(CURRENT_TIMESTAMP::text)" if db.is_postgres else "CURRENT_TIMESTAMP"
    db.execute(
        f"""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT {default_ts}
        )
        """
    )
    schema_root = resources.files("architectural_knowledge_db.db") / "schema"
    schema_dir = schema_root / "pg" if db.is_postgres else schema_root
    for sql_file in sorted(
        (p for p in schema_dir.iterdir() if p.name.endswith(".sql")),
        key=lambda p: p.name,
    ):
        version = sql_file.name
        if db.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (version,)).fetchone():
            continue
        db.executescript(sql_file.read_text(encoding="utf-8"))
        db.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
    db.commit()
