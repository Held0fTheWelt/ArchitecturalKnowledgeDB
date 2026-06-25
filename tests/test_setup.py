from __future__ import annotations

from pathlib import Path

from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.setup import StarterSetupService
from architectural_knowledge_db.services.uml import UMLService


def test_starter_setup_writes_templates_and_imports_adr_and_uml(conn, tmp_path: Path) -> None:
    target = tmp_path / "docs" / "architecture"

    result = StarterSetupService(conn).setup_project(
        project_id="demo",
        project_name="Demo System",
        target_dir=target,
    )

    adrs = KnowledgeService(conn).list_adrs("demo")
    diagrams = UMLService(conn).list_diagrams("demo", limit=10)
    spec_text = (target / "specs" / "ARCHITECTURE_SPEC.md").read_text(encoding="utf-8")

    assert result["project"]["project_id"] == "demo"
    assert result["imports"]["adrs"]["imported"] == 2
    assert result["imports"]["uml"]["imported"] == 2
    assert {adr["adr_id"] for adr in adrs} == {"ADR-0001", "ADR-0002"}
    assert {diagram["diagram_id"] for diagram in diagrams} == {"knowledge-refresh-flow", "system-context"}
    assert "Demo System" in spec_text
    assert "{{project_name}}" not in spec_text


def test_starter_setup_does_not_overwrite_existing_files_by_default(conn, tmp_path: Path) -> None:
    target = tmp_path / "docs" / "architecture"
    service = StarterSetupService(conn)
    service.setup_project("demo", "Demo System", target, import_content=False)
    adr_path = target / "adr" / "ADR-0001-bootstrap-architecture-knowledge-base.md"
    adr_path.write_text("# Custom ADR\n", encoding="utf-8", newline="\n")

    result = service.setup_project("demo", "Demo System", target, import_content=False)

    assert adr_path.read_text(encoding="utf-8") == "# Custom ADR\n"
    assert str(adr_path) in result["skipped_files"]
