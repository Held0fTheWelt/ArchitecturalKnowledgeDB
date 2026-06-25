from __future__ import annotations

from tests.conftest import add_project

EXPECTED = {"topics", "mvps", "specs", "questions"}


def test_entity_tables_and_index_exist(conn):
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED <= names
    idx = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_mvps_seq" in idx


def test_upsert_and_hydrate_entities(conn):
    from architectural_knowledge_db.models import TopicInput, MvpInput, SpecInput, QuestionInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    t = ks.upsert_topic("p", TopicInput(topic_id="content-health", title="Content health"))
    m = ks.upsert_mvp("p", MvpInput(mvp_id="M1", title="First", seq=1, intent_md="why"))
    s = ks.upsert_spec("p", SpecInput(spec_id="S1", title="Scan", archetype="plugin", mvp_uid=m["item_uid"]))
    q = ks.upsert_question("p", QuestionInput(question_id="Q1", title="open?"))
    assert t["item_type"] == "topic" and t["details"]["lifecycle"] == "active"
    assert m["details"]["seq"] == 1
    assert s["details"]["archetype"] == "plugin" and s["details"]["mvp_uid"] == m["item_uid"]
    assert q["details"]["status"] == "open"


def test_mcp_entities_roundtrip(conn):
    from architectural_knowledge_db.mcp import McpDispatcher, MCP_MANIFEST
    add_project(conn, "p")
    names = {t["name"] for t in MCP_MANIFEST["tools"]}
    assert {"akdb_propose_topic", "akdb_create_mvp", "akdb_roadmap"} <= names
    d = McpDispatcher(conn)
    d.dispatch("akdb_create_mvp", {"project_id": "p", "mvp_id": "M1", "title": "first"})
    assert [e["mvp_id"] for e in d.dispatch("akdb_roadmap", {"project_id": "p"})] == ["M1"]
