import sqlite3

from architectural_knowledge_db.db.database import Database
from architectural_knowledge_db.services.search import SearchService


def _svc(is_pg: bool) -> SearchService:
    raw = None if is_pg else sqlite3.connect(":memory:")
    return SearchService(Database(raw, is_postgres=is_pg))


def test_sqlite_fts_sql_uses_fts5_functions():
    sql, params = _svc(False)._sqlite_fts_sql(["alpha"], ["s1", "s2"], None, 10)
    assert "fts_knowledge MATCH ?" in sql
    assert "bm25(fts_knowledge)" in sql
    assert "snippet(fts_knowledge" in sql
    assert params[-1] == 10


def test_pg_fts_sql_uses_tsquery_and_binds_or_terms():
    sql, params = _svc(True)._pg_fts_sql(["alpha", "beta"], ["s1"], ["adr"], 5)
    assert "websearch_to_tsquery('english', ?)" in sql
    assert "f.tsv @@ websearch_to_tsquery" in sql
    assert "ts_rank(f.tsv" in sql
    # OR terms mirror SQLite fts5 semantics (spaces in raw query are AND in websearch).
    assert params[0] == "alpha OR beta"
    assert params[0] == params[1] == params[2]
    assert params[-1] == 5
