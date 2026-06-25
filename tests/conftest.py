from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.projects import ProjectService


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "akdb.sqlite"
    connection = initialize_database(db_path)
    try:
        yield connection
    finally:
        connection.close()


def add_project(conn: sqlite3.Connection, project_id: str) -> None:
    ProjectService(conn).upsert_project(ProjectUpsert(project_id=project_id, display_name=project_id))
    conn.commit()
