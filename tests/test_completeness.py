from __future__ import annotations

from tests.conftest import add_project


def test_contract_loads_per_archetype(conn):
    from architectural_knowledge_db.services.completeness import CompletenessService
    c = CompletenessService(conn).contract("plugin")
    assert "c4-component" in c["required_diagrams"]
    assert c["file_map"] == "required"
    assert "required_diagrams" in c["blocking"]
    assert CompletenessService(conn).contract("rule")["required_diagrams"] == ["activity"]


def test_spec_validate_blocks(conn):
    from architectural_knowledge_db.models import SpecInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.completeness import CompletenessService
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    spec = ks.upsert_spec("p", SpecInput(spec_id="S1", title="Scan", archetype="function"))
    v = CompletenessService(conn).spec_validate("p", spec["item_uid"])
    assert v["ok"] is False and v["blocking"]["missing_required_diagrams"]


def test_spec_validate_ok_when_complete(conn):
    from architectural_knowledge_db.models import SpecInput, SourceAreaInput, KnowledgeLinkInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.uml import UMLService
    from architectural_knowledge_db.services.completeness import CompletenessService
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
    spec = ks.upsert_spec("p", SpecInput(spec_id="S1", title="Scan", archetype="function"))
    suid = spec["item_uid"]
    for ref in ("comp", "seq", elem["element_uid"]):
        ks.upsert_link("p", KnowledgeLinkInput(source_item_uid=suid, target_ref=ref, link_type="spec_realizes_uml"))
    ks.upsert_link("p", KnowledgeLinkInput(
        source_item_uid=elem["element_uid"], target_ref="src/scanner.py", link_type="element_maps_to_file"))
    v = CompletenessService(conn).spec_validate("p", suid)
    assert v["ok"] is True
    findings = conn.execute(
        "SELECT 1 FROM consistency_findings WHERE project_id='p' AND finding_type LIKE 'completeness:%'"
    ).fetchall()
    assert findings == []  # a complete spec writes no blocking/warning findings


def test_mcp_completeness_tools(conn):
    from architectural_knowledge_db.models import SpecInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.mcp import McpDispatcher, MCP_MANIFEST
    add_project(conn, "p")
    suid = KnowledgeService(conn).upsert_spec("p", SpecInput(spec_id="S1", title="x", archetype="function"))["item_uid"]
    names = {t["name"] for t in MCP_MANIFEST["tools"]}
    assert {"akdb_spec_validate", "akdb_set_spec_status", "akdb_scaffold_spec",
            "akdb_find_reuse", "akdb_spec_to_plan"} <= names
    d = McpDispatcher(conn)
    out = d.dispatch("akdb_spec_validate", {"project_id": "p", "spec_uid": suid})
    assert "ok" in out
    assert d.dispatch("akdb_scaffold_spec", {"project_id": "p", "archetype": "plugin"})["archetype"] == "plugin"
