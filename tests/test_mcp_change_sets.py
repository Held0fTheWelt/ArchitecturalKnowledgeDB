from __future__ import annotations

from architectural_knowledge_db.mcp import McpDispatcher
from architectural_knowledge_db.models import ProjectUpsert, RuleInput
from architectural_knowledge_db.services.authoring import AuthoringService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService


def _spec(conn) -> str:
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    authoring = AuthoringService(conn)
    mvp = authoring.create_mvp("p", "M1", "m")["mvp"]["item_uid"]
    return authoring.create_spec("p", "S1", "T", "plugin", mvp)["item_uid"]


IMPACT = "## Architektur-Impact\n- add rule R1\n"


def test_open_work_orders_tool(conn):
    spec = _spec(conn)
    dispatcher = McpDispatcher(conn)
    dispatcher.dispatch(
        "akdb_ingest_impact",
        {"project_id": "p", "spec_uid": spec, "markdown": IMPACT},
    )
    work = dispatcher.dispatch("akdb_open_work_orders", {"project_id": "p"})
    assert work[0]["spec_id"] == "S1"
    assert work[0]["open"] == 1


def test_plan_basis_set_state_promote_render_pending_tools(conn, tmp_path):
    spec = _spec(conn)
    dispatcher = McpDispatcher(conn)
    dispatcher.dispatch(
        "akdb_ingest_impact",
        {"project_id": "p", "spec_uid": spec, "markdown": IMPACT},
    )
    basis = dispatcher.dispatch(
        "akdb_plan_basis", {"project_id": "p", "spec_uid": spec}
    )
    assert len(basis["change_items"]) == 1

    pending = dispatcher.dispatch(
        "akdb_render_pending",
        {"project_id": "p", "target_dest_root": str(tmp_path / "mirror")},
    )
    assert any("_pending/S1.md" in path.replace("\\", "/") for path in pending)

    item_id = basis["change_items"][0]["id"]
    KnowledgeService(conn).upsert_rule("p", RuleInput(rule_id="R1", rule_text="no raw mesh"))
    dispatcher.dispatch(
        "akdb_set_change_state",
        {"project_id": "p", "change_item_id": item_id, "state": "done"},
    )
    out = dispatcher.dispatch(
        "akdb_promote", {"project_id": "p", "spec_uid": spec}
    )
    assert out["spec"]["details"]["lifecycle"] == "implemented"
    assert dispatcher.dispatch("akdb_open_work_orders", {"project_id": "p"}) == []
