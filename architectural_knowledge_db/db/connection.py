from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from architectural_knowledge_db.config import Settings
from architectural_knowledge_db.db.database import Database
from architectural_knowledge_db.db.migrations import run_migrations


def connect(database_path: Path | str | None = None,
            database_url: str | None = None) -> Database:
    settings = Settings.from_env()
    url = database_url if database_url is not None else settings.database_url
    if url and url.startswith("postgres"):
        import psycopg
        from psycopg.rows import dict_row
        raw = psycopg.connect(url, row_factory=dict_row)
        return Database(raw, is_postgres=True)

    path = Path(database_path) if database_path is not None else settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute("PRAGMA journal_mode = WAL")
    raw.execute("PRAGMA busy_timeout = 5000")
    raw.execute("PRAGMA synchronous = NORMAL")
    return Database(raw, is_postgres=False)


@contextmanager
def managed_connection(database_path: Path | str | None = None,
                       database_url: str | None = None) -> Iterator[Database]:
    conn = connect(database_path, database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(database_path: Path | str | None = None,
                        database_url: str | None = None) -> Database:
    conn = connect(database_path, database_url)
    run_migrations(conn)
    return conn
