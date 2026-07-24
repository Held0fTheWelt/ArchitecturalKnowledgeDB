from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.authoring import AuthoringService
from architectural_knowledge_db.services.change_sets import ChangeSetService
from architectural_knowledge_db.services.projects import ProjectService


IMPACT = "## Architektur-Impact\n- add ADR-9  — new\n- modify rule R1\n"


def _spec(conn):
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    authoring = AuthoringService(conn)
    mvp = authoring.create_mvp("p", "M1", "m")["mvp"]["item_uid"]
    return authoring.create_spec("p", "S1", "T", "plugin", mvp)["item_uid"]


def test_ingest_is_idempotent(conn):
    spec = _spec(conn)
    service = ChangeSetService(conn)
    first = service.ingest_impact("p", spec, IMPACT)
    second = service.ingest_impact("p", spec, IMPACT)
    assert first["created"] == 2 and second["created"] == 0


def test_open_work_orders_lists_the_spec(conn):
    spec = _spec(conn)
    ChangeSetService(conn).ingest_impact("p", spec, IMPACT)
    work = ChangeSetService(conn).open_work_orders("p")
    assert work[0]["spec_id"] == "S1" and work[0]["open"] == 2 and work[0]["done"] == 0
