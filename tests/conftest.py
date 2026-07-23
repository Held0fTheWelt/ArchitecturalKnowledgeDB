from __future__ import annotations

import os
from pathlib import Path

import pytest

from architectural_knowledge_db.db.connection import connect, initialize_database
from architectural_knowledge_db.db.migrations import run_migrations
from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.projects import ProjectService

_PG_URL = os.getenv("AKDB_TEST_DB_URL")


def _backends():
    yield pytest.param("sqlite", id="sqlite")
    yield pytest.param(
        "postgres",
        id="postgres",
        marks=pytest.mark.skipif(not _PG_URL, reason="AKDB_TEST_DB_URL not set"),
    )


@pytest.fixture(params=list(_backends()))
def conn(request, tmp_path: Path):
    if request.param == "sqlite":
        db = initialize_database(tmp_path / "akdb.sqlite")
        try:
            yield db
        finally:
            db.close()
    else:
        db = connect(database_url=_PG_URL)
        # Isolate each test: rebuild the public schema, then migrate.
        db.execute("DROP SCHEMA IF EXISTS public CASCADE")
        db.execute("CREATE SCHEMA public")
        db.commit()
        run_migrations(db)
        try:
            yield db
        finally:
            db.close()


def add_project(conn, project_id: str) -> None:
    ProjectService(conn).upsert_project(ProjectUpsert(project_id=project_id, display_name=project_id))
    conn.commit()


def catalog_table_names(conn) -> set[str]:
    """Backend-portable table name set (sqlite_master | pg_tables)."""
    if getattr(conn, "is_postgres", False):
        rows = conn.execute(
            "SELECT tablename AS name FROM pg_catalog.pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    else:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def catalog_index_names(conn) -> set[str]:
    """Backend-portable index name set (sqlite_master | pg_indexes)."""
    if getattr(conn, "is_postgres", False):
        rows = conn.execute(
            "SELECT indexname AS name FROM pg_catalog.pg_indexes WHERE schemaname = 'public'"
        ).fetchall()
    else:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    return {r["name"] for r in rows}
