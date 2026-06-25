from __future__ import annotations

from tests.conftest import add_project


def test_connect_finds_explained_path(conn):
    from architectural_knowledge_db.models import AdrInput, KnowledgeLinkInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.reasoning import ReasoningService
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    a = ks.upsert_adr("p", AdrInput(adr_id="A", title="A"))["item_uid"]
    b = ks.upsert_adr("p", AdrInput(adr_id="B", title="B"))["item_uid"]
    c = ks.upsert_adr("p", AdrInput(adr_id="C", title="C"))["item_uid"]
    ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=a, target_ref=b, link_type="relates_to"))
    ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=b, target_ref=c, link_type="relates_to"))
    out = ReasoningService(conn).connect("p", a, c)
    assert out["found"] is True
    assert [step["to"] for step in out["path"]] == [b, c]
    assert "-->" in out["explanation"]


def test_connect_unreachable(conn):
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.reasoning import ReasoningService
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    a = ks.upsert_adr("p", AdrInput(adr_id="A", title="A"))["item_uid"]
    b = ks.upsert_adr("p", AdrInput(adr_id="B", title="B"))["item_uid"]
    assert ReasoningService(conn).connect("p", a, b)["found"] is False


def test_tensions_flags_superseded_reference(conn):
    from architectural_knowledge_db.models import AdrInput, KnowledgeLinkInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.reasoning import ReasoningService
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    old = ks.upsert_adr("p", AdrInput(adr_id="OLD", title="Old", status="superseded"))["item_uid"]
    new = ks.upsert_adr("p", AdrInput(adr_id="NEW", title="New", status="accepted"))["item_uid"]
    ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=new, target_ref=old, link_type="relates_to"))
    t = ReasoningService(conn).tensions("p")
    assert any(x["kind"] == "superseded_still_referenced" and x["conflicts_with"] == old for x in t)


def test_gaps_reports_topic_without_spec(conn):
    from architectural_knowledge_db.services.authoring import AuthoringService
    from architectural_knowledge_db.services.reasoning import ReasoningService
    add_project(conn, "p")
    topic = AuthoringService(conn).propose_topic("p", "t", "Theme")["topic"]["item_uid"]
    g = ReasoningService(conn).gaps("p")
    assert any(x["kind"] == "topic_without_spec" and x["subject"] == topic for x in g)


def test_mcp_reasoning_survey_tools(conn):
    from architectural_knowledge_db.services.authoring import AuthoringService
    from architectural_knowledge_db.mcp import McpDispatcher, MCP_MANIFEST
    add_project(conn, "p")
    AuthoringService(conn).create_mvp("p", "M1", "first")
    names = {t["name"] for t in MCP_MANIFEST["tools"]}
    assert {"akdb_connect", "akdb_tensions", "akdb_gaps", "akdb_survey",
            "akdb_spec_authoring_context", "akdb_brief"} <= names
    d = McpDispatcher(conn)
    survey = d.dispatch("akdb_survey", {"project_id": "p"})
    assert {"topics", "changelog_tail", "specs_by_status", "health"} <= set(survey)
