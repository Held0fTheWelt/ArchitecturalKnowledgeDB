from __future__ import annotations

from pathlib import Path

import pytest

from architectural_knowledge_db.models import (
    SadDecisionInput,
    SadDocumentInput,
    SadSectionInput,
    UMLDiagramInput,
    UMLDiagramUpdate,
)
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.sad import SadService
from architectural_knowledge_db.services.uml import UMLService
from tests.conftest import add_project


def _author_document(service: SadService, project_id: str, document_id: str, source_key: str) -> None:
    service.upsert_document(
        project_id,
        SadDocumentInput(
            document_id=document_id,
            title=f"{document_id} architecture",
            source_key=source_key,
            preamble_md=f"# {document_id} architecture",
        ),
    )
    service.upsert_section(
        project_id,
        SadSectionInput(
            document_id=document_id,
            section_id="intro",
            title="1. Introduction",
            order=0,
            body_md=f"{document_id} introduction.",
        ),
    )
    service.upsert_section(
        project_id,
        SadSectionInput(
            document_id=document_id,
            section_id="decisions",
            title="9. Decisions",
            order=1,
            role="decisions",
            body_md="| ID | Title | Status |\n| --- | --- | --- |",
        ),
    )
    service.upsert_decision(
        project_id,
        SadDecisionInput(
            document_id=document_id,
            decision_id="D1",
            title="DB-native architecture",
            order=0,
            status="accepted",
            body_md="Architecture is authored in AKDB.",
        ),
    )


def test_sad_crud_is_db_native_and_exported(conn, tmp_path: Path) -> None:
    add_project(conn, "p")
    service = SadService(conn)
    _author_document(service, "p", "root", "architecture.md")

    document = service.get_document("p", "root")
    assert document["source_uri"] == "akdb://p/sad/root"
    assert document["metadata"]["repo_source_key"] == "docs/architecture/architecture.md"
    assert document["sections"][0]["source_uri"] == "akdb://p/sad/root"
    assert (
        document["sections"][0]["metadata"]["repo_source_key"]
        == "docs/architecture/architecture.md"
    )
    assert document["decisions"][0]["status"] == "accepted"
    assert "## 1. Introduction" in document["metadata"]["body_text"]
    assert "### D1: DB-native architecture" in document["metadata"]["body_text"]

    out = tmp_path / "out"
    ImportExportService(conn).export_sad("p", out)
    text = (out / "architecture.md").read_text(encoding="utf-8")
    assert "# root architecture" in text
    assert "## 1. Introduction" in text
    assert "### D1: DB-native architecture" in text

    service.delete_decision("p", "root", "D1")
    service.delete_section("p", "root", "intro")
    current = service.get_document("p", "root")
    assert current["decisions"] == []
    assert [item["title"] for item in current["sections"]] == ["9. Decisions"]
    assert "### D1:" not in current["metadata"]["body_text"]
    assert "## 1. Introduction" not in current["metadata"]["body_text"]


def test_multi_sad_export_preserves_document_hierarchy(conn, tmp_path: Path) -> None:
    add_project(conn, "p")
    service = SadService(conn)
    _author_document(service, "p", "root", "architecture.md")
    _author_document(service, "p", "authoring", "subsystems/agent-authoring/architecture.md")
    UMLService(conn).create_diagram(
        "p",
        UMLDiagramInput(
            diagram_id="authoring-context",
            title="Authoring context",
            raw_source="@startuml\ncomponent Authoring\n@enduml\n",
            model={
                "source_key": "subsystems/agent-authoring/UML/context.puml",
                "sad_document_id": "authoring",
            },
        ),
    )

    result = ImportExportService(conn).export_sad("p", tmp_path / "out")

    assert result["documents"] == 2
    assert (tmp_path / "out" / "architecture.md").is_file()
    child = tmp_path / "out" / "subsystems" / "agent-authoring" / "architecture.md"
    assert child.is_file()
    assert "authoring introduction." in child.read_text(encoding="utf-8")
    assert (
        tmp_path / "out" / "subsystems" / "agent-authoring" / "UML" / "context.puml"
    ).is_file()


def test_sad_upsert_preserves_canon_tree_placement(conn, tmp_path: Path) -> None:
    add_project(conn, "p")
    service = SadService(conn)

    service.upsert_document(
        "p",
        SadDocumentInput(
            document_id="workflow",
            title="Workflow architecture",
            source_key="project/workflow/architecture.md",
            preamble_md="# Workflow architecture",
        ),
    )
    updated = service.upsert_document(
        "p",
        SadDocumentInput(
            document_id="workflow",
            title="Workflow architecture",
            source_key="project/workflow/architecture.md",
            preamble_md="# Workflow architecture\n\nReconciled.",
        ),
    )

    expected = "docs/architecture/project/workflow/architecture.md"
    assert updated["metadata"]["repo_source_key"] == expected
    assert updated["preamble"][0]["metadata"]["repo_source_key"] == expected
    assert "Reconciled." in updated["metadata"]["body_text"]
    mirror = ImportExportService(conn)._expected_mirror_files(
        "p",
        tmp_path / "mirror",
    )
    assert mirror["project/workflow/architecture.md"][0].endswith(
        "# Workflow architecture\n\nReconciled.\n"
    )


def test_sad_source_key_cannot_escape_export_root(conn) -> None:
    add_project(conn, "p")
    with pytest.raises(ValueError, match="inside the export root"):
        SadService(conn).upsert_document(
            "p",
            SadDocumentInput(document_id="bad", title="Bad", source_key="../outside.md"),
        )


def test_sad_source_key_is_unique_per_project(conn) -> None:
    add_project(conn, "p")
    service = SadService(conn)
    _author_document(service, "p", "root", "architecture.md")

    with pytest.raises(ValueError, match="already used"):
        service.upsert_document(
            "p",
            SadDocumentInput(
                document_id="other",
                title="Other",
                source_key="architecture.md",
            ),
        )


def test_full_sad_export_removes_stale_managed_files_only(conn, tmp_path: Path) -> None:
    add_project(conn, "p")
    sad = SadService(conn)
    _author_document(sad, "p", "root", "architecture.md")
    uml = UMLService(conn)
    uml.create_diagram(
        "p",
        UMLDiagramInput(
            diagram_id="context",
            title="Context",
            model={
                "source_key": "UML/old-context.puml",
                "sad_document_id": "root",
            },
        ),
    )
    out = tmp_path / "out"
    first = ImportExportService(conn).export_sad("p", out)
    manual = out / "dual-backend.md"
    manual.write_text("Supporting note.", encoding="utf-8")
    assert (out / "UML" / "old-context.puml").is_file()
    assert Path(first["manifest"]).is_file()

    uml.update_diagram(
        "p",
        "context",
        UMLDiagramUpdate(source_key="UML/context.puml"),
    )
    ImportExportService(conn).export_sad("p", out)

    assert not (out / "UML" / "old-context.puml").exists()
    assert (out / "UML" / "context.puml").is_file()
    assert manual.read_text(encoding="utf-8") == "Supporting note."
