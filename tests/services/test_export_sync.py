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
}


@pytest.fixture
def import_fixture():
    def _make(conn, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
        for rel, text in FIXTURES.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="")
        ImportExportService(conn).import_documents("p", tmp_path / "docs" / "architecture", include=["**/*"])
        dest = tmp_path / "mirror"
        ExportTargetsService(conn).register_target(
            "p", "m", repository_id="Git", dest_root=str(dest), layout="arc42-canon",
            content_kinds=["sad"], auto_export=False,
        )
        return dest, "p"

    return _make


def test_sync_makes_verify_clean_and_prunes_stray(conn, tmp_path, import_fixture):
    dest, pid = import_fixture(conn, tmp_path)
    ies = ImportExportService(conn)
    Path(dest).mkdir(parents=True, exist_ok=True)
    (Path(dest) / "stray.md").write_text("x\n", encoding="utf-8", newline="")
    ies.export_sync(pid, "m")
    r = ies.verify_export(pid, "m")
    assert r["mismatched"] == [] and r["missing"] == [] and r["extra"] == []
    assert not (Path(dest) / "stray.md").exists()
    assert ExportTargetsService(conn).peek_dirty(pid, "m") == []
