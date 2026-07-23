from __future__ import annotations

from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService, parse_sad_decisions
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.search import SearchService
from tests.conftest import add_project


def test_adr_import_uses_relative_path_for_non_adr_filename_collisions(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    docs = tmp_path / "docs"
    nested = docs / "specs"
    nested.mkdir(parents=True)
    docs.mkdir(exist_ok=True)
    (docs / "README.md").write_text("# Root Readme\n\n## Decision\n\nRoot.\n", encoding="utf-8")
    (nested / "README.md").write_text("# Specs Readme\n\n## Decision\n\nNested.\n", encoding="utf-8")

    result = ImportExportService(conn).import_adrs("akdb", docs)
    adrs = KnowledgeService(conn).list_adrs("akdb")

    assert result["imported"] == 2
    assert {adr["adr_id"] for adr in result["adrs"]} == {"README", "SPECS-README"}
    assert {adr["local_id"] for adr in adrs} == {"README", "SPECS-README"}


def test_adr_import_preserves_domain_ids_and_skips_catalog_readme_and_templates(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    adr_root = tmp_path / "ADR"
    template_dir = adr_root / "_template"
    template_dir.mkdir(parents=True)
    (adr_root / "README.md").write_text("# ADR Catalog\n\nIndex only.\n", encoding="utf-8")
    (template_dir / "adr-template.md").write_text("# ADR-0000: Template\n\n## Decision\n\nFill me.\n", encoding="utf-8")
    (adr_root / "adr-prod-0003-plugin-boundary.md").write_text(
        "# ADR-PROD-0003: Plugin Boundary\n\n## Status\n\naccepted\n\n## Decision\n\nKeep internal docs out of public packages.\n",
        encoding="utf-8",
    )

    result = ImportExportService(conn).import_adrs("akdb", adr_root)

    assert result["imported"] == 1
    assert set(result["skipped"]) == {"README.md", "_template/adr-template.md"}
    assert result["adrs"][0]["adr_id"] == "ADR-PROD-0003"


def test_document_import_indexes_markdown_project_reality(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text(
        "# Runtime Reality\n\nThe service now imports project notes and specs.\n",
        encoding="utf-8",
    )
    (docs / "ADR-0001-old.md").write_text("# ADR-0001: Old\n\n## Decision\n\nOld path.\n", encoding="utf-8")

    result = ImportExportService(conn).import_documents("akdb", docs, exclude=["ADR*.md"])
    items = KnowledgeService(conn).list_items("akdb", include_types=["document"])
    matches = SearchService(conn).search("akdb", "project notes", include_types=["document"])

    assert result["imported"] == 1
    assert items[0]["local_id"] == "readme"
    assert items[0]["details"]["source_key"] == "README.md"
    assert matches[0]["item_type"] == "document"


def test_document_import_creates_structured_sad_and_product_fact_records(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    docs = tmp_path / "docs" / "architecture" / "plugins" / "Demo"
    docs.mkdir(parents=True)
    (docs / "architecture.md").write_text(
        """---
id: SAD-PLUGIN-DEMO
status: accepted
owns-adrs:
  - ADR-PROD-0003
uml-package: UML/Plugins/Demo
---
# Demo - Software Architecture

**Last reconciled to code:** `2026-06-21`

## 9. Architecture Decisions

### D1: Keep The Boundary

**Status:** Accepted
**Decision.** The demo keeps internal material out of buyer packages.
**Evidence.** [context](Git/UML/Plugins/Demo/components/c4-context.md).
""",
        encoding="utf-8",
    )
    (docs / "product-facts.yml").write_text(
        """schema_version: 1
plugin: Demo
display_name: Demo
category: AI Plugins
folder: AIPlugins/Demo
fab_status: Internal
sad: docs/architecture/plugins/Demo/architecture.md
sad_reconciled: "2026-06-21"
summary: Demo summary.
detail: Demo detail.
""",
        encoding="utf-8",
    )

    result = ImportExportService(conn).import_documents("akdb", tmp_path / "docs" / "architecture")
    items = KnowledgeService(conn).list_items(
        "akdb",
        include_types=["sad", "sad_frontmatter", "sad_preamble", "sad_decision", "product_fact_sheet"],
        limit=10,
    )
    links = conn.execute("SELECT link_type, target_ref FROM knowledge_links WHERE project_id = ?", ("akdb",)).fetchall()

    assert result["imported"] == 2
    assert result["derived"] == 4
    assert {item["item_type"] for item in items} == {
        "sad",
        "sad_frontmatter",
        "sad_preamble",
        "sad_decision",
        "product_fact_sheet",
    }
    assert any(row["link_type"] == "references_adr" and row["target_ref"] == "ADR-PROD-0003" for row in links)
    assert any(row["link_type"] == "references_product_facts" for row in links)
    assert any(row["target_ref"] == "UML/Plugins/Demo/components/c4-context.md" for row in links)


def test_parse_sad_decisions_stops_before_following_main_sections() -> None:
    decisions = parse_sad_decisions(
        """# Demo - Software Architecture

## 9. Architecture Decisions

### D1: Keep The Boundary

**Status:** Accepted
**Decision.** The demo keeps its boundary explicit.

### D2: Preserve Evidence

**Status:** Accepted
**Decision.** The demo preserves evidence links.

## 10. Quality Requirements

The quality requirements must not become part of D2.

## 11. Risks and Technical Debt

The risks must not become part of D2.

## 12. Glossary

The glossary must not become part of D2.
"""
    )

    assert [decision["decision_id"] for decision in decisions] == ["D1", "D2"]
    assert decisions[0]["body_md"] == (
        "**Status:** Accepted\n**Decision.** The demo keeps its boundary explicit."
    )
    assert decisions[1]["body_md"] == (
        "**Status:** Accepted\n**Decision.** The demo preserves evidence links."
    )
    assert all("## 10." not in decision["body_md"] for decision in decisions)
    assert all("## 11." not in decision["body_md"] for decision in decisions)
    assert all("## 12." not in decision["body_md"] for decision in decisions)


def test_parse_sad_decisions_accepts_hyphenated_ids() -> None:
    decisions = parse_sad_decisions(
        """## 9. Architecture Decisions

### D-DB: SQLite default, PostgreSQL opt-in via a Database facade

**Status:** Proposed

AKDB's default embedded backend is SQLite.

## 10. Quality Requirements

Must not join the decision body.
"""
    )

    assert [decision["decision_id"] for decision in decisions] == ["D-DB"]
    assert decisions[0]["status"] == "proposed"
    assert "Must not join" not in decisions[0]["body_md"]


def test_document_import_preserves_multi_document_yaml(conn, tmp_path: Path) -> None:
    add_project(conn, "akdb")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "governance.yaml").write_text(
        "schema: governance\nrules:\n  - id: R1\n---\nschema: gates\ngates:\n  - id: G1\n",
        encoding="utf-8",
    )

    result = ImportExportService(conn).import_documents("akdb", docs)
    items = KnowledgeService(conn).list_items("akdb", include_types=["document"])

    assert result["imported"] == 1
    data = items[0]["details"]["data"]
    assert data["document_count"] == 2
    assert [document["schema"] for document in data["documents"]] == ["governance", "gates"]
