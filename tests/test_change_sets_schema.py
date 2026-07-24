import pytest

from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.projects import ProjectService
from tests.conftest import catalog_table_names


def test_change_items_table_exists(conn):
    assert "change_items" in catalog_table_names(conn)


def test_change_items_rejects_bad_op(conn):
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    with pytest.raises(Exception):
        conn.execute(
            "INSERT INTO change_items(project_id,spec_uid,op,target_kind,target_ref,state)"
            " VALUES('p','u','NOPE','adr','ADR-1','proposed')"
        )
