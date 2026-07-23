import sqlite3

from architectural_knowledge_db.db.database import (
    Database,
    rewrite_sqlite_json_extract_for_pg,
    to_pyformat,
)


def test_qmark_becomes_pyformat():
    assert to_pyformat("SELECT * FROM t WHERE a = ? AND b = ?") \
        == "SELECT * FROM t WHERE a = %s AND b = %s"


def test_literal_percent_is_escaped_before_placeholders():
    assert to_pyformat("SELECT '100%' AS p WHERE a = ?") \
        == "SELECT '100%%' AS p WHERE a = %s"


def test_json_extract_rewrites_for_postgres():
    sql = "SELECT * FROM t WHERE json_extract(r.metadata_json, '$.diagram_id') = ?"
    assert rewrite_sqlite_json_extract_for_pg(sql) == (
        "SELECT * FROM t WHERE (r.metadata_json::json->>'diagram_id') = ?"
    )


def _sqlite_db():
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    return Database(raw, is_postgres=False)


def test_database_execute_and_named_rows():
    db = _sqlite_db()
    db.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO t(name) VALUES(?)", ("alice",))
    db.commit()
    row = db.execute("SELECT name FROM t WHERE id = ?", (1,)).fetchone()
    assert row["name"] == "alice"
    assert db.is_postgres is False
    assert db.total_changes >= 1
    db.close()


def test_database_executescript_sqlite():
    db = _sqlite_db()
    db.executescript("CREATE TABLE a(x); CREATE TABLE b(y);")
    names = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"a", "b"} <= names
    db.close()


def test_database_execute_no_params():
    db = _sqlite_db()
    assert db.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
    db.close()


def test_settings_reads_database_url(monkeypatch):
    from architectural_knowledge_db.config import Settings
    monkeypatch.setenv("AKDB_DB_URL", "postgresql://u:p@localhost/akdb")
    assert Settings.from_env().database_url == "postgresql://u:p@localhost/akdb"


def test_settings_database_url_defaults_none(monkeypatch):
    from architectural_knowledge_db.config import Settings
    monkeypatch.delenv("AKDB_DB_URL", raising=False)
    assert Settings.from_env().database_url is None


def test_connect_returns_database_for_sqlite(tmp_path):
    from architectural_knowledge_db.db.connection import connect
    from architectural_knowledge_db.db.database import Database
    db = connect(tmp_path / "x.sqlite")
    try:
        assert isinstance(db, Database)
        assert db.is_postgres is False
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    finally:
        db.close()
