import os

import pytest

_PG_URL = os.getenv("AKDB_TEST_DB_URL")


def test_sqlite_migrations_still_apply(tmp_path):
    from architectural_knowledge_db.db.connection import initialize_database

    db = initialize_database(tmp_path / "x.sqlite")
    try:
        n = db.execute("SELECT count(*) AS c FROM schema_migrations").fetchone()["c"]
        assert n >= 7
    finally:
        db.close()


@pytest.mark.skipif(not _PG_URL, reason="AKDB_TEST_DB_URL not set")
def test_postgres_migrations_apply_cleanly():
    from architectural_knowledge_db.db.connection import connect
    from architectural_knowledge_db.db.migrations import run_migrations

    db = connect(database_url=_PG_URL)
    try:
        db.execute("DROP SCHEMA IF EXISTS public CASCADE")
        db.execute("CREATE SCHEMA public")
        db.commit()
        run_migrations(db)
        # a core table and the FTS table exist and are queryable
        db.execute("SELECT 1 FROM knowledge_items WHERE 1=0").fetchone()
        db.execute("SELECT 1 FROM fts_knowledge WHERE 1=0").fetchone()
        assert db.execute(
            "SELECT count(*) AS c FROM schema_migrations"
        ).fetchone()["c"] >= 7
    finally:
        db.close()
