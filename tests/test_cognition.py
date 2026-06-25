from __future__ import annotations

from tests.conftest import add_project


def test_link_type_index_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_links_project_linktype'"
    ).fetchone()
    assert row is not None


def test_alias_folds_into_fts(conn):
    from architectural_knowledge_db.models import AdrInput, KnowledgeLinkInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.search import SearchService

    add_project(conn, "p")
    ks = KnowledgeService(conn)
    adr = ks.upsert_adr("p", AdrInput(adr_id="ADR-1", title="Publication boundary"))
    uid = adr["item_uid"]
    # baseline: a coined wording is NOT found yet
    assert SearchService(conn).search("p", "zorptext") == []
    # add an alias wording, then re-index
    ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=uid, target_ref="zorptext", link_type="alias"))
    ks._index_item(uid)
    hits = SearchService(conn).search("p", "zorptext")
    assert any(h["item_uid"] == uid for h in hits)


def test_cognition_models_defaults():
    from architectural_knowledge_db.models import RecallRequest, ExploreRequest, RememberRequest
    r = RecallRequest(query="auth boundary")
    assert r.hops == 1 and r.detail == "compact" and r.semantic is False and r.spaces is None
    e = ExploreRequest(source="uid-1", follow=["mvp_extends"])
    assert e.hops == 1
    m = RememberRequest(target="uid-1", wording="the plug")
    assert m.note is None


def test_remember_adds_alias_and_indexes(conn):
    from architectural_knowledge_db.models import AdrInput, RememberRequest
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.cognition import CognitionService
    from architectural_knowledge_db.services.search import SearchService

    add_project(conn, "p")
    ks = KnowledgeService(conn)
    uid = ks.upsert_adr("p", AdrInput(adr_id="ADR-1", title="Publication boundary"))["item_uid"]
    out = CognitionService(conn).remember("p", RememberRequest(target=uid, wording="the plug"))
    assert out["added_alias"] is True
    assert any(h["item_uid"] == uid for h in SearchService(conn).search("p", "the plug"))


def test_recall_resolves_and_ranks_neighbours(conn):
    from architectural_knowledge_db.models import AdrInput, RuleInput, KnowledgeLinkInput, RecallRequest
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.cognition import CognitionService

    add_project(conn, "p")
    ks = KnowledgeService(conn)
    concept = ks.upsert_adr("p", AdrInput(adr_id="ADR-1", title="Publication boundary"))["item_uid"]
    guard = ks.upsert_rule("p", RuleInput(rule_id="R-1", rule_text="never leak internals",
                                          authority_level="hard_guardrail"))["item_uid"]
    note = ks.upsert_rule("p", RuleInput(rule_id="R-2", rule_text="prefer summaries",
                                         authority_level="project_note"))["item_uid"]
    for tgt in (note, guard):  # insert low-authority first to prove ordering isn't insertion order
        ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=concept, target_ref=tgt, link_type="relates_to"))
    out = CognitionService(conn).recall("p", RecallRequest(query="Publication boundary"))
    assert concept in [c["item_uid"] for c in out["concepts"]]
    order = [n["item_uid"] for n in out["neighbours"]]
    assert order.index(guard) < order.index(note)  # hard_guardrail ranks before project_note
    assert all("link_type" in n and "authority_level" in n for n in out["neighbours"])


def test_recall_no_match_returns_hint(conn):
    from architectural_knowledge_db.models import RecallRequest
    from architectural_knowledge_db.services.cognition import CognitionService
    add_project(conn, "p")
    out = CognitionService(conn).recall("p", RecallRequest(query="nonexistent-zzz"))
    assert out["concepts"] == [] and "hint" in out


def test_explore_follows_only_chosen_link_types(conn):
    from architectural_knowledge_db.models import AdrInput, KnowledgeLinkInput, ExploreRequest
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.cognition import CognitionService

    add_project(conn, "p")
    ks = KnowledgeService(conn)
    a = ks.upsert_adr("p", AdrInput(adr_id="A", title="A"))["item_uid"]
    b = ks.upsert_adr("p", AdrInput(adr_id="B", title="B"))["item_uid"]
    c = ks.upsert_adr("p", AdrInput(adr_id="C", title="C"))["item_uid"]
    ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=a, target_ref=b, link_type="mvp_extends"))
    ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=a, target_ref=c, link_type="relates_to"))
    out = CognitionService(conn).explore("p", ExploreRequest(source=a, follow=["mvp_extends"]))
    refs = [n["item_uid"] for n in out["neighbours"]]
    assert b in refs and c not in refs


def test_mcp_dispatch_cognition_tools(conn):
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.mcp import McpDispatcher, MCP_MANIFEST

    add_project(conn, "p")
    uid = KnowledgeService(conn).upsert_adr("p", AdrInput(adr_id="ADR-1", title="Publication boundary"))["item_uid"]
    names = {t["name"] for t in MCP_MANIFEST["tools"]}
    assert {"akdb_recall", "akdb_explore", "akdb_remember"} <= names
    d = McpDispatcher(conn)
    assert d.dispatch("akdb_remember", {"project_id": "p", "target": uid, "wording": "the plug"})["added_alias"]
    out = d.dispatch("akdb_recall", {"project_id": "p", "query": "the plug"})
    assert uid in [c["item_uid"] for c in out["concepts"]]
