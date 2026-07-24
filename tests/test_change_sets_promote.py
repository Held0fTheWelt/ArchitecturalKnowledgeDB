from tests.test_change_sets_service import _spec
from architectural_knowledge_db.services.change_sets import ChangeSetService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.models import AdrInput, RuleInput


def test_promote_refuses_when_not_done(conn):
    s = _spec(conn)
    cs = ChangeSetService(conn)
    cs.ingest_impact("p", s, "## Architektur-Impact\n- add rule R1\n")
    assert cs.promote("p", s).get("refused") is True


def test_promote_refuses_when_not_done_reason(conn):
    s = _spec(conn)
    cs = ChangeSetService(conn)
    cs.ingest_impact("p", s, "## Architektur-Impact\n- add rule R1\n")
    assert cs.promote("p", s)["reason"] == "open items"


def test_promote_refuses_when_target_absent(conn):
    # item marked done but the rule was never authored during the build → not truly done
    s = _spec(conn)
    cs = ChangeSetService(conn)
    cs.ingest_impact("p", s, "## Architektur-Impact\n- add rule R1\n")
    cid = cs.open_work_orders("p")[0]["items"][0]["id"]
    cs.set_item_state("p", cid, "done")
    out = cs.promote("p", s)
    assert out.get("refused") is True
    assert "R1" in out["reason"]


def test_promote_presence_based_no_status_write(conn):
    # rule has NO status column — promote must verify presence, not set a status
    s = _spec(conn)
    cs = ChangeSetService(conn)
    cs.ingest_impact("p", s, "## Architektur-Impact\n- add rule R1\n")
    KnowledgeService(conn).upsert_rule("p", RuleInput(rule_id="R1", rule_text="no raw mesh"))
    cid = cs.open_work_orders("p")[0]["items"][0]["id"]
    cs.set_item_state("p", cid, "done")
    out = cs.promote("p", s)
    assert out["spec"]["details"]["lifecycle"] == "implemented"
    assert cs.open_work_orders("p") == []  # backlog for this spec is now closed


def test_promote_flips_adr_status_to_accepted(conn):
    s = _spec(conn)
    cs = ChangeSetService(conn)
    cs.ingest_impact("p", s, "## Architektur-Impact\n- add ADR-X\n")
    KnowledgeService(conn).upsert_adr(
        "p", AdrInput(adr_id="ADR-X", title="Use X", status="proposed")
    )
    cid = cs.open_work_orders("p")[0]["items"][0]["id"]
    cs.set_item_state("p", cid, "done")
    out = cs.promote("p", s)
    assert KnowledgeService(conn).get_adr("p", "ADR-X")["status"] == "accepted"
    assert out["spec"]["details"]["lifecycle"] == "implemented"
