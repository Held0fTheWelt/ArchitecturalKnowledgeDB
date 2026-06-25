from __future__ import annotations

from pathlib import Path

import pytest

from architectural_knowledge_db.mcp import McpDispatcher
from tests.conftest import add_project


def _seed_sources(root: Path) -> None:
    adr = root / "docs" / "ADR"
    adr.mkdir(parents=True)
    (adr / "adr-demo-0001.md").write_text(
        "# ADR-DEMO-0001: First\n\n## Status\nAccepted\n\n"
        "## Related ADRs\n- [ADR-DEMO-0002](adr-demo-0002.md)\n\n"
        "## Decision\nDo X.\n",
        encoding="utf-8",
    )
    (adr / "adr-demo-0002.md").write_text(
        "# ADR-DEMO-0002: Second\n\n## Status\nAccepted\n\n## Decision\nDo Y.\n",
        encoding="utf-8",
    )
    uml = root / "UML"
    uml.mkdir()
    (uml / "demo.puml").write_text("@startuml demo\ntitle Demo\nclass A\nclass B\nA --> B\n@enduml\n", encoding="utf-8")
    docs = root / "docs" / "architecture"
    docs.mkdir(parents=True)
    (docs / "overview.md").write_text("# Overview\n\nArchitecture overview text.\n", encoding="utf-8")


def test_reingest_imports_all_stages(conn, tmp_path) -> None:
    add_project(conn, "demo")
    _seed_sources(tmp_path)
    result = McpDispatcher(conn).dispatch(
        "akdb_reingest_project",
        {"project_id": "demo", "source_root": str(tmp_path), "scan_git": False},
    )
    stages = result["stages"]
    assert stages["adrs"]["imported"] == 2
    assert stages["uml"]["imported"] >= 1
    assert stages["documents"]["imported"] >= 1


def test_reingest_populates_link_graph(conn, tmp_path) -> None:
    # Proves finding #2 (empty links) is DB-state: a fresh ingest extracts the
    # markdown "Related ADRs" link into the knowledge link graph.
    add_project(conn, "demo")
    _seed_sources(tmp_path)
    McpDispatcher(conn).dispatch(
        "akdb_reingest_project",
        {"project_id": "demo", "source_root": str(tmp_path), "scan_git": False},
    )
    links = McpDispatcher(conn).dispatch("akdb_get_links", {"project_id": "demo"})
    assert links["outbound"] or links["inbound"], "fresh ingest should populate knowledge links"


def test_reingest_skips_missing_folders(conn, tmp_path) -> None:
    add_project(conn, "demo")
    # empty source root: every stage should report skipped_missing, not crash
    result = McpDispatcher(conn).dispatch(
        "akdb_reingest_project",
        {"project_id": "demo", "source_root": str(tmp_path), "scan_git": False},
    )
    assert result["stages"]["adrs"]["skipped_missing"] is True
    assert result["stages"]["uml"]["skipped_missing"] is True


def test_reingest_unknown_project_raises(conn, tmp_path) -> None:
    with pytest.raises(ValueError):
        McpDispatcher(conn).dispatch(
            "akdb_reingest_project",
            {"project_id": "ghost", "source_root": str(tmp_path), "scan_git": False},
        )


def test_reingest_tool_is_in_manifest() -> None:
    from architectural_knowledge_db.mcp import MCP_MANIFEST

    names = {tool["name"] for tool in MCP_MANIFEST["tools"]}
    assert "akdb_reingest_project" in names
