from __future__ import annotations

from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService
from tests.conftest import add_project
from tests.test_sad_sections import SAD


def test_export_sad_renders_architecture_md(conn, tmp_path: Path) -> None:
    add_project(conn, "p")
    src = tmp_path / "src"
    src.mkdir()
    (src / "architecture.md").write_text(SAD, encoding="utf-8")
    svc = ImportExportService(conn)
    svc.import_documents("p", src)
    out = tmp_path / "out"
    svc.export_sad("p", out)
    text = (out / "architecture.md").read_text(encoding="utf-8")
    assert "## 1. Introduction" in text
    assert "## 9. Decisions" in text
    assert "### D1: First decision" in text
    assert "**Status:** Accepted" in text
    assert "Body of D1." in text
