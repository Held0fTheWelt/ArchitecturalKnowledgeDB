from __future__ import annotations

from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService
from tests.conftest import add_project

SAD = """---
title: Sample
---

# Sample SAD

## 1. Introduction

Intro prose.

## 9. Decisions

### D1: First decision

**Status:** Accepted

Body of D1.
"""


def test_sad_import_stores_sections(conn, tmp_path: Path) -> None:
    add_project(conn, "p")
    folder = tmp_path / "sad"
    folder.mkdir()
    (folder / "architecture.md").write_text(SAD, encoding="utf-8")
    ImportExportService(conn).import_documents("p", folder)
    sections = [
        i
        for i in ImportExportService(conn).knowledge.list_items(
            "p", include_types=["sad_section"], include_shared=False, limit=50
        )
    ]
    titles = [s["title"] for s in sections]
    assert "1. Introduction" in titles and "9. Decisions" in titles
    intro = next(s for s in sections if s["title"] == "1. Introduction")
    assert (intro["metadata"] or {}).get("order") == 0
    assert "Intro prose." in (intro["metadata"] or {})["body_md"]
    preambles = ImportExportService(conn).knowledge.list_items(
        "p", include_types=["sad_preamble"], include_shared=False, limit=50
    )
    assert len(preambles) == 1
    assert (preambles[0]["metadata"] or {})["body_md"] == "# Sample SAD"
