from __future__ import annotations

from tests.conftest import add_project, catalog_table_names


def test_item_memory_table_exists(conn):
    assert "item_memory" in catalog_table_names(conn)


def test_use_pin_decay(conn):
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.memory import MemoryService
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    a = ks.upsert_adr("p", AdrInput(adr_id="A", title="A"))["item_uid"]
    b = ks.upsert_adr("p", AdrInput(adr_id="B", title="B"))["item_uid"]
    mem = MemoryService(conn)
    mem.record_use("p", [a])
    assert mem.state(a)["salience"] > mem.state(b)["salience"]
    mem.pin("p", b)
    mem.decay("p", factor=0.0)            # zero out non-pinned salience
    assert mem.state(a)["salience"] == 0.0
    assert mem.state(b)["pinned"] == 1


def test_use_boosts_rank_within_same_authority(conn):
    from architectural_knowledge_db.models import AdrInput, RuleInput, KnowledgeLinkInput, RecallRequest
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.cognition import CognitionService
    from architectural_knowledge_db.services.memory import MemoryService
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    concept = ks.upsert_adr("p", AdrInput(adr_id="C", title="Concept"))["item_uid"]
    n1 = ks.upsert_rule("p", RuleInput(rule_id="N1", rule_text="x", authority_level="project_note"))["item_uid"]
    n2 = ks.upsert_rule("p", RuleInput(rule_id="N2", rule_text="y", authority_level="project_note"))["item_uid"]
    for t in (n1, n2):
        ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=concept, target_ref=t, link_type="relates_to"))
    MemoryService(conn).record_use("p", [n2], boost=5.0)   # n2 is "useful"
    out = CognitionService(conn).recall("p", RecallRequest(query="Concept"))
    order = [n["item_uid"] for n in out["neighbours"]]
    assert order.index(n2) < order.index(n1)   # salience lifts n2 above same-authority n1


def test_working_set_add_list_clear(conn):
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.cognition import CognitionService
    add_project(conn, "p")
    a = KnowledgeService(conn).upsert_adr("p", AdrInput(adr_id="A", title="A"))["item_uid"]
    cog = CognitionService(conn)
    cog.working_set("p", "add", ref=a)
    assert a in [m["item_uid"] for m in cog.working_set("p", "list")["members"]]
    cog.working_set("p", "clear")
    assert cog.working_set("p", "list")["members"] == []


def test_recall_delta_returns_recent(conn):
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.cognition import CognitionService
    add_project(conn, "p")
    a = KnowledgeService(conn).upsert_adr("p", AdrInput(adr_id="A", title="A"))["item_uid"]
    out = CognitionService(conn).recall_delta("p", "2000-01-01T00:00:00")
    assert a in [r["item_uid"] for r in out]


def test_mcp_adaptive_tools(conn):
    from architectural_knowledge_db.models import AdrInput, RuleInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.mcp import McpDispatcher, MCP_MANIFEST
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    a = ks.upsert_adr("p", AdrInput(adr_id="A", title="A"))["item_uid"]
    ks.upsert_rule("p", RuleInput(rule_id="R1", rule_text="no print", applies_to=["**/x.py"],
                                  forbidden_changes=["print("], authority_level="hard_guardrail"))
    names = {t["name"] for t in MCP_MANIFEST["tools"]}
    assert {"akdb_pin", "akdb_recall_delta", "akdb_working_set", "akdb_check_change", "akdb_review"} <= names
    d = McpDispatcher(conn)
    out = d.dispatch("akdb_check_change", {"project_id": "p", "path": "pkg/x.py", "summary": "print( debug"})
    assert out["ok"] is False
    d.dispatch("akdb_working_set", {"project_id": "p", "action": "add", "ref": a})
    members = d.dispatch("akdb_working_set", {"project_id": "p", "action": "list"})["members"]
    assert a in [m["item_uid"] for m in members]
