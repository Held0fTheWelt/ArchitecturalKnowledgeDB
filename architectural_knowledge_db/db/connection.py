from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from architectural_knowledge_db.config import Settings
from architectural_knowledge_db.db.migrations import run_migrations


def connect(database_path: Path | str | None = None) -> sqlite3.Connection:
    settings = Settings.from_env()
    path = Path(database_path) if database_path is not None else settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def managed_connection(database_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(database_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database(database_path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(database_path)
    run_migrations(conn)
    return conn
