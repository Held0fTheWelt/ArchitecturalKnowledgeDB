from __future__ import annotations

from unittest.mock import MagicMock

import sqlite3

from architectural_knowledge_db.db.database import Database
from architectural_knowledge_db.services.import_export import _auto_export_root_for_connection


def test_auto_export_root_skips_pragma_on_postgres():
    raw = MagicMock()
    db = Database(raw, is_postgres=True)
    assert _auto_export_root_for_connection(db) is None
    raw.execute.assert_not_called()


def test_auto_export_root_uses_pragma_on_sqlite():
    raw = MagicMock()
    # PRAGMA database_list columns: seq, name, file — non-Row uses index 2.
    raw.execute.return_value.fetchone.return_value = (0, "main", "")
    db = Database(raw, is_postgres=False)
    assert _auto_export_root_for_connection(db) is None
    raw.execute.assert_called_once_with("PRAGMA database_list", ())


def test_auto_export_root_memory_db_returns_none():
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    try:
        db = Database(raw, is_postgres=False)
        assert _auto_export_root_for_connection(db) is None
    finally:
        raw.close()
