from __future__ import annotations

from tests.conftest import add_project


def test_propose_topic_dedups(conn):
    from architectural_knowledge_db.services.authoring import AuthoringService
    add_project(conn, "p")
    a = AuthoringService(conn)
    first = a.propose_topic("p", "content-health", "Content health governance")
    assert first["created"] is True
    again = a.propose_topic("p", "content-health-2", "Content health governance")
    assert again["created"] is False and again["duplicates"]


def test_create_mvp_seq_and_predecessor(conn):
    from architectural_knowledge_db.services.authoring import AuthoringService
    add_project(conn, "p")
    a = AuthoringService(conn)
    topic = a.propose_topic("p", "t", "Theme")["topic"]["item_uid"]
    m1 = a.create_mvp("p", "M1", "first", topic_uid=topic)
    m2 = a.create_mvp("p", "M2", "second", topic_uid=topic)
    assert m1["seq"] == 1 and m2["seq"] == 2
    assert m1["suggested_predecessor"] is None
    assert m2["suggested_predecessor"]["item_uid"] == m1["mvp"]["item_uid"]


def test_spec_question_filemap(conn):
    from architectural_knowledge_db.services.authoring import AuthoringService
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    add_project(conn, "p")
    a = AuthoringService(conn)
    m = a.create_mvp("p", "M1", "m")["mvp"]["item_uid"]
    spec = a.create_spec("p", "S1", "Scan", "plugin", m)
    assert spec["details"]["mvp_uid"] == m
    q = a.open_question("p", "Q1", "open?")["item_uid"]
    a.resolve_question("p", q, spec["item_uid"])
    qrow = KnowledgeService(conn).get_item_by_uid(q)
    assert qrow["details"]["status"] == "answered"
    links = conn.execute("SELECT link_type, target_ref FROM knowledge_links WHERE source_item_uid=?", (q,)).fetchall()
    assert any(l["link_type"] == "question_resolved_by" and l["target_ref"] == spec["item_uid"] for l in links)


def test_set_spec_status_gate(conn):
    from architectural_knowledge_db.models import SpecInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.authoring import AuthoringService
    add_project(conn, "p")
    s = KnowledgeService(conn).upsert_spec("p", SpecInput(spec_id="S1", title="x", archetype="function"))
    out = AuthoringService(conn).set_spec_status("p", s["item_uid"], "ready")
    assert out["changed"] is False and out["validation"]["ok"] is False


def test_scaffold_spec_lists_required_diagrams(conn):
    from architectural_knowledge_db.services.authoring import AuthoringService
    add_project(conn, "p")
    out = AuthoringService(conn).scaffold_spec("p", "plugin")
    assert "c4-component" in out["required_diagrams"]
    assert out["archetype"] == "plugin"


def test_find_reuse_surfaces_prior_spec(conn):
    from architectural_knowledge_db.models import SpecInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.authoring import AuthoringService
    add_project(conn, "p")
    KnowledgeService(conn).upsert_spec("p", SpecInput(spec_id="S1", title="ZorpScanner", archetype="plugin"))
    hits = AuthoringService(conn).find_reuse("p", "ZorpScanner")
    assert any(h["title"] == "ZorpScanner" for h in hits)


def test_spec_to_plan_refuses_when_not_ready(conn):
    from architectural_knowledge_db.models import SpecInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.authoring import AuthoringService
    add_project(conn, "p")
    s = KnowledgeService(conn).upsert_spec("p", SpecInput(spec_id="S1", title="x", archetype="function"))["item_uid"]
    out = AuthoringService(conn).spec_to_plan("p", s)
    assert out["refused"] is True


def test_spec_to_plan_emits_one_task_per_file(conn):
    from architectural_knowledge_db.models import SpecInput, SourceAreaInput, KnowledgeLinkInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.uml import UMLService
    from architectural_knowledge_db.services.authoring import AuthoringService
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    uml = UMLService(conn)
    ks.upsert_source_area("p", SourceAreaInput(source_area_id="SA", title="src", path_patterns=["src/**"]))
    uml.upsert_diagram("p", {"diagram_id": "comp", "title": "comp", "diagram_kind": "c4-component",
                             "model": {}, "elements": [{"element_type": "Component", "name": "Scanner"}],
                             "relationships": []})
    uml.upsert_diagram("p", {"diagram_id": "seq", "title": "seq", "diagram_kind": "sequence",
                             "model": {}, "elements": [], "relationships": []})
    elem = uml.get_element("p", "comp:scanner")
    suid = ks.upsert_spec("p", SpecInput(spec_id="S1", title="Scan", archetype="function"))["item_uid"]
    for ref in ("comp", "seq", elem["element_uid"]):
        ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=suid, target_ref=ref, link_type="spec_realizes_uml"))
    for path in ("src/scanner.py", "src/parser.py"):
        ks.upsert_link("p", KnowledgeLinkInput(
            source_item_uid=elem["element_uid"], target_ref=path, link_type="element_maps_to_file"))
    out = AuthoringService(conn).spec_to_plan("p", suid)
    assert out["refused"] is False and len(out["tasks"]) == 2
    paths = [t["target_path"] for t in out["tasks"]]
    assert sorted(paths) == ["src/parser.py", "src/scanner.py"] and len(set(paths)) == 2
    assert "c4-component" in out["checkpoints"]
