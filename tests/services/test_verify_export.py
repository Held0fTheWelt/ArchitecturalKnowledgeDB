from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert

FIXTURES = {
    "docs/architecture/plugins/X/architecture.md": "# X SAD\n\n## 1. Intro\n\nbody\n",
    "docs/architecture/plugins/X/product-facts.yml": "display_name: X\n",
    "UML/Plugins/X/c.puml": "@startuml\n@enduml\n",
}


@pytest.fixture
def sync_helper():
    def _make(conn, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
        for rel, text in FIXTURES.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="")
        ies = ImportExportService(conn)
        ies.import_documents("p", tmp_path / "docs" / "architecture", include=["**/*"])
        ies.import_documents("p", tmp_path / "UML", include=["**/*"])
        dest = tmp_path / "mirror"
        ExportTargetsService(conn).register_target(
            "p", "m", repository_id="Git", dest_root=str(dest), layout="arc42-canon",
            content_kinds=["sad", "uml", "adr"], auto_export=False,
        )
        ies.export_sync("p", "m")
        return dest, "p"

    return _make


def test_clean_mirror_verifies(conn, tmp_path, sync_helper):
    dest, pid = sync_helper(conn, tmp_path)
    r = ImportExportService(conn).verify_export(pid, "m")
    assert r["mismatched"] == [] and r["missing"] == [] and r["extra"] == []
    assert r["matched"] >= 1


def test_tamper_is_detected(conn, tmp_path, sync_helper):
    dest, pid = sync_helper(conn, tmp_path)
    f = next(Path(dest).rglob("architecture.md"))
    f.write_text("tampered\n", encoding="utf-8", newline="")
    assert any("architecture.md" in m for m in ImportExportService(conn).verify_export(pid, "m")["mismatched"])


def test_missing_and_extra_detected(conn, tmp_path, sync_helper):
    dest, pid = sync_helper(conn, tmp_path)
    f = next(Path(dest).rglob("architecture.md"))
    f.unlink()
    (Path(dest) / "stray.md").write_text("x\n", encoding="utf-8", newline="")
    r = ImportExportService(conn).verify_export(pid, "m")
    assert any("architecture.md" in m for m in r["missing"])
    assert any("stray.md" in e for e in r["extra"])
