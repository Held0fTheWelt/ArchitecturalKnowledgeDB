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


def test_export_sad_updates_decision_summary_from_structured_items(conn, tmp_path: Path) -> None:
    add_project(conn, "p")
    src = tmp_path / "src"
    src.mkdir()
    (src / "architecture.md").write_text(
        """# Sample

## 9. Decisions

| ID | Title | Status |
| --- | --- | --- |
| D1 | First decision | Proposed |

### D1: First decision

**Status:** Accepted

First body.

### D-SoR: Second decision

**Status:** Accepted

Second body.
""",
        encoding="utf-8",
    )
    svc = ImportExportService(conn)
    svc.import_documents("p", src)
    out = tmp_path / "out"
    svc.export_sad("p", out)
    text = (out / "architecture.md").read_text(encoding="utf-8")
    assert "| D1 | First decision | Accepted |" in text
    assert "| D-SoR | Second decision | Accepted |" in text
    assert text.index("### D1:") < text.index("### D-SoR:")
