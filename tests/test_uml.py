from __future__ import annotations

from pathlib import Path

import pytest

from architectural_knowledge_db.models import (
    ContextPackRequest,
    KnowledgeLinkInput,
    UMLDiagramInput,
    UMLDiagramUpdate,
    UMLElementInput,
    UMLRelationshipInput,
    UMLRelationshipUpdate,
)
from architectural_knowledge_db.services.context import ContextPackBuilder
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.uml import UMLService
from tests.conftest import add_project


def test_plantuml_import_preserves_raw_and_indexes_elements(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    uml_dir = tmp_path / "uml"
    uml_dir.mkdir()
    source = """@startuml
title Knowledge Store
skinparam classAttributeIconSize 0
class KnowledgeService as KS <<service>>
class ProjectService
KS --> ProjectService : uses
note right of KS
  Preserved note.
end note
@enduml
"""
    (uml_dir / "knowledge-store.puml").write_text(source, encoding="utf-8", newline="\n")

    result = UMLService(conn).import_diagrams("akdb", uml_dir)
    diagram = UMLService(conn).get_diagram("akdb", "knowledge-store")
    rendered = UMLService(conn).render_diagram("akdb", "knowledge-store")

    assert result["imported"] == 1
    assert diagram["diagram_kind"] == "class"
    assert {element["name"] for element in diagram["elements"]} >= {"KnowledgeService", "ProjectService"}
    assert rendered == source

    pack = ContextPackBuilder(conn).build("akdb", ContextPackRequest(task="Change KnowledgeService"))
    assert pack["uml_diagrams"][0]["local_id"] == "knowledge-store"
    assert any(item["details"]["name"] == "KnowledgeService" for item in pack["uml_elements"])


def test_plantuml_kind_prefers_sequence_when_actor_and_participant_coexist(
    conn, tmp_path: Path
) -> None:
    add_project(conn, "akdb")
    uml_dir = tmp_path / "uml"
    uml_dir.mkdir()
    (uml_dir / "sequence.puml").write_text(
        "@startuml\n"
        "actor Maintainer\n"
        "participant Service\n"
        "Maintainer -> Service : call\n"
        "@enduml\n",
        encoding="utf-8",
        newline="\n",
    )

    UMLService(conn).import_diagrams("akdb", uml_dir)

    assert UMLService(conn).get_diagram("akdb", "sequence")[
        "diagram_kind"
    ] == "sequence"


def test_plantuml_component_kind_is_not_unknown(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    uml_dir = tmp_path / "uml"
    uml_dir.mkdir()
    (uml_dir / "components.puml").write_text(
        "@startuml\ncomponent API\ncomponent Service\nAPI --> Service\n@enduml\n",
        encoding="utf-8",
        newline="\n",
    )

    UMLService(conn).import_diagrams("akdb", uml_dir)

    assert UMLService(conn).get_diagram("akdb", "components")[
        "diagram_kind"
    ] == "component"


def test_uml_import_auto_exports_original_path_and_raw_text(conn, tmp_path: Path, monkeypatch) -> None:
    add_project(conn, "akdb")
    mirror = tmp_path / "mirror"
    monkeypatch.setenv("AKDB_AUTO_EXPORT_ROOT", str(mirror))
    uml_dir = tmp_path / "uml"
    nested = uml_dir / "Project" / "Demo"
    nested.mkdir(parents=True)
    source_file = nested / "model.puml"
    source_file.write_bytes(
        b"@startuml\r\ntitle Demo\r\ncomponent A\r\ncomponent B\r\nA --> B : calls\r\n@enduml\r\n"
    )

    result = UMLService(conn).import_diagrams("akdb", uml_dir)

    assert result["auto_export"]["verification"]["mismatched"] == []
    assert result["auto_export"]["verification"]["extra"] == []
    assert (mirror / "uml" / "Project" / "Demo" / "model.puml").read_bytes() == source_file.read_bytes()


def test_uml_db_edit_marks_dirty_and_exports_structured_model(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    uml_dir = tmp_path / "uml"
    uml_dir.mkdir()
    (uml_dir / "simple.puml").write_text("@startuml\nclass A\n@enduml\n", encoding="utf-8")
    service = UMLService(conn)
    service.import_diagrams("akdb", uml_dir)

    service.add_element("akdb", UMLElementInput(diagram_id="simple", element_type="class", name="B"))
    service.add_relationship(
        "akdb",
        UMLRelationshipInput(
            diagram_id="simple",
            source_element_id="simple:a",
            target_element_id="simple:b",
            relationship_type="dependency",
            label="uses",
        ),
    )
    export_dir = tmp_path / "out"
    result = service.export_diagrams("akdb", export_dir)
    exported = Path(result["files"][0]).read_text(encoding="utf-8")

    assert "class B" in exported
    assert "a ..> b : uses" in exported


def test_uml_roundtrip_check(conn, tmp_path: Path) -> None:
    uml_dir = tmp_path / "uml"
    uml_dir.mkdir()
    (uml_dir / "flow.puml").write_text("@startuml\nstart\n:Do work;\nstop\n@enduml\n", encoding="utf-8")

    result = UMLService(conn).check_roundtrip(uml_dir)

    assert result["passed"] is True


def test_uml_reimport_removes_old_element_links_before_replacing_items(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    uml_dir = tmp_path / "uml"
    uml_dir.mkdir()
    source = uml_dir / "simple.puml"
    source.write_text("@startuml\nclass A\n@enduml\n", encoding="utf-8")

    uml = UMLService(conn)
    uml.import_diagrams("akdb", uml_dir)
    element_uid = uml.get_diagram("akdb", "simple")["elements"][0]["element_uid"]
    KnowledgeService(conn).upsert_link(
        "akdb",
        KnowledgeLinkInput(source_item_uid=element_uid, target_ref="docs/example.md", link_type="documents"),
    )

    source.write_text("@startuml\nclass B\n@enduml\n", encoding="utf-8")
    result = uml.import_diagrams("akdb", uml_dir)
    diagram = uml.get_diagram("akdb", "simple")

    assert result["imported"] == 1
    assert {element["name"] for element in diagram["elements"]} == {"B"}
    link_count = conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_links WHERE source_item_uid = ?",
        (element_uid,),
    ).fetchone()["n"]
    assert link_count == 0


def test_mermaid_import_indexes_flowchart(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    uml_dir = tmp_path / "uml"
    uml_dir.mkdir()
    (uml_dir / "architecture.mmd").write_text("flowchart TD\n  A[Agent] -->|calls| S[Service]\n", encoding="utf-8")

    result = UMLService(conn).import_diagrams("akdb", uml_dir)
    diagram = UMLService(conn).get_diagram("akdb", "architecture")

    assert result["imported"] == 1
    assert diagram["notation"] == "mermaid"
    assert diagram["diagram_kind"] == "flowchart"
    assert {element["name"] for element in diagram["elements"]} == {"Agent", "Service"}


def test_uml_import_skips_templates_and_includes(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    uml_dir = tmp_path / "uml"
    (uml_dir / "_templates").mkdir(parents=True)
    (uml_dir / "_includes").mkdir(parents=True)
    (uml_dir / "current").mkdir()
    (uml_dir / "current" / "model.puml").write_text("@startuml\nclass Current\n@enduml\n", encoding="utf-8")
    (uml_dir / "_templates" / "template.puml").write_text("@startuml\nclass Template\n@enduml\n", encoding="utf-8")
    (uml_dir / "_includes" / "shared.puml").write_text("@startuml\nclass Shared\n@enduml\n", encoding="utf-8")

    result = UMLService(conn).import_diagrams("akdb", uml_dir)

    assert result["imported"] == 1
    assert result["skipped"] == ["_includes/shared.puml", "_templates/template.puml"]


def test_uml_full_db_native_crud(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    from architectural_knowledge_db.models import SadDocumentInput
    from architectural_knowledge_db.services.sad import SadService

    SadService(conn).upsert_document(
        "akdb",
        SadDocumentInput(document_id="root", title="Root architecture"),
    )
    service = UMLService(conn)
    diagram = service.create_diagram(
        "akdb",
        UMLDiagramInput(
            diagram_id="db-native",
            title="DB Native",
            diagram_kind="component",
            model={"source_key": "UML/components/db-native.puml", "sad_document_id": "root"},
        ),
    )
    assert diagram["source_uri"] == "akdb://akdb/uml/db-native"

    a = service.add_element(
        "akdb", UMLElementInput(diagram_id="db-native", element_id="db-native:a", element_type="component", name="A")
    )
    b = service.add_element(
        "akdb", UMLElementInput(diagram_id="db-native", element_id="db-native:b", element_type="component", name="B")
    )
    relationship = service.add_relationship(
        "akdb",
        UMLRelationshipInput(
            diagram_id="db-native",
            source_element_id=a["element_id"],
            target_element_id=b["element_id"],
            label="calls",
        ),
    )
    service.update_relationship(
        "akdb",
        relationship["relationship_uid"],
        UMLRelationshipUpdate(relationship_type="dependency", label="uses"),
    )
    service.update_diagram(
        "akdb",
        "db-native",
        UMLDiagramUpdate(title="DB Native Components", diagram_kind="c4-component"),
    )
    exported = service.export_diagrams("akdb", tmp_path / "out")
    text = Path(exported["files"][0]).read_text(encoding="utf-8")
    assert "a ..> b : uses" in text

    service.delete_relationship("akdb", relationship["relationship_uid"])
    service.delete_element("akdb", b["element_id"])
    assert service.get_diagram("akdb", "db-native")["relationships"] == []
    assert service.delete_diagram("akdb", "db-native")["deleted"] is True


def test_db_native_uml_rejects_unsafe_or_orphaned_export_paths(conn) -> None:
    add_project(conn, "akdb")
    service = UMLService(conn)

    with pytest.raises(ValueError, match="inside the export root"):
        service.create_diagram(
            "akdb",
            UMLDiagramInput(
                diagram_id="unsafe",
                title="Unsafe",
                model={"source_key": "../unsafe.puml"},
            ),
        )
    with pytest.raises(ValueError, match="Unknown SAD document"):
        service.create_diagram(
            "akdb",
            UMLDiagramInput(
                diagram_id="orphan",
                title="Orphan",
                model={
                    "source_key": "UML/orphan.puml",
                    "sad_document_id": "missing",
                },
            ),
        )
