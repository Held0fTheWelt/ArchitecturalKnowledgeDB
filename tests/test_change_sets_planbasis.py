from architectural_knowledge_db.services.change_sets import ChangeSetService
from tests.test_change_sets_service import IMPACT, _spec


def test_plan_basis_merges_deltas_and_filetasks(conn):
    spec = _spec(conn)
    service = ChangeSetService(conn)
    service.ingest_impact("p", spec, IMPACT)
    basis = service.plan_basis("p", spec)
    assert len(basis["change_items"]) == 2
    assert "file_tasks" in basis and "checkpoints" in basis


def test_set_item_state_transitions(conn):
    spec = _spec(conn)
    service = ChangeSetService(conn)
    service.ingest_impact("p", spec, IMPACT)
    change_id = service.open_work_orders("p")[0]["items"][0]["id"]
    assert service.set_item_state("p", change_id, "in_progress")["item"]["state"] == "in_progress"
