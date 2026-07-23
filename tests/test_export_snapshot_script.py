from __future__ import annotations

import gzip
import importlib.util
import sqlite3
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_snapshot.py"
_spec = importlib.util.spec_from_file_location("export_snapshot", _SCRIPT_PATH)
export_snapshot = importlib.util.module_from_spec(_spec)
sys.modules["export_snapshot"] = export_snapshot
_spec.loader.exec_module(export_snapshot)


def _make_db_with_fts(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE knowledge_items (item_uid TEXT PRIMARY KEY, title TEXT)")
    conn.execute("INSERT INTO knowledge_items VALUES ('a:1', 'Alpha')")
    conn.execute("INSERT INTO knowledge_items VALUES ('a:2', 'Beta')")
    conn.execute("CREATE TABLE export_targets (project_id TEXT, target_id TEXT)")
    conn.execute("INSERT INTO export_targets VALUES ('p', 't')")
    conn.execute(
        "CREATE VIRTUAL TABLE fts_knowledge USING fts5(item_uid UNINDEXED, title, tokenize = 'porter unicode61')"
    )
    conn.execute("INSERT INTO fts_knowledge (item_uid, title) VALUES ('a:1', 'Alpha')")
    conn.commit()
    conn.close()


def test_build_snapshot_excludes_fts_and_is_gzip_of_sql_text(tmp_path):
    db_path = tmp_path / "db.sqlite"
    _make_db_with_fts(db_path)
    out_path = tmp_path / "snapshot.sql.gz"

    sql_text = export_snapshot.build_snapshot(db_path, out_path)

    assert out_path.is_file()
    with gzip.open(out_path, "rt", encoding="utf-8") as f:
        assert f.read() == sql_text
    assert "sqlite_master" not in sql_text
    assert 'INSERT INTO "fts_knowledge"' not in sql_text
    assert "CREATE VIRTUAL TABLE fts_knowledge" not in sql_text
    # Shadow content tables are normal tables and DO survive the filter --
    # only the virtual table's own bootstrap/DML is excluded (see module docstring).
    assert "fts_knowledge_content" in sql_text
    assert "knowledge_items" in sql_text
    assert "export_targets" in sql_text


def test_snapshot_restores_cleanly_in_a_fresh_connection(tmp_path):
    db_path = tmp_path / "db.sqlite"
    _make_db_with_fts(db_path)
    out_path = tmp_path / "snapshot.sql.gz"
    export_snapshot.build_snapshot(db_path, out_path)

    with gzip.open(out_path, "rt", encoding="utf-8") as f:
        sql_text = f.read()

    restored = tmp_path / "restored.sqlite"
    conn = sqlite3.connect(str(restored))
    conn.executescript(sql_text)
    rows = conn.execute("select item_uid, title from knowledge_items order by item_uid").fetchall()
    targets = conn.execute("select project_id, target_id from export_targets").fetchall()
    conn.close()

    assert rows == [("a:1", "Alpha"), ("a:2", "Beta")]
    assert targets == [("p", "t")]


def test_main_writes_snapshot_and_supports_restore_check(tmp_path, capsys):
    db_path = tmp_path / "db.sqlite"
    _make_db_with_fts(db_path)
    out_path = tmp_path / "out" / "snapshot.sql.gz"

    rc = export_snapshot.main(["--db", str(db_path), "--out", str(out_path), "--restore-check"])

    assert rc == 0
    assert out_path.is_file()
    captured = capsys.readouterr()
    assert "restore-check OK: knowledge_items=2 export_targets=1" in captured.out


def test_main_errors_cleanly_on_missing_db(tmp_path, capsys):
    rc = export_snapshot.main(["--db", str(tmp_path / "nope.sqlite"), "--out", str(tmp_path / "out.sql.gz")])
    assert rc == 1
    assert "no such database" in capsys.readouterr().err
