from __future__ import annotations

from architectural_knowledge_db.models import AdrInput, KnowledgeLinkInput, UMLElementInput
from architectural_knowledge_db.services.consistency import ConsistencyService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.uml import UMLService
from tests.conftest import add_project


def test_consistency_detects_dangling_supersede_and_broken_link(conn) -> None:
    add_project(conn, "akdb")
    knowledge = KnowledgeService(conn)
    adr = knowledge.upsert_adr(
        "akdb",
        AdrInput(adr_id="ADR-0002", title="New Decision", supersedes=["ADR-0001"]),
    )
    consistency = ConsistencyService(conn)
    consistency.link("akdb", adr["item_uid"], "missing:target", "references", evidence="test")

    findings = consistency.check("akdb")
    types = {finding["finding_type"] for finding in findings}

    assert "supersede_dangling" in types
    assert "broken_link" in types


def test_impact_traverses_inbound_and_outbound_links(conn) -> None:
    add_project(conn, "akdb")
    knowledge = KnowledgeService(conn)
    first = knowledge.upsert_adr("akdb", AdrInput(adr_id="ADR-0001", title="First"))
    second = knowledge.upsert_adr("akdb", AdrInput(adr_id="ADR-0002", title="Second"))
    consistency = ConsistencyService(conn)
    consistency.link("akdb", first["item_uid"], second["item_uid"], "references")

    impact = consistency.impact_of("akdb", second["item_uid"])

    assert impact["impacted_count"] == 1
    assert impact["impacted"][0]["source_ref"] == first["item_uid"]


def test_consistency_does_not_report_imported_uml_elements_as_orphans(conn) -> None:
    add_project(conn, "akdb")
    UMLService(conn).upsert_diagram(
        "akdb",
        {
            "diagram_id": "model",
            "title": "Model",
            "diagram_kind": "class",
            "source_uri": None,
            "raw_source": None,
            "model": {"dirty": True},
            "elements": [{"element_type": "class", "name": "Lonely", "metadata": {}}],
            "relationships": [],
        },
    )

    findings = ConsistencyService(conn).check("akdb", types=["orphans"])

    assert not any(finding["target_ref"] == "akdb:uml_element:model:lonely" for finding in findings)


def test_consistency_reports_unlinked_adr_orphan(conn) -> None:
    add_project(conn, "akdb")
    KnowledgeService(conn).upsert_adr("akdb", AdrInput(adr_id="ADR-0003", title="Unlinked"))

    findings = ConsistencyService(conn).check("akdb", types=["orphans"])

    assert any(finding["target_ref"] == "akdb:adr:ADR-0003" for finding in findings)


def test_consistency_ignores_historical_adr_ids_and_source_path_uml_links(conn) -> None:
    add_project(conn, "akdb")
    adr = KnowledgeService(conn).upsert_adr("akdb", AdrInput(adr_id="ADR-CATALOG", title="Catalog"))
    knowledge = KnowledgeService(conn)
    knowledge.upsert_link(
        "akdb",
        KnowledgeLinkInput(source_item_uid=adr["item_uid"], target_ref="ADR-PROD-0003", link_type="references_adr"),
    )
    knowledge.upsert_link(
        "akdb",
        KnowledgeLinkInput(
            source_item_uid=adr["item_uid"],
            target_ref="UML/Plugins/Demo/TRACEABILITY.md",
            link_type="references_uml",
        ),
    )

    findings = ConsistencyService(conn).check("akdb", types=["broken_links", "adr_uml"])

    assert findings == []
